"""Stenography API 라우터 - 속기록 관리

# @TASK P12-T1.1 - 속기록 관리 API
# @SPEC docs/planning/02-trd.md#속기록

속기록 등록/수정/삭제, STT 자막과의 비교 기능을 제공합니다.
stenography_records 테이블 사용 (Supabase REST).
"""

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from supabase import Client

from app.core.auth_middleware import require_role
from app.core.database import get_supabase
from app.services.stenography_history import record_edit as record_edit_history
from app.services.subtitle_select import prefer_ai_subtitles

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meetings", tags=["stenography"])

# 속기사 대시보드용 별도 라우터 (prefix: /api/stenography)
dashboard_router = APIRouter(prefix="/api/stenography", tags=["stenography-dashboard"])

# 업로드 디렉토리 루트
UPLOAD_BASE_DIR = Path("uploads/stenography")

# 최대 파일 크기 (50MB)
MAX_FILE_SIZE = 50 * 1024 * 1024


def _get_upload_dir(meeting_id: str) -> Path:
    """회의별 속기록 업로드 디렉토리 경로를 반환합니다."""
    return UPLOAD_BASE_DIR / meeting_id


# =============================================================================
# Pydantic 스키마
# =============================================================================


class StenographyUpdate(BaseModel):
    """속기록 수정 요청"""

    content: Optional[str] = Field(None, description="속기 원문")
    status: Optional[str] = Field(None, description="상태 (draft|submitted|approved)")
    stenographer_name: Optional[str] = Field(None, description="작성자명")


class StenographyLineItem(BaseModel):
    """속기록 행 아이템 (일괄 저장용)"""

    id: Optional[str] = None
    sequence_no: int
    text: str = ""
    speaker: Optional[str] = None
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    starts_new_paragraph: bool = False


class StenographyLinesBatchSave(BaseModel):
    """속기록 행 일괄 저장 요청"""

    lines: list[StenographyLineItem]


class ImportFromTextRequest(BaseModel):
    """텍스트에서 속기록 행 가져오기 요청"""

    text: str
    delimiter: str = "\n"


class StenographyLineUpdate(BaseModel):
    """속기록 라인 수정 요청 (배치 항목)"""

    id: str
    text: Optional[str] = None
    speaker: Optional[str] = None
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    starts_new_paragraph: Optional[bool] = None
    sequence_no: Optional[int] = None
    version: Optional[int] = None  # 낙관적 동시성 제어 (None이면 검사 생략)


class StenographyLinesBatchUpdate(BaseModel):
    """속기록 라인 배치 수정 요청"""

    items: list[StenographyLineUpdate]


class StenographyLineAdd(BaseModel):
    """속기록 라인 단건 추가 요청"""

    text: str = ""
    speaker: Optional[str] = None
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    starts_new_paragraph: bool = False
    after_sequence_no: int = 0


# =============================================================================
# Helpers
# =============================================================================


def _regenerate_content_snapshot(
    supabase: Client, record_id: str, lines: list[dict]
) -> None:
    """stenography_records.content를 lines 데이터로 재생성합니다."""
    parts = []
    for line in sorted(lines, key=lambda l: l.get("sequence_no", 0)):
        if line.get("starts_new_paragraph") and parts:
            parts.append("")  # 단락 구분 빈 줄
        text = line.get("text", "")
        if line.get("speaker"):
            parts.append(f"[{line['speaker']}] {text}")
        else:
            parts.append(text)
    content = "\n".join(parts)
    supabase.table("stenography_records").update(
        {
            "content": content,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", record_id).execute()


async def _regenerate_record_content(record_id: str, supabase: Client) -> None:
    """stenography_records.content를 stenography_lines에서 재생성합니다 (async)."""
    lines_result = (
        supabase.table("stenography_lines")
        .select("text, starts_new_paragraph")
        .eq("record_id", record_id)
        .order("sequence_no")
        .execute()
    )
    lines = lines_result.data or []
    parts = []
    for line in lines:
        if line.get("starts_new_paragraph") and parts:
            parts.append("")
        parts.append(line.get("text", ""))
    content = "\n".join(parts)
    supabase.table("stenography_records").update(
        {"content": content, "updated_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", record_id).execute()


# =============================================================================
# GET - 속기록 목록 조회
# =============================================================================


@router.get(
    "/{meeting_id}/stenography",
    summary="속기록 목록 조회",
)
async def list_stenography_records(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
) -> list[dict]:
    """회의의 속기록 목록을 조회합니다."""
    try:
        result = (
            supabase.table("stenography_records")
            .select("*")
            .eq("meeting_id", meeting_id)
            .order("created_at")
            .execute()
        )
        return result.data or []
    except Exception:
        return []


# =============================================================================
# POST - 속기록 등록 (텍스트 또는 파일)
# =============================================================================


@router.post(
    "/{meeting_id}/stenography",
    status_code=status.HTTP_201_CREATED,
    summary="속기록 등록",
)
async def create_stenography_record(
    meeting_id: str,
    stenographer_name: str = Form(..., description="작성자명"),
    content: Optional[str] = Form(None, description="속기 원문 텍스트"),
    file: Optional[UploadFile] = File(None, description="속기록 파일"),
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("stenographer", "admin")),
) -> dict:
    """속기록을 등록합니다.

    - multipart/form-data로 전송
    - content(텍스트) 또는 file(파일) 중 하나 이상 필요
    - 파일 저장 경로: uploads/stenography/{meeting_id}/
    """
    # Layer 1: 입력 검증 - content 또는 file 중 하나 이상 필요
    if not content and (file is None or not file.filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="content(텍스트) 또는 file(파일) 중 하나 이상 필요합니다.",
        )

    record_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    record_data: dict = {
        "id": record_id,
        "meeting_id": meeting_id,
        "content": content or "",
        "stenographer_name": stenographer_name,
        "status": "draft",
        "file_path": None,
        "filename": None,
        "file_size": None,
        "created_at": now,
        "updated_at": now,
    }

    # 파일 업로드 처리
    if file is not None and file.filename:
        file_content = await file.read()

        # Layer 1: 파일 크기 제한
        if len(file_content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"파일 크기가 {MAX_FILE_SIZE // (1024 * 1024)}MB를 초과합니다.",
            )

        upload_dir = _get_upload_dir(meeting_id)
        upload_dir.mkdir(parents=True, exist_ok=True)

        ext = Path(file.filename).suffix
        safe_filename = f"{record_id}{ext}"
        file_path = upload_dir / safe_filename

        with open(file_path, "wb") as f:
            f.write(file_content)

        record_data["file_path"] = str(file_path)
        record_data["filename"] = file.filename
        record_data["file_size"] = len(file_content)

    try:
        result = supabase.table("stenography_records").insert(record_data).execute()
        return result.data[0] if result.data else record_data
    except Exception as e:
        # DB 저장 실패 시 파일 삭제
        if record_data.get("file_path"):
            fp = Path(record_data["file_path"])
            if fp.exists():
                fp.unlink()
        logger.error("속기록 등록 실패: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="속기록 등록에 실패했습니다.",
        )


# =============================================================================
# PATCH - 속기록 수정
# =============================================================================


@router.patch(
    "/{meeting_id}/stenography/{record_id}",
    summary="속기록 수정",
)
async def update_stenography_record(
    meeting_id: str,
    record_id: str,
    body: StenographyUpdate,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("stenographer", "admin")),
) -> dict:
    """속기록을 수정합니다. content, status, stenographer_name 변경 가능."""
    update_data = body.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="수정할 필드가 없습니다.",
        )

    # Layer 2: status 값 검증
    if "status" in update_data:
        valid_statuses = ("draft", "submitted", "approved")
        if update_data["status"] not in valid_statuses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"status는 {valid_statuses} 중 하나여야 합니다.",
            )

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    try:
        result = (
            supabase.table("stenography_records")
            .update(update_data)
            .eq("id", record_id)
            .eq("meeting_id", meeting_id)
            .execute()
        )
    except Exception as e:
        logger.error("속기록 수정 실패: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="속기록 수정에 실패했습니다.",
        )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="속기록을 찾을 수 없습니다.",
        )

    return result.data[0]


# =============================================================================
# DELETE - 속기록 삭제
# =============================================================================


@router.delete(
    "/{meeting_id}/stenography/{record_id}",
    summary="속기록 삭제",
)
async def delete_stenography_record(
    meeting_id: str,
    record_id: str,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("stenographer", "admin")),
) -> dict:
    """속기록을 삭제합니다 (DB + 디스크 파일)."""
    # 레코드 조회
    try:
        result = (
            supabase.table("stenography_records")
            .select("*")
            .eq("id", record_id)
            .eq("meeting_id", meeting_id)
            .limit(1)
            .execute()
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="속기록을 찾을 수 없습니다.",
        )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="속기록을 찾을 수 없습니다.",
        )

    record = result.data[0]

    # 디스크에서 파일 삭제
    file_path = record.get("file_path")
    if file_path:
        fp = Path(file_path)
        if fp.exists():
            fp.unlink()

    # DB에서 레코드 삭제
    try:
        supabase.table("stenography_records").delete().eq("id", record_id).execute()
    except Exception as e:
        logger.error("속기록 삭제 실패: %s", e)

    return {"deleted": True, "record_id": record_id}


# =============================================================================
# GET - STT 자막과 비교
# =============================================================================


@router.get(
    "/{meeting_id}/stenography/{record_id}/compare",
    summary="속기록-STT 자막 비교",
)
async def compare_stenography_with_subtitles(
    meeting_id: str,
    record_id: str,
    supabase: Client = Depends(get_supabase),
) -> dict:
    """속기록을 STT 자막과 비교합니다.

    속기록 content를 줄 단위로 분리하고,
    subtitles 테이블에서 해당 회의 자막을 조회하여
    비교 결과를 반환합니다.
    """
    # 속기록 조회
    try:
        steno_result = (
            supabase.table("stenography_records")
            .select("*")
            .eq("id", record_id)
            .eq("meeting_id", meeting_id)
            .limit(1)
            .execute()
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="속기록을 찾을 수 없습니다.",
        )

    if not steno_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="속기록을 찾을 수 없습니다.",
        )

    record = steno_result.data[0]
    content = record.get("content", "")
    stenography_lines = [line.strip() for line in content.split("\n") if line.strip()]

    # STT 자막 조회
    try:
        subtitle_result = (
            supabase.table("subtitles")
            .select("id, text, start_time, end_time, speaker, kind")
            .eq("meeting_id", meeting_id)
            .order("start_time")
            .execute()
        )
        subtitle_texts = [
            s.get("text", "")
            for s in prefer_ai_subtitles(subtitle_result.data or [])
        ]
    except Exception:
        subtitle_texts = []

    return {
        "stenography_lines": stenography_lines,
        "subtitle_texts": subtitle_texts,
        "total_steno_lines": len(stenography_lines),
        "total_subtitle_count": len(subtitle_texts),
    }


# =============================================================================
# GET - 속기록 행 목록 조회
# =============================================================================


@router.get(
    "/{meeting_id}/stenography/{record_id}/lines",
    summary="속기록 행 목록 조회",
)
async def get_stenography_lines(
    meeting_id: str,
    record_id: str,
    supabase: Client = Depends(get_supabase),
) -> list[dict]:
    """속기록의 행 목록을 sequence_no 오름차순으로 조회합니다."""
    # 레코드가 해당 회의에 속하는지 확인
    record_result = (
        supabase.table("stenography_records")
        .select("id")
        .eq("id", record_id)
        .eq("meeting_id", meeting_id)
        .limit(1)
        .execute()
    )
    if not record_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="속기록을 찾을 수 없습니다.",
        )

    lines_result = (
        supabase.table("stenography_lines")
        .select("*")
        .eq("record_id", record_id)
        .order("sequence_no")
        .execute()
    )
    return lines_result.data or []


# =============================================================================
# PUT - 속기록 행 일괄 저장 (replace-all)
# =============================================================================


@router.put(
    "/{meeting_id}/stenography/{record_id}/lines",
    summary="속기록 행 일괄 저장",
)
async def batch_save_stenography_lines(
    meeting_id: str,
    record_id: str,
    body: StenographyLinesBatchSave,
    supabase: Client = Depends(get_supabase),
) -> list[dict]:
    """속기록 행을 일괄 저장합니다. 기존 행을 모두 삭제하고 새로 입력합니다."""
    # 레코드 확인
    record_result = (
        supabase.table("stenography_records")
        .select("id")
        .eq("id", record_id)
        .eq("meeting_id", meeting_id)
        .limit(1)
        .execute()
    )
    if not record_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="속기록을 찾을 수 없습니다.",
        )

    # 기존 행 삭제
    supabase.table("stenography_lines").delete().eq("record_id", record_id).execute()

    # 새 행 준비 (incoming id 무시, 새 UUID 생성)
    now = datetime.now(timezone.utc).isoformat()
    new_lines = []
    for line in body.lines:
        new_lines.append(
            {
                "id": str(uuid.uuid4()),
                "record_id": record_id,
                "sequence_no": line.sequence_no,
                "text": line.text,
                "speaker": line.speaker,
                "start_ms": line.start_ms,
                "end_ms": line.end_ms,
                "starts_new_paragraph": line.starts_new_paragraph,
                "created_at": now,
                "updated_at": now,
            }
        )

    if new_lines:
        insert_result = (
            supabase.table("stenography_lines").insert(new_lines).execute()
        )
        inserted = insert_result.data if insert_result.data else new_lines
    else:
        inserted = []

    # 콘텐츠 스냅샷 재생성
    _regenerate_content_snapshot(supabase, record_id, inserted)

    return inserted


# =============================================================================
# PATCH - 속기록 라인 배치 수정
# =============================================================================


@router.patch(
    "/{meeting_id}/stenography/{record_id}/lines",
    summary="속기록 라인 배치 수정",
)
async def update_stenography_lines_batch(
    meeting_id: str,
    record_id: str,
    body: StenographyLinesBatchUpdate,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("stenographer", "admin")),
) -> dict:
    """속기록 라인을 일괄 수정하고 content를 재생성합니다."""
    record_result = (
        supabase.table("stenography_records")
        .select("id")
        .eq("id", record_id)
        .eq("meeting_id", meeting_id)
        .limit(1)
        .execute()
    )
    if not record_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="속기록을 찾을 수 없습니다.",
        )

    updated_items: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    # 편집자 정보 추출
    editor_id = _user.get("id") if _user else None
    editor_name = _user.get("display_name") or _user.get("username", "unknown") if _user else "unknown"

    # ------------------------------------------------------------------ #
    # PASS 1: fetch current DB rows and check version conflicts.           #
    # No writes happen here. Cache fetched rows to reuse in pass 2.        #
    # ------------------------------------------------------------------ #
    cached_rows: dict[str, dict | None] = {}
    conflicts: list[dict] = []

    for item in body.items:
        # Fetch current row (needed for version check AND edit history)
        try:
            old_line_result = (
                supabase.table("stenography_lines")
                .select("*")
                .eq("id", item.id)
                .eq("record_id", record_id)
                .limit(1)
                .execute()
            )
            old_line: dict | None = old_line_result.data[0] if old_line_result.data else None
        except Exception:
            old_line = None
        cached_rows[item.id] = old_line

        # Version conflict check (only when version is provided)
        if item.version is not None and old_line is not None:
            current_version = old_line.get("version", 1)
            if current_version != item.version:
                conflicts.append({"id": item.id, "current": old_line})

    # 충돌이 하나라도 있으면 아무것도 쓰지 않고 즉시 409 반환
    if conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "다른 사용자가 먼저 수정했습니다.",
                "conflicts": conflicts,
            },
        )

    # ------------------------------------------------------------------ #
    # PASS 2: no conflicts — perform the actual updates.                   #
    # Reuse cached_rows to avoid double-fetching.                          #
    # ------------------------------------------------------------------ #
    for item in body.items:
        update_data: dict = {}
        if item.text is not None:
            update_data["text"] = item.text
        if item.speaker is not None:
            update_data["speaker"] = item.speaker
        if item.start_ms is not None:
            update_data["start_ms"] = item.start_ms
        if item.end_ms is not None:
            update_data["end_ms"] = item.end_ms
        if item.starts_new_paragraph is not None:
            update_data["starts_new_paragraph"] = item.starts_new_paragraph
        if item.sequence_no is not None:
            update_data["sequence_no"] = item.sequence_no

        if not update_data:
            continue

        old_line = cached_rows.get(item.id)

        # 버전 증가 및 updated_by 기록
        current_version = old_line.get("version", 1) if old_line else 1
        update_data["version"] = current_version + 1
        update_data["updated_by"] = editor_name
        update_data["updated_at"] = now

        result = (
            supabase.table("stenography_lines")
            .update(update_data)
            .eq("id", item.id)
            .eq("record_id", record_id)
            .execute()
        )
        if result.data:
            updated_items.append(result.data[0])

            # 수정 이력 기록 (version/updated_by는 이력 제외)
            if old_line:
                field_map = {
                    "text": "text",
                    "speaker": "speaker",
                    "start_ms": "start_ms",
                    "end_ms": "end_ms",
                    "starts_new_paragraph": "paragraph",
                }
                for field_key, history_field in field_map.items():
                    if field_key in update_data and field_key != "updated_at":
                        old_val = old_line.get(field_key)
                        new_val = update_data[field_key]
                        old_str = str(old_val) if old_val is not None else None
                        new_str = str(new_val)
                        try:
                            record_edit_history(
                                supabase=supabase,
                                line_id=item.id,
                                editor_id=editor_id,
                                editor_name=editor_name,
                                field_changed=history_field,
                                old_value=old_str,
                                new_value=new_str,
                            )
                        except Exception as e:
                            logger.warning("이력 기록 실패 (line=%s, field=%s): %s", item.id, history_field, e)

    await _regenerate_record_content(record_id, supabase)

    return {
        "updated": len(updated_items),
        "items": updated_items,
    }


# =============================================================================
# POST - STT 자막에서 속기록 행 생성
# =============================================================================


@router.post(
    "/{meeting_id}/stenography/{record_id}/lines/from-subtitles",
    summary="STT 자막에서 속기록 행 생성",
)
async def create_lines_from_subtitles(
    meeting_id: str,
    record_id: str,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("stenographer", "admin")),
) -> dict:
    """STT 자막 데이터로 속기록 행을 생성합니다 (타이밍 + 화자 단락 구분 포함)."""
    # 레코드 확인
    record_result = (
        supabase.table("stenography_records")
        .select("id")
        .eq("id", record_id)
        .eq("meeting_id", meeting_id)
        .limit(1)
        .execute()
    )
    if not record_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="속기록을 찾을 수 없습니다.",
        )

    # 자막 조회 (start_time 오름차순). live+ai 혼재 시 AI 자막만(중복 라인 방지).
    subtitle_result = (
        supabase.table("subtitles")
        .select("*")
        .eq("meeting_id", meeting_id)
        .order("start_time")
        .execute()
    )
    subtitles = prefer_ai_subtitles(subtitle_result.data or [])

    # 행 생성 (화자 변경 시 단락 구분)
    now = datetime.now(timezone.utc).isoformat()
    new_lines = []
    prev_speaker = None
    for i, subtitle in enumerate(subtitles, 1):
        speaker = subtitle.get("speaker")
        starts_new_paragraph = bool(
            prev_speaker is not None and speaker != prev_speaker
        )
        start_time = subtitle.get("start_time", 0)
        end_time = subtitle.get("end_time", 0)
        new_lines.append(
            {
                "id": str(uuid.uuid4()),
                "record_id": record_id,
                "sequence_no": i,
                "text": subtitle.get("text", ""),
                "speaker": speaker,
                "start_ms": int(start_time * 1000) if start_time is not None else None,
                "end_ms": int(end_time * 1000) if end_time is not None else None,
                "starts_new_paragraph": starts_new_paragraph,
                "created_at": now,
                "updated_at": now,
            }
        )
        prev_speaker = speaker

    # 기존 행 삭제 후 삽입
    supabase.table("stenography_lines").delete().eq("record_id", record_id).execute()

    if new_lines:
        insert_result = (
            supabase.table("stenography_lines").insert(new_lines).execute()
        )
        inserted = insert_result.data if insert_result.data else new_lines
    else:
        inserted = []

    # 콘텐츠 스냅샷 재생성
    _regenerate_content_snapshot(supabase, record_id, inserted)

    return {"lines": inserted, "count": len(inserted)}


# =============================================================================
# POST - 텍스트에서 속기록 행 가져오기
# =============================================================================


@router.post(
    "/{meeting_id}/stenography/{record_id}/lines/import-from-text",
    summary="텍스트에서 속기록 행 가져오기",
)
async def import_lines_from_text(
    meeting_id: str,
    record_id: str,
    body: ImportFromTextRequest,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("stenographer", "admin")),
) -> dict:
    """레거시 텍스트 블록을 행 단위로 파싱하여 속기록 행을 생성합니다.

    - delimiter로 텍스트 분리
    - 빈 줄(이중 개행) 감지 시 다음 줄에 starts_new_paragraph=True
    - 화자/타이밍 없음
    """
    # 레코드 확인
    record_result = (
        supabase.table("stenography_records")
        .select("id")
        .eq("id", record_id)
        .eq("meeting_id", meeting_id)
        .limit(1)
        .execute()
    )
    if not record_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="속기록을 찾을 수 없습니다.",
        )

    # 텍스트 파싱 (단락 구분 감지)
    now = datetime.now(timezone.utc).isoformat()
    new_lines = []
    sequence_no = 1
    pending_paragraph = False

    for raw_line in body.text.split(body.delimiter):
        stripped = raw_line.strip()
        if not stripped:
            # 빈 줄: 이미 내용이 있으면 다음 줄을 새 단락으로 표시
            if sequence_no > 1:
                pending_paragraph = True
            continue

        new_lines.append(
            {
                "id": str(uuid.uuid4()),
                "record_id": record_id,
                "sequence_no": sequence_no,
                "text": stripped,
                "speaker": None,
                "start_ms": None,
                "end_ms": None,
                "starts_new_paragraph": pending_paragraph,
                "created_at": now,
                "updated_at": now,
            }
        )
        sequence_no += 1
        pending_paragraph = False

    # 기존 행 삭제 후 삽입
    supabase.table("stenography_lines").delete().eq("record_id", record_id).execute()

    if new_lines:
        insert_result = (
            supabase.table("stenography_lines").insert(new_lines).execute()
        )
        inserted = insert_result.data if insert_result.data else new_lines
    else:
        inserted = []

    # 콘텐츠 스냅샷 재생성
    _regenerate_content_snapshot(supabase, record_id, inserted)

    return {"lines": inserted, "count": len(inserted)}


# =============================================================================
# POST - 속기 라인 단건 추가
# =============================================================================


@router.post(
    "/{meeting_id}/stenography/{record_id}/lines/add",
    summary="속기 라인 추가",
)
async def add_stenography_line(
    meeting_id: str,
    record_id: str,
    body: StenographyLineAdd,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("stenographer", "admin")),
) -> dict:
    """속기 라인 1개를 추가합니다."""
    record_result = (
        supabase.table("stenography_records")
        .select("id")
        .eq("id", record_id)
        .eq("meeting_id", meeting_id)
        .limit(1)
        .execute()
    )
    if not record_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="속기록을 찾을 수 없습니다.",
        )

    sequence_no = body.after_sequence_no + 5
    now = datetime.now(timezone.utc).isoformat()
    line_data = {
        "record_id": record_id,
        "sequence_no": sequence_no,
        "text": body.text,
        "speaker": body.speaker,
        "start_ms": body.start_ms,
        "end_ms": body.end_ms,
        "starts_new_paragraph": body.starts_new_paragraph,
        "created_at": now,
        "updated_at": now,
    }

    result = supabase.table("stenography_lines").insert(line_data).execute()
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="속기 라인 추가에 실패했습니다.",
        )

    await _regenerate_record_content(record_id, supabase)
    return result.data[0]


# =============================================================================
# GET - 속기록 수정 이력 조회
# =============================================================================


@router.get(
    "/{meeting_id}/stenography/{record_id}/history",
    summary="속기록 수정 이력 조회",
)
async def get_edit_history(
    meeting_id: str,
    record_id: str,
    limit: int = 50,
    offset: int = 0,
    supabase: Client = Depends(get_supabase),
) -> dict:
    """속기록 라인의 수정 이력을 조회합니다.

    # @TASK P11C-T4 - 수정이력 API
    """
    from app.services.stenography_history import get_history

    # 레코드 확인
    record_result = (
        supabase.table("stenography_records")
        .select("id")
        .eq("id", record_id)
        .eq("meeting_id", meeting_id)
        .limit(1)
        .execute()
    )
    if not record_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="속기록을 찾을 수 없습니다.",
        )

    items, total = get_history(supabase, record_id, limit=limit, offset=offset)

    return {"items": items, "total": total}


# =============================================================================
# POST - AI 화자 자동 구분
# =============================================================================


@router.post(
    "/{meeting_id}/stenography/{record_id}/ai/speakers",
    summary="AI 화자 자동 구분",
)
async def ai_detect_speakers(
    meeting_id: str,
    record_id: str,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("stenographer", "admin")),
) -> dict:
    """GPT-5-mini를 사용하여 속기 라인의 화자를 자동 구분합니다.

    # @TASK P11C-T6 - AI 보조 API
    """
    from app.services.stenography_ai import auto_detect_speakers

    # 레코드 확인
    record_result = (
        supabase.table("stenography_records")
        .select("id")
        .eq("id", record_id)
        .eq("meeting_id", meeting_id)
        .limit(1)
        .execute()
    )
    if not record_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="속기록을 찾을 수 없습니다.",
        )

    try:
        suggestions = await auto_detect_speakers(supabase, record_id, meeting_id)
        return {"suggestions": suggestions, "count": len(suggestions)}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
    except Exception as e:
        logger.error("AI 화자 구분 실패: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AI 화자 구분에 실패했습니다.",
        )


# =============================================================================
# POST - AI 맞춤법 교정
# =============================================================================


@router.post(
    "/{meeting_id}/stenography/{record_id}/ai/proofread",
    summary="AI 맞춤법 교정",
)
async def ai_proofread(
    meeting_id: str,
    record_id: str,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("stenographer", "admin")),
) -> dict:
    """GPT-5-mini를 사용하여 속기 라인의 맞춤법/용어를 교정합니다.

    # @TASK P11C-T6 - AI 보조 API
    """
    from app.services.stenography_ai import auto_proofread

    # 레코드 확인
    record_result = (
        supabase.table("stenography_records")
        .select("id")
        .eq("id", record_id)
        .eq("meeting_id", meeting_id)
        .limit(1)
        .execute()
    )
    if not record_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="속기록을 찾을 수 없습니다.",
        )

    try:
        corrections = await auto_proofread(supabase, record_id)
        return {"corrections": corrections, "count": len(corrections)}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
    except Exception as e:
        logger.error("AI 맞춤법 교정 실패: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AI 맞춤법 교정에 실패했습니다.",
        )


# =============================================================================
# POST - AI 문단 자동 구분
# =============================================================================


@router.post(
    "/{meeting_id}/stenography/{record_id}/ai/paragraphs",
    summary="AI 문단 자동 구분",
)
async def ai_detect_paragraphs(
    meeting_id: str,
    record_id: str,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("stenographer", "admin")),
) -> dict:
    """GPT-5-mini를 사용하여 속기 라인의 문단을 자동 구분합니다.

    # @TASK P11C-T6 - AI 보조 API
    """
    from app.services.stenography_ai import auto_paragraphs

    # 레코드 확인
    record_result = (
        supabase.table("stenography_records")
        .select("id")
        .eq("id", record_id)
        .eq("meeting_id", meeting_id)
        .limit(1)
        .execute()
    )
    if not record_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="속기록을 찾을 수 없습니다.",
        )

    try:
        paragraphs = await auto_paragraphs(supabase, record_id)
        return {"paragraphs": paragraphs, "count": len(paragraphs)}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
    except Exception as e:
        logger.error("AI 문단 구분 실패: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AI 문단 구분에 실패했습니다.",
        )


# =============================================================================
# GET - 속기사 대시보드: 전체 속기록 목록
# =============================================================================


@dashboard_router.get(
    "",
    summary="전체 속기록 목록 (대시보드)",
)
async def list_all_stenography_records(
    status_filter: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    supabase: Client = Depends(get_supabase),
) -> dict:
    """전체 속기록 목록을 상태별로 조회합니다 (속기사 대시보드용).

    # @TASK P11C-T8 - 속기사 대시보드 API
    """
    try:
        query = supabase.table("stenography_records").select(
            "*, meetings!inner(title, meeting_date, committee)",
            count="exact",
        )

        if status_filter and status_filter in ("draft", "submitted", "approved"):
            query = query.eq("status", status_filter)

        query = query.order("created_at", desc=True).limit(limit).offset(offset)
        result = query.execute()

        return {
            "items": result.data or [],
            "total": result.count if hasattr(result, "count") and result.count else len(result.data or []),
        }
    except Exception:
        # Fallback: meetings join이 안 될 수 있음 (Supabase 설정 따라)
        try:
            query = supabase.table("stenography_records").select("*")
            if status_filter and status_filter in ("draft", "submitted", "approved"):
                query = query.eq("status", status_filter)
            query = query.order("created_at", desc=True).limit(limit).offset(offset)
            result = query.execute()
            return {
                "items": result.data or [],
                "total": len(result.data or []),
            }
        except Exception as e:
            logger.error("전체 속기록 목록 조회 실패: %s", e)
            return {"items": [], "total": 0}
