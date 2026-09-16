"""Agenda Files API 라우터 - 부록파일 업로드/다운로드

# @TASK P11-T3.1 - 부록파일 업로드/다운로드 API
# @SPEC docs/planning/02-trd.md#부록파일

안건별 부록 파일(첨부파일) 업로드, 목록 조회, 다운로드, 삭제를 제공합니다.
로컬 파일 시스템 사용 (uploads/agenda_files/{agenda_id}/ 디렉토리).
"""

import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from supabase import Client

from app.core.auth_middleware import require_role
from app.core.database import get_supabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meetings", tags=["agenda_files"])

# 업로드 디렉토리 루트
UPLOAD_BASE_DIR = Path("uploads/agenda_files")
_UPLOAD_BASE_RESOLVED = UPLOAD_BASE_DIR.resolve()

# 최대 파일 크기 (50MB)
MAX_FILE_SIZE = 50 * 1024 * 1024


def _get_upload_dir(agenda_id: str) -> Path:
    """안건별 업로드 디렉토리 경로를 반환합니다 (path traversal 방지)."""
    upload_dir = (UPLOAD_BASE_DIR / agenda_id).resolve()
    if not str(upload_dir).startswith(str(_UPLOAD_BASE_RESOLVED)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="잘못된 agenda ID입니다.",
        )
    return upload_dir


def _validate_file_path(file_path: str) -> Path:
    """DB에서 읽은 file_path가 업로드 디렉토리 내부인지 검증합니다."""
    resolved = Path(file_path).resolve()
    if not str(resolved).startswith(str(_UPLOAD_BASE_RESOLVED)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="잘못된 파일 경로입니다.",
        )
    return resolved


# =============================================================================
# POST - 파일 업로드
# =============================================================================


@router.post(
    "/{meeting_id}/agendas/{agenda_id}/files",
    status_code=status.HTTP_201_CREATED,
    summary="부록 파일 업로드",
)
async def upload_agenda_file(
    meeting_id: str,
    agenda_id: str,
    file: UploadFile,
    _user: dict = Depends(require_role("staff", "committee_staff", "meeting_manager", "stenographer", "admin")),
    supabase: Client = Depends(get_supabase),
) -> dict:
    """안건에 부록 파일을 업로드합니다.

    - multipart/form-data로 파일 전송
    - 로컬 파일 시스템에 저장
    - agenda_files 테이블에 메타데이터 기록
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="파일명이 없습니다.",
        )

    # Layer 1: 파일 크기 제한
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"파일 크기가 {MAX_FILE_SIZE // (1024*1024)}MB를 초과합니다.",
        )

    # 파일 저장
    upload_dir = _get_upload_dir(agenda_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_id = str(uuid.uuid4())
    # 안전한 파일명: UUID + 원본 확장자
    ext = Path(file.filename).suffix
    safe_filename = f"{file_id}{ext}"
    file_path = upload_dir / safe_filename

    with open(file_path, "wb") as f:
        f.write(content)

    # DB에 메타데이터 저장
    file_meta = {
        "id": file_id,
        "agenda_id": agenda_id,
        "meeting_id": meeting_id,
        "filename": file.filename,
        "file_path": str(file_path),
        "file_size": len(content),
        "mime_type": file.content_type or "application/octet-stream",
    }

    try:
        result = supabase.table("agenda_files").insert(file_meta).execute()
        return result.data[0] if result.data else file_meta
    except Exception as e:
        # DB 저장 실패 시 파일도 삭제
        if file_path.exists():
            file_path.unlink()
        logger.error("파일 메타데이터 저장 실패: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="파일 메타데이터 저장에 실패했습니다.",
        )


# =============================================================================
# GET - 파일 목록 조회
# =============================================================================


@router.get(
    "/{meeting_id}/agendas/{agenda_id}/files",
    summary="부록 파일 목록 조회",
)
async def list_agenda_files(
    meeting_id: str,
    agenda_id: str,
    supabase: Client = Depends(get_supabase),
) -> list[dict]:
    """안건의 부록 파일 목록을 조회합니다."""
    try:
        result = (
            supabase.table("agenda_files")
            .select("*")
            .eq("agenda_id", agenda_id)
            .eq("meeting_id", meeting_id)
            .order("created_at")
            .execute()
        )
        return result.data or []
    except Exception:
        return []


# =============================================================================
# GET - 파일 다운로드
# =============================================================================


@router.get(
    "/{meeting_id}/agendas/{agenda_id}/files/{file_id}/download",
    summary="부록 파일 다운로드",
)
async def download_agenda_file(
    meeting_id: str,
    agenda_id: str,
    file_id: str,
    supabase: Client = Depends(get_supabase),
):
    """부록 파일을 다운로드합니다."""
    try:
        result = (
            supabase.table("agenda_files")
            .select("*")
            .eq("id", file_id)
            .eq("agenda_id", agenda_id)
            .eq("meeting_id", meeting_id)
            .limit(1)
            .execute()
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="파일을 찾을 수 없습니다.",
        )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="파일을 찾을 수 없습니다.",
        )

    file_meta = result.data[0]
    file_path = _validate_file_path(file_meta["file_path"])

    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="파일이 디스크에 존재하지 않습니다.",
        )

    return FileResponse(
        path=str(file_path),
        filename=file_meta.get("filename", file_path.name),
        media_type=file_meta.get("mime_type", "application/octet-stream"),
    )


# =============================================================================
# DELETE - 파일 삭제
# =============================================================================


@router.delete(
    "/{meeting_id}/agendas/{agenda_id}/files/{file_id}",
    summary="부록 파일 삭제",
)
async def delete_agenda_file(
    meeting_id: str,
    agenda_id: str,
    file_id: str,
    _user: dict = Depends(require_role("staff", "committee_staff", "meeting_manager", "stenographer", "admin")),
    supabase: Client = Depends(get_supabase),
) -> dict:
    """부록 파일을 삭제합니다 (DB + 디스크)."""
    # 메타데이터 조회
    try:
        result = (
            supabase.table("agenda_files")
            .select("*")
            .eq("id", file_id)
            .eq("agenda_id", agenda_id)
            .eq("meeting_id", meeting_id)
            .limit(1)
            .execute()
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="파일을 찾을 수 없습니다.",
        )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="파일을 찾을 수 없습니다.",
        )

    file_meta = result.data[0]

    # 디스크에서 파일 삭제 (path traversal 방지)
    file_path = _validate_file_path(file_meta["file_path"])
    if file_path.exists():
        file_path.unlink()

    # DB에서 레코드 삭제
    try:
        supabase.table("agenda_files").delete().eq("id", file_id).execute()
    except Exception as e:
        logger.error("파일 메타데이터 삭제 실패: %s", e)

    return {"deleted": True, "file_id": file_id}
