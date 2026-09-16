"""stt_batch_queue — 관리자 버튼과 새벽 자동이 공유하는 "배치 1개" 가드."""

from unittest.mock import MagicMock, patch

import pytest

from app.services import stt_batch_queue as q


@pytest.fixture(autouse=True)
def _reset():
    q._reset_for_tests()
    yield
    q._reset_for_tests()


def _fake_task(status_: str, error: str | None = None):
    t = MagicMock()
    t.status = status_
    t.error = error
    return t


async def test_run_batch_sequential_done_and_failed():
    meetings = {
        "m1": {"id": "m1", "vod_url": "https://kms/a.mp4", "status": "ended"},
        "m2": {"id": "m2", "vod_url": None, "status": "ended"},          # VOD 미등록
        "m3": {"id": "m3", "vod_url": "https://kms/c.mp4", "status": "live"},  # 생중계
        "m4": {"id": "m4", "vod_url": "https://kms/d.mp4", "status": "ended"},  # 처리 실패
    }
    process = MagicMock()

    async def fake_process(self, meeting_id, vod_url, supabase):
        process(meeting_id)
        if meeting_id == "m4":
            raise RuntimeError("download failed")

    tasks = {"m1": _fake_task("completed")}
    with patch("app.services.meeting_service.get_meeting_by_id_service", side_effect=lambda sb, mid: meetings.get(mid)), \
         patch("app.services.vod_stt_service.VodSttService.process", fake_process), \
         patch("app.services.vod_stt_service.get_task_by_meeting", side_effect=tasks.get), \
         patch("app.services.vod_stt_service.is_processing", return_value=False):
        result = await q.run_batch(["m1", "m2", "m3", "m4", "m1"], lambda: MagicMock(), source="auto")

    assert result is not None
    assert result["done"] == ["m1"]
    reasons = {f["meeting_id"]: f["reason"] for f in result["failed"]}
    assert reasons["m2"] == "VOD 미등록"
    assert reasons["m3"] == "이미 처리 중이거나 생중계"
    assert "download failed" in reasons["m4"]
    assert process.call_args_list[0].args == ("m1",)  # 중복 제거 — m1 은 한 번만
    assert process.call_count == 2
    assert q.is_running() is False
    st = q.status()
    assert st["source"] == "auto" and st["finished_at"] is not None


async def test_run_batch_refused_while_running():
    assert q._claim(["x"], "manual") is True
    assert await q.run_batch(["y"], lambda: MagicMock(), source="auto") is None
    assert q.status()["pending"] == ["x"]  # 기존 배치 상태 그대로


def test_start_batch_refused_while_running_and_empty():
    assert q.start_batch([], lambda: MagicMock()) is False
    assert q._claim(["x"], "manual") is True
    assert q.start_batch(["y"], lambda: MagicMock()) is False


def test_record_and_status_last_auto_run():
    assert q.status()["last_auto_run"] is None
    q.record_auto_run({"ran_at": "2026-09-03T04:00:00+09:00", "done": ["m1"]})
    assert q.status()["last_auto_run"]["done"] == ["m1"]
    assert q.last_auto_run()["ran_at"].startswith("2026-09-03")
