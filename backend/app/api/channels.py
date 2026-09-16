"""Channels API 라우터"""

import asyncio
import json
import logging
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse, Response, StreamingResponse

from app.core.auth_middleware import require_role
from app.core.channels import get_all_channels, get_channel, set_stream_override
from app.core.stream_hosts import allowed_stream_hosts
from app.core.config import settings
from app.services.auto_stt import get_auto_stt_manager
from app.services.channel_status import get_channel_status_service
from app.services.hls_parser import render_playlist
from app.services.live_batch_stt import live_sync_target_sec
from app.services.openai_realtime_stt import get_channel_stt_service

# SSRF 방지: 허용된 HLS 스트림 호스트.
# 목록의 정본은 core/stream_hosts.py 로 옮겼다 — 빌트인에 **등록된 채널의 호스트**를
# 더해, 다른 의회가 자기 CDN 을 등록하면 그 주소로도 STT 를 시작할 수 있게 하기 위해서다.

logger = logging.getLogger(__name__)

# 깊은 재생목록에서 CDN 으로 302 하는 최신 세그먼트 수 (get_channel_hls_segment)
HLS_CDN_TAIL = 4

router = APIRouter(prefix="/api/channels", tags=["channels"])


@router.get("")
async def list_channels() -> list[dict]:
    """전체 채널 목록을 반환합니다."""
    return get_all_channels()


@router.get("/status")
async def get_channels_status(background_tasks: BackgroundTasks) -> list[dict]:
    """전체 채널 + 실시간 방송 상태를 반환합니다.

    부수효과: 방송중인데 STT가 꺼진 채널이 있으면 백그라운드에서 자동 시작합니다.
    """
    service = get_channel_status_service()
    channels = await service.get_channels_with_status()

    # 각 채널에 STT 실행 상태 + /live 영상 지연 목표(서버 env, 재빌드 없이 조정) 추가.
    # /live 는 이 응답으로 방송 여부를 판정한 뒤 플레이어를 띄우므로 별도 왕복 없이 마운트 전에 값을 안다.
    stt_service = get_channel_stt_service()
    target = live_sync_target_sec()
    for ch in channels:
        ch["stt_running"] = stt_service.is_running(ch["id"])
        ch["sync_target_sec"] = target

    # 방송중인데 STT가 실행되지 않은 채널을 백그라운드에서 보정
    auto_stt = get_auto_stt_manager()
    if auto_stt.enabled:
        background_tasks.add_task(auto_stt.ensure_stt_for_live_channels)

    return channels


@router.get("/status/stream")
async def stream_channel_status() -> StreamingResponse:
    """SSE 스트림으로 채널 방송 상태 변경을 실시간 전송합니다.

    ★channel_sse_enabled=False면 404 — 시청자당 1개씩 상시 점유되는 스트림이
    터널(ngrok Hobby, TCP 연결 분당 150) 용량을 압박해 2026-07-21 장애의 한 축이 됐다.
    프론트(useChannelStatus)는 실패 시 30초 폴링으로 자동 폴백한다.
    NCP 실서버 이전 후 재활성화 권장.
    """
    if not settings.channel_sse_enabled:
        raise HTTPException(status_code=404, detail="SSE 비활성화 — 폴링을 사용하세요")
    service = get_channel_status_service()
    queue = service.subscribe()

    async def event_generator():
        try:
            # 초기 상태 전송
            channels = await service.get_channels_with_status()
            for ch in channels:
                ch["sync_target_sec"] = live_sync_target_sec()
            yield f"data: {json.dumps(channels, ensure_ascii=False)}\n\n"

            # 백그라운드 폴링 + 변경 이벤트 대기
            while True:
                try:
                    # 5초마다 폴링 트리거 (캐시 TTL과 동일)
                    changes = await asyncio.wait_for(queue.get(), timeout=5.0)
                    # 변경 발생 시 전체 상태 재전송
                    channels = await service.get_channels_with_status()
                    for ch in channels:
                        ch["sync_target_sec"] = live_sync_target_sec()
                    yield f"event: status_change\ndata: {json.dumps({'channels': channels, 'changes': changes}, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    # 타임아웃: 폴링 트리거 + keepalive
                    await service.fetch_status()
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            service.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{channel_id}/stt/start")
async def start_channel_stt(
    channel_id: str,
    replay_meeting: str | None = Query(None, description="DB 자막을 실시간 재생할 meeting_id (테스트용)"),
    stream_url: str | None = Query(None, description="커스텀 HLS 스트림 URL (외부 스트림 테스트용)"),
    _user: dict = Depends(require_role("admin", "meeting_manager")),
) -> dict:
    """채널 STT 처리를 시작합니다.

    replay_meeting이 제공되면 해당 회의의 DB 자막을 실시간 속도로 재생합니다.
    stream_url이 제공되면 채널 기본 URL 대신 해당 URL로 STT를 시작합니다.
    국회 웹캐스트 URL(assembly.webcast.go.kr)은 자동으로 HLS m3u8로 변환됩니다.
    """
    channel = get_channel(channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail=f"Channel {channel_id} not found")

    service = get_channel_stt_service()

    if service.is_running(channel_id):
        logger.info("STT start requested for %s: already running", channel_id)
        return {"status": "already_running", "channel_id": channel_id}

    # 동시 STT 채널 상한 (비용 가드) — 수동 시작도 자동 시작과 동일하게 적용
    if len(service.active_channels) >= settings.stt_max_concurrent_channels:
        raise HTTPException(
            status_code=429,
            detail=(
                f"동시 STT 채널 상한({settings.stt_max_concurrent_channels})에 도달했습니다. "
                "다른 채널 STT를 중지하거나 STT_MAX_CONCURRENT_CHANNELS 환경변수를 올려주세요."
            ),
        )

    if replay_meeting:
        # NOTE: 'DB 자막 실시간 재생' replay는 OpenAI 엔진 전환(Phase 12)에서 미지원.
        # replay_meeting은 "이 meeting_id에 바인딩된 라이브 STT 시작"으로 처리한다(크래시 방지).
        logger.info("STT start requested for %s (bind to meeting=%s)", channel_id, replay_meeting)
        await service.start(channel_id, channel["stream_url"], meeting_id=replay_meeting)
        return {"status": "started", "channel_id": channel_id, "mode": "live", "meeting_id": replay_meeting}

    # 커스텀 스트림 URL 처리 (SSRF 방지: 허용 호스트만)
    effective_url = channel["stream_url"]
    if stream_url:
        from app.services.assembly_stream_resolver import is_assembly_url, resolve_assembly_stream

        if is_assembly_url(stream_url):
            try:
                effective_url = await resolve_assembly_stream(stream_url)
                logger.info("Resolved assembly stream for %s: %s", channel_id, effective_url)
            except Exception as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"국회 스트림 URL 변환 실패: {e}",
                )
        else:
            # SSRF 방지: 허용된 호스트만 직접 URL로 사용
            parsed = urlparse(stream_url)
            host = (parsed.hostname or "").lower()
            if host not in allowed_stream_hosts():
                raise HTTPException(
                    status_code=422,
                    detail=f"허용되지 않은 스트림 호스트입니다: {host}",
                )
            effective_url = stream_url

    logger.info("STT start requested for %s (HLS): %s", channel_id, effective_url)
    await service.start(channel_id, effective_url)
    # 커스텀 URL이면 채널 상태에도 반영 — /live 플레이어가 같은 스트림을 재생해
    # 영상-자막 동기화를 실제 화면으로 검증할 수 있다.
    if stream_url:
        set_stream_override(channel_id, effective_url)
    return {
        "status": "started",
        "channel_id": channel_id,
        "mode": "HLS",
        "stream_url": effective_url,
    }


@router.post("/{channel_id}/stt/stop")
async def stop_channel_stt(
    channel_id: str,
    _user: dict = Depends(require_role("admin", "meeting_manager")),
) -> dict:
    """채널 STT 처리를 중지합니다.

    NOTE: AutoSttManager가 활성화되어 있으면 방송중인 채널의 STT를
    자동으로 재시작합니다. 클라이언트가 stop을 호출해도 방송중이면
    다음 폴링 시 보정됩니다.
    """
    channel = get_channel(channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail=f"Channel {channel_id} not found")

    service = get_channel_stt_service()
    # 테스트용 스트림 오버라이드 해제 (실행 여부와 무관하게 정리)
    set_stream_override(channel_id, None)

    if not service.is_running(channel_id):
        logger.info("STT stop requested for %s: not running", channel_id)
        return {"status": "not_running", "channel_id": channel_id}

    logger.info("STT stop requested for %s: stopping...", channel_id)
    await service.stop(channel_id)
    return {"status": "stopped", "channel_id": channel_id}


@router.get("/{channel_id}/stt/status")
async def get_channel_stt_status(channel_id: str) -> dict:
    """채널 STT 실행 상태를 확인합니다."""
    channel = get_channel(channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail=f"Channel {channel_id} not found")

    service = get_channel_stt_service()
    # 영상 지연 목표와 그 근거(ready_lag·edge_lag·sync_need 분포)도 같이 — 배치 엔진에만 있는 메서드라 getattr 가드
    sync_info = getattr(service, "get_sync_info", lambda _c: {})(channel_id)
    return {"running": service.is_running(channel_id), "channel_id": channel_id, **sync_info}


@router.get("/{channel_id}/stt/debug")
async def get_channel_stt_debug(channel_id: str) -> dict:
    """채널 STT 디버그 정보를 반환합니다."""
    channel = get_channel(channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail=f"Channel {channel_id} not found")

    service = get_channel_stt_service()
    return service.get_debug_info(channel_id)


@router.get("/{channel_id}/hls/playlist.m3u8")
async def get_channel_hls_playlist(channel_id: str) -> Response:
    """접속 즉시 20초 전에서 재생을 시작하게 하는 '깊은' 재생목록 (2026-09-08).

    원본 CDN 재생목록은 6초뿐이라 브라우저가 영상 지연 목표(20초)를 못 잡고 접속 직후
    ≈14초를 일시정지로 벌었다. STT 가 전사용으로 이미 받은 세그먼트 보관분(40초)이
    원본 창보다 깊으면 그것으로 재생목록을 만들고, 아니면(STT 미가동·막 시작) 원본으로
    302 — 그때는 예전 그대로 프런트 톱업 일시정지가 폴백한다.
    """
    channel = get_channel(channel_id)
    if channel is None or not channel.get("stream_url"):
        raise HTTPException(status_code=404, detail=f"Channel {channel_id} not found")
    origin_window, target, entries = get_channel_stt_service().get_hls_window(channel_id)
    buffered = sum(e[1] for e in entries)
    if not entries or buffered <= (origin_window or 0):
        return RedirectResponse(channel["stream_url"], status_code=302)
    return Response(
        render_playlist(entries, target),
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/{channel_id}/hls/{seq}.ts")
async def get_channel_hls_segment(channel_id: str, seq: int) -> Response:
    """보관분 세그먼트 — 재생목록의 상대경로 `{seq}.ts` 가 여기로 온다.

    최신 HLS_CDN_TAIL 개는 CDN 원본으로 302 (정상 재생 중 트래픽은 CDN 이 진다 — 전부를 서버가
    중계하면 시청자 수 × 0.74Mbps 가 poc-app 에 실린다). 재생목록의 URI 자체를 CDN 주소로 바꾸면
    hls.js 가 sn 별 URI 변경을 오류로 보므로(render_playlist 참조) 분산은 반드시 여기서 한다.
    CDN 은 재생목록에서 빠진 뒤 7개까지 더 주므로 4개면 여유 3개 (2026-09-08 ch7 실측).
    """
    service = get_channel_stt_service()
    _, _, entries = service.get_hls_window(channel_id)
    for s, _, url, *_ in entries[-HLS_CDN_TAIL:]:
        if s == seq:
            return RedirectResponse(url, status_code=302)
    data = service.get_hls_segment(channel_id, seq)
    if data is None:
        raise HTTPException(status_code=404, detail="segment not buffered")
    return Response(data, media_type="video/MP2T", headers={"Cache-Control": "no-cache"})


@router.get("/{channel_id}")
async def get_channel_by_id(channel_id: str) -> dict:
    """채널 ID로 채널을 조회합니다."""
    channel = get_channel(channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail=f"Channel {channel_id} not found")
    return channel
