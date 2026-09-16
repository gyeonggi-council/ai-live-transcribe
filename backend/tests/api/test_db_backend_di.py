"""DB_BACKEND 기반 리포지토리 DI 계약 테스트.

전환 원칙: Supabase fallback 은 유지하되, DB_BACKEND=postgres 에서는
notifications 라우터가 Supabase 를 전혀 호출하지 않고 PgNotificationRepository
(직접 PostgreSQL)로 응답해야 한다. 기본값(supabase)에서는 기존 REST 경로와
응답이 그대로 유지되고 PostgreSQL engine 도 만들어지지 않아야 한다.
"""

import json
from datetime import datetime, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_supabase
from app.main import app
from tests.conftest import MockSupabaseClient


MEETING_ID = UUID("11111111-1111-1111-1111-111111111111")
NOTIFICATION_ID = UUID("22222222-2222-2222-2222-222222222222")


class _FakeResult:
    """SQLAlchemy Result 의 mappings().all() 경로만 흉내낸다."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> "_FakeResult":
        return self

    def all(self) -> list[dict]:
        return list(self._rows)


class _FakeSession:
    """주입되는 SQL 세션 스텁 — 실행 statement 와 종료 여부를 기록한다."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.statements: list[object] = []
        self.closed = False

    def execute(self, statement, *args, **kwargs) -> _FakeResult:
        self.statements.append(statement)
        return _FakeResult(self._rows)

    def close(self) -> None:
        self.closed = True


def _explode_supabase(*args, **kwargs):
    raise AssertionError("postgres 모드에서는 Supabase 를 호출하면 안 된다")


def _explode_postgres(*args, **kwargs):
    raise AssertionError("supabase 모드에서는 PostgreSQL engine 을 만들면 안 된다")


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def pg_rows() -> list[dict]:
    return [
        {
            "id": NOTIFICATION_ID,
            "type": "stt_completed",
            "title": "STT 완료",
            "message": "자막 생성이 완료되었습니다.",
            "related_meeting_id": MEETING_ID,
            "is_read": False,
            "created_at": datetime(2026, 8, 17, 9, 30, tzinfo=timezone.utc),
        }
    ]


def test_db_backend_defaults_to_supabase(monkeypatch):
    """DB_BACKEND 기본값은 supabase 이며, postgres 일 때만 직접 경로를 쓴다."""
    from app.core import postgres
    from app.core.config import Settings

    assert Settings.model_fields["db_backend"].default == "supabase"

    monkeypatch.setattr(postgres.settings, "db_backend", "supabase")
    assert postgres.is_postgres_backend() is False

    monkeypatch.setattr(postgres.settings, "db_backend", "postgres")
    assert postgres.is_postgres_backend() is True


def test_get_notification_repository_selects_repository_by_session():
    """DI provider 는 PostgreSQL session 이 주어질 때만 Pg 리포지토리를 만든다."""
    from app.api.deps import get_notification_repository
    from app.repositories.notification_repository import (
        NotificationRepository,
        PgNotificationRepository,
    )

    pg_repo = get_notification_repository(session=_FakeSession([]), supabase=None)
    assert isinstance(pg_repo, PgNotificationRepository)

    rest_repo = get_notification_repository(session=None, supabase=MockSupabaseClient())
    assert isinstance(rest_repo, NotificationRepository)


def test_supabase_mode_keeps_rest_path_without_opening_postgres(monkeypatch):
    """기본 모드에서는 기존 Supabase 응답이 유지되고 engine 을 만들지 않는다."""
    from app.core import config, postgres

    monkeypatch.setattr(config.settings, "db_backend", "supabase")
    monkeypatch.setattr(postgres, "get_postgres_session_factory", _explode_postgres)

    row = {
        "id": str(NOTIFICATION_ID),
        "type": "stt_completed",
        "title": "STT 완료",
        "message": "자막 생성이 완료되었습니다.",
        "related_meeting_id": str(MEETING_ID),
        "is_read": False,
        "created_at": "2026-08-17T09:30:00+00:00",
    }
    mock_client = MockSupabaseClient(table_data={"notifications": [row]})
    app.dependency_overrides[get_supabase] = lambda: mock_client

    response = TestClient(app).get("/api/notifications")

    assert response.status_code == 200
    assert response.json() == [row]


def test_postgres_mode_serves_notifications_without_supabase(monkeypatch, pg_rows):
    """postgres 모드는 Supabase 없이 SQL 세션으로 알림을 조회하고 세션을 닫는다."""
    from app.api import deps
    from app.core import config, database, postgres

    session = _FakeSession(pg_rows)

    monkeypatch.setattr(config.settings, "db_backend", "postgres")
    # 어떤 경로로도 Supabase 에 진입하면 즉시 실패한다 (클라이언트 생성·네트워크 금지).
    monkeypatch.setattr(deps, "get_supabase", _explode_supabase)
    monkeypatch.setattr(database, "get_supabase_client", _explode_supabase)
    monkeypatch.setattr(postgres, "get_postgres_session_factory", lambda: lambda: session)

    response = TestClient(app).get("/api/notifications?limit=5")

    assert response.status_code == 200
    body = response.json()
    json.dumps(body)  # 직렬화 불가 타입이 남아 있으면 TypeError
    assert len(body) == 1
    assert body[0]["id"] == str(NOTIFICATION_ID)
    assert body[0]["related_meeting_id"] == str(MEETING_ID)
    assert body[0]["created_at"].startswith("2026-08-17T09:30:00")

    # 조회는 SQL 로 수행되고, request-scoped 세션은 응답 후 닫힌다.
    assert len(session.statements) == 1
    sql = str(session.statements[0]).lower()
    assert "notifications" in sql
    assert "order by" in sql
    assert session.closed is True
