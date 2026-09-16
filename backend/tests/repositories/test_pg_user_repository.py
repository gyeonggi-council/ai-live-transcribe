"""직접 PostgreSQL users 조회 리포지토리 계약 테스트."""

from datetime import datetime, timezone
from uuid import UUID


class _Result:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> "_Result":
        return self

    def first(self) -> dict | None:
        return self._rows[0] if self._rows else None


class _Session:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.statements: list[object] = []

    def execute(self, statement, *args, **kwargs) -> _Result:
        self.statements.append(statement)
        return _Result(self.rows)


def test_get_active_user_by_id_returns_json_safe_row_and_filters_activity():
    from app.repositories.user_repository import PgUserRepository

    user_id = UUID("11111111-1111-1111-1111-111111111111")
    session = _Session(
        [
            {
                "id": user_id,
                "username": "operator",
                "display_name": "운영자",
                "role": "admin",
                "is_active": True,
                "last_login_at": datetime(2026, 8, 17, 9, tzinfo=timezone.utc),
            }
        ]
    )

    user = PgUserRepository(session).get_active_by_id(str(user_id))

    assert user is not None
    assert user["id"] == str(user_id)
    assert user["last_login_at"].startswith("2026-08-17T09:00:00")
    sql = str(session.statements[0]).lower()
    assert "users" in sql
    assert "is_active" in sql
