"""STT 허용 스트림 호스트 — 등록된 채널의 호스트가 자동으로 허용된다 (2026-09-16)"""

from app.core import channels as ch
from app.core.stream_hosts import BUILTIN_STREAM_HOSTS, allowed_stream_hosts, is_allowed_stream_host


def test_builtin_hosts_survive_even_with_no_channels():
    """채널이 하나도 없어도 기존 4호스트는 허용된다 — 기존 동작 보존."""
    ch._install_snapshot([], source="db-empty")
    hosts = allowed_stream_hosts()
    assert BUILTIN_STREAM_HOSTS <= hosts


def test_registered_channel_host_is_allowed():
    ch._install_snapshot(
        [{"id": "c1", "name": "본회의", "code": None, "is_active": True,
          "stream_url": "https://cdn.other-council.example/live/a/playlist.m3u8"}],
        source="db",
    )
    assert is_allowed_stream_host("https://cdn.other-council.example/live/b/playlist.m3u8")
    assert not is_allowed_stream_host("https://evil.example/live/x.m3u8")


def test_cache_follows_channel_changes():
    """채널을 바꾸면 허용 목록이 따라온다 — lru_cache 였다면 새 채널이 영원히 거부된다."""
    ch._install_snapshot([], source="db-empty")
    assert not is_allowed_stream_host("https://late.example/x.m3u8")
    ch._install_snapshot(
        [{"id": "c2", "name": "x", "is_active": True, "stream_url": "https://late.example/a.m3u8"}],
        source="db",
    )
    assert is_allowed_stream_host("https://late.example/x.m3u8")
