"""알림 리포지토리 — notifications 테이블 Supabase 접근 전담"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, Column, DateTime, MetaData, String, Table, Text, select
from sqlalchemy.orm import Session
from supabase import Client


_notification_metadata = MetaData()
_notifications = Table(
    "notifications",
    _notification_metadata,
    Column("id"),
    Column("type", String),
    Column("title", String),
    Column("message", Text),
    Column("related_meeting_id"),
    Column("is_read", Boolean),
    Column("created_at", DateTime(timezone=True)),
)


def _json_safe(value: Any) -> Any:
    """PostgreSQL 행 값을 기존 REST 응답과 같은 JSON-safe 형태로 바꿉니다."""
    if isinstance(value, (UUID, datetime, date)):
        return str(value) if isinstance(value, UUID) else value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


class PgNotificationRepository:
    """직접 PostgreSQL session을 사용하는 notifications 리포지토리.

    전환 기간에는 기존 NotificationRepository와 병행하며, 반환 형태는 REST
    클라이언트와 호환되는 JSON-safe dict 목록으로 고정합니다.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def list(self, limit: int, is_read: bool | None = None) -> list[dict[str, Any]]:
        statement = select(_notifications).order_by(_notifications.c.created_at.desc()).limit(limit)
        if is_read is not None:
            statement = statement.where(_notifications.c.is_read.is_(is_read))
        rows = self._session.execute(statement).mappings().all()
        return [_json_safe(dict(row)) for row in rows]


class NotificationRepository:
    def __init__(self, supabase: Client) -> None:
        self._db = supabase

    def insert(self, data: dict) -> list[dict]:
        result = self._db.table("notifications").insert(data).execute()
        return result.data

    def list(self, limit: int, is_read: bool | None = None) -> list[dict]:
        query = (
            self._db.table("notifications")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
        )
        if is_read is not None:
            query = query.eq("is_read", is_read)
        result = query.execute()
        return result.data or []

    def mark_read(self, notification_id: str) -> list[dict]:
        result = (
            self._db.table("notifications")
            .update({"is_read": True})
            .eq("id", notification_id)
            .execute()
        )
        return result.data
