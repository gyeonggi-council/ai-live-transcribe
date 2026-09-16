# -*- coding: utf-8 -*-
"""clip_store(파일 I/O·경로 방어) · SRT 구간 재배치 · 워크벤치 파일명 규약"""

import os
import time

import pytest

from app.core.config import settings
from app.services import clip_service, clip_store
from app.services.transcript_export import export_srt_merged, export_srt_range

JOB = "11111111-2222-4333-8444-555555555555"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "clip_store_dir", str(tmp_path / "clips"))
    clip_store.ensure_dirs()
    return tmp_path / "clips"


class TestClipStore:
    def test_layout(self, store):
        assert clip_store.job_dir(JOB) == store / "jobs" / JOB
        assert clip_store.work_dir(JOB) == store / "work" / JOB

    @pytest.mark.parametrize("bad", ["../x", "a/b.mp4", "..", ".hidden", "a\\b", "", "x?.mp4"])
    def test_safe_file_rejects_traversal(self, store, bad):
        with pytest.raises(clip_store.UnsafePathError):
            clip_store.safe_file(JOB, bad)

    def test_safe_file_accepts_korean_names(self, store):
        p = clip_store.safe_file(JOB, "김지호 위원_제392회 제2차 건설교통위원회_20260721_1분35초.mp4")
        assert p.parent == clip_store.job_dir(JOB)

    def test_bad_job_id_rejected(self, store):
        with pytest.raises(clip_store.UnsafePathError):
            clip_store.job_dir("../etc")

    def test_usage_and_remove(self, store):
        d = clip_store.job_dir(JOB)
        d.mkdir(parents=True)
        (d / "a.mp4").write_bytes(b"x" * 1000)
        (clip_store.work_dir(JOB)).mkdir(parents=True)
        (clip_store.work_dir(JOB) / "part.mp4").write_bytes(b"y" * 50)
        assert clip_store.usage_bytes() == 1000       # work/ 는 세지 않는다
        assert clip_store.remove_job_files(JOB) == 1050
        assert not d.exists()

    def test_estimate_bytes_uses_setting(self, store, monkeypatch):
        monkeypatch.setattr(settings, "clip_bytes_per_second", 100)
        assert clip_store.estimate_bytes(30) == 3000

    def test_sweep_orphans_only_old_and_unknown(self, store):
        known = clip_store.job_dir(JOB); known.mkdir(parents=True)
        old = store / "jobs" / "aaaaaaaa-0000-4000-8000-000000000000"; old.mkdir(parents=True)
        new = store / "work" / "bbbbbbbb-0000-4000-8000-000000000000"; new.mkdir(parents=True)
        past = time.time() - 10 * 3600
        os.utime(old, (past, past))
        removed = clip_store.sweep_orphan_dirs({JOB}, max_age_seconds=6 * 3600)
        assert removed == ["jobs/aaaaaaaa-0000-4000-8000-000000000000"]
        assert known.exists() and new.exists() and not old.exists()


SUBS = [
    {"start_time": 100.0, "end_time": 104.0, "text": "첫 문장", "speaker": "김지호 위원"},
    {"start_time": 104.0, "end_time": 109.0, "text": "둘째 문장", "speaker": None},
    {"start_time": 109.0, "end_time": 112.0, "text": "   ", "speaker": None},   # 빈 텍스트 제외
    {"start_time": 300.0, "end_time": 305.0, "text": "다른 구간", "speaker": "위원장"},
]


class TestSrtRange:
    def test_rebased_to_clip_start_and_clamped(self):
        srt = export_srt_range(SUBS, 102.0, 110.0)
        blocks = srt.strip().split("\n\n")
        assert len(blocks) == 2
        assert blocks[0].splitlines()[1] == "00:00:00,000 --> 00:00:02,000"   # 100~104 → 102 클램프
        assert blocks[0].splitlines()[2] == "[김지호 위원] 첫 문장"
        assert blocks[1].splitlines()[1] == "00:00:02,000 --> 00:00:07,000"

    def test_time_shift_moves_live_subtitles_onto_vod_axis(self):
        # 자막 100초 = 영상 142.5초 (오프셋 +42.5) → 클립 140~150 에 들어온다
        srt = export_srt_range(SUBS, 140.0, 150.0, time_shift=42.5)
        assert "첫 문장" in srt and "00:00:02,500 -->" in srt
        assert export_srt_range(SUBS, 140.0, 150.0) == ""

    def test_merged_timeline_accumulates(self):
        srt = export_srt_merged(SUBS, [{"start": 100, "end": 110}, {"start": 298, "end": 308}])
        blocks = srt.strip().split("\n\n")
        assert blocks[-1].splitlines()[0] == "3"
        # 둘째 구간(298~308)의 자막 300~305 → 누적 10초 뒤: 12~17
        assert blocks[-1].splitlines()[1] == "00:00:12,000 --> 00:00:17,000"


class TestJobFilename:
    def test_user_convention_name_meeting_number(self):
        """담당자 요청(2026-09-10): 이름_회의명_번호 — 날짜·시작 시각·_AI잠정 없음."""
        name = clip_service.build_job_filename(
            "김태희", "제393회 [임시회] 제3차 도시환경위원회 [2026.09.08]", 3)
        assert name == "김태희_제393회 제3차 도시환경위원회_3.mp4"

    def test_merged_is_hapbon_without_number(self):
        assert clip_service.build_job_filename("클립", "회의", 2, merged=True) == "클립_회의_합본.mp4"

    def test_missing_number_falls_back_to_1_and_blank_parts(self):
        assert clip_service.build_job_filename("", None) == "클립_회의_1.mp4"

    def test_unsafe_chars_removed(self):
        name = clip_service.build_job_filename('a:b*c', 'x/y', 5)
        assert ":" not in name and name == "a b c_x y_5.mp4"

    def test_build_clip_filename_suffix_keeps_default(self):
        assert clip_service.build_clip_filename("1", "m", 10, 75) == "ggc_1_0m10s-1m15s.mp4"
        assert clip_service.build_clip_filename("1", "m", 10, 75, suffix="_AI잠정") == "ggc_1_0m10s-1m15s_AI잠정.mp4"


class TestCompressCommand:
    """자동 클립(2026-09-10) — 720p 로 작게. 입력 시킹(-ss 가 -i 앞)은 그대로 지켜야 필요한 바이트만 받는다."""

    def test_compress_reencodes_720p_single_thread(self):
        from app.services.clip_service import build_extract_cmd

        cmd = build_extract_cmd("https://kms.ggc.go.kr/mp4/x.mp4", 30, 60, "/tmp/o.mp4", compress=True, crf=28)
        assert cmd.index("-ss") < cmd.index("-i")
        assert "copy" not in cmd
        assert cmd[cmd.index("-c:v") + 1] == "libx264" and cmd[cmd.index("-crf") + 1] == "28"
        assert cmd.count("-threads") == 2 and all(cmd[i + 1] == "1" for i, a in enumerate(cmd) if a == "-threads")
        assert "min(720,ih)" in cmd[cmd.index("-vf") + 1]
        assert cmd[-1] == "/tmp/o.mp4" and "+faststart" in cmd

    def test_default_is_stream_copy(self):
        from app.services.clip_service import build_extract_cmd

        cmd = build_extract_cmd("https://kms.ggc.go.kr/mp4/x.mp4", 30, 60, "/tmp/o.mp4")
        assert cmd[cmd.index("-c") + 1] == "copy" and "-threads" not in cmd and "libx264" not in cmd
