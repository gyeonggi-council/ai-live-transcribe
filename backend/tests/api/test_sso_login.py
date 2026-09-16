"""SSO 교환 라우트 테스트 — 내부 introspection(ggc-sso-internal)은 monkeypatch 로 대체.

계약(ggc_sso/docs/integrate.md §4-③, §6):
  GET /api/auth/sso
    401 {detail, login}                    — 쿠키 없음 / introspect 실패(SSO 꺼짐 포함)
    403 {detail:"unregistered", usercode}  — 관리자가 비활성화한 계정
    200 {status:"authenticated", access_token, token_type, user}
        — QR 폴링 authenticated 응답과 **같은 JSON 형태**. 미등록 신규 사용자는
          QR 성공 분기와 동일하게 자동 생성한다(2026-08-22 사용자 결정).
"""

import pytest
from fastapi.testclient import TestClient

import app.api.qr_login as qr_login
import app.sso_client as sso_client
from app.core.database import get_supabase
from app.main import app
from app.services.auth_service import verify_token
from tests.api.test_qr_login import _make_user, _RecordingClient, _UserStore

COOKIE = sso_client.SSO_COOKIE  # __Host-ggc_sso


@pytest.fixture(autouse=True)
def _fresh_rate_buckets():
    qr_login._buckets.clear()
    yield
    qr_login._buckets.clear()


def _client_with(store: _UserStore) -> TestClient:
    app.dependency_overrides[get_supabase] = lambda: _RecordingClient(store)
    return TestClient(app)


@pytest.fixture
def registered_user() -> dict:
    return _make_user()


@pytest.fixture
def store(registered_user: dict) -> _UserStore:
    return _UserStore(users=[registered_user])


@pytest.fixture
def client(store: _UserStore):
    yield _client_with(store)
    app.dependency_overrides.clear()


def _fake_introspect(monkeypatch, result: dict | None):
    calls: list = []

    def fake(sid):
        calls.append(sid)
        return result

    monkeypatch.setattr(sso_client, "introspect", fake)
    return calls


class TestSsoExchange:
    def test_no_cookie_returns_401_with_login_url(self, client: TestClient, monkeypatch):
        calls = _fake_introspect(monkeypatch, {"usercode": "should-not-matter"})
        resp = client.get("/api/auth/sso")
        assert resp.status_code == 401
        body = resp.json()
        assert body["login"].startswith("/sso/login?next=")
        assert "%2Ftranscribe%2Flogin" in body["login"]
        # 쿠키가 없으면 내부 introspection 을 부르지도 않는다
        assert calls == []

    def test_invalid_session_returns_401(self, client: TestClient, monkeypatch):
        _fake_introspect(monkeypatch, None)
        client.cookies.set(COOKIE, "sid-invalid")
        resp = client.get("/api/auth/sso")
        assert resp.status_code == 401
        assert "login" in resp.json()

    def test_registered_user_gets_jwt(
        self, client: TestClient, store: _UserStore, registered_user: dict, monkeypatch
    ):
        _fake_introspect(
            monkeypatch,
            {"usercode": registered_user["username"], "user_name": "홍길동", "source": "sso"},
        )
        client.cookies.set(COOKIE, "sid-ok")
        resp = client.get("/api/auth/sso")
        assert resp.status_code == 200
        body = resp.json()
        # QR 폴링 authenticated 와 같은 형태
        assert body["status"] == "authenticated"
        assert body["token_type"] == "bearer"
        assert body["user"]["username"] == registered_user["username"]
        payload = verify_token(body["access_token"])
        assert payload is not None
        assert payload["sub"] == registered_user["id"]
        # 기존 사용자는 새로 만들지 않고 last_login_at 만 갱신한다
        assert store.inserted == []
        assert any("last_login_at" in u for u in store.updated)

    def test_inactive_user_returns_403_unregistered(self, monkeypatch):
        inactive = _make_user(is_active=False)
        store = _UserStore(users=[inactive])
        client = _client_with(store)
        try:
            _fake_introspect(monkeypatch, {"usercode": inactive["username"]})
            client.cookies.set(COOKIE, "sid-ok")
            resp = client.get("/api/auth/sso")
            assert resp.status_code == 403
            assert resp.json() == {"detail": "unregistered", "usercode": inactive["username"]}
            assert store.inserted == []
        finally:
            app.dependency_overrides.clear()

    def test_unknown_user_is_auto_created(self, monkeypatch):
        """QR 성공 분기와 같은 자동 생성 — SSO 는 프로필을 안 주므로 이름만 채운다."""
        store = _UserStore(users=[])
        client = _client_with(store)
        try:
            _fake_introspect(monkeypatch, {"usercode": "3000000099", "user_name": "김새내"})
            client.cookies.set(COOKIE, "sid-ok")
            resp = client.get("/api/auth/sso")
            assert resp.status_code == 200
            assert resp.json()["status"] == "authenticated"
            assert len(store.inserted) == 1
            row = store.inserted[0]
            assert row["username"] == "3000000099"
            assert row["display_name"] == "김새내"
            # 자동 부여는 staff 까지다 — admin 계열은 사람이 승격시킨다
            assert row["role"] == "staff"
        finally:
            app.dependency_overrides.clear()

    def test_usercode_missing_returns_401(self, client: TestClient, monkeypatch):
        """상류 계약 위반(usercode 없음) — 계정을 찾을 수 없으니 미인증으로 취급."""
        _fake_introspect(monkeypatch, {"user_name": "이름만"})
        client.cookies.set(COOKIE, "sid-ok")
        resp = client.get("/api/auth/sso")
        assert resp.status_code == 401


class TestQrPollMintsSsoCookie:
    """④ 로컬 QR 성공 분기 — mint 성공 시 같은 응답에 __Host-ggc_sso 쿠키를 심는다."""

    def _auth_upstream(self, monkeypatch, usercode: str):
        async def fake_poll(session_id: str):
            return {
                "status": "authenticated",
                "access_token": "upstream-token",
                "usercode": usercode,
                "user_name": "홍길동",
            }

        monkeypatch.setattr(qr_login, "_upstream_poll_session", fake_poll)

        async def fake_revoke(token: str):
            return None

        monkeypatch.setattr(qr_login, "_revoke", fake_revoke)

    def test_mint_success_sets_cookie(
        self, client: TestClient, registered_user: dict, monkeypatch
    ):
        self._auth_upstream(monkeypatch, registered_user["username"])
        minted = {
            "sid": "sso-sid-123",
            "expires_at": "2026-08-23T12:00:00+00:00",
            "cookie": {
                "name": COOKIE,
                "max_age": 28800,
                "path": "/",
                "secure": True,
                "httponly": True,
                "samesite": "lax",
            },
        }
        monkeypatch.setattr(sso_client, "mint", lambda *a, **kw: minted)
        resp = client.get("/api/auth/qr/sid-1")
        assert resp.status_code == 200
        assert resp.json()["status"] == "authenticated"  # JSON 본문은 그대로
        set_cookie = resp.headers.get("set-cookie", "")
        assert f"{COOKIE}=sso-sid-123" in set_cookie
        assert "HttpOnly" in set_cookie and "Path=/" in set_cookie

    def test_mint_failure_is_silent(
        self, client: TestClient, registered_user: dict, monkeypatch
    ):
        """mint 실패·SSO 꺼짐이면 쿠키 없이 로컬 로그인만 성공한다."""
        self._auth_upstream(monkeypatch, registered_user["username"])
        monkeypatch.setattr(sso_client, "mint", lambda *a, **kw: None)
        resp = client.get("/api/auth/qr/sid-1")
        assert resp.status_code == 200
        assert resp.json()["status"] == "authenticated"
        assert COOKIE not in resp.headers.get("set-cookie", "")
