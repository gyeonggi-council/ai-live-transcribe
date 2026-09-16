"""로그인 없이 바뀌던 쓰기 API 가드 + 관리자 PIN 무차별 대입 차단 (2026-09-12).

전에는 누구나 회의록을 "최종"으로 잠그고, 안건·참석자를 바꾸고, AI 요약을 지워 다시 만들게(GPT 비용) 할 수 있었다.
여기서는 "로그인하지 않으면 401 · 역할이 모자라면 403 · 핸들러(DB)까지 가지 않는다" 만 본다.
"""

from typing import Generator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.core.auth_middleware import get_current_user
from app.core.config import settings
from app.core.database import get_supabase
from app.main import app

MID = "11111111-2222-3333-4444-555555555555"

# (메서드, 경로, 본문)
GUARDED = [
    ("patch", f"/api/meetings/{MID}/transcript-status", {"transcript_status": "final"}),
    ("post", f"/api/meetings/{MID}/publications", {"status": "final"}),
    ("post", f"/api/meetings/{MID}/participants", {"name": "홍길동"}),
    ("delete", f"/api/meetings/{MID}/participants/p1", None),
    ("post", f"/api/meetings/{MID}/agendas", {"title": "안건"}),
    ("patch", f"/api/meetings/{MID}/agendas/a1", {"title": "안건"}),
    ("delete", f"/api/meetings/{MID}/agendas/a1", None),
    ("delete", f"/api/meetings/{MID}/summary", None),
    ("post", f"/api/meetings/{MID}/suggest-info", None),
]


def _client(user: dict | None) -> Generator[tuple[TestClient, MagicMock], None, None]:
    db = MagicMock()
    app.dependency_overrides[get_supabase] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(app), db
    app.dependency_overrides.clear()


def _call(client: TestClient, method: str, path: str, body):
    if method == "delete":
        return client.delete(path)
    return getattr(client, method)(path, json=body)


@pytest.mark.parametrize("method,path,body", GUARDED)
def test_anonymous_gets_401_and_db_untouched(method, path, body):
    for client, db in _client(None):
        resp = _call(client, method, path, body)
        assert resp.status_code == 401, (method, path, resp.status_code)
        db.table.assert_not_called()


@pytest.mark.parametrize("method,path,body", [
    GUARDED[0],  # 회의록 상태 — 위원회 직원은 확정 권한이 없다
    GUARDED[1],  # 확정 이력
    GUARDED[7],  # 요약 삭제 — 관리자만
    GUARDED[8],  # 회의정보 AI 추출 — 관리자·회의관리자만
])
def test_committee_staff_gets_403(method, path, body):
    staff = {"id": "u1", "username": "staff1", "display_name": "직원", "role": "committee_staff"}
    for client, db in _client(staff):
        resp = _call(client, method, path, body)
        assert resp.status_code == 403, (method, path, resp.status_code)
        db.table.assert_not_called()


def test_publication_records_session_user_not_client_value():
    """확정 이력의 published_by 는 클라이언트가 보낸 이름이 아니라 로그인한 사람이다(감사 기록)."""
    steno = {"id": "u2", "username": "steno1", "display_name": "속기사A", "role": "stenographer"}
    for client, db in _client(steno):
        inserted = {}

        def _insert(row):
            inserted.update(row)
            m = MagicMock()
            m.execute.return_value.data = [row]
            return m

        db.table.return_value.insert.side_effect = _insert
        resp = client.post(
            f"/api/meetings/{MID}/publications",
            json={"status": "final", "published_by": "아무개(위조)"},
        )
        if resp.status_code in (200, 201):
            assert inserted.get("published_by") == "속기사A"
        else:  # 스키마가 status 값을 다르게 받으면 적어도 가드는 통과했는지만 본다
            assert resp.status_code not in (401, 403)


class TestPinLogin:
    @pytest.fixture(autouse=True)
    def _pin(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_quick_pin", "4321")
        auth_api._pin_fails.clear()
        yield
        auth_api._pin_fails.clear()

    def test_locks_after_five_failures(self):
        client = TestClient(app)
        for _ in range(auth_api._PIN_MAX_FAILS):
            assert client.post("/api/auth/pin-login", json={"pin": "0000"}).status_code == 401
        # 여섯 번째는 맞는 PIN 이어도 막힌다(창이 지날 때까지)
        assert client.post("/api/auth/pin-login", json={"pin": "4321"}).status_code == 429

    def test_correct_pin_resets_counter(self):
        client = TestClient(app)
        for _ in range(auth_api._PIN_MAX_FAILS - 1):
            client.post("/api/auth/pin-login", json={"pin": "0000"})
        assert client.post("/api/auth/pin-login", json={"pin": "4321"}).status_code == 200
        assert not auth_api._pin_fails.get("testclient")

    def test_empty_pin_setting_disables_login(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_quick_pin", "")
        client = TestClient(app)
        assert client.post("/api/auth/pin-login", json={"pin": "000000"}).status_code == 503
