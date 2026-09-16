"""Minutes API 라우터 - 안건별 자막 분류

# @TASK P10-T2.1 - 안건별 자막 분류 API 엔드포인트
# @SPEC docs/planning/02-trd.md#회의록-작성

회의록 작성을 위한 안건별 자막 분류 엔드포인트를 제공합니다.
"""

import logging

from fastapi import APIRouter, Depends
from supabase import Client

from app.core.database import get_supabase
from app.services.minutes_service import classify_subtitles_by_agenda
from app.services.subtitle_select import prefer_ai_subtitles

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meetings", tags=["minutes"])


# @TASK P10-T2.1 - 안건별 자막 분류 엔드포인트
@router.get(
    "/{meeting_id}/minutes/by-agenda",
    summary="안건별 자막 분류 조회",
)
async def get_minutes_by_agenda(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
) -> dict:
    """회의의 안건별로 자막을 시간대에 따라 분류하여 반환합니다.

    - 안건이 있는 경우: 안건 간 시간 구간으로 자막을 분류
    - 안건이 없는 경우: 전체 자막을 하나의 그룹으로 반환
    - 각 안건 내에서 화자별 그룹핑 (연속 동일 화자 병합)
    """
    # Layer 1: 안건 조회
    agendas_result = (
        supabase.table("meeting_agendas")
        .select("*")
        .eq("meeting_id", meeting_id)
        .order("order_num")
        .execute()
    )
    agendas = agendas_result.data

    # Layer 2: 자막 조회 (시간순). live+ai 혼재 시 AI 자막만 사용(중복·미확인 방지).
    subtitles_result = (
        supabase.table("subtitles")
        .select("*")
        .eq("meeting_id", meeting_id)
        .order("start_time")
        .execute()
    )
    subtitles = prefer_ai_subtitles(subtitles_result.data or [])

    # Layer 3: 비즈니스 로직 - 안건별 자막 분류
    result = classify_subtitles_by_agenda(agendas, subtitles)

    logger.info(
        "안건별 자막 분류 완료: meeting_id=%s, agendas=%d, subtitles=%d",
        meeting_id,
        len(agendas),
        len(subtitles),
    )

    return result
