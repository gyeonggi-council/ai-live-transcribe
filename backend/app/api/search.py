"""Global Search API router (Supabase REST)

# @TASK P5-T3.1 - 통합 검색 API
# @SPEC docs/planning/02-trd.md#통합-검색-API

subtitles 테이블 텍스트 검색 + meetings 정보를 2단계 조회로 결합합니다.
Supabase REST에서는 직접 JOIN이 안되므로:
  1. (날짜 필터 있으면) meetings 먼저 조회 -> meeting_id 목록 확보
  2. subtitles ILIKE 검색 + speaker/meeting_id 필터
  3. 결과의 meeting_id로 meetings 재조회 -> 제목/날짜 매핑
"""

import logging

from fastapi import APIRouter, Depends, Query
from supabase import Client

from app.core.database import get_supabase

logger = logging.getLogger(__name__)

router = APIRouter(tags=["search"])


# @TASK P5-T3.1 - 통합 검색 엔드포인트
# @TEST tests/api/test_search.py
@router.get("/search", summary="통합 검색")
async def global_search(
    q: str = Query(..., min_length=1, description="검색어"),
    date_from: str | None = Query(None, description="시작일 (YYYY-MM-DD)"),
    date_to: str | None = Query(None, description="종료일 (YYYY-MM-DD)"),
    speaker: str | None = Query(None, description="화자 필터"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    supabase: Client = Depends(get_supabase),
) -> dict:
    """자막 텍스트를 검색하고, 각 결과에 회의 정보를 포함하여 반환합니다.

    - subtitles.text ILIKE 검색
    - speaker 필터 (선택)
    - date_from / date_to 날짜 범위 필터 (선택, meetings 테이블 기준)
    - 각 결과에 meeting_title, meeting_date 포함
    """
    search_term = q.strip()

    # ------------------------------------------------------------------
    # Step 1: 날짜 필터가 있으면 meetings를 먼저 조회하여 meeting_id 목록 확보
    # ------------------------------------------------------------------
    meeting_id_filter: list[str] | None = None

    if date_from or date_to:
        meetings_query = supabase.table("meetings").select("id, title, meeting_date")

        if date_from:
            meetings_query = meetings_query.gte("meeting_date", date_from)
        if date_to:
            meetings_query = meetings_query.lte("meeting_date", date_to)

        meetings_for_filter = meetings_query.execute()
        meeting_id_filter = [m["id"] for m in meetings_for_filter.data]

        # 날짜 범위에 해당하는 회의가 없으면 빈 결과 즉시 반환
        if not meeting_id_filter:
            return {
                "items": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
                "query": search_term,
            }

    # ------------------------------------------------------------------
    # Step 2: subtitles 검색 (count 조회)
    # ------------------------------------------------------------------
    count_query = (
        supabase.table("subtitles")
        .select("id", count="exact")
        .ilike("text", f"%{search_term}%")
    )
    if speaker:
        count_query = count_query.eq("speaker", speaker)
    if meeting_id_filter is not None:
        count_query = count_query.in_("meeting_id", meeting_id_filter)

    count_result = count_query.execute()
    total = count_result.count or 0

    # ------------------------------------------------------------------
    # Step 3: subtitles 검색 (데이터 조회 + 페이지네이션)
    # ------------------------------------------------------------------
    data_query = (
        supabase.table("subtitles")
        .select("*")
        .ilike("text", f"%{search_term}%")
    )
    if speaker:
        data_query = data_query.eq("speaker", speaker)
    if meeting_id_filter is not None:
        data_query = data_query.in_("meeting_id", meeting_id_filter)

    data_query = data_query.order("start_time").range(offset, offset + limit - 1)
    subtitle_result = data_query.execute()

    # 결과가 없으면 빈 응답
    if not subtitle_result.data:
        return {
            "items": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
            "query": search_term,
        }

    # ------------------------------------------------------------------
    # Step 4: 검색된 자막의 meeting_id들로 meetings 조회
    # ------------------------------------------------------------------
    unique_meeting_ids = list({sub["meeting_id"] for sub in subtitle_result.data})

    meetings_result = (
        supabase.table("meetings")
        .select("id, title, meeting_date")
        .in_("id", unique_meeting_ids)
        .execute()
    )
    meetings_map: dict[str, dict] = {
        m["id"]: m for m in meetings_result.data
    }

    # ------------------------------------------------------------------
    # Step 5: 결과 합치기
    # ------------------------------------------------------------------
    items = []
    for sub in subtitle_result.data:
        meeting = meetings_map.get(sub["meeting_id"], {})
        items.append({
            "subtitle_id": sub["id"],
            "meeting_id": sub["meeting_id"],
            "meeting_title": meeting.get("title", ""),
            "meeting_date": meeting.get("meeting_date", ""),
            "text": sub["text"],
            "start_time": sub["start_time"],
            "end_time": sub["end_time"],
            "speaker": sub.get("speaker"),
            "confidence": sub.get("confidence"),
        })

    logger.info(
        "통합 검색: q=%r, total=%d, returned=%d (speaker=%s, date_from=%s, date_to=%s)",
        search_term,
        total,
        len(items),
        speaker,
        date_from,
        date_to,
    )

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "query": search_term,
    }
