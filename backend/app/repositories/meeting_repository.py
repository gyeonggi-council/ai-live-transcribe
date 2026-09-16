"""회의 리포지토리 — meetings 애그리거트 (meetings + meeting_agendas
+ meeting_participants + transcript_publications) Supabase 접근 전담"""

from __future__ import annotations

from supabase import Client


class MeetingRepository:
    """meetings 및 자식 테이블 쿼리 모음.

    예외를 잡지 않는다 — 채널 정적 폴백 정책은 services/meeting_service.py 소관.
    """

    def __init__(self, supabase: Client) -> None:
        self._db = supabase

    # -------------------------------------------------------------- meetings
    def list(
        self,
        status_values: list[str] | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> list[dict]:
        query = self._db.table("meetings").select("*")
        if status_values:
            query = query.in_("status", status_values)
        query = query.order("meeting_date", desc=True)
        query = query.range(offset, offset + limit - 1)
        result = query.execute()
        return result.data

    def find_live_by_channel(self, channel_id: str) -> dict | None:
        result = (
            self._db.table("meetings")
            .select("*")
            .eq("channel_id", channel_id)
            .eq("status", "live")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def find_recent_finished_by_channel(self, channel_id: str) -> dict | None:
        result = (
            self._db.table("meetings")
            .select("*")
            .eq("channel_id", channel_id)
            .in_("status", ["ended", "processing"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def find_any_live(self) -> dict | None:
        result = (
            self._db.table("meetings")
            .select("*")
            .eq("status", "live")
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def get_by_id(self, meeting_id: str) -> dict | None:
        result = (
            self._db.table("meetings")
            .select("*")
            .eq("id", meeting_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def find_by_vod_url(self, vod_url: str) -> dict | None:
        result = (
            self._db.table("meetings")
            .select("id,title,meeting_date")
            .eq("vod_url", vod_url)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def insert(self, data: dict) -> dict:
        result = self._db.table("meetings").insert(data).execute()
        return result.data[0]

    def update(self, meeting_id: str, data: dict) -> list[dict]:
        result = (
            self._db.table("meetings")
            .update(data)
            .eq("id", meeting_id)
            .execute()
        )
        return result.data

    # -------------------------------------------------------------- meeting_agendas
    def list_agendas(self, meeting_id: str) -> list[dict]:
        result = (
            self._db.table("meeting_agendas")
            .select("*")
            .eq("meeting_id", meeting_id)
            .order("order_num")
            .execute()
        )
        return result.data

    def insert_agenda(self, data: dict) -> list[dict]:
        result = self._db.table("meeting_agendas").insert(data).execute()
        return result.data

    def update_agenda(self, agenda_id: str, meeting_id: str, data: dict) -> list[dict]:
        result = (
            self._db.table("meeting_agendas")
            .update(data)
            .eq("id", agenda_id)
            .eq("meeting_id", meeting_id)
            .execute()
        )
        return result.data

    def delete_agenda(self, agenda_id: str, meeting_id: str) -> list[dict]:
        result = (
            self._db.table("meeting_agendas")
            .delete()
            .eq("id", agenda_id)
            .eq("meeting_id", meeting_id)
            .execute()
        )
        return result.data

    # -------------------------------------------------------------- meeting_participants
    def list_participants(self, meeting_id: str) -> list[dict]:
        result = (
            self._db.table("meeting_participants")
            .select("*")
            .eq("meeting_id", meeting_id)
            .order("created_at")
            .execute()
        )
        return result.data

    def insert_participant(self, data: dict) -> list[dict]:
        # unique 제약 위반 등 예외는 그대로 전파 — 409 매핑은 라우터 소관
        result = self._db.table("meeting_participants").insert(data).execute()
        return result.data

    def delete_participant(self, participant_id: str, meeting_id: str) -> list[dict]:
        result = (
            self._db.table("meeting_participants")
            .delete()
            .eq("id", participant_id)
            .eq("meeting_id", meeting_id)
            .execute()
        )
        return result.data

    # -------------------------------------------------------------- transcript_publications
    def list_publications(self, meeting_id: str) -> list[dict]:
        result = (
            self._db.table("transcript_publications")
            .select("*")
            .eq("meeting_id", meeting_id)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data

    def insert_publication(self, data: dict) -> list[dict]:
        result = self._db.table("transcript_publications").insert(data).execute()
        return result.data
