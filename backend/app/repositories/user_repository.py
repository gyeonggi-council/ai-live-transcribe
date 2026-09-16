"""직접 PostgreSQL users 접근 리포지토리."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, Column, MetaData, String, Table, select
from sqlalchemy.orm import Session

from app.repositories.notification_repository import _json_safe


_user_metadata = MetaData()
_users = Table(
    "users",
    _user_metadata,
    Column("id"),
    Column("username", String),
    Column("password_hash", String),
    Column("display_name", String),
    Column("role", String),
    Column("assigned_committee", String),
    Column("is_active", Boolean),
    Column("last_login_at"),
)


class PgUserRepository:
    """JWT payload의 사용자 ID를 private PostgreSQL 사용자 레코드에 매핑합니다."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_active_by_id(self, user_id: str) -> dict[str, Any] | None:
        statement = select(_users).where(
            _users.c.id == user_id,
            _users.c.is_active.is_(True),
        )
        row = self._session.execute(statement).mappings().first()
        return _json_safe(dict(row)) if row is not None else None
