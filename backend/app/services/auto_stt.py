"""STT 자동 시작/중지 매니저

방송 상태 변경을 감지하여 STT를 자동으로 시작/중지합니다.

동작 방식:
- 서버 시작 시: 현재 방송중(livestatus=1)인 채널에 STT 자동 시작
- SSE 상태 변경 감지 시: 방송 시작 → STT 시작, 방송 종료 → STT 중지
- GET /api/channels/status 호출 시: 방송중인데 STT가 꺼진 채널 보정

안전장치:
- OpenAI API 키 미설정 시 비활성화
- stt_auto_start 설정으로 on/off 제어
- 이미 실행 중인 채널은 중복 시작 방지
"""

from __future__ import annotations

import asyncio
import logging

from app.core.channels import CHANNELS, get_channel_by_code
from app.core.config import settings
from app.services.channel_status import ChannelStatusService, get_channel_status_service
from app.services.openai_realtime_stt import get_channel_stt_service
from app.services.live_meeting import LiveMeetingManager, get_live_meeting_manager

logger = logging.getLogger(__name__)

# 방송 상태 코드
LIVESTATUS_BROADCASTING = 1
LIVESTATUS_BEFORE = 0
LIVESTATUS_ENDED = 3
LIVESTATUS_NO_STREAM = 4


class AutoSttManager:
    """방송 상태에 따라 STT를 자동 시작/중지하는 매니저.

    두 가지 메커니즘으로 동작합니다:
    1. SSE 구독을 통한 상태 변경 감지 (실시간 반응)
    2. ensure_stt_for_live_channels() 호출을 통한 보정 (폴링 호출 시)
    """

    def __init__(
        self,
        status_service: ChannelStatusService,
        stt_service,  # LiveBatchSttService | OpenAiRealtimeSttService (동일 인터페이스)
        live_meeting_mgr: LiveMeetingManager,
    ) -> None:
        self._status_service = status_service
        self._stt_service = stt_service
        self._live_meeting_mgr = live_meeting_mgr
        self._monitor_task: asyncio.Task | None = None  # type: ignore[type-arg]
        # 라이브 STT는 OpenAI Realtime 엔진을 사용 → OPENAI_API_KEY 필요
        self._enabled = settings.stt_auto_start and bool(settings.openai_api_key)
        # ★시작 진행 중 채널 (2026-07-22 ch1 실증: STT 셋업이 끝나 태스크가 등록되기
        #   전까지 is_running=False라, 시청자 폴링이 유발하는 ensure가 start를 계속
        #   큐잉해 직전 세션을 취소하는 폭풍 발생 — 진행 중이면 스킵)
        self._starting: set[str] = set()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _at_capacity(self, channel_id: str) -> bool:
        """동시 STT 채널 상한(비용 가드)에 도달했는지 검사한다."""
        active = len(self._stt_service.active_channels)
        if active >= settings.stt_max_concurrent_channels:
            logger.warning(
                "AutoSTT: 동시 STT 채널 상한(%d) 도달 — %s 자동 시작 보류 (active=%d)",
                settings.stt_max_concurrent_channels, channel_id, active,
            )
            return True
        return False

    async def start(self) -> None:
        """자동 STT 매니저를 시작합니다.

        1. 현재 방송중인 채널에 STT 자동 시작
        2. SSE 구독으로 상태 변경 모니터링 시작
        """
        if not self._enabled:
            if not settings.openai_api_key:
                logger.warning("AutoSttManager disabled: OPENAI_API_KEY not configured")
            elif not settings.stt_auto_start:
                logger.info("AutoSttManager disabled: stt_auto_start=False")
            return

        logger.info("AutoSttManager starting: auto-start STT for broadcasting channels")

        # 0. 서버 재시작 시 DB에서 live 회의 매핑 복원
        await self._live_meeting_mgr.recover_active_meetings()

        # 1. 현재 방송중인 채널에 STT 시작 (+ 회의 자동 생성)
        await self._start_stt_for_live_channels()

        # 2. SSE 구독으로 상태 변경 모니터링
        self._monitor_task = asyncio.create_task(
            self._monitor_status_changes(),
            name="auto-stt-monitor",
        )

    async def stop(self) -> None:
        """자동 STT 매니저를 중지합니다."""
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        # 모든 활성 채널 STT 정리
        await self._stt_service.stop_all()
        logger.info("AutoSttManager stopped (all channel STT cleaned up)")

    async def ensure_stt_for_live_channels(self) -> list[str]:
        """방송중인데 STT가 꺼진 채널을 보정합니다.

        GET /api/channels/status 호출 시 부수효과로 실행됩니다.
        이미 실행 중인 채널은 무시합니다.

        Returns:
            새로 STT를 시작한 채널 ID 목록
        """
        if not self._enabled:
            return []

        started = []
        status_map = await self._status_service.fetch_status()

        for ch in CHANNELS:
            code = ch["code"]
            channel_id = ch["id"]
            livestatus = status_map.get(code, 0)

            if livestatus == LIVESTATUS_BROADCASTING and not self._stt_service.is_running(channel_id):
                if channel_id in self._starting:  # 이미 시작 절차 진행 중 — 중복 기동 방지
                    continue
                if self._at_capacity(channel_id):
                    continue
                logger.info(
                    "AutoSTT: starting STT for live channel %s (%s) - detected via polling",
                    channel_id,
                    ch["name"],
                )
                self._starting.add(channel_id)
                try:
                    meeting_id = await self._live_meeting_mgr.create_meeting_for_channel(channel_id)
                    await self._stt_service.start(channel_id, ch["stream_url"], meeting_id=meeting_id)
                    started.append(channel_id)
                finally:
                    self._starting.discard(channel_id)

        return started

    async def _start_stt_for_live_channels(self) -> None:
        """현재 방송중인 모든 채널에 STT를 시작합니다."""
        try:
            status_map = await self._status_service.fetch_status()

            started_count = 0
            for ch in CHANNELS:
                code = ch["code"]
                channel_id = ch["id"]
                livestatus = status_map.get(code, 0)

                if livestatus == LIVESTATUS_BROADCASTING:
                    if not self._stt_service.is_running(channel_id):
                        if self._at_capacity(channel_id):
                            continue
                        logger.info(
                            "AutoSTT: starting STT for live channel %s (%s)",
                            channel_id,
                            ch["name"],
                        )
                        meeting_id = await self._live_meeting_mgr.create_meeting_for_channel(channel_id)
                        await self._stt_service.start(channel_id, ch["stream_url"], meeting_id=meeting_id)
                        started_count += 1
                    else:
                        logger.debug(
                            "AutoSTT: channel %s already running", channel_id
                        )

            if started_count > 0:
                logger.info("AutoSTT: started STT for %d broadcasting channels", started_count)
            else:
                logger.info("AutoSTT: no broadcasting channels found at startup")

        except Exception as e:
            logger.error("AutoSTT: failed to start STT for live channels: %s", e)

    async def _monitor_status_changes(self) -> None:
        """SSE 구독을 통해 상태 변경을 감지하고 STT를 자동 시작/중지합니다.

        상태 변경은 edge-trigger(전환 시 1회)라, 동시 채널 상한으로 보류된 채널은
        이벤트가 다시 오지 않는다. 60초 주기로 ensure를 돌려 슬롯이 비면 내부에서
        자동 재시도한다 (외부 HTTP 폴링에 의존하지 않음).
        """
        queue = self._status_service.subscribe()
        try:
            while True:
                try:
                    changes = await asyncio.wait_for(queue.get(), timeout=60.0)
                except asyncio.TimeoutError:
                    try:
                        await self.ensure_stt_for_live_channels()
                    except Exception as e:
                        logger.debug("AutoSTT periodic ensure failed: %s", e)
                    continue
                await self._handle_status_changes(changes)
        except asyncio.CancelledError:
            pass
        finally:
            self._status_service.unsubscribe(queue)

    async def _handle_status_changes(self, changes: list[dict]) -> None:
        """상태 변경 이벤트를 처리합니다.

        - 방송 시작 (new_status=1): 회의 자동 생성 + STT 시작
        - 정회 (new_status=2): STT만 중지, 회의는 유지 (재개 시 같은 회의 사용)
        - 방송 종료 (new_status=0,3,4): STT 중지 + 회의 종료
        - STT 중지로 슬롯이 비면: 상한 때문에 보류됐던 방송중 채널을 즉시 보정
        """
        stopped_any = False
        for change in changes:
            code = change.get("code", "")
            old_status = change.get("old_status")
            new_status = change.get("new_status")

            channel = get_channel_by_code(code)
            if channel is None:
                continue

            channel_id = channel["id"]
            channel_name = channel["name"]

            # 방송 시작 → 회의 생성 + STT 시작
            if new_status == LIVESTATUS_BROADCASTING and old_status != LIVESTATUS_BROADCASTING:
                if not self._stt_service.is_running(channel_id):
                    if self._at_capacity(channel_id):
                        continue
                    logger.info(
                        "AutoSTT: channel %s (%s) started broadcasting -> creating meeting + starting STT",
                        channel_id,
                        channel_name,
                    )
                    try:
                        meeting_id = await self._live_meeting_mgr.create_meeting_for_channel(channel_id)
                        await self._stt_service.start(channel_id, channel["stream_url"], meeting_id=meeting_id)
                    except Exception as e:
                        logger.error(
                            "AutoSTT: failed to start STT for %s: %s", channel_id, e
                        )

            # 방송 종료/정회 → STT 중지
            elif old_status == LIVESTATUS_BROADCASTING and new_status != LIVESTATUS_BROADCASTING:
                if self._stt_service.is_running(channel_id):
                    logger.info(
                        "AutoSTT: channel %s (%s) stopped broadcasting (status=%s) -> stopping STT",
                        channel_id,
                        channel_name,
                        change.get("new_text", new_status),
                    )
                    try:
                        await self._stt_service.stop(channel_id)
                        stopped_any = True
                    except Exception as e:
                        logger.error(
                            "AutoSTT: failed to stop STT for %s: %s", channel_id, e
                        )

                # 정회(2)는 회의 유지, 완전 종료(0,3,4)만 회의 종료
                if new_status in (LIVESTATUS_BEFORE, LIVESTATUS_ENDED, LIVESTATUS_NO_STREAM):
                    try:
                        await self._live_meeting_mgr.end_meeting_for_channel(channel_id)
                    except Exception as e:
                        logger.error(
                            "AutoSTT: failed to end meeting for %s: %s", channel_id, e
                        )

        # 슬롯이 비었으면 상한으로 보류됐던 방송중 채널을 즉시 보정
        if stopped_any:
            try:
                await self.ensure_stt_for_live_channels()
            except Exception as e:
                logger.debug("AutoSTT ensure-after-stop failed: %s", e)


# 싱글톤 인스턴스
_auto_stt_manager: AutoSttManager | None = None


def get_auto_stt_manager() -> AutoSttManager:
    """AutoSttManager 싱글톤을 반환합니다."""
    global _auto_stt_manager
    if _auto_stt_manager is None:
        _auto_stt_manager = AutoSttManager(
            status_service=get_channel_status_service(),
            stt_service=get_channel_stt_service(),
            live_meeting_mgr=get_live_meeting_manager(),
        )
    return _auto_stt_manager
