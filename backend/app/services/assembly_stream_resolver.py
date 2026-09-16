"""국회 웹캐스트 플레이어 URL → HLS m3u8 URL 리졸버

국회 생중계 페이지(assembly.webcast.go.kr)의 플레이어 URL에서
직접 재생 가능한 HLS m3u8 URL을 추출합니다.

국회 웹캐스트 2단계 로딩:
  1. 플레이어 페이지 URL에서 xcode, xcgcd 파라미터 추출
  2. AJAX 호출: /main/service/live_play.asp?xcode={}&xcgcd={}&vv=1
  3. JSON 응답에서 HLS URL 추출: data.xhls[0]["480p"] 또는 default

사용 예시:
  url = "https://assembly.webcast.go.kr/main/player.asp?xcode=37&xcgcd=DCM000037224330101&"
  m3u8_url = await resolve_assembly_stream(url)
  # → "https://m.webcast.go.kr/live/gukbang_480p/playlist.m3u8"
"""

import json
import logging
from urllib.parse import parse_qs, urlparse

import httpx

logger = logging.getLogger(__name__)

ASSEMBLY_HOST = "assembly.webcast.go.kr"
LIVE_PLAY_ENDPOINT = "https://assembly.webcast.go.kr/main/service/live_play.asp"

# 선호 품질 순서 (480p → default → 첫 번째 가용 키)
PREFERRED_QUALITIES = ["480p", "default", "240p", "720p"]


def is_assembly_url(url: str) -> bool:
    """국회 웹캐스트 URL인지 확인합니다."""
    return ASSEMBLY_HOST in url


def _extract_params(url: str) -> tuple[str | None, str | None]:
    """플레이어 URL에서 xcode와 xcgcd 파라미터를 추출합니다."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    xcode = qs.get("xcode", [None])[0]
    xcgcd = qs.get("xcgcd", [None])[0]
    return xcode, xcgcd


def _pick_hls_url(xhls_entry: dict) -> str | None:
    """xhls 항목에서 선호 품질의 HLS URL을 선택합니다."""
    for quality in PREFERRED_QUALITIES:
        if quality in xhls_entry and xhls_entry[quality]:
            return xhls_entry[quality]
    # 폴백: 첫 번째 비어있지 않은 값
    for value in xhls_entry.values():
        if isinstance(value, str) and value.startswith("http"):
            return value
    return None


async def resolve_assembly_stream(url: str) -> str:
    """국회 웹캐스트 URL에서 HLS m3u8 URL을 추출합니다.

    이미 .m3u8 URL이면 그대로 반환합니다.
    국회 플레이어 URL이면 AJAX를 통해 실제 스트림 URL을 리졸브합니다.

    Args:
        url: 국회 웹캐스트 플레이어 URL 또는 직접 m3u8 URL

    Returns:
        HLS m3u8 스트림 URL

    Raises:
        ValueError: URL에서 필수 파라미터를 추출할 수 없거나 스트림을 찾을 수 없을 때
        httpx.HTTPError: AJAX 호출 실패 시
    """
    # 이미 m3u8 URL이면 바로 반환
    if url.rstrip("?&").endswith(".m3u8"):
        logger.info("Already an m3u8 URL: %s", url)
        return url

    xcode, xcgcd = _extract_params(url)
    if not xcode or not xcgcd:
        raise ValueError(
            f"국회 웹캐스트 URL에서 xcode/xcgcd 파라미터를 찾을 수 없습니다: {url}"
        )

    logger.info("Resolving assembly stream: xcode=%s, xcgcd=%s", xcode, xcgcd)

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            LIVE_PLAY_ENDPOINT,
            params={"xcode": xcode, "xcgcd": xcgcd, "vv": "1"},
        )
        response.raise_for_status()

    # 국회 서버 응답에 비표준 인코딩 문자가 포함될 수 있어 errors='replace' 처리
    raw_text = response.content.decode("utf-8", errors="replace")
    data = json.loads(raw_text)

    # JSON 구조: { "xhls": [ { "480p": "...", "default": "...", ... } ] }
    xhls_list = data.get("xhls", [])
    if not xhls_list:
        raise ValueError(
            f"국회 웹캐스트 AJAX 응답에 xhls 데이터가 없습니다 (xcode={xcode})"
        )

    hls_url = _pick_hls_url(xhls_list[0])
    if not hls_url:
        raise ValueError(
            f"국회 웹캐스트 xhls에서 유효한 HLS URL을 찾을 수 없습니다: {xhls_list[0]}"
        )

    logger.info("Resolved assembly stream: %s → %s", url, hls_url)
    return hls_url
