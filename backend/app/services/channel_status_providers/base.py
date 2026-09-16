"""방송상태 제공자 — "이 채널이 지금 방송 중인가" 를 판정하는 방식 (2026-09-16)

경기도의회는 생중계 사이트가 그 답을 주는 API 를 갖고 있지만, 다른 의회는 없다.
그래서 판정 방식을 갈아끼울 수 있게 갈랐다. 이 추상화가 없으면 다른 의회에서는
전 채널이 "방송전"으로 보이고 자동 STT 가 **예외 없이 영영 시작되지 않는다**
(로그에 "no broadcasting channels found" 한 줄만 남아 원인을 찾을 수 없다).

상태 코드는 기존과 같다: 0 방송전 · 1 방송중 · 2 정회중 · 3 종료 · 4 생중계없음
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

LIVESTATUS_BEFORE = 0
LIVESTATUS_BROADCASTING = 1
LIVESTATUS_RECESS = 2
LIVESTATUS_ENDED = 3
LIVESTATUS_NONE = 4


@runtime_checkable
class ChannelStatusProvider(Protocol):
    name: str

    async def poll(self, channels: list[dict]) -> dict[str, int]:
        """채널 목록을 받아 {channel_id: livestatus} 를 돌려준다.

        **예외를 위로 던지지 않는다.** 여기서 던지면 폴링 루프가 죽고 전 채널이
        0 으로 굳는다 — 이식 장벽과 똑같은 증상이 되어 구분이 안 된다.
        """
        ...

    async def schedules(self, channels: list[dict]) -> dict[str, dict]:
        """{channel_id: {session_no, session_order}} — 모르면 빈 dict."""
        ...
