"""얼굴로 의원 찾기 API.

- POST /api/faces/identify              브라우저가 보낸 화면 한 장에서 의원 식별
- POST /api/channels/{id}/identify-faces 서버가 직접 뜬 화면에서 의원 식별(대비책)
- GET  /api/faces/status                명부 적재 상태(몇 명분 얼굴이 있나)
- POST /api/faces/rebuild               공식 사진으로 명부 재적재 (관리자)
- DELETE /api/faces/{councilor_id}/video 자동 등록된 현장 템플릿 삭제 (관리자)

식별 자체는 로그인 없이 쓸 수 있다 — 의원 이름·정당·선거구는 의회 홈페이지에 공개된 정보이고,
이 화면은 의회망 손님도 보기 때문이다. 대신 CPU 를 쓰는 요청이라 **동시 1건·연타 차단**을 둔다.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from supabase import Client

from app.core.auth_middleware import require_role
from app.core.config import settings
from app.core.database import get_supabase
from app.services import face_identify, face_index

logger = logging.getLogger(__name__)

router = APIRouter(tags=["faces"])

_MAX_IMAGE_BYTES = 6 * 1024 * 1024

# 호출자별 연타 차단 (프로세스 안 단순 기록 — 파드 1개 전제, 실패해도 기능만 느려진다)
_last_call: dict[str, float] = {}


def _throttle(key: str) -> None:
    now = time.time()
    prev = _last_call.get(key, 0.0)
    if now - prev < settings.face_min_interval_seconds:
        raise HTTPException(status_code=429, detail="잠시 후 다시 눌러 주세요.")
    _last_call[key] = now
    if len(_last_call) > 500:
        cutoff = now - 600
        for k in [k for k, v in _last_call.items() if v < cutoff]:
            _last_call.pop(k, None)


def _client_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?"))


def _ensure_enabled() -> None:
    if not settings.face_recognition_enabled:
        raise HTTPException(status_code=503, detail="얼굴 찾기 기능이 꺼져 있습니다.")


@router.post("/api/faces/identify", summary="화면 한 장에서 의원 식별")
async def identify_uploaded_frame(
    request: Request,
    file: UploadFile = File(..., description="영상 화면 캡처 (JPEG/PNG)"),
    channel_id: str | None = Form(None),
    speaker_hint: str | None = Form(None),
    supabase: Client = Depends(get_supabase),
) -> dict:
    _ensure_enabled()
    _throttle(_client_key(request))
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="이미지가 비어 있습니다.")
    if len(raw) > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="이미지가 너무 큽니다(최대 6MB).")
    try:
        return await face_identify.identify_image(
            supabase, raw, channel_id=channel_id, speaker_hint=speaker_hint
        )
    except face_index.FaceModelUnavailable as e:
        logger.warning("얼굴 모델 사용 불가: %s", e)
        raise HTTPException(status_code=503, detail="얼굴 인식 모델이 준비되지 않았습니다.") from e


@router.post("/api/channels/{channel_id}/identify-faces", summary="채널 현재 화면에서 의원 식별")
async def identify_channel_frame(
    channel_id: str,
    request: Request,
    speaker_hint: str | None = None,
    supabase: Client = Depends(get_supabase),
) -> dict:
    _ensure_enabled()
    _throttle(_client_key(request))
    try:
        return await face_identify.identify_channel(supabase, channel_id, speaker_hint=speaker_hint)
    except face_index.FaceModelUnavailable as e:
        raise HTTPException(status_code=503, detail="얼굴 인식 모델이 준비되지 않았습니다.") from e


@router.get("/api/faces/status", summary="얼굴 명부 상태")
async def face_status(supabase: Client = Depends(get_supabase)) -> dict:
    return {
        "enabled": settings.face_recognition_enabled,
        **face_index.gallery_stats(supabase),
    }


@router.post("/api/faces/rebuild", summary="공식 사진으로 얼굴 명부 적재 (관리자)")
async def rebuild_faces(
    only_missing: bool = True,
    _user: dict = Depends(require_role("admin")),
    supabase: Client = Depends(get_supabase),
) -> dict:
    _ensure_enabled()
    try:
        return await face_index.rebuild_portrait_gallery(supabase, only_missing=only_missing)
    except face_index.FaceModelUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.delete("/api/faces/{councilor_id}/video", summary="자동 등록된 현장 템플릿 삭제 (관리자)")
async def delete_video_templates(
    councilor_id: str,
    _user: dict = Depends(require_role("admin")),
    supabase: Client = Depends(get_supabase),
) -> dict:
    res = (
        supabase.table("councilor_faces")
        .delete()
        .eq("councilor_id", councilor_id)
        .eq("source", "video")
        .execute()
    )
    face_index.invalidate_gallery()
    return {"deleted": len(res.data or [])}
