"""PgNotificationRepository 계약 테스트 (직접 PostgreSQL 접근)

Supabase REST가 아니라 주입된 SQL 세션으로 notifications를 조회하는
목표 리포지토리 계약을 검증한다. 세션은 최소 페이크로 대체하고,
- 반환 행이 JSON 직렬화 가능한 dict 인지
- 정렬이 리포지토리가 아니라 SQL(created_at DESC)에서 이뤄지는지
를 확인한다.
"""

import json
from datetime import datetime, timezone
from uuid import UUID

MEETING_ID = UUID("11111111-1111-1111-1111-111111111111")


class _FakeResult:
    """SQLAlchemy Result 의 mappings().all() 경로만 흉내낸다."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> "_FakeResult":
        return self

    def all(self) -> list[dict]:
        return list(self._rows)


class _FakeSession:
    """주입되는 SQL 세션 스텁 — 실행된 statement 를 기록한다."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.statements: list[object] = []

    def execute(self, statement, *args, **kwargs) -> _FakeResult:
        self.statements.append(statement)
        return _FakeResult(self._rows)


def test_list_returns_json_safe_rows_ordered_by_created_at():
    from app.repositories.notification_repository import PgNotificationRepository

    db_rows = [
        {
            "id": UUID("22222222-2222-2222-2222-222222222222"),
            "type": "stt_completed",
            "title": "STT 완료",
            "message": "자막 생성이 완료되었습니다.",
            "related_meeting_id": MEETING_ID,
            "is_read": False,
            "created_at": datetime(2026, 8, 17, 9, 30, tzinfo=timezone.utc),
        },
        {
            "id": UUID("33333333-3333-3333-3333-333333333333"),
            "type": "stt_failed",
            "title": "STT 실패",
            "message": "자막 생성에 실패했습니다.",
            "related_meeting_id": MEETING_ID,
            "is_read": True,
            "created_at": datetime(2026, 8, 17, 8, 0, tzinfo=timezone.utc),
        },
    ]
    session = _FakeSession(db_rows)

    rows = PgNotificationRepository(session).list(limit=50)

    # 1) 순수 dict 목록이며 JSON 직렬화가 가능해야 한다 (UUID/datetime 변환 완료)
    assert isinstance(rows, list)
    assert all(type(row) is dict for row in rows)
    json.dumps(rows)  # 직렬화 불가 타입이 남아 있으면 TypeError

    assert rows[0]["id"] == "22222222-2222-2222-2222-222222222222"
    assert rows[0]["related_meeting_id"] == str(MEETING_ID)
    assert rows[0]["created_at"].startswith("2026-08-17T09:30:00")
    assert rows[0]["is_read"] is False

    # 2) 정렬은 파이썬이 아니라 SQL 이 담당한다 (created_at 내림차순 + limit)
    assert len(session.statements) == 1
    sql = str(session.statements[0]).lower()
    assert "notifications" in sql
    assert "order by" in sql
    assert "created_at" in sql
    assert "desc" in sql
