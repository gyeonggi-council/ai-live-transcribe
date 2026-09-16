"""Notifications API 라우터

# @TASK P11-T5.1 - 알림 API
# @SPEC docs/planning/02-trd.md#알림

알림 CRUD 및 읽음 처리 엔드포인트를 제공합니다.
notifications 테이블: id(uuid), type, title, message, related_meeting_id, is_read, created_at
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from supabase import Client

from app.core.auth_middleware import require_role
from app.core.database import get_supabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


# =============================================================================
# Pydantic 스키마
# =============================================================================


class NotificationCreate(BaseModel):
    """알림 생성 요청"""

    type: str = Field(..., max_length=50, description="알림 유형 (status_change, stt_complete 등)")
    title: str = Field(..., max_length=200, description="알림 제목")
    message: str = Field(..., description="알림 메시지")
    related_meeting_id: Optional[str] = Field(None, description="관련 회의 ID")


# =============================================================================
# 알림 자동 생성 유틸리티 (다른 모듈에서 호출)
# =============================================================================


def create_notification_record(
    supabase: Client,
    notification_type: str,
    title: str,
    message: str,
    related_meeting_id: Optional[str] = None,
) -> Optional[dict]:
    """알림 레코드를 생성합니다 (내부 유틸리티).

    meetings.py 등에서 상태 변경 시 호출합니다.
    """
    data = {
        "type": notification_type,
        "title": title,
        "message": message,
        "related_meeting_id": related_meeting_id,
        "is_read": False,
    }
    try:
        result = supabase.table("notifications").insert(data).execute()
        return result.data[0] if result.data else data
    except Exception as e:
        logger.warning("알림 생성 실패 (무시됨): %s", e)
        return None


# =============================================================================
# GET /api/notifications - 알림 목록 조회
# =============================================================================


@router.get(
    "",
    summary="알림 목록 조회",
)
async def get_notifications(
    limit: int = Query(50, ge=1, le=200, description="조회 개수"),
    is_read: Optional[bool] = Query(None, description="읽음 여부 필터"),
    supabase: Client = Depends(get_supabase),
) -> list[dict]:
    """최근 알림 목록을 조회합니다.

    - limit: 조회 개수 (기본 50)
    - is_read: true/false로 읽음 여부 필터링 가능
    """
    try:
        query = (
            supabase.table("notifications")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
        )
        if is_read is not None:
            query = query.eq("is_read", is_read)
        result = query.execute()
        return result.data or []
    except Exception:
        return []


# =============================================================================
# POST /api/notifications - 알림 생성
# =============================================================================


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="알림 생성",
)
async def create_notification(
    body: NotificationCreate,
    _user: dict = Depends(require_role("admin")),
    supabase: Client = Depends(get_supabase),
) -> dict:
    """새 알림을 생성합니다."""
    data = {
        "type": body.type,
        "title": body.title,
        "message": body.message,
        "related_meeting_id": body.related_meeting_id,
        "is_read": False,
    }

    try:
        result = supabase.table("notifications").insert(data).execute()
        if result.data:
            return result.data[0]
        return data
    except Exception as e:
        logger.error("알림 생성 실패: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="알림 생성에 실패했습니다.",
        )


# =============================================================================
# PATCH /api/notifications/{id}/read - 알림 읽음 처리
# =============================================================================


@router.patch(
    "/{notification_id}/read",
    summary="알림 읽음 처리",
)
async def mark_notification_read(
    notification_id: str,
    supabase: Client = Depends(get_supabase),
) -> dict:
    """알림을 읽음 상태로 변경합니다."""
    try:
        result = (
            supabase.table("notifications")
            .update({"is_read": True})
            .eq("id", notification_id)
            .execute()
        )
    except Exception as e:
        logger.error("알림 읽음 처리 실패: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="알림 읽음 처리에 실패했습니다.",
        )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="알림을 찾을 수 없습니다.",
        )

    return result.data[0]
