"""Collaborative Editing API 라우터 - 공동교정/편집

# @TASK P12-T2.1 - 공동교정/편집 API
# @SPEC docs/planning/02-trd.md#공동교정

편집 세션 관리 및 자막 코멘트 기능을 제공합니다.
edit_sessions, subtitle_comments 테이블 사용 (Supabase REST).
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from supabase import Client

from app.core.auth_middleware import require_role
from app.core.database import get_supabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meetings", tags=["collaborative"])


# =============================================================================
# Pydantic 스키마
# =============================================================================


class EditSessionCreate(BaseModel):
    """편집 세션 시작 요청"""

    editor_name: str = Field(..., min_length=1, max_length=100, description="편집자 이름")


class EditSessionUpdate(BaseModel):
    """편집 세션 업데이트 요청"""

    status: Optional[str] = Field(None, description="세션 상태 (active|completed)")


class CommentCreate(BaseModel):
    """코멘트 생성 요청"""

    author_name: str = Field(..., min_length=1, max_length=100, description="작성자 이름")
    content: str = Field(..., min_length=1, description="코멘트 내용")


class CommentUpdate(BaseModel):
    """코멘트 수정 요청"""

    resolved: Optional[bool] = Field(None, description="해결 여부")
    content: Optional[str] = Field(None, description="코멘트 내용")


# =============================================================================
# Edit Sessions - 편집 세션 관리
# =============================================================================


@router.get(
    "/{meeting_id}/edit-sessions",
    summary="활성 편집 세션 목록",
)
async def list_edit_sessions(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
) -> list[dict]:
    """활성 편집 세션 목록을 조회합니다 (status=active만)."""
    try:
        result = (
            supabase.table("edit_sessions")
            .select("*")
            .eq("meeting_id", meeting_id)
            .eq("status", "active")
            .order("started_at")
            .execute()
        )
        return result.data or []
    except Exception:
        return []


@router.post(
    "/{meeting_id}/edit-sessions",
    status_code=status.HTTP_201_CREATED,
    summary="편집 세션 시작",
)
async def create_edit_session(
    meeting_id: str,
    body: EditSessionCreate,
    _user: dict = Depends(require_role("staff", "committee_staff", "meeting_manager", "stenographer", "admin")),
    supabase: Client = Depends(get_supabase),
) -> dict:
    """새 편집 세션을 시작합니다."""
    now = datetime.now(timezone.utc).isoformat()
    session_data = {
        "id": str(uuid.uuid4()),
        "meeting_id": meeting_id,
        "editor_name": body.editor_name,
        "started_at": now,
        "last_active_at": now,
        "status": "active",
    }

    try:
        result = supabase.table("edit_sessions").insert(session_data).execute()
        return result.data[0] if result.data else session_data
    except Exception as e:
        logger.error("편집 세션 생성 실패: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="편집 세션 생성에 실패했습니다.",
        )


@router.patch(
    "/{meeting_id}/edit-sessions/{session_id}",
    summary="편집 세션 업데이트",
)
async def update_edit_session(
    meeting_id: str,
    session_id: str,
    body: EditSessionUpdate,
    _user: dict = Depends(require_role("staff", "committee_staff", "meeting_manager", "stenographer", "admin")),
    supabase: Client = Depends(get_supabase),
) -> dict:
    """편집 세션을 업데이트합니다.

    - last_active_at 자동 갱신
    - status를 completed로 변경하여 세션 종료 가능
    """
    update_data: dict = {
        "last_active_at": datetime.now(timezone.utc).isoformat(),
    }

    if body.status is not None:
        valid_statuses = ("active", "completed")
        if body.status not in valid_statuses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"status는 {valid_statuses} 중 하나여야 합니다.",
            )
        update_data["status"] = body.status

    try:
        result = (
            supabase.table("edit_sessions")
            .update(update_data)
            .eq("id", session_id)
            .eq("meeting_id", meeting_id)
            .execute()
        )
    except Exception as e:
        logger.error("편집 세션 업데이트 실패: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="편집 세션 업데이트에 실패했습니다.",
        )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="편집 세션을 찾을 수 없습니다.",
        )

    return result.data[0]


@router.delete(
    "/{meeting_id}/edit-sessions/{session_id}",
    summary="편집 세션 종료",
)
async def delete_edit_session(
    meeting_id: str,
    session_id: str,
    _user: dict = Depends(require_role("staff", "committee_staff", "meeting_manager", "stenographer", "admin")),
    supabase: Client = Depends(get_supabase),
) -> dict:
    """편집 세션을 종료합니다 (status=completed로 소프트 삭제)."""
    update_data = {
        "status": "completed",
        "last_active_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        result = (
            supabase.table("edit_sessions")
            .update(update_data)
            .eq("id", session_id)
            .eq("meeting_id", meeting_id)
            .execute()
        )
    except Exception as e:
        logger.error("편집 세션 종료 실패: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="편집 세션 종료에 실패했습니다.",
        )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="편집 세션을 찾을 수 없습니다.",
        )

    return {"deleted": True, "session_id": session_id}


# =============================================================================
# Comments - 자막 코멘트 관리
# =============================================================================


@router.get(
    "/{meeting_id}/comments",
    summary="코멘트 목록 조회",
)
async def list_comments(
    meeting_id: str,
    subtitle_id: Optional[str] = Query(None, description="특정 자막의 코멘트만 조회"),
    supabase: Client = Depends(get_supabase),
) -> list[dict]:
    """회의의 코멘트 목록을 조회합니다.

    - subtitle_id 파라미터로 특정 자막의 코멘트만 필터링 가능
    """
    try:
        query = (
            supabase.table("subtitle_comments")
            .select("*")
            .eq("meeting_id", meeting_id)
        )
        if subtitle_id:
            query = query.eq("subtitle_id", subtitle_id)

        result = query.order("created_at").execute()
        return result.data or []
    except Exception:
        return []


@router.post(
    "/{meeting_id}/subtitles/{subtitle_id}/comments",
    status_code=status.HTTP_201_CREATED,
    summary="코멘트 추가",
)
async def create_comment(
    meeting_id: str,
    subtitle_id: str,
    body: CommentCreate,
    _user: dict = Depends(require_role("staff", "committee_staff", "meeting_manager", "stenographer", "admin")),
    supabase: Client = Depends(get_supabase),
) -> dict:
    """자막에 코멘트를 추가합니다."""
    now = datetime.now(timezone.utc).isoformat()
    comment_data = {
        "id": str(uuid.uuid4()),
        "subtitle_id": subtitle_id,
        "meeting_id": meeting_id,
        "author_name": body.author_name,
        "content": body.content,
        "resolved": False,
        "created_at": now,
    }

    try:
        result = supabase.table("subtitle_comments").insert(comment_data).execute()
        return result.data[0] if result.data else comment_data
    except Exception as e:
        logger.error("코멘트 생성 실패: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="코멘트 생성에 실패했습니다.",
        )


@router.patch(
    "/{meeting_id}/comments/{comment_id}",
    summary="코멘트 수정",
)
async def update_comment(
    meeting_id: str,
    comment_id: str,
    body: CommentUpdate,
    _user: dict = Depends(require_role("staff", "committee_staff", "meeting_manager", "stenographer", "admin")),
    supabase: Client = Depends(get_supabase),
) -> dict:
    """코멘트를 수정합니다 (resolved 토글 또는 내용 수정)."""
    update_data = body.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="수정할 필드가 없습니다.",
        )

    try:
        result = (
            supabase.table("subtitle_comments")
            .update(update_data)
            .eq("id", comment_id)
            .eq("meeting_id", meeting_id)
            .execute()
        )
    except Exception as e:
        logger.error("코멘트 수정 실패: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="코멘트 수정에 실패했습니다.",
        )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="코멘트를 찾을 수 없습니다.",
        )

    return result.data[0]


@router.delete(
    "/{meeting_id}/comments/{comment_id}",
    summary="코멘트 삭제",
)
async def delete_comment(
    meeting_id: str,
    comment_id: str,
    _user: dict = Depends(require_role("staff", "committee_staff", "meeting_manager", "stenographer", "admin")),
    supabase: Client = Depends(get_supabase),
) -> dict:
    """코멘트를 삭제합니다."""
    # 존재 확인
    try:
        check_result = (
            supabase.table("subtitle_comments")
            .select("id")
            .eq("id", comment_id)
            .eq("meeting_id", meeting_id)
            .limit(1)
            .execute()
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="코멘트를 찾을 수 없습니다.",
        )

    if not check_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="코멘트를 찾을 수 없습니다.",
        )

    # 삭제
    try:
        supabase.table("subtitle_comments").delete().eq("id", comment_id).execute()
    except Exception as e:
        logger.error("코멘트 삭제 실패: %s", e)

    return {"deleted": True, "comment_id": comment_id}
