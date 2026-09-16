"""Dictionary API 라우터 - 사용자 사전 CRUD

용어 사전 항목의 조회, 추가, 삭제를 제공합니다.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from supabase import Client

from app.core.auth_middleware import require_role
from app.core.database import get_supabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dictionary", tags=["dictionary"])


class DictionaryCreate(BaseModel):
    """사전 항목 생성 스키마"""
    wrong_text: str
    correct_text: str
    category: str | None = "general"
    created_by: str | None = None


@router.get(
    "",
    summary="사전 목록 조회",
)
async def get_dictionary_entries(
    category: Annotated[str | None, Query(description="카테고리 필터")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    supabase: Client = Depends(get_supabase),
) -> dict:
    """사전 항목 목록을 조회합니다."""
    query = supabase.table("dictionary").select("*", count="exact")

    if category:
        query = query.eq("category", category)

    query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
    result = query.execute()

    return {
        "items": result.data or [],
        "total": result.count or 0,
        "limit": limit,
        "offset": offset,
    }


@router.post(
    "",
    summary="사전 항목 추가",
    status_code=status.HTTP_201_CREATED,
)
async def create_dictionary_entry(
    body: DictionaryCreate,
    _user: dict = Depends(require_role("admin", "committee_staff")),
    supabase: Client = Depends(get_supabase),
) -> dict:
    """새 사전 항목을 추가합니다. 동일한 wrong_text가 있으면 덮어씁니다."""
    # 중복 확인
    existing = (
        supabase.table("dictionary")
        .select("id")
        .eq("wrong_text", body.wrong_text)
        .limit(1)
        .execute()
    )

    data = body.model_dump(exclude_none=True)

    if existing.data:
        # 기존 항목 업데이트
        result = (
            supabase.table("dictionary")
            .update(data)
            .eq("id", existing.data[0]["id"])
            .execute()
        )
        logger.info("사전 항목 업데이트: %s → %s", body.wrong_text, body.correct_text)
    else:
        result = supabase.table("dictionary").insert(data).execute()
        logger.info("사전 항목 추가: %s → %s", body.wrong_text, body.correct_text)

    return result.data[0] if result.data else data


@router.delete(
    "/{entry_id}",
    summary="사전 항목 삭제",
)
async def delete_dictionary_entry(
    entry_id: str,
    _user: dict = Depends(require_role("admin", "committee_staff")),
    supabase: Client = Depends(get_supabase),
) -> dict:
    """사전 항목을 삭제합니다."""
    result = (
        supabase.table("dictionary")
        .delete()
        .eq("id", entry_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사전 항목을 찾을 수 없습니다.",
        )

    logger.info("사전 항목 삭제: id=%s", entry_id)
    return {"deleted": True, "id": entry_id}
