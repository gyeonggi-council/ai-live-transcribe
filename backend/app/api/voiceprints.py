"""의원 목소리 샘플(voiceprint) API — 실명 화자 식별 등록/관리.

- POST /api/councilors/{id}/voiceprint            업로드한 음성으로 등록
- GET  /api/councilors/{id}/voiceprint            등록 상태
- DELETE /api/councilors/{id}/voiceprint          삭제
- GET  /api/voiceprints                           등록 목록 (위원회별)
- POST /api/meetings/{mid}/speakers/enroll-from-clip   기존 회의 VOD 구간에서 등록
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.core.auth_middleware import require_role
from app.core.config import settings
from app.core.database import get_supabase_client
from app.services.voiceprint_service import VoiceprintError, voiceprint_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["voiceprints"])

# 업로드 파일 상한 (등록 시 10초로 트림되므로 여유 있게)
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


@router.post("/councilors/{councilor_id}/voiceprint")
async def enroll_voiceprint(
    councilor_id: str,
    file: UploadFile = File(...),
    _user: dict = Depends(require_role("admin", "meeting_manager")),
) -> dict:
    """업로드한 음성 파일로 의원 목소리를 등록한다(16kHz wav로 정규화, 2~10초)."""
    audio = await file.read()
    if len(audio) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="파일이 너무 큽니다(최대 25MB).")
    try:
        result = await voiceprint_service.enroll_from_bytes(councilor_id, audio, source="upload")
    except VoiceprintError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "enrolled", **result}


@router.get("/councilors/{councilor_id}/voiceprint")
async def get_voiceprint_status(councilor_id: str) -> dict:
    """의원 목소리 등록 상태."""
    return voiceprint_service.get_status(councilor_id)


@router.patch("/councilors/{councilor_id}/voiceprint/chair")
async def set_voiceprint_chair(
    councilor_id: str,
    body: dict,
    _user: dict = Depends(require_role("admin", "meeting_manager")),
) -> dict:
    """의원을 소속 위원회의 위원장으로 지정/해제 (위원회당 1명, 실시간 식별 slot 1 고정)."""
    is_chair = bool(body.get("is_chair", True))
    ok = voiceprint_service.set_chair(councilor_id, is_chair)
    if not ok:
        raise HTTPException(status_code=404, detail="먼저 목소리를 등록해야 위원장으로 지정할 수 있습니다.")
    return {"status": "ok", "councilor_id": councilor_id, "is_chair": is_chair}


@router.delete("/councilors/{councilor_id}/voiceprint")
async def delete_voiceprint(
    councilor_id: str,
    _user: dict = Depends(require_role("admin", "meeting_manager")),
) -> dict:
    """의원 목소리 샘플 삭제."""
    deleted = voiceprint_service.delete(councilor_id)
    return {"status": "deleted" if deleted else "not_found", "councilor_id": councilor_id}


@router.get("/voiceprints")
async def list_voiceprints() -> dict:
    """등록된 목소리 목록(메타데이터만, 위원회별로 ≤4명 권장)."""
    items = voiceprint_service.list_enrolled()
    return {"voiceprints": items, "total": len(items), "max_per_committee": settings.diarize_max_known_speakers}


@router.post("/meetings/{meeting_id}/speakers/enroll-from-clip")
async def enroll_from_clip(
    meeting_id: str,
    body: dict,
    _user: dict = Depends(require_role("admin", "meeting_manager")),
) -> dict:
    """기존 회의 VOD의 특정 구간([start,end])을 의원 목소리로 등록한다.

    화자가 명확히 식별된 발언 구간을 골라 해당 의원의 voiceprint로 부트스트랩하는 용도.
    body: {councilor_id, start(초), end(초)}
    """
    councilor_id = body.get("councilor_id")
    start = body.get("start")
    end = body.get("end")
    if not councilor_id or start is None or end is None:
        raise HTTPException(status_code=422, detail="councilor_id, start, end가 필요합니다.")
    try:
        start_f = float(start)
        end_f = float(end)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="start/end는 숫자(초)여야 합니다.")
    dur = end_f - start_f
    if dur <= 0:
        raise HTTPException(status_code=400, detail="end는 start보다 커야 합니다.")
    dur = min(dur, settings.voiceprint_max_seconds)

    supabase = get_supabase_client()
    m = supabase.table("meetings").select("vod_url").eq("id", meeting_id).limit(1).execute()
    if not m.data or not m.data[0].get("vod_url"):
        raise HTTPException(status_code=404, detail="회의 VOD를 찾을 수 없습니다.")
    vod_url = m.data[0]["vod_url"]

    wav = await _extract_clip_wav(vod_url, start_f, dur)
    if not wav:
        raise HTTPException(status_code=502, detail="VOD 구간 오디오 추출 실패(ffmpeg).")
    try:
        result = await voiceprint_service.enroll_from_bytes(councilor_id, wav, source="meeting_clip")
    except VoiceprintError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "enrolled", **result}


async def _extract_clip_wav(url: str, start: float, dur: float) -> bytes | None:
    """VOD URL의 [start, start+dur] 구간을 16kHz mono wav로 추출(ffmpeg HTTP seek)."""
    rate = settings.voiceprint_sample_rate
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-ss", str(start), "-t", str(dur), "-i", url,
            "-vn", "-ac", "1", "-ar", str(rate), "-f", "wav", "pipe:1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        logger.error("ffmpeg not installed — clip enrollment unavailable")
        return None
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
    except asyncio.TimeoutError:
        proc.kill()
        return None
    if proc.returncode != 0 or len(stdout) < 100:
        logger.warning("clip extract failed (rc=%s): %s", proc.returncode, stderr[:200].decode("utf-8", "ignore"))
        return None
    return stdout
