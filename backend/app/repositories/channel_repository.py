"""채널 리포지토리 — subtitle.channels 테이블 접근 전담 (2026-09-16)

계층화 규약: .table() 호출은 여기만, .single() 금지, 예외는 전파.

채널은 집계가 없어 SQL 뷰가 필요 없다(PostgREST 의 GROUP BY 제약과 무관).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from supabase import Client

TABLE = "channels"

# 조회 컬럼을 명시한다 — `*` 를 쓰면 나중에 컬럼이 늘 때 API 응답에 조용히 새 필드가 샌다.
COLUMNS = (
    "id, name, code, stream_url, committee, page_url, status_provider, "
    "provider_config, manual_status, manual_until, sort_order, is_active, is_test, "
    "created_at, updated_at"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChannelRepository:
    def __init__(self, supabase: Client) -> None:
        self._db = supabase

    def list_all(self) -> list[dict]:
        """비활성 채널도 포함한 전량. 정렬은 sort_order → id.

        비활성을 여기서 거르지 않는 이유: 지난 회의의 위원회명을 되살리려면
        `get_channel()` 이 삭제된 채널도 찾을 수 있어야 한다(soft delete).
        """
        result = (
            self._db.table(TABLE)
            .select(COLUMNS)
            .order("sort_order")
            .order("id")
            .execute()
        )
        return result.data or []

    def get(self, channel_id: str) -> Optional[dict]:
        result = (
            self._db.table(TABLE).select(COLUMNS).eq("id", channel_id).limit(1).execute()
        )
        data = result.data or []
        return data[0] if data else None

    def get_by_code(self, code: str) -> Optional[dict]:
        result = self._db.table(TABLE).select(COLUMNS).eq("code", code).limit(1).execute()
        data = result.data or []
        return data[0] if data else None

    def create(self, row: dict[str, Any]) -> dict:
        payload = {**row, "created_at": _now_iso(), "updated_at": _now_iso()}
        result = self._db.table(TABLE).insert(payload).execute()
        data = result.data or []
        return data[0] if data else payload

    def update(self, channel_id: str, patch: dict[str, Any]) -> Optional[dict]:
        payload = {**patch, "updated_at": _now_iso()}
        result = (
            self._db.table(TABLE).update(payload).eq("id", channel_id).execute()
        )
        data = result.data or []
        return data[0] if data else None

    def soft_delete(self, channel_id: str) -> Optional[dict]:
        return self.update(channel_id, {"is_active": False})

    def delete(self, channel_id: str) -> None:
        self._db.table(TABLE).delete().eq("id", channel_id).execute()
