"""자막 리포지토리 — subtitles 테이블 Supabase 접근 전담"""

from supabase import Client


class SubtitleRepository:
    """subtitles 테이블 쿼리 모음.

    기존 라우터의 쿼리 패턴(컬럼 문자열·체인 순서)을 그대로 미러링한다.
    예외는 전파하며, 폴백/HTTP 매핑은 호출자 소관.
    """

    def __init__(self, supabase: Client) -> None:
        self._db = supabase

    # -------------------------------------------------------------- 조회
    def count_by_meeting(self, meeting_id: str) -> int:
        result = (
            self._db.table("subtitles")
            .select("id", count="exact")
            .eq("meeting_id", meeting_id)
            .execute()
        )
        return result.count or 0

    def list_by_meeting(self, meeting_id: str, limit: int, offset: int) -> list[dict]:
        result = (
            self._db.table("subtitles")
            .select("*")
            .eq("meeting_id", meeting_id)
            .order("start_time")
            .range(offset, offset + limit - 1)
            .execute()
        )
        return result.data

    def list_all_ordered(self, meeting_id: str) -> list[dict]:
        result = (
            self._db.table("subtitles")
            .select("*")
            .eq("meeting_id", meeting_id)
            .order("start_time")
            .execute()
        )
        return result.data

    def list_id_text(
        self, meeting_id: str, subtitle_ids: list[str] | None = None
    ) -> list[dict]:
        query = self._db.table("subtitles").select("id, text").eq("meeting_id", meeting_id)
        if subtitle_ids:
            query = query.in_("id", subtitle_ids)
        result = query.order("start_time").execute()
        return result.data

    def list_speaker_lines(self, meeting_id: str, limit: int = 100) -> list[dict]:
        result = (
            self._db.table("subtitles")
            .select("text, speaker, start_time")
            .eq("meeting_id", meeting_id)
            .order("start_time")
            .limit(limit)
            .execute()
        )
        return result.data

    def count_search(self, meeting_id: str, term: str) -> int:
        result = (
            self._db.table("subtitles")
            .select("id", count="exact")
            .eq("meeting_id", meeting_id)
            .ilike("text", f"%{term}%")
            .execute()
        )
        return result.count or 0

    def search(self, meeting_id: str, term: str, limit: int, offset: int) -> list[dict]:
        result = (
            self._db.table("subtitles")
            .select("*")
            .eq("meeting_id", meeting_id)
            .ilike("text", f"%{term}%")
            .order("start_time")
            .range(offset, offset + limit - 1)
            .execute()
        )
        return result.data

    def get(self, subtitle_id: str, meeting_id: str) -> dict | None:
        result = (
            self._db.table("subtitles")
            .select("*")
            .eq("id", subtitle_id)
            .eq("meeting_id", meeting_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def get_by_id(self, subtitle_id: str) -> dict | None:
        result = (
            self._db.table("subtitles")
            .select("*")
            .eq("id", subtitle_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def get_text(self, subtitle_id: str, meeting_id: str) -> dict | None:
        result = (
            self._db.table("subtitles")
            .select("text")
            .eq("id", subtitle_id)
            .eq("meeting_id", meeting_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    # -------------------------------------------------------------- 변경
    # result.data(list)를 그대로 반환해 "빈 리스트 → 404" 판정을 호출자가 유지한다.
    def update(
        self, subtitle_id: str, data: dict, meeting_id: str | None = None
    ) -> list[dict]:
        query = self._db.table("subtitles").update(data).eq("id", subtitle_id)
        if meeting_id is not None:
            query = query.eq("meeting_id", meeting_id)
        result = query.execute()
        return result.data

    def insert(self, data: dict) -> list[dict]:
        result = self._db.table("subtitles").insert(data).execute()
        return result.data

    def insert_many(self, rows: list[dict]) -> list[dict]:
        result = self._db.table("subtitles").insert(rows).execute()
        return result.data

    def delete(self, subtitle_id: str) -> None:
        self._db.table("subtitles").delete().eq("id", subtitle_id).execute()

    def delete_by_meeting(self, meeting_id: str, kind: str | None = None) -> None:
        """회의의 자막을 삭제한다.

        kind 를 주면 그 종류만 지운다. AI 자막 재생성처럼 '한 종류를 갈아끼우는'
        작업은 반드시 kind='ai' 로 호출해야 한다 — 안 그러면 실시간 자막(초안)까지
        사라져 회의 상세의 '실시간 자막(초안)' 탭이 영구히 빈다.
        """
        query = self._db.table("subtitles").delete().eq("meeting_id", meeting_id)
        if kind:
            query = query.eq("kind", kind)
        query.execute()
