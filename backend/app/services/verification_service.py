"""자막 대조 검증 서비스

# @TASK P7-T1.2 - 대조관리 서비스 (Verification Service)
# @SPEC docs/planning/08-feature-tasks.md

STT 결과물의 정확성을 검증하는 대조관리 기능을 제공합니다.
verification_status 컬럼: 'unverified' (기본) | 'verified' | 'flagged'
"""

import logging

from supabase import Client

logger = logging.getLogger(__name__)

VALID_STATUSES = {"unverified", "verified", "flagged"}


def get_verification_stats(supabase: Client, meeting_id: str) -> dict:
    """회의별 검증 통계 조회

    Returns:
        {
            "total": 100,
            "verified": 80,
            "unverified": 15,
            "flagged": 5,
            "progress": 0.80  # verified / total
        }
    """
    try:
        # 전체 자막 조회 (verification_status 포함)
        result = (
            supabase.table("subtitles")
            .select("id, verification_status", count="exact")
            .eq("meeting_id", meeting_id)
            .execute()
        )
        rows = result.data or []
        total = len(rows)

        if total == 0:
            return {
                "total": 0,
                "verified": 0,
                "unverified": 0,
                "flagged": 0,
                "progress": 0.0,
            }

        verified = sum(
            1 for r in rows if r.get("verification_status") == "verified"
        )
        flagged = sum(
            1 for r in rows if r.get("verification_status") == "flagged"
        )
        unverified = total - verified - flagged

        return {
            "total": total,
            "verified": verified,
            "unverified": unverified,
            "flagged": flagged,
            "progress": round(verified / total, 4) if total > 0 else 0.0,
        }
    except Exception as e:
        logger.warning("검증 통계 조회 실패 (meeting_id=%s): %s", meeting_id, e)
        return {
            "total": 0,
            "verified": 0,
            "unverified": 0,
            "flagged": 0,
            "progress": 0.0,
        }


def get_review_queue(
    supabase: Client,
    meeting_id: str,
    confidence_threshold: float = 0.7,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """미검증/저신뢰 자막 큐 조회 (낮은 신뢰도 우선)

    verification_status가 'verified'가 아닌 자막을 신뢰도 오름차순으로 반환합니다.

    Returns:
        {
            "items": [...subtitle rows sorted by confidence ASC...],
            "total": N,
            "limit": 50,
            "offset": 0
        }
    """
    try:
        result = (
            supabase.table("subtitles")
            .select("*", count="exact")
            .eq("meeting_id", meeting_id)
            .neq("verification_status", "verified")
            .order("confidence", desc=False)
            .range(offset, offset + limit - 1)
            .execute()
        )
        items = result.data or []
        total = result.count if result.count is not None else len(items)

        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    except Exception as e:
        logger.warning("리뷰 큐 조회 실패 (meeting_id=%s): %s", meeting_id, e)
        return {
            "items": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
        }


def update_verification_status(
    supabase: Client,
    meeting_id: str,
    subtitle_id: str,
    status: str,
) -> dict | None:
    """개별 자막 검증 상태 변경

    Args:
        supabase: Supabase 클라이언트
        meeting_id: 회의 ID
        subtitle_id: 자막 ID
        status: 변경할 상태 ('verified' | 'flagged')

    Returns:
        업데이트된 자막 row 또는 None
    """
    if status not in VALID_STATUSES:
        logger.warning(
            "잘못된 검증 상태: %s (허용: %s)", status, VALID_STATUSES
        )
        return None

    try:
        result = (
            supabase.table("subtitles")
            .update({"verification_status": status})
            .eq("id", subtitle_id)
            .eq("meeting_id", meeting_id)
            .execute()
        )
        if result.data:
            logger.info(
                "자막 검증 상태 변경: subtitle_id=%s, status=%s",
                subtitle_id,
                status,
            )
            return result.data[0]
        return None
    except Exception as e:
        logger.warning(
            "검증 상태 변경 실패 (subtitle_id=%s): %s", subtitle_id, e
        )
        return None


def batch_verify(
    supabase: Client,
    meeting_id: str,
    subtitle_ids: list[str],
    status: str = "verified",
) -> dict:
    """일괄 검증 처리

    Args:
        supabase: Supabase 클라이언트
        meeting_id: 회의 ID
        subtitle_ids: 자막 ID 목록
        status: 변경할 상태 (기본: 'verified')

    Returns:
        {"updated": N, "items": [...updated rows...]}
    """
    if status not in VALID_STATUSES:
        logger.warning(
            "잘못된 검증 상태: %s (허용: %s)", status, VALID_STATUSES
        )
        return {"updated": 0, "items": []}

    if not subtitle_ids:
        return {"updated": 0, "items": []}

    updated_items: list[dict] = []

    for subtitle_id in subtitle_ids:
        result = update_verification_status(
            supabase, meeting_id, subtitle_id, status
        )
        if result is not None:
            updated_items.append(result)

    logger.info(
        "일괄 검증 완료: meeting_id=%s, 요청=%d, 성공=%d",
        meeting_id,
        len(subtitle_ids),
        len(updated_items),
    )

    return {"updated": len(updated_items), "items": updated_items}
