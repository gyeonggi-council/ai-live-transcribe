"""경기도의회 HLS 채널 설정

의회생중계 사이트에서 추출한 18개 채널 정보.
stream URL 패턴: https://{ip}/{ch}/playlist.m3u8

방송 상태 코드:
  0 = 방송전
  1 = 방송중
  2 = 정회중
  3 = 종료
  4 = 생중계없음
"""

from typing import Optional

# 방송 상태 코드 → 텍스트 매핑
STATUS_TEXT = {
    0: "방송전",
    1: "방송중",
    2: "정회중",
    3: "종료",
    4: "생중계없음",
}


def get_status_text(code: int) -> str:
    """방송 상태 코드를 텍스트로 변환합니다."""
    return STATUS_TEXT.get(code, "알수없음")

CHANNELS = [
    {
        "id": "ch14",
        "name": "본회의",
        "code": "A011",
        "stream_url": "https://stream01.cdn.gov-ntruss.com/live/ch14/playlist.m3u8",
    },
    {
        "id": "ch1",
        "name": "의회운영위원회",
        "code": "C001",
        "stream_url": "https://stream01.cdn.gov-ntruss.com/live/ch1/playlist.m3u8",
    },
    {
        "id": "ch3",
        "name": "기획재정위원회",
        "code": "C105",
        "stream_url": "https://stream02.cdn.gov-ntruss.com/live/ch3/playlist.m3u8",
    },
    {
        "id": "ch6",
        "name": "경제노동위원회",
        "code": "C205",
        "stream_url": "https://stream02.cdn.gov-ntruss.com/live/ch6/playlist.m3u8",
    },
    {
        "id": "ch7",
        "name": "안전행정위원회",
        "code": "C301",
        "stream_url": "https://stream02.cdn.gov-ntruss.com/live/ch7/playlist.m3u8",
    },
    {
        "id": "ch8",
        "name": "문화체육관광위원회",
        "code": "C501",
        "stream_url": "https://stream01.cdn.gov-ntruss.com/live/ch8/playlist.m3u8",
    },
    {
        "id": "ch15",
        "name": "농정해양위원회",
        "code": "C601",
        "stream_url": "https://stream01.cdn.gov-ntruss.com/live/ch15/playlist.m3u8",
    },
    {
        "id": "ch2",
        "name": "보건복지위원회",
        "code": "C701",
        "stream_url": "https://stream02.cdn.gov-ntruss.com/live/ch2/playlist.m3u8",
    },
    {
        "id": "ch12",
        "name": "건설교통위원회",
        "code": "C807",
        "stream_url": "https://stream01.cdn.gov-ntruss.com/live/ch12/playlist.m3u8",
    },
    {
        "id": "ch13",
        "name": "도시환경위원회",
        "code": "C901",
        "stream_url": "https://stream01.cdn.gov-ntruss.com/live/ch13/playlist.m3u8",
    },
    {
        "id": "ch16",
        "name": "미래과학협력위원회",
        "code": "C9043",
        "stream_url": "https://stream01.cdn.gov-ntruss.com/live/ch16/playlist.m3u8",
    },
    {
        "id": "ch11",
        "name": "여성가족평생교육위원회",
        "code": "C905",
        "stream_url": "https://stream01.cdn.gov-ntruss.com/live/ch11/playlist.m3u8",
    },
    {
        "id": "ch4",
        "name": "교육기획위원회",
        "code": "C908",
        "stream_url": "https://stream02.cdn.gov-ntruss.com/live/ch4/playlist.m3u8",
    },
    {
        "id": "ch5",
        "name": "교육행정위원회",
        "code": "C909",
        "stream_url": "https://stream01.cdn.gov-ntruss.com/live/ch5/playlist.m3u8",
    },
    {
        "id": "ch60",
        "name": "경기도청 예산결산특별위원회",
        "code": "E020",
        "stream_url": "https://stream01.cdn.gov-ntruss.com/live/ch60/playlist.m3u8",
    },
    {
        "id": "ch61",
        "name": "경기도교육청 예산결산특별위원회",
        "code": "E030",
        "stream_url": "https://stream01.cdn.gov-ntruss.com/live/ch61/playlist.m3u8",
    },
    {
        "id": "ch10",
        "name": "행정사무조사",
        "code": "E040",
        "stream_url": "https://stream01.cdn.gov-ntruss.com/live/ch10/playlist.m3u8",
    },
    {
        "id": "ch90",
        "name": "도의회 북부분원",
        "code": "E050",
        "stream_url": "https://stream02.cdn.gov-ntruss.com/live2/ch90/playlist.m3u8",
    },
    {
        "id": "chT1",
        "name": "외부 스트림 테스트",
        "code": "TEST1",
        "stream_url": "",
    },
]


def get_all_channels() -> list[dict]:
    """전체 채널 목록을 반환합니다."""
    return CHANNELS


def get_channel(channel_id: str) -> Optional[dict]:
    """채널 ID로 채널을 조회합니다."""
    for ch in CHANNELS:
        if ch["id"] == channel_id:
            return ch
    return None


def get_channel_by_code(code: str) -> Optional[dict]:
    """adCode(예: 'A011')로 채널을 조회합니다."""
    for ch in CHANNELS:
        if ch["code"] == code:
            return ch
    return None


def get_committee_for_channel(channel_id: str) -> Optional[str]:
    """채널 ID로 해당 위원회명을 반환합니다. 본회의/특별위 등은 None."""
    ch = get_channel(channel_id)
    if ch:
        return ch.get("committee") or ch.get("name")
    return None


# ─── 런타임 스트림 오버라이드 (외부 스트림 테스트: chT1) ────────────────────
# STT를 커스텀 URL로 시작하면 여기 기록되고, 채널 상태 API가 프런트 플레이어에
# 같은 URL을 노출한다 — 영상과 자막이 동일한 스트림을 보며 동기화 검증 가능.
_STREAM_OVERRIDES: dict[str, str] = {}


def set_stream_override(channel_id: str, stream_url: Optional[str]) -> None:
    """채널의 런타임 스트림 URL을 설정(stream_url=None이면 해제)합니다."""
    if stream_url:
        _STREAM_OVERRIDES[channel_id] = stream_url
    else:
        _STREAM_OVERRIDES.pop(channel_id, None)


def get_stream_override(channel_id: str) -> Optional[str]:
    """채널의 런타임 스트림 URL 오버라이드를 반환합니다 (없으면 None)."""
    return _STREAM_OVERRIDES.get(channel_id)
