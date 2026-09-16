"""STT 가 붙어도 되는 스트림 호스트 (2026-09-16)

전에는 상수 하나였다. 다른 의회가 자기 CDN 을 쓰면 그 상수 때문에 거부됐다.
이제 **등록된 채널의 호스트**를 허용 목록으로 쓰고, 빌트인은 그대로 둔다.

⚠ 와일드카드(`*.cdn.example`)를 허용하지 않는다 — 그 CDN 에 스트림을 올릴 수 있는
  누구나 우리 OpenAI 예산으로 전사를 돌릴 수 있게 된다. 정확히 일치할 때만 허용한다.

⚠ 채널 **등록**에는 이 검사를 걸지 않는다. 걸면 "허용 목록에 없어서 등록할 수 없고,
  등록이 안 되니 허용 목록에 못 들어가는" 순환에 빠진다. 등록은 url_guard 가 막는다.
"""

from __future__ import annotations

from urllib.parse import urlparse

from app.core.config import settings

# 기존 ALLOWED_STREAM_HOSTS 와 같은 값 — 채널이 하나도 없어도 이건 허용된다.
BUILTIN_STREAM_HOSTS = frozenset({
    "stream01.cdn.gov-ntruss.com",
    "stream02.cdn.gov-ntruss.com",
    # 국회 웹캐스트 CDN (외부 스트림 테스트 — 직접 m3u8 입력 지원)
    "m.webcast.go.kr",
    # 로컬 동기화 테스트 하네스 (scripts/hls_test_stream.py — 관리자 전용 API)
    "127.0.0.1",
    "localhost",
})

_cache: tuple[int, frozenset[str]] | None = None


def _hosts_of(channels: list[dict]) -> set[str]:
    out: set[str] = set()
    for ch in channels:
        for key in ("stream_url", "page_url"):
            value = ch.get(key)
            if not value:
                continue
            host = urlparse(str(value)).hostname
            if host:
                out.add(host)
    return out


def allowed_stream_hosts() -> frozenset[str]:
    """빌트인 ∪ 등록된 채널의 호스트 ∪ 설정(EXTRA_STREAM_HOSTS)."""
    global _cache
    # 채널 스냅샷 버전을 캐시 키로 쓴다. lru_cache 를 쓰면 채널을 추가해도
    # 무효화할 방법이 없어 새 채널의 스트림이 계속 거부된다.
    from app.core.channels import channels_snapshot_info, get_all_channels

    version = channels_snapshot_info()["version"]
    if _cache is not None and _cache[0] == version:
        return _cache[1]

    hosts = set(BUILTIN_STREAM_HOSTS) | _hosts_of(get_all_channels())
    for extra in (settings.extra_stream_hosts or "").split(","):
        host = extra.strip()
        if host:
            hosts.add(host)

    result = frozenset(hosts)
    _cache = (version, result)
    return result


def is_allowed_stream_host(url: str) -> bool:
    host = urlparse(url).hostname
    return bool(host) and host in allowed_stream_hosts()
