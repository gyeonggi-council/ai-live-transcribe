"""채널 관리 API — 다른 의회가 자기 생중계 주소를 넣는 자리 (2026-09-16)

★공개 `/api/channels` 라우터와 **별도 prefix** 다. 같은 라우터에 넣으면
  기존 `@router.get("/{channel_id}")` 가 먼저 선언돼 있어 `/api/channels/discover` 를
  channel_id 로 잡아 404 를 낸다(FastAPI 는 선언 순서로 매칭한다).
  분리해 두면 공개 계약이 한 글자도 안 바뀐다.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from supabase import Client

from app.core.auth_middleware import require_role
from app.core.channels import channels_snapshot_info, invalidate_channels, refresh_channels
from app.core.config import settings
from app.core.database import get_supabase
from app.core.url_guard import UnsafeUrlError, assert_safe_url
from app.repositories.channel_repository import ChannelRepository
from app.schemas.channel import (
    ChannelBulkCreate,
    ChannelCreate,
    ChannelUpdate,
    DiscoverRequest,
    ManualStatusRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/channels",
    tags=["admin-channels"],
    dependencies=[Depends(require_role("admin"))],
)

PRESETS_PATH = Path(__file__).resolve().parent.parent / "data" / "council_presets.json"


def _repo(db: Client) -> ChannelRepository:
    return ChannelRepository(db)


def _check_url(value: str | None, field: str) -> None:
    """등록 시에는 **허용 호스트 목록을 보지 않는다** — 보면 새 호스트를 영원히 못 넣는다.
    대신 내부망·이상한 포트·이상한 스킴만 막는다."""
    if not value:
        return
    try:
        assert_safe_url(value)
    except UnsafeUrlError as exc:
        raise HTTPException(status_code=422, detail=f"{field}: {exc}") from exc


@router.get("")
async def list_channels_admin(db: Client = Depends(get_supabase)) -> dict:
    """비활성 채널까지 포함한 전량 + 캐시 상태."""
    return {"items": _repo(db).list_all(), "snapshot": channels_snapshot_info()}


@router.get("/presets")
async def list_presets() -> dict:
    """전국 의회 생중계 페이지 목록(광역 17 + 경기 시·군 31).

    **영상 주소가 아니라 생중계 페이지 주소다.** 대부분의 의회는 방송 중일 때만
    영상 주소가 드러나기 때문이다(2026-09-16 실측). 페이지를 넣으면 자동 찾기가 돈다.
    """
    if not PRESETS_PATH.exists():
        return {"councils": [], "generated_at": None}
    return json.loads(PRESETS_PATH.read_text(encoding="utf-8"))


@router.post("", status_code=201)
async def create_channel(payload: ChannelCreate, db: Client = Depends(get_supabase)) -> dict:
    repo = _repo(db)
    if repo.get(payload.id):
        raise HTTPException(status_code=409, detail=f"이미 있는 채널 ID 입니다: {payload.id}")
    if payload.code and repo.get_by_code(payload.code):
        raise HTTPException(status_code=409, detail=f"이미 쓰는 채널 코드입니다: {payload.code}")
    _check_url(payload.stream_url, "stream_url")
    _check_url(payload.page_url, "page_url")

    row = repo.create(payload.model_dump())
    invalidate_channels()
    return row


@router.post("/bulk")
async def create_channels_bulk(
    payload: ChannelBulkCreate, db: Client = Depends(get_supabase)
) -> dict:
    """자동 찾기 결과를 한 번에 저장한다. 실패한 항목은 건너뛰고 사유를 돌려준다."""
    repo = _repo(db)
    created, skipped, errors = [], [], []
    for item in payload.items:
        try:
            if repo.get(item.id) or (item.code and repo.get_by_code(item.code)):
                skipped.append(item.id)
                continue
            _check_url(item.stream_url, "stream_url")
            repo.create(item.model_dump())
            created.append(item.id)
        except HTTPException as exc:
            errors.append({"id": item.id, "detail": exc.detail})
        except Exception as exc:                        # noqa: BLE001
            errors.append({"id": item.id, "detail": str(exc)})
    invalidate_channels()
    return {"created": created, "skipped": skipped, "errors": errors}


@router.patch("/{channel_id}")
async def update_channel(
    channel_id: str, payload: ChannelUpdate, db: Client = Depends(get_supabase)
) -> dict:
    repo = _repo(db)
    if not repo.get(channel_id):
        raise HTTPException(status_code=404, detail=f"없는 채널입니다: {channel_id}")

    patch = payload.model_dump(exclude_unset=True)
    if "id" in patch:
        raise HTTPException(status_code=422, detail="채널 ID 는 바꿀 수 없습니다")
    if patch.get("code"):
        other = repo.get_by_code(patch["code"])
        if other and other["id"] != channel_id:
            raise HTTPException(status_code=409, detail=f"이미 쓰는 채널 코드입니다: {patch['code']}")
    _check_url(patch.get("stream_url"), "stream_url")
    _check_url(patch.get("page_url"), "page_url")

    row = repo.update(channel_id, patch)
    invalidate_channels()
    return row or {}


@router.delete("/{channel_id}", status_code=204)
async def delete_channel(
    channel_id: str, hard: bool = False, db: Client = Depends(get_supabase)
) -> Response:
    repo = _repo(db)
    if not repo.get(channel_id):
        raise HTTPException(status_code=404, detail=f"없는 채널입니다: {channel_id}")

    from app.services.openai_realtime_stt import get_channel_stt_service

    if get_channel_stt_service().is_running(channel_id):
        raise HTTPException(
            status_code=409,
            detail="이 채널의 자막이 돌고 있습니다. 먼저 STT 를 중지해 주세요.",
        )

    if hard:
        # 지난 회의가 이 채널을 가리키면 지우지 않는다 — 회의 목록의 위원회명이 빈다.
        used = db.table("meetings").select("id").eq("channel_id", channel_id).limit(1).execute()
        if used.data:
            raise HTTPException(
                status_code=409,
                detail="이 채널로 진행한 회의가 있어 완전 삭제할 수 없습니다. 비활성으로 두세요.",
            )
        repo.delete(channel_id)
    else:
        repo.soft_delete(channel_id)

    invalidate_channels()
    return Response(status_code=204)


@router.post("/reorder")
async def reorder_channels(ids: list[str], db: Client = Depends(get_supabase)) -> dict:
    repo = _repo(db)
    for index, channel_id in enumerate(ids):
        repo.update(channel_id, {"sort_order": (index + 1) * 10})
    invalidate_channels()
    return {"ok": True, "count": len(ids)}


@router.post("/discover")
async def discover(payload: DiscoverRequest) -> dict:
    """생중계 페이지 주소에서 채널 후보를 찾는다."""
    if not settings.discovery_enabled:
        raise HTTPException(status_code=503, detail="자동 찾기가 꺼져 있습니다")
    from app.services.stream_discovery import discover_channels

    return (await discover_channels(payload.page_url)).to_dict()


@router.post("/{channel_id}/probe")
async def probe_channel(channel_id: str, db: Client = Depends(get_supabase)) -> dict:
    """이 채널의 영상 주소를 지금 한 번 받아 본다 (등록 전후 확인용)."""
    row = _repo(db).get(channel_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"없는 채널입니다: {channel_id}")

    from app.core.url_guard import safe_fetch

    url = row.get("stream_url") or ""
    if not url:
        return {"ok": False, "detail": "영상 주소가 비어 있습니다"}
    try:
        res = await safe_fetch(url, max_bytes=8192, timeout=5.0, allow_insecure_tls=True)
    except Exception as exc:                            # noqa: BLE001
        return {"ok": False, "detail": str(exc)}
    is_playlist = res.text.lstrip().startswith("#EXTM3U")
    return {
        "ok": is_playlist,
        "http_status": res.status_code,
        "insecure_tls": res.insecure,
        # 방송 전에는 살아 있는 주소도 404 를 준다 — 실패로 읽지 않게 문구로 알린다.
        "detail": "재생목록 확인됨" if is_playlist else "응답 없음 (방송 전일 수 있습니다)",
    }


@router.post("/{channel_id}/manual-status")
async def set_manual_status(
    channel_id: str, payload: ManualStatusRequest, db: Client = Depends(get_supabase)
) -> dict:
    """수동 방송 상태를 켠다. `minutes` 뒤 자동으로 꺼진다."""
    repo = _repo(db)
    if not repo.get(channel_id):
        raise HTTPException(status_code=404, detail=f"없는 채널입니다: {channel_id}")
    until = datetime.now(timezone.utc) + timedelta(minutes=payload.minutes)
    row = repo.update(
        channel_id,
        {"manual_status": payload.livestatus, "manual_until": until.isoformat()},
    )
    invalidate_channels()
    return row or {}


@router.post("/refresh")
async def refresh_cache() -> dict:
    """캐시를 지금 다시 읽는다 (다른 파드는 TTL 로 따라온다)."""
    count = refresh_channels(force=True)
    return {"count": count, "snapshot": channels_snapshot_info()}
