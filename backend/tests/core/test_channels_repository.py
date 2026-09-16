"""채널 캐시 — DB → 폴백 → 무효화 (2026-09-16)"""

import pytest

from app.core import channels as ch
from app.core.config import settings

ROWS = [
    {"id": "aa1", "name": "본회의", "code": "X1", "stream_url": "https://c.example/a.m3u8",
     "is_active": True, "committee": None},
    {"id": "aa2", "name": "지운채널", "code": "X2", "stream_url": "", "is_active": False,
     "committee": None},
]


@pytest.fixture(autouse=True)
def _clean():
    ch.reset_channels_cache()
    yield
    ch.reset_channels_cache()


def test_db_rows_are_used(monkeypatch):
    monkeypatch.setattr(ch, "_load_rows_from_db", lambda: list(ROWS))
    assert ch.refresh_channels(force=True) == 2
    assert ch.channels_snapshot_info()["source"] == "db"
    assert [c["id"] for c in ch.get_all_channels()] == ["aa1"]      # 활성만


def test_inactive_channel_is_still_findable(monkeypatch):
    """지운 채널의 지난 회의가 위원회명을 잃지 않아야 한다."""
    monkeypatch.setattr(ch, "_load_rows_from_db", lambda: list(ROWS))
    ch.refresh_channels(force=True)
    assert ch.get_channel("aa2") is not None
    assert ch.get_committee_for_channel("aa2") == "지운채널"
    assert ch.get_channel_by_code("X2") is not None


def test_empty_table_does_not_fall_back_to_seed(monkeypatch):
    """행 0 은 '아직 등록 안 함' 이다. 시드로 채우면 다른 의회에 경기도 채널이 뜬다."""
    monkeypatch.setattr(ch, "_load_rows_from_db", lambda: [])
    assert ch.refresh_channels(force=True) == 0
    assert ch.channels_snapshot_info()["source"] == "db-empty"
    assert ch.get_all_channels() == []


def test_db_error_falls_back_to_seed(monkeypatch):
    def boom():
        raise RuntimeError("PostgREST 404")

    monkeypatch.setattr(ch, "_load_rows_from_db", boom)
    monkeypatch.setattr(settings, "channels_seed_fallback", True)
    assert ch.refresh_channels(force=True) == len(ch.SEED_CHANNELS)
    assert ch.channels_snapshot_info()["source"] == "seed"


def test_db_error_keeps_previous_snapshot(monkeypatch):
    monkeypatch.setattr(ch, "_load_rows_from_db", lambda: list(ROWS))
    ch.refresh_channels(force=True)

    def boom():
        raise RuntimeError("일시 장애")

    monkeypatch.setattr(ch, "_load_rows_from_db", boom)
    assert ch.refresh_channels(force=True) == 2          # 직전 값을 유지
    assert ch.get_channel("aa1") is not None


def test_kill_switch_ignores_db(monkeypatch):
    monkeypatch.setattr(settings, "channels_source", "seed")
    monkeypatch.setattr(ch, "_load_rows_from_db", lambda: (_ for _ in ()).throw(AssertionError("DB 를 보면 안 된다")))
    assert ch.refresh_channels(force=True) == len(ch.SEED_CHANNELS)


def test_invalidate_keeps_values_but_expires(monkeypatch):
    monkeypatch.setattr(ch, "_load_rows_from_db", lambda: list(ROWS))
    ch.refresh_channels(force=True)
    before = ch.channels_snapshot_info()["version"]
    ch.invalidate_channels()
    after = ch.channels_snapshot_info()
    assert after["version"] > before
    assert after["count"] == 2      # 값은 남긴다 — 무효화가 화면을 비우면 안 된다
