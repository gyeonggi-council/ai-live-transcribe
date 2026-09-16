"""스트림 탐침 제공자 — m3u8 을 직접 보고 방송 여부를 판정한다 (2026-09-16)

기관 중립 기본값이다. 생중계 API 가 없는 의회는 이것으로 자동 STT 가 돈다.

판정 근거는 **미디어 시퀀스(또는 마지막 세그먼트 이름)가 늘어나는가** 하나다.
  · 늘었다                      → 1 방송중 (즉시. 히스테리시스 없음)
  · 안 늘고 60초 지남           → 2 정회중
  · 안 늘고 300초 지남          → 3 종료
  · #EXT-X-ENDLIST              → 3 종료
  · HTTP 실패 3연속             → 0 방송전

켜짐을 즉시, 꺼짐을 느리게 두는 이유: STT 시작 비용은 낮다(무음 창은 API 호출 자체를
생략한다). 반대로 꺼짐 판정은 회의를 닫으므로 깜빡임에 강해야 한다. 정회(2)는 회의를
유지하는 기존 auto_stt 로직을 그대로 탄다.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field

import httpx

from app.core.config import settings

from .base import (
    LIVESTATUS_BEFORE,
    LIVESTATUS_BROADCASTING,
    LIVESTATUS_ENDED,
    LIVESTATUS_RECESS,
)

logger = logging.getLogger(__name__)

_MEDIA_SEQ_RE = re.compile(r"#EXT-X-MEDIA-SEQUENCE:\s*(\d+)")
_ENDLIST = "#EXT-X-ENDLIST"
# 마스터 재생목록이면 첫 미디어 재생목록으로 한 번만 내려간다
_URI_LINE_RE = re.compile(r"^(?!#)(\S+)$", re.MULTILINE)

MAX_BYTES = 256 * 1024          # 재생목록은 수 KB 다. 그 이상은 우리가 찾는 것이 아니다
MAX_FAIL_STREAK = 3
BACKOFF_STEPS = (0, 20, 40, 80, 160, 300)


@dataclass
class _ProbeState:
    marker: str = ""            # 마지막으로 본 시퀀스/세그먼트 이름
    changed_at: float = 0.0
    fail_streak: int = 0
    backoff_until: float = 0.0
    media_url: str = ""         # 마스터를 한 번 푼 결과를 재사용
    last_status: int = LIVESTATUS_BEFORE


class StreamProbeProvider:
    name = "probe"

    def __init__(self) -> None:
        self._state: dict[str, _ProbeState] = {}

    # ------------------------------------------------------------------ 내부
    @staticmethod
    def _marker_of(text: str) -> tuple[str, bool]:
        """(진행 표시자, 끝났는가). 표시자가 바뀌면 방송 중이라는 뜻이다."""
        ended = _ENDLIST in text
        m = _MEDIA_SEQ_RE.search(text)
        if m:
            return m.group(1), ended
        uris = _URI_LINE_RE.findall(text)
        return (uris[-1] if uris else ""), ended

    @staticmethod
    def _is_master(text: str) -> bool:
        return "#EXT-X-STREAM-INF" in text and "#EXTINF" not in text

    async def _fetch(self, client: httpx.AsyncClient, url: str) -> str:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                chunks.append(chunk)
                total += len(chunk)
                if total >= MAX_BYTES:
                    break
        return b"".join(chunks).decode("utf-8", "replace")

    async def _probe_one(self, client: httpx.AsyncClient, channel: dict) -> int:
        cid = channel["id"]
        st = self._state.setdefault(cid, _ProbeState())
        now = time.monotonic()

        if now < st.backoff_until:
            return st.last_status

        url = st.media_url or channel.get("stream_url") or ""
        if not url:
            return LIVESTATUS_BEFORE

        try:
            text = await self._fetch(client, url)
            if self._is_master(text) and not st.media_url:
                uris = _URI_LINE_RE.findall(text)
                if uris:
                    st.media_url = httpx.URL(url).join(uris[0]).__str__()
                    text = await self._fetch(client, st.media_url)
        except Exception as exc:                      # noqa: BLE001
            st.fail_streak += 1
            st.media_url = ""                         # 마스터 해석을 다시 하게 한다
            step = BACKOFF_STEPS[min(st.fail_streak, len(BACKOFF_STEPS) - 1)]
            st.backoff_until = now + step
            if st.fail_streak >= MAX_FAIL_STREAK:
                st.last_status = LIVESTATUS_BEFORE
            logger.debug("탐침 실패 %s (%d회): %s", cid, st.fail_streak, exc)
            return st.last_status

        st.fail_streak = 0
        st.backoff_until = 0.0
        marker, ended = self._marker_of(text)

        if ended:
            st.last_status = LIVESTATUS_ENDED
            return st.last_status

        if marker and marker != st.marker:
            st.marker = marker
            st.changed_at = now
            st.last_status = LIVESTATUS_BROADCASTING
            return st.last_status

        if not st.changed_at:
            st.changed_at = now

        idle = now - st.changed_at
        if idle >= settings.probe_off_seconds:
            st.last_status = LIVESTATUS_ENDED
        elif idle >= settings.probe_stale_seconds:
            st.last_status = LIVESTATUS_RECESS
        return st.last_status

    # ------------------------------------------------------------------ 공개
    async def poll(self, channels: list[dict]) -> dict[str, int]:
        if not channels:
            return {}

        # STT 가 이미 도는 채널은 건너뛴다 — live_batch_stt 가 초당 1회 같은 재생목록을
        # 폴링하고 있어서, 여기서 또 받으면 CDN 요청만 두 배가 된다.
        try:
            from app.services.openai_realtime_stt import get_channel_stt_service

            running = get_channel_stt_service()
        except Exception:                             # noqa: BLE001
            running = None

        sem = asyncio.Semaphore(max(1, settings.probe_concurrency))
        result: dict[str, int] = {}

        async with httpx.AsyncClient(
            timeout=settings.probe_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ggc-live-transcribe/1.0)"},
        ) as client:

            async def one(ch: dict) -> None:
                cid = ch["id"]
                if running is not None:
                    try:
                        if running.is_running(cid):
                            result[cid] = LIVESTATUS_BROADCASTING
                            return
                    except Exception:                 # noqa: BLE001
                        pass
                async with sem:
                    try:
                        result[cid] = await self._probe_one(client, ch)
                    except Exception as exc:          # noqa: BLE001 — 루프를 죽이지 않는다
                        logger.debug("탐침 예외 %s: %s", cid, exc)
                        result[cid] = self._state.get(cid, _ProbeState()).last_status

            await asyncio.gather(*(one(ch) for ch in channels))

        return result

    async def schedules(self, channels: list[dict]) -> dict[str, dict]:
        return {}
