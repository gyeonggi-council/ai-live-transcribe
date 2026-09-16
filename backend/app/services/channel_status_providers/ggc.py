"""경기도의회 생중계 API 제공자 — 기존 동작 그대로 (2026-09-16 분리)

주소만 설정(`COUNCIL_ONAIR_API_URL`)으로 뺐고 파싱·헤더는 손대지 않았다.
응답 항목의 `adCode` 가 channels.code 와 맞아야 채널이 해석된다.
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class GgcOnairProvider:
    name = "ggc"

    def __init__(self) -> None:
        self._schedule_by_id: dict[str, dict] = {}

    async def poll(self, channels: list[dict]) -> dict[str, int]:
        url = settings.council_onair_api_url
        if not url:
            return {}

        by_code = {ch["code"]: ch["id"] for ch in channels if ch.get("code")}
        if not by_code:
            return {}

        try:
            ymd = datetime.now().strftime("%Y-%m-%d")
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    url,
                    data={"ymd": ymd},
                    headers={
                        "Referer": "https://live.ggc.go.kr/",
                        "Content-Type": "application/x-www-form-urlencoded",
                        "X-Requested-With": "XMLHttpRequest",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                        "Accept": "application/json, text/javascript, */*; q=0.01",
                    },
                )
                resp.raise_for_status()
                # HTML 에러 페이지 감지: JSON 파싱 시도로 검증
                data = resp.json()
        except Exception as exc:                      # noqa: BLE001 — 루프를 죽이지 않는다
            logger.warning("방송 상태 조회 실패: %s", exc)
            raise

        status: dict[str, int] = {}
        schedule: dict[str, dict] = {}
        for item in data:
            ad_code = item.get("adCode", "")
            channel_id = by_code.get(ad_code)
            if not channel_id:
                continue
            status[channel_id] = item.get("kmsLivestatus", 0)
            schedule[channel_id] = {
                "session_no": item.get("adTh", 0),
                "session_order": item.get("adCha", 0),
            }
        self._schedule_by_id = schedule
        return status

    async def schedules(self, channels: list[dict]) -> dict[str, dict]:
        return self._schedule_by_id
