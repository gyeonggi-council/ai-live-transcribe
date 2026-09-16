"""의원정보 API 라우터"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import Client

from app.core.database import get_supabase
from app.services.councilor_sync import CouncilorSyncService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/councilors", tags=["councilors"])


def _get_service(supabase: Client = Depends(get_supabase)) -> CouncilorSyncService:
    return CouncilorSyncService(supabase)


@router.get("")
async def list_councilors(
    committee: str | None = Query(None, description="위원회 필터"),
    q: str | None = Query(None, description="검색어 (이름/정당/지역구)"),
    service: CouncilorSyncService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """의원 목록 조회 (필터/검색)"""
    if q:
        return service.search(q)
    if committee:
        return service.get_by_committee(committee)
    return service.get_all_active()


@router.get("/sync-status")
async def get_sync_status(
    service: CouncilorSyncService = Depends(_get_service),
) -> dict[str, Any]:
    """동기화 상태 조회"""
    last_sync = service.get_last_sync_time()
    all_active = service.get_all_active()
    return {
        "last_synced_at": last_sync,
        "active_count": len(all_active),
    }


@router.get("/{councilor_id}")
async def get_councilor(
    councilor_id: str,
    service: CouncilorSyncService = Depends(_get_service),
) -> dict[str, Any]:
    """의원 상세 조회"""
    result = service.get_by_id(councilor_id)
    if not result:
        raise HTTPException(status_code=404, detail="의원을 찾을 수 없습니다.")
    return result


@router.post("/sync")
async def sync_councilors(
    service: CouncilorSyncService = Depends(_get_service),
) -> dict[str, Any]:
    """경기도의회 API에서 의원정보 동기화 (관리자용)"""
    try:
        result = await service.sync_from_api()
        return {
            "message": "동기화 완료",
            **result,
        }
    except Exception as e:
        logger.error("의원 동기화 실패: %s", e)
        raise HTTPException(
            status_code=502,
            detail=f"경기도의회 API 동기화 실패: {e}",
        ) from e


# ─── 의원 사진 (압축 프록시, 2026-07-20) ─────────────────────────────────
# ggc.go.kr 원본(_org, 수십~수백 KB)을 그대로 쓰면 위원 명단 모달이 무겁다.
# 최초 요청 시 내려받아 축소(폭 128px, JPEG q=72, ~5KB) 후 디스크 캐시.
_PHOTO_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "photo_cache",
)


@router.get("/{councilor_id}/photo")
async def councilor_photo(
    councilor_id: str,
    supabase: Client = Depends(get_supabase),
):
    """의원 사진 (128px 축소 JPEG, 24시간 캐시)"""
    import asyncio
    import io

    import httpx
    from fastapi.responses import FileResponse

    cache_path = os.path.join(_PHOTO_CACHE_DIR, f"{councilor_id}.jpg")
    headers = {"Cache-Control": "public, max-age=86400"}
    if os.path.isfile(cache_path):
        return FileResponse(cache_path, media_type="image/jpeg", headers=headers)

    row = (
        supabase.table("councilors")
        .select("profile_image_url")
        .eq("id", councilor_id)
        .limit(1)
        .execute()
    ).data
    url = (row[0].get("profile_image_url") or "") if row else ""
    if not url:
        raise HTTPException(status_code=404, detail="사진이 등록되지 않았습니다.")
    if url.startswith("/"):
        url = "https://www.ggc.go.kr" + url

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            raw = resp.content
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"사진 원본 조회 실패: {e}") from e

    def _shrink() -> bytes:
        from PIL import Image

        img = Image.open(io.BytesIO(raw)).convert("RGB")
        img.thumbnail((128, 170))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=72, optimize=True)
        return buf.getvalue()

    try:
        small = await asyncio.to_thread(_shrink)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"사진 처리 실패: {e}") from e

    os.makedirs(_PHOTO_CACHE_DIR, exist_ok=True)
    with open(cache_path, "wb") as f:
        f.write(small)
    return FileResponse(cache_path, media_type="image/jpeg", headers=headers)
