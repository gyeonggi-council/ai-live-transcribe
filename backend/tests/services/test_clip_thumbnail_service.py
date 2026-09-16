# -*- coding: utf-8 -*-
"""클립 썸네일 — 캐시 적중 · 잡 디렉터리 안 저장(정리가 따라온다) · 실패 백오프"""

import asyncio

import pytest

from app.core.config import settings
from app.services import clip_store, clip_thumbnail_service as cts

JOB = "11111111-2222-4333-8444-555555555555"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "clip_store_dir", str(tmp_path / "clips"))
    clip_store.ensure_dirs()
    cts._failed_until.clear()
    cts._locks.clear()
    d = clip_store.job_dir(JOB)
    d.mkdir(parents=True)
    return d


class TestThumbPath:
    def test_lives_inside_job_dir_so_cleanup_follows(self, store):
        """잡 디렉터리 안이라 remove_job_files 가 썸네일까지 지운다 — 별도 정리 코드가 없다."""
        p = clip_store.thumb_path(JOB, 0)
        assert p == store / ".thumb_000.jpg"
        p.write_bytes(b"\xff\xd8x" * 10)
        assert clip_store.remove_job_files(JOB) > 0
        assert not p.exists()

    def test_name_never_takes_user_input(self, store):
        """이름은 인덱스로만 만든다 — 파일명이 경로에 닿지 않는다."""
        assert clip_store.thumb_path(JOB, 12).name == ".thumb_012.jpg"
        with pytest.raises(clip_store.UnsafePathError):
            clip_store.thumb_path("../etc", 0)

    def test_download_path_cannot_reach_it(self, store):
        """선행 점 때문에 다운로드 엔드포인트로는 절대 새 나가지 않는다."""
        with pytest.raises(clip_store.UnsafePathError):
            clip_store.safe_file(JOB, ".thumb_000.jpg")


class TestEnsure:
    def test_cache_hit_does_not_run_ffmpeg(self, store, monkeypatch):
        cached = clip_store.thumb_path(JOB, 0)
        cached.write_bytes(b"\xff\xd8JPEG")
        mp4 = store / "a.mp4"
        mp4.write_bytes(b"x")

        def boom(*a, **k):  # pragma: no cover - 불려선 안 된다
            raise AssertionError("캐시가 있는데 ffmpeg 를 불렀다")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", boom)
        got = asyncio.run(cts.ensure_clip_thumbnail(JOB, 0, mp4, 100))
        assert got == cached

    def test_missing_source_returns_none(self, store):
        assert asyncio.run(cts.ensure_clip_thumbnail(JOB, 0, store / "없다.mp4", 10)) is None

    def test_failure_is_remembered_so_ffmpeg_is_not_hammered(self, store, monkeypatch):
        """실패한 파일을 매 요청마다 재시도하면 목록 한 장에 ffmpeg 가 수십 번 돈다."""
        mp4 = store / "a.mp4"
        mp4.write_bytes(b"not a video")
        calls = {"n": 0}

        class FakeProc:
            returncode = 1

            async def communicate(self):
                return b"", b"Invalid data found"

            def kill(self):
                pass

        async def fake_exec(*a, **k):
            calls["n"] += 1
            return FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        assert asyncio.run(cts.ensure_clip_thumbnail(JOB, 0, mp4, 10)) is None
        assert asyncio.run(cts.ensure_clip_thumbnail(JOB, 0, mp4, 10)) is None
        assert calls["n"] == 1          # 두 번째는 백오프에 걸려 안 부른다
        assert not clip_store.thumb_path(JOB, 0).exists()

    def test_capture_point_is_halfway_for_short_clips(self, store, monkeypatch):
        """3초 캡처가 기본이지만 2초짜리 구간은 그 지점이 영상 밖이다."""
        seen = {}

        def fake_build(mp4_path, at_seconds, out_path):
            seen["at"] = at_seconds
            return ["true"]

        monkeypatch.setattr(cts, "_build_command", fake_build)
        mp4 = store / "a.mp4"
        mp4.write_bytes(b"x")
        asyncio.run(cts.ensure_clip_thumbnail(JOB, 0, mp4, 2.0))
        assert seen["at"] == 1.0
        cts._failed_until.clear()
        asyncio.run(cts.ensure_clip_thumbnail(JOB, 1, mp4, 600.0))
        assert seen["at"] == cts.CAPTURE_SECONDS
