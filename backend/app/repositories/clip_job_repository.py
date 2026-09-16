"""클립 잡 리포지토리 — clip_jobs 테이블(+ meetings 의 클립 관련 컬럼) 접근 전담

계층화 규약: .table() 호출은 여기만, .single() 금지, 예외는 전파.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from supabase import Client

TABLE = "clip_jobs"
ACTIVE_STATUSES = ("queued", "running")
MEETING_COLUMNS = ("id, title, meeting_date, vod_url, kms_midx, duration_seconds, "
                   "committee, channel_id, clip_time_offset, status, subtitle_stage")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ClipJobRepository:
    def __init__(self, supabase: Client) -> None:
        self._db = supabase

    @property
    def client(self) -> Client:
        """SRT 생성 등 다른 서비스가 같은 클라이언트를 재사용할 때."""
        return self._db

    # ------------------------------------------------------------------ jobs
    def insert(self, row: dict) -> dict:
        result = self._db.table(TABLE).insert(row).execute()
        data = result.data or []
        return data[0] if data else row

    def get(self, job_id: str) -> Optional[dict]:
        result = self._db.table(TABLE).select("*").eq("id", job_id).limit(1).execute()
        data = result.data or []
        return data[0] if data else None

    def update(self, job_id: str, patch: dict) -> Optional[dict]:
        result = self._db.table(TABLE).update(patch).eq("id", job_id).execute()
        data = result.data or []
        return data[0] if data else None

    def list_for_owner(self, owner_user_id: Optional[str], owner_username: str, *,
                       since_iso: str, limit: int, offset: int,
                       meeting_id: Optional[str] = None) -> list[dict]:
        q = self._db.table(TABLE).select("*")
        if owner_user_id:
            q = q.eq("owner_user_id", owner_user_id)
        else:
            q = q.eq("owner_username", owner_username)
        if meeting_id:
            q = q.eq("meeting_id", meeting_id)
        result = (q.gte("created_at", since_iso)
                   .order("created_at", desc=True)
                   .range(offset, offset + limit - 1)
                   .execute())
        return result.data or []

    def list_all(self, *, since_iso: str, limit: int, offset: int,
                 meeting_id: Optional[str] = None) -> list[dict]:
        q = self._db.table(TABLE).select("*")
        if meeting_id:
            q = q.eq("meeting_id", meeting_id)
        result = (q.gte("created_at", since_iso)
                   .order("created_at", desc=True)
                   .range(offset, offset + limit - 1)
                   .execute())
        return result.data or []

    def list_active(self, origin: Optional[str] = None) -> list[dict]:
        """대기·실행 중 잡. origin 을 주면 그쪽만 — api 파드는 manual, 자동 클립 작업자는 auto 만 돌린다."""
        q = self._db.table(TABLE).select("*").in_("status", list(ACTIVE_STATUSES))
        if origin:
            q = q.eq("origin", origin)
        result = q.order("created_at").execute()
        return result.data or []

    # ------------------------------------------------------------ auto (031)
    def next_queued_auto(self) -> Optional[dict]:
        result = (self._db.table(TABLE).select("*")
                  .eq("origin", "auto").eq("status", "queued")
                  .order("created_at").limit(1).execute())
        data = result.data or []
        return data[0] if data else None

    def meetings_with_auto_jobs(self, meeting_ids: list[str]) -> set[str]:
        """자동 잡이 한 번이라도 만들어진 회의(상태 무관 — 만료돼도 다시 만들지 않는다)."""
        ids = sorted({str(m) for m in meeting_ids if m})
        if not ids:
            return set()
        result = (self._db.table(TABLE).select("meeting_id")
                  .eq("origin", "auto").in_("meeting_id", ids).execute())
        return {str(r["meeting_id"]) for r in (result.data or []) if r.get("meeting_id")}

    def list_auto(self, *, meeting_id: Optional[str] = None, since_iso: Optional[str] = None,
                  limit: int = 500) -> list[dict]:
        q = self._db.table(TABLE).select("*").eq("origin", "auto")
        if meeting_id:
            q = q.eq("meeting_id", meeting_id)
        if since_iso:
            q = q.gte("created_at", since_iso)
        result = q.order("created_at", desc=True).limit(limit).execute()
        return result.data or []

    def list_auto_candidate_meetings(self, since_date: str) -> list[dict]:
        """자동 클립 대상 회의 — AI 자막 완료(검토본 포함) + VOD + 종료 + 기간 안. 오래된 회의부터."""
        result = (self._db.table("meetings").select(MEETING_COLUMNS)
                  .not_.is_("vod_url", "null")
                  .eq("status", "ended")
                  .in_("subtitle_stage", ["ai", "reviewing", "final"])
                  .gte("meeting_date", since_date)
                  .order("meeting_date").limit(200).execute())
        return result.data or []

    def list_evictable(self) -> list[dict]:
        """완료됐고 아직 파일이 있는 잡 — 오래된 순."""
        result = (self._db.table(TABLE).select("*")
                  .eq("status", "done")
                  .is_("evicted_at", "null")
                  .order("created_at")
                  .execute())
        return result.data or []

    def count_active(self) -> tuple[int, int]:
        rows = self.list_active()
        running = sum(1 for r in rows if r.get("status") == "running")
        queued = sum(1 for r in rows if r.get("status") == "queued")
        return running, queued

    def mark_evicted(self, job_id: str, reason: str) -> None:
        self.update(job_id, {
            "status": "expired",
            "evicted_at": _now_iso(),
            "evicted_reason": reason,
            "files": [],
            "bytes_total": 0,
        })

    # -------------------------------------------------------------- meetings
    def get_meeting(self, meeting_id: str) -> Optional[dict]:
        result = (self._db.table("meetings").select(MEETING_COLUMNS)
                  .eq("id", meeting_id).limit(1).execute())
        data = result.data or []
        return data[0] if data else None

    def get_meeting_by_midx(self, midx: str) -> Optional[dict]:
        result = (self._db.table("meetings").select(MEETING_COLUMNS)
                  .eq("kms_midx", str(midx)).limit(1).execute())
        data = result.data or []
        return data[0] if data else None

    def get_meetings_brief(self, meeting_ids: list[str]) -> dict[str, dict]:
        ids = sorted({str(m) for m in meeting_ids if m})
        if not ids:
            return {}
        result = (self._db.table("meetings").select("id, title, meeting_date")
                  .in_("id", ids).execute())
        return {str(r["id"]): r for r in (result.data or []) if r.get("id")}

    def set_meeting_offset(self, meeting_id: str, offset: float) -> None:
        self._db.table("meetings").update({
            "clip_time_offset": float(offset),
            "clip_time_offset_updated_at": _now_iso(),
        }).eq("id", meeting_id).execute()
