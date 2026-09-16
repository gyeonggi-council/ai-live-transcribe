"""채널 방송 상태 조회 서비스

경기도의회 생중계 사이트(live.ggc.go.kr)에서 실시간 방송 상태를 수집하고,
인메모리 캐시(5초 TTL)로 중복 요청을 방지합니다.
상태 변경 감지를 통해 SSE 이벤트를 트리거합니다.
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Optional

import httpx

from app.core.channels import get_all_channels, get_status_text, get_stream_override
from app.core.config import settings
from app.services.channel_status_providers import get_provider, group_by_provider

logger = logging.getLogger(__name__)

# 하위호환 — assembly_schedule_sync 가 이 이름을 import 한다. 값의 정본은 설정이다.
ONAIR_API_URL = settings.council_onair_api_url
CACHE_TTL_SECONDS = 5


class ChannelStatusService:
    """채널 방송 상태를 관리하는 싱글턴 서비스."""

    def __init__(self) -> None:
        # channel_id → livestatus (정본). 코드가 없는 채널도 여기엔 있다.
        self._status_by_id: dict[str, int] = {}
        self._schedule_by_id: dict[str, dict] = {}
        self._prev_status_by_id: dict[str, int] = {}
        # adCode → livestatus / 일정 (옛 계약 유지용 뷰)
        self._status: dict[str, int] = {}
        self._schedule: dict[str, dict] = {}
        # 캐시 타임스탬프
        self._last_fetched: float = 0.0
        # 동시 fetch 방지 락
        self._lock = asyncio.Lock()
        # 상태 변경 콜백 리스트 (SSE 구독자)
        self._subscribers: list[asyncio.Queue] = []

    async def fetch_status(self) -> dict[str, int]:
        """방송 상태를 가져옵니다 (캐시 적용).

        ⚠ **반환 키는 지금까지처럼 채널 코드(adCode)다.** 채널 ID 로 바꾸면
        `auto_stt` 의 `status_map.get(code, 0)` 이 전부 0 을 돌려주고 — 예외 없이 —
        STT 가 영영 시작되지 않는다. 채널 ID 로 받으려면 `get_status_map_by_id()`.
        """
        now = time.monotonic()
        if now - self._last_fetched < CACHE_TTL_SECONDS and self._status_by_id:
            return self._status

        async with self._lock:
            now = time.monotonic()
            if now - self._last_fetched < CACHE_TTL_SECONDS and self._status_by_id:
                return self._status

            self._prev_status_by_id = dict(self._status_by_id)
            channels = get_all_channels()
            merged: dict[str, int] = {}
            merged_schedule: dict[str, dict] = {}
            failed = False

            for provider_name, group in group_by_provider(channels).items():
                provider = get_provider(provider_name)
                if provider is None:
                    continue
                try:
                    merged.update(await provider.poll(group))
                    merged_schedule.update(await provider.schedules(group))
                except Exception as exc:              # noqa: BLE001
                    failed = True
                    logger.warning("방송 상태 조회 실패(%s): %s", provider_name, exc)

            if failed and not merged:
                # 전부 실패했으면 기존 캐시를 유지하고 짧게 재시도한다.
                self._last_fetched = time.monotonic() - (CACHE_TTL_SECONDS - 1)
                return self._status

            by_id = {ch["id"]: ch for ch in channels}
            self._status_by_id = merged
            self._schedule_by_id = merged_schedule
            # 코드 키 뷰 — 옛 계약을 그대로 유지한다
            self._status = {
                by_id[cid]["code"]: st
                for cid, st in merged.items()
                if by_id.get(cid) and by_id[cid].get("code")
            }
            self._schedule = {
                by_id[cid]["code"]: sc
                for cid, sc in merged_schedule.items()
                if by_id.get(cid) and by_id[cid].get("code")
            }
            self._last_fetched = time.monotonic()

            changes = self._detect_changes()
            if changes:
                await self._notify_subscribers(changes)

        return self._status

    async def get_status_map_by_id(self) -> dict[str, int]:
        """{channel_id: livestatus} — 코드가 없는 채널(기관 중립 제공자)도 포함한다."""
        await self.fetch_status()
        return dict(self._status_by_id)

    def _detect_changes(self) -> list[dict]:
        """이전 상태와 비교하여 변경된 채널 목록을 반환합니다.

        이벤트에 `channel_id` 를 **추가**하고 `code` 는 남긴다 — 코드가 없는 채널
        (기관 중립 제공자)도 변경 알림을 받아야 하고, 옛 구독자는 code 를 읽는다.
        """
        from app.core.channels import get_channel

        changes = []
        all_ids = set(self._status_by_id) | set(self._prev_status_by_id)
        for cid in all_ids:
            old = self._prev_status_by_id.get(cid)
            new = self._status_by_id.get(cid)
            if old == new:
                continue
            ch = get_channel(cid) or {}
            changes.append({
                "channel_id": cid,
                "code": ch.get("code") or "",
                "old_status": old,
                "new_status": new,
                "old_text": get_status_text(old) if old is not None else None,
                "new_text": get_status_text(new) if new is not None else None,
            })
        return changes

    async def _notify_subscribers(self, changes: list[dict]) -> None:
        """SSE 구독자에게 상태 변경 알림."""
        dead: list[asyncio.Queue] = []
        for queue in self._subscribers:
            try:
                queue.put_nowait(changes)
            except asyncio.QueueFull:
                dead.append(queue)
        for q in dead:
            self._subscribers.remove(q)

    def subscribe(self) -> asyncio.Queue:
        """SSE 구독 큐를 생성합니다."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """SSE 구독을 해제합니다."""
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    def get_schedule(self, code: str) -> Optional[dict]:
        """위원회 코드의 오늘 회차·차수를 반환합니다 (없으면 None).

        `fetch_status()` 가 채워 둔 캐시를 그대로 읽는다 — 여기서 새로 조회하지 않는다.
        라이브 회의 제목(`제393회 제1차 …`)을 만들 때 LiveMeetingManager 가 쓴다.
        """
        sched = self._schedule.get(code)
        if not sched:
            return None
        # API 가 값을 못 채우면 0 을 준다. 0 은 '없음'이지 '제0회'가 아니다.
        session_no = sched.get("session_no") or None
        session_order = sched.get("session_order") or None
        if session_no is None:
            return None
        return {"session_no": session_no, "session_order": session_order}

    async def get_channels_with_status(self) -> list[dict]:
        """전체 채널 목록에 방송 상태를 병합하여 반환합니다."""
        # 자막 WS 룸 연결 수 = 채널별 현재 시청자 수 (lazy import — 순환 참조 회피)
        from app.api.websocket import manager as ws_manager

        status_map = await self.get_status_map_by_id()
        result = []
        for ch in get_all_channels():
            channel_id = ch["id"]
            livestatus = status_map.get(channel_id, 0)
            schedule = self._schedule_by_id.get(channel_id, {})
            has_schedule = channel_id in self._schedule_by_id
            entry = {
                **ch,
                "livestatus": livestatus,
                "status_text": get_status_text(livestatus),
                "has_schedule": has_schedule,
                "viewers": len(ws_manager.active_connections.get(ch["id"], [])),
            }
            if has_schedule:
                entry["session_no"] = schedule.get("session_no", 0)
                entry["session_order"] = schedule.get("session_order", 0)

            # 외부 스트림 테스트(chT1 등): 커스텀 URL로 STT가 도는 동안에는
            # 그 URL과 '방송중'을 노출해 /live 플레이어가 같은 스트림을 재생.
            # (의회 방송 상태 API에는 없는 채널이라 변경 이벤트와 무관)
            override = get_stream_override(ch["id"])
            if override:
                from app.services.openai_realtime_stt import get_channel_stt_service

                if get_channel_stt_service().is_running(ch["id"]):
                    entry["stream_url"] = override
                    entry["livestatus"] = 1
                    entry["status_text"] = "외부 스트림 테스트"
            result.append(entry)
        return result


# 싱글턴 인스턴스
_service: Optional[ChannelStatusService] = None


def get_channel_status_service() -> ChannelStatusService:
    """ChannelStatusService 싱글턴을 반환합니다."""
    global _service
    if _service is None:
        _service = ChannelStatusService()
    return _service
