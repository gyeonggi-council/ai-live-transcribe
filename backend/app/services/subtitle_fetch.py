"""회의 자막 전량 조회 — 한 곳에서(2026-09-14).

PostgREST 는 한 번에 최대 1,000행만 준다. 이전에는 같은 페이지 루프가 세 곳(speaker_segments·exports·agenda_draft_service)에
따로 있었고 AI 대화·요약은 그마저 안 써서 긴 회의의 뒷부분이 조용히 사라졌다. 이제 자막 전량이 필요하면 여기를 부른다.

★ select 에 'kind' 가 있어야 prefer_ai_subtitles 가 동작한다(기본 select 에 포함).
★ 보조 정렬 id — start_time 이 같은 행의 순서가 페이지 사이에서 흔들리지 않게(Codex 검토 2026-09-14).
"""

from __future__ import annotations

from supabase import Client

PAGE_SIZE = 1000
DEFAULT_SELECT = "id, start_time, end_time, text, speaker, kind"


def fetch_all_subtitles(supabase: Client, meeting_id: str, select: str = DEFAULT_SELECT) -> list[dict]:
    """회의 자막 전체를 start_time(보조 id) 순으로 — 1000행 초과 대비 range 페이지네이션."""
    rows: list[dict] = []
    offset = 0
    while True:
        result = (
            supabase.table("subtitles")
            .select(select)
            .eq("meeting_id", meeting_id)
            .order("start_time")
            .order("id")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        data = result.data or []
        rows.extend(data)
        if len(data) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows
