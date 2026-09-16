"""HLS 채널 — 목록은 DB(subtitle.channels)에서 오고, 아래 상수는 기본 시드 겸 폴백이다.

시드 18개는 경기도의회 생중계 사이트의 공개 페이지에서 추출한 것이다
(그 페이지의 자바스크립트가 `"https://"+ip+"/live/"+ch+"/playlist.m3u8"` 로 주소를 만든다).
다른 의회는 /admin/channels 에서 자기 채널을 등록한다 — 이 파일을 고칠 필요가 없다.

방송 상태 코드:
  0 = 방송전
  1 = 방송중
  2 = 정회중
  3 = 종료
  4 = 생중계없음
"""

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

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


# ─── 채널 저장소 — 코드 상수에서 DB 로 (2026-09-16) ─────────────────────────
#
# 위의 CHANNELS 는 이제 **기본 시드 겸 폴백**이다. 실제 목록은 subtitle.channels 표에서
# 오고, 관리자 화면(/admin/channels)이 그 표를 고친다. 아래 네 함수의 시그니처는
# 그대로 두었다 — 이 모듈을 쓰는 17개 파일을 한 줄도 안 고치기 위해서다.
#
# 왜 매 호출 DB 조회가 아닌가:
#   get_committee_for_channel() 은 hot path 다(live_corrector 가 자막 확정마다, stt_prompt,
#   speaker_cue_tracker). get_all_channels() 는 시청자 폴링(30초 × 접속자 수)마다 불린다.
#   매번 PostgREST 왕복이면 브리지 커넥션이 마르고 라이브 자막이 밀린다.
# 그래서: 기동 시 1회 적재 + 프로세스 스냅샷 + TTL + **만료돼도 낡은 값을 즉시 주고 뒤에서 갱신**
#   (supabase-py 는 동기 클라이언트라, hot path 에서 동기 HTTP 를 타면 이벤트 루프가 막힌다).
# 파드가 셋(api·web·clipper)이라 쓰기 무효화는 자기 파드만 즉시고, 나머지는 TTL 로 수렴한다.

SEED_CHANNELS = CHANNELS


@dataclass(frozen=True)
class _Snapshot:
    rows: tuple[dict, ...] = ()
    by_id: dict = field(default_factory=dict)
    by_code: dict = field(default_factory=dict)
    loaded_at: float = 0.0
    source: str = "none"          # db | db-empty | seed | none
    version: int = 0


_snapshot = _Snapshot()
_snapshot_lock = threading.Lock()
_refreshing = False


def _build(rows, source: str, version: int) -> _Snapshot:
    rows = tuple(rows)
    return _Snapshot(
        rows=rows,
        by_id={r["id"]: r for r in rows},
        by_code={r["code"]: r for r in rows if r.get("code")},
        loaded_at=time.monotonic(),
        source=source,
        version=version,
    )


def _install_snapshot(rows, source: str = "seed") -> None:
    """스냅샷을 직접 심는다 — 테스트 픽스처와 킬스위치 전용."""
    global _snapshot
    with _snapshot_lock:
        _snapshot = _build(rows, source, _snapshot.version + 1)


def reset_channels_cache() -> None:
    """캐시를 비운다(테스트 정리용)."""
    global _snapshot
    with _snapshot_lock:
        _snapshot = _Snapshot(version=_snapshot.version + 1)


def invalidate_channels() -> None:
    """다음 조회에서 DB 를 다시 읽게 한다. 관리자 CRUD 가 쓰기 직후 호출한다."""
    global _snapshot
    with _snapshot_lock:
        _snapshot = _Snapshot(
            rows=_snapshot.rows,
            by_id=_snapshot.by_id,
            by_code=_snapshot.by_code,
            loaded_at=0.0,              # 만료시킨다(값은 남겨 두어 빈 화면을 만들지 않는다)
            source=_snapshot.source,
            version=_snapshot.version + 1,
        )


def channels_snapshot_info() -> dict:
    snap = _snapshot
    return {
        "count": len(snap.rows),
        "source": snap.source,
        "version": snap.version,
        "age_seconds": (time.monotonic() - snap.loaded_at) if snap.loaded_at else None,
    }


def _load_rows_from_db() -> list[dict]:
    # core → repositories 역방향 의존을 함수 안에서 끊는다(live_meeting 이 쓰는 관행과 같다).
    from app.core.database import get_supabase_client
    from app.repositories.channel_repository import ChannelRepository

    return ChannelRepository(get_supabase_client()).list_all()


def refresh_channels(force: bool = False) -> int:
    """DB 에서 채널을 다시 읽어 스냅샷을 갈아 끼운다. 반환값은 적재된 행 수.

    폴백 정책:
      · 성공 + 행 ≥ 1  → DB 스냅샷(source='db')
      · 성공 + 행 0    → **빈 목록**(source='db-empty'). 시드로 되돌리지 않는다 —
                         다른 의회 배포에 경기도 채널 18개가 뜨면 안 된다.
      · 예외           → 직전 성공 스냅샷 유지 → 없으면 (허용 시) 시드 → 아니면 빈 목록
    """
    global _snapshot

    if settings.channels_source == "seed":
        if _snapshot.source != "seed" or force:
            _install_snapshot(SEED_CHANNELS, "seed")
        return len(_snapshot.rows)

    try:
        rows = _load_rows_from_db()
    except Exception as exc:                       # noqa: BLE001 — 여기서 죽으면 서비스가 죽는다
        if _snapshot.rows:
            logger.warning("채널 표를 읽지 못해 직전 값을 유지한다: %s", exc)
            return len(_snapshot.rows)
        if settings.channels_seed_fallback:
            logger.error("채널 표를 읽지 못해 코드 시드로 기동한다: %s", exc)
            _install_snapshot(SEED_CHANNELS, "seed")
            return len(_snapshot.rows)
        logger.error("채널 표를 읽지 못했고 시드 폴백도 꺼져 있다: %s", exc)
        _install_snapshot([], "none")
        return 0

    if not rows:
        logger.error(
            "채널 표가 비어 있다 — /admin/channels 에서 채널을 등록해야 자막이 시작된다"
        )
        _install_snapshot([], "db-empty")
        return 0

    _install_snapshot(rows, "db")
    return len(rows)


def _maybe_refresh() -> _Snapshot:
    """스냅샷을 돌려준다. 만료됐으면 낡은 값을 주고 뒤에서 갱신한다(stale-while-revalidate)."""
    global _refreshing
    snap = _snapshot

    ttl = max(1, settings.channels_cache_ttl_seconds)
    fresh = snap.loaded_at and (time.monotonic() - snap.loaded_at) < ttl
    if fresh:
        return snap

    if not snap.rows:
        # 아직 한 번도 못 읽었다 — 여기서만 블로킹한다(기동 직후 첫 호출).
        # 평소에는 lifespan 의 ensure_channels_loaded() 가 선점하므로 실제로는 안 걸린다.
        refresh_channels(force=True)
        return _snapshot

    if _refreshing:
        return snap

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        refresh_channels()
        return _snapshot

    _refreshing = True

    async def _bg() -> None:
        global _refreshing
        try:
            await asyncio.to_thread(refresh_channels)
        except Exception as exc:                   # noqa: BLE001
            logger.debug("채널 백그라운드 갱신 실패: %s", exc)
        finally:
            _refreshing = False

    loop.create_task(_bg())
    return snap


async def ensure_channels_loaded() -> int:
    """기동 시 1회 적재 (main.lifespan 에서 부른다)."""
    return await asyncio.to_thread(refresh_channels, True)


def get_all_channels() -> list[dict]:
    """전체 채널 목록을 반환합니다.

    **활성 채널만** 돌려준다 — 목록 화면·자동 STT·상태 폴링이 이걸 쓴다.
    """
    return [ch for ch in _maybe_refresh().rows if ch.get("is_active", True)]


def get_channel(channel_id: str) -> Optional[dict]:
    """채널 ID로 채널을 조회합니다. (비활성 채널도 찾는다)

    비활성도 찾는 이유: 지운 채널의 **지난 회의**가 위원회명·내보내기·속기에서
    `get_committee_for_channel()` 을 타고 들어온다. 여기서 숨기면 그 값들이 빈다.
    """
    return _maybe_refresh().by_id.get(channel_id)


def get_channel_by_code(code: str) -> Optional[dict]:
    """adCode(예: 'A011')로 채널을 조회합니다. (비활성 채널도 찾는다)"""
    return _maybe_refresh().by_code.get(code)


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
