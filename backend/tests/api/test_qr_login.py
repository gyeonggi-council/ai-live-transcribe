"""QR 로그인 API 테스트 — 상류(모바일 로그인 서비스)는 monkeypatch 로 대체.

계약: POST /api/auth/qr/session → {sessionId, apiUrl, ttl}
      GET  /api/auth/qr/{id}    → pending | expired | unregistered | authenticated(+JWT)
"""

import uuid
from typing import Generator

import httpx
import pytest
from fastapi.testclient import TestClient

import app.api.qr_login as qr_login
from app.core.database import get_supabase
from app.main import app
from app.services.auth_service import hash_password, verify_token
from tests.conftest import AuthAwareMockQuery, MockSupabaseQuery


def _make_user(username: str = "3000000008", is_active: bool = True) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "username": username,
        "password_hash": hash_password("unused-password"),
        "display_name": "홍길동",
        "role": "staff",
        "assigned_committee": None,
        "is_active": is_active,
        "last_login_at": None,
        "created_at": "2026-08-19T00:00:00+00:00",
    }


class _UserMockClient:
    def __init__(self, users: list | None = None):
        self._users = users or []

    def table(self, name: str):
        if name == "users":
            return AuthAwareMockQuery(data=self._users)
        return MockSupabaseQuery(data=[])


@pytest.fixture(autouse=True)
def _fresh_rate_buckets():
    qr_login._buckets.clear()
    yield
    qr_login._buckets.clear()


@pytest.fixture
def registered_user() -> dict:
    return _make_user()


@pytest.fixture
def client(registered_user: dict) -> Generator[TestClient, None, None]:
    mock = _UserMockClient(users=[registered_user])
    app.dependency_overrides[get_supabase] = lambda: mock
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestCreateSession:
    def test_session_created(self, client: TestClient, monkeypatch):
        async def fake_create():
            return {"sessionId": "sid-1", "apiUrl": "https://magent.ggc.go.kr", "ttl": 300}

        monkeypatch.setattr(qr_login, "_upstream_create_session", fake_create)
        resp = client.post("/api/auth/qr/session")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"sessionId": "sid-1", "apiUrl": "https://magent.ggc.go.kr", "ttl": 300}

    def test_upstream_error_returns_502(self, client: TestClient, monkeypatch):
        async def fake_create():
            raise httpx.ConnectError("boom")

        monkeypatch.setattr(qr_login, "_upstream_create_session", fake_create)
        resp = client.post("/api/auth/qr/session")
        assert resp.status_code == 502

    def test_unconfigured_returns_503(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(qr_login.settings, "ggc_login_base_url", "")
        resp = client.post("/api/auth/qr/session")
        assert resp.status_code == 503


class TestPollSession:
    def _patch_poll(self, monkeypatch, payload: dict):
        async def fake_poll(session_id: str):
            return payload

        monkeypatch.setattr(qr_login, "_upstream_poll_session", fake_poll)

        async def fake_revoke(token: str):
            return None

        monkeypatch.setattr(qr_login, "_revoke", fake_revoke)

    def test_pending(self, client: TestClient, monkeypatch):
        self._patch_poll(monkeypatch, {"status": "pending"})
        resp = client.get("/api/auth/qr/sid-1")
        assert resp.status_code == 200
        assert resp.json() == {"status": "pending"}

    def test_expired(self, client: TestClient, monkeypatch):
        self._patch_poll(monkeypatch, {"status": "expired"})
        resp = client.get("/api/auth/qr/sid-1")
        assert resp.json() == {"status": "expired"}

    def test_authenticated_registered_user_gets_jwt(
        self, client: TestClient, registered_user: dict, monkeypatch
    ):
        self._patch_poll(
            monkeypatch,
            {
                "status": "authenticated",
                "access_token": "upstream-token",
                "usercode": registered_user["username"],
                "user_name": "홍길동",
            },
        )
        resp = client.get("/api/auth/qr/sid-1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "authenticated"
        assert body["user"]["username"] == registered_user["username"]
        payload = verify_token(body["access_token"])
        assert payload is not None
        assert payload["sub"] == registered_user["id"]
        assert payload["role"] == registered_user["role"]

    def test_authenticated_without_usercode_is_unregistered(
        self, client: TestClient, monkeypatch
    ):
        """상류가 식별자를 안 주면 계정을 만들 수 없다 (계약 위반 상황)."""
        self._patch_poll(
            monkeypatch,
            {
                "status": "authenticated",
                "access_token": "upstream-token",
                "usercode": "",
                "user_name": "이름만있음",
            },
        )
        resp = client.get("/api/auth/qr/sid-1")
        body = resp.json()
        assert body["status"] == "unregistered"
        assert "access_token" not in body

    def test_authenticated_inactive_user_is_unregistered(
        self, client: TestClient, monkeypatch
    ):
        inactive = _make_user(username="3000000009", is_active=False)
        mock = _UserMockClient(users=[inactive])
        app.dependency_overrides[get_supabase] = lambda: mock
        self._patch_poll(
            monkeypatch,
            {
                "status": "authenticated",
                "access_token": "upstream-token",
                "usercode": inactive["username"],
            },
        )
        resp = client.get("/api/auth/qr/sid-1")
        assert resp.json()["status"] == "unregistered"


# =============================================================================
# QR 자동 등록 (2026-08-22) — 미등록 사용자도 QR 인증만으로 들어온다
# =============================================================================

from tests.conftest import MockSupabaseResponse  # noqa: E402


class _UserStore:
    """users 테이블 목 저장소 — insert/update 를 기록한다."""

    def __init__(self, users: list | None = None):
        self.users = users or []
        self.inserted: list[dict] = []
        self.updated: list[dict] = []


class _RecordingUsersQuery(AuthAwareMockQuery):
    def __init__(self, store: _UserStore):
        super().__init__(data=store.users)
        self._store = store
        self._insert_row: dict | None = None
        self._update_values: dict | None = None

    def insert(self, row, *a, **kw):
        self._insert_row = row
        return self

    def update(self, values, *a, **kw):
        self._update_values = values
        return self

    def execute(self):
        if self._insert_row is not None:
            row = dict(self._insert_row)
            row.setdefault("id", str(uuid.uuid4()))
            row.setdefault("assigned_committee", None)
            row.setdefault("created_at", "2026-08-22T00:00:00+00:00")
            self._store.users.append(row)
            self._store.inserted.append(dict(self._insert_row))
            return MockSupabaseResponse(data=[row], count=None)
        if self._update_values is not None:
            targets = [
                r
                for r in self._store.users
                if all(r.get(c) == v for c, v in self._filters.items())
            ]
            for r in targets:
                r.update(self._update_values)
            self._store.updated.append(dict(self._update_values))
            return MockSupabaseResponse(data=targets, count=None)
        return super().execute()


class _RecordingClient:
    def __init__(self, store: _UserStore):
        self._store = store

    def table(self, name: str):
        if name == "users":
            return _RecordingUsersQuery(self._store)
        return MockSupabaseQuery(data=[])


#: 상류가 authenticated 에 싣는 프로필 전체 (openapi.json 기준).
#: DID·토큰 계열이 섞여 있는 것이 요점 — 그것들이 DB 로 새지 않는지 검사한다.
_UPSTREAM_FULL = {
    "status": "authenticated",
    "access_token": "upstream-token",
    "refresh_token": "upstream-refresh",
    "token_type": "bearer",
    "expires_in": 3599,
    "scope": "read write",
    "usercode": "wooni0103",
    "user_name": "홍길동",
    "role": "ROLE_COUNCILOR",
    "group_name": "공간정보화과",
    "deptnm": "공간정보화과",
    "jobpositionname": "주무관",
    "wallet_id": "ff4d7698-ddad-4c9b-8676-c8742a41be71",
    "holder_did": "BxsxPDDDxUtL1XxS9yTFqK",
    "last_login": "2026-08-22",
    "app_last_login": "2026-08-21",
    "wallet_created_at": "2026-07-04",
}

#: DB 어디에도 들어가면 안 되는 키
_FORBIDDEN_KEYS = {
    "wallet_id",
    "holder_did",
    "wallet_created_at",
    "access_token",
    "refresh_token",
    "token_type",
    "scope",
    "expires_in",
}


def _store_client(store: _UserStore, monkeypatch, payload: dict) -> TestClient:
    app.dependency_overrides[get_supabase] = lambda: _RecordingClient(store)

    async def fake_poll(session_id: str):
        return payload

    async def fake_revoke(token: str):
        return None

    monkeypatch.setattr(qr_login, "_upstream_poll_session", fake_poll)
    monkeypatch.setattr(qr_login, "_revoke", fake_revoke)
    return TestClient(app)


class TestAutoProvisioning:
    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_unknown_usercode_creates_account_and_logs_in(self, monkeypatch):
        """예전에는 unregistered 로 끝났다. 이제는 계정을 만들어 바로 들여보낸다."""
        store = _UserStore()
        client = _store_client(store, monkeypatch, _UPSTREAM_FULL)

        body = client.get("/api/auth/qr/sid-1").json()

        assert body["status"] == "authenticated"
        assert body["user"]["username"] == "wooni0103"
        assert verify_token(body["access_token"]) is not None
        assert len(store.inserted) == 1

    def test_created_account_stores_the_profile(self, monkeypatch):
        store = _UserStore()
        client = _store_client(store, monkeypatch, _UPSTREAM_FULL)
        client.get("/api/auth/qr/sid-1")

        row = store.inserted[0]
        assert row["username"] == "wooni0103"
        assert row["display_name"] == "홍길동"
        assert row["portal_role"] == "ROLE_COUNCILOR"
        assert row["dept_name"] == "공간정보화과"
        assert row["job_position"] == "주무관"
        assert row["portal_last_login"] == "2026-08-22"
        assert row["portal_app_last_login"] == "2026-08-21"

    def test_did_and_tokens_never_reach_the_database(self, monkeypatch):
        """이 테스트가 깨지면 개인정보 결정(2026-08-22)이 무너진 것이다."""
        store = _UserStore()
        client = _store_client(store, monkeypatch, _UPSTREAM_FULL)
        client.get("/api/auth/qr/sid-1")

        written = {k for row in store.inserted + store.updated for k in row}
        leaked = written & _FORBIDDEN_KEYS
        assert not leaked, f"DB 로 새면 안 되는 필드가 저장됐다: {sorted(leaked)}"

    def test_councilor_gets_staff_not_admin(self, monkeypatch):
        """자동 부여는 staff 까지다 — admin 은 AI 자막 생성(유료)을 실행할 수 있다."""
        store = _UserStore()
        client = _store_client(store, monkeypatch, _UPSTREAM_FULL)
        client.get("/api/auth/qr/sid-1")

        assert store.inserted[0]["role"] == "staff"

    def test_unknown_portal_role_falls_back_to_staff(self, monkeypatch):
        store = _UserStore()
        payload = {**_UPSTREAM_FULL, "role": "ROLE_SOMETHING_NEW"}
        client = _store_client(store, monkeypatch, payload)
        client.get("/api/auth/qr/sid-1")

        assert store.inserted[0]["role"] == "staff"
        # 원문은 그대로 남겨야 나중에 매핑표를 넓힐 수 있다
        assert store.inserted[0]["portal_role"] == "ROLE_SOMETHING_NEW"

    def test_existing_account_keeps_our_role(self, monkeypatch):
        """관리자가 손으로 올려둔 권한이 다음 로그인에 staff 로 되돌아가면 안 된다."""
        existing = _make_user(username="wooni0103")
        existing["role"] = "admin"
        store = _UserStore(users=[existing])
        client = _store_client(store, monkeypatch, _UPSTREAM_FULL)

        body = client.get("/api/auth/qr/sid-1").json()

        assert body["user"]["role"] == "admin"
        assert store.inserted == []
        assert all("role" not in u for u in store.updated), "우리 role 을 덮어썼다"

    def test_existing_account_syncs_profile(self, monkeypatch):
        existing = _make_user(username="wooni0103")
        store = _UserStore(users=[existing])
        client = _store_client(store, monkeypatch, _UPSTREAM_FULL)
        client.get("/api/auth/qr/sid-1")

        merged = {k: v for u in store.updated for k, v in u.items()}
        assert merged["dept_name"] == "공간정보화과"
        assert merged["portal_role"] == "ROLE_COUNCILOR"
        assert "profile_synced_at" in merged
        assert "last_login_at" in merged

    def test_inactive_account_still_blocked(self, monkeypatch):
        """자동 생성이 생겨도 관리자가 막은 계정은 못 들어온다."""
        blocked = _make_user(username="wooni0103", is_active=False)
        store = _UserStore(users=[blocked])
        client = _store_client(store, monkeypatch, _UPSTREAM_FULL)

        body = client.get("/api/auth/qr/sid-1").json()

        assert body["status"] == "unregistered"
        assert store.inserted == []
        assert "access_token" not in body
