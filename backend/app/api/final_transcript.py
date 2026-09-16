"""AI 회의록 최종본 생성/상태 API."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth_middleware import require_role
from app.core.database import get_supabase
from app.services.final_transcript_service import (
    generate_final_transcript,
    get_final_task,
    is_generating,
)

router = APIRouter(prefix="/api/meetings", tags=["final-transcript"])


class FinalTranscriptRequest(BaseModel):
    precise_mode: bool = False


@router.post("/{meeting_id}/final-transcript")
async def start_final_transcript(
    meeting_id: str,
    body: FinalTranscriptRequest,
    background_tasks: BackgroundTasks,
    supabase=Depends(get_supabase),
    _user=Depends(require_role("meeting_manager", "committee_staff", "admin")),
):
    # ★기능 비활성 (사용자 결정 2026-06-11): VOD 전체를 다시 전사하는 고비용
    #   파이프라인이라 AI 자막과 중복 지출 — UI에서도 버튼 제거됨.
    #   재활성하려면 이 가드를 제거하면 된다 (이하 파이프라인 코드는 보존).
    raise HTTPException(
        status_code=403,
        detail="AI 최종본 생성 기능은 비활성화되어 있습니다 (AI 자막 생성을 사용해주세요).",
    )

    if is_generating(meeting_id):
        raise HTTPException(status_code=409, detail="이미 최종본 생성이 진행 중입니다.")
    background_tasks.add_task(
        generate_final_transcript, supabase, meeting_id, precise_mode=body.precise_mode
    )
    return {"status": "started", "meeting_id": meeting_id}


@router.get("/{meeting_id}/final-transcript/status")
async def final_transcript_status(meeting_id: str):
    task = get_final_task(meeting_id)
    if task is None:
        return {"status": "idle", "progress": 0.0, "message": "", "record_id": None}
    return {
        "status": task.status,
        "progress": task.progress,
        "message": task.message,
        "error": task.error,
        "record_id": task.record_id,
    }
