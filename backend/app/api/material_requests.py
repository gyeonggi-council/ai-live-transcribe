"""요구자료(의원 자료 제출 요구) 목록 API.

실시간 자막 모니터링 직원용 — 자동 감지된 요구자료를 조회·확인·정리하고,
의회사무처가 KMS 공식 등록 시 참고할 목록을 관리한다.

- GET   /api/meetings/{id}/material-requests           목록 조회 (공개)
- POST  /api/meetings/{id}/material-requests/scan      VOD/사후 전체 자막 스캔 (AI 비용 발생)
- POST  /api/meetings/{id}/material-requests           수동 추가
- PATCH /api/meetings/{id}/material-requests/{rid}     상태/내용 수정 (확인·무시·등록됨)
※ 편집 계열(scan·수동 추가·수정)은 직원 역할만 — 2026-09-12 로그인 없이 바뀌던 것을 막았다. 목록 조회는 공개.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from supabase import Client

from app.core.auth_middleware import require_role
from app.core.config import settings as app_settings
from app.core.database import get_supabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meetings", tags=["material-requests"])

_VALID_STATUS = ("detected", "confirmed", "dismissed", "registered")
# 요구자료를 스캔(AI 비용)·추가·수정할 수 있는 역할 — 자막 모니터링 직원
_EDIT_ROLES = ("committee_staff", "meeting_manager", "stenographer", "admin")


class MaterialRequestUpdate(BaseModel):
    status: Optional[str] = None
    summary: Optional[str] = Field(None, max_length=200)
    councilor_name: Optional[str] = Field(None, max_length=50)
    department: Optional[str] = Field(None, max_length=100)


class MaterialRequestCreate(BaseModel):
    summary: str = Field(..., min_length=2, max_length=200)
    councilor_name: Optional[str] = Field(None, max_length=50)
    department: Optional[str] = Field(None, max_length=100)
    request_text: Optional[str] = Field(None, max_length=500)
    start_time: Optional[float] = None


@router.get("/{meeting_id}/material-requests")
async def list_material_requests(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
) -> list[dict]:
    """회의의 요구자료 감지 목록을 시간순으로 반환합니다."""
    try:
        result = (
            supabase.table("material_requests")
            .select("*")
            .eq("meeting_id", meeting_id)
            .order("start_time")
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.warning("요구자료 목록 조회 실패 %s: %s", meeting_id, e)
        return []


@router.post("/{meeting_id}/material-requests/scan")
async def scan_material_requests(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role(*_EDIT_ROLES)),
) -> dict:
    """회의 전체 자막을 AI로 스캔해 요구자료를 감지합니다 (VOD/사후 분석).

    재스캔 시 직원이 손대지 않은(detected) 이전 스캔 결과만 교체됩니다.
    """
    if not app_settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenAI API 키가 설정되지 않았습니다.",
        )

    from app.services.material_request_detector import scan_meeting_subtitles

    try:
        items = await scan_meeting_subtitles(supabase, meeting_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        logger.error("요구자료 스캔 실패 %s: %s", meeting_id, e)
        raise HTTPException(status_code=500, detail=str(e))

    return {"meeting_id": meeting_id, "count": len(items), "items": items}


@router.post("/{meeting_id}/material-requests", status_code=status.HTTP_201_CREATED)
async def create_material_request(
    meeting_id: str,
    body: MaterialRequestCreate,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role(*_EDIT_ROLES)),
) -> dict:
    """요구자료를 수동으로 추가합니다 (감지 누락 보완용)."""
    row = {
        "id": str(uuid.uuid4()),
        "meeting_id": meeting_id,
        "summary": body.summary.strip(),
        "councilor_name": body.councilor_name,
        "department": body.department,
        "request_text": body.request_text,
        "start_time": body.start_time,
        "confidence": "high",
        "status": "confirmed",
        "source": "manual",
    }
    try:
        result = supabase.table("material_requests").insert(row).execute()
        return result.data[0] if result.data else row
    except Exception as e:
        logger.error("요구자료 수동 추가 실패 %s: %s", meeting_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{meeting_id}/material-requests/{request_id}")
async def update_material_request(
    meeting_id: str,
    request_id: str,
    body: MaterialRequestUpdate,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role(*_EDIT_ROLES)),
) -> dict:
    """요구자료 항목을 수정합니다 (상태 확인/무시/등록됨, 제목·의원·부서 보정)."""
    updates: dict = {}
    if body.status is not None:
        if body.status not in _VALID_STATUS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"status는 {_VALID_STATUS} 중 하나여야 합니다.",
            )
        updates["status"] = body.status
    if body.summary is not None:
        updates["summary"] = body.summary.strip()
    if body.councilor_name is not None:
        updates["councilor_name"] = body.councilor_name.strip() or None
    if body.department is not None:
        updates["department"] = body.department.strip() or None
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="수정할 필드가 없습니다."
        )
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()

    try:
        result = (
            supabase.table("material_requests")
            .update(updates)
            .eq("id", request_id)
            .eq("meeting_id", meeting_id)
            .execute()
        )
    except Exception as e:
        logger.error("요구자료 수정 실패 %s/%s: %s", meeting_id, request_id, e)
        raise HTTPException(status_code=500, detail=str(e))

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="요구자료 항목을 찾을 수 없습니다."
        )
    return result.data[0]
