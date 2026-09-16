"""수동·일정 제공자 — 관리자가 켜고 끄거나, 등록된 의사일정으로 판정한다 (2026-09-16)

자동 감지가 안 되는 기관의 안전한 시작점이다. "주소는 아는데 방송 여부를 알 길이 없는"
상태에서도 회의 시간에 관리자가 한 번 켜면 자막이 나온다.

`manual_until` 로 **반드시 만료시킨다** — 끄는 것을 잊으면 STT 가 밤새 돌아 비용이 샌다.
채널 동시 실행 상한(STT_MAX_CONCURRENT_CHANNELS)은 개수만 막지 시간은 못 막는다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .base import LIVESTATUS_BEFORE

logger = logging.getLogger(__name__)


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


class ManualProvider:
    name = "manual"

    async def poll(self, channels: list[dict]) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        out: dict[str, int] = {}
        for ch in channels:
            status = ch.get("manual_status")
            until = _parse(ch.get("manual_until"))
            if status is None:
                out[ch["id"]] = LIVESTATUS_BEFORE
                continue
            if until is not None and now >= until:
                out[ch["id"]] = LIVESTATUS_BEFORE      # 만료 — 자동으로 꺼진다
                continue
            out[ch["id"]] = int(status)
        return out

    async def schedules(self, channels: list[dict]) -> dict[str, dict]:
        return {}
