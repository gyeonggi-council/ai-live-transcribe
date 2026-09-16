"""LiveAudioRecorder 단위 테스트 (라이브 MP3 녹음 — 자막 검증용).

실제 ffmpeg 없이 시작/쓰기/종료 수명주기와 경로 안전성을 검증한다.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import live_recorder as lr
from app.services.live_recorder import LiveAudioRecorder, recording_path


def test_recording_path_safe_ids(monkeypatch):
    monkeypatch.setattr(lr.settings, "live_record_dir", "recordings")
    p = recording_path("11111111-1111-1111-1111-111111111111")
    assert p is not None and p.name == "11111111-1111-1111-1111-111111111111.mp3"
    assert recording_path("ch8") is not None


def test_recording_path_rejects_traversal():
    assert recording_path("../etc/passwd") is None
    assert recording_path("a/b") is None
    assert recording_path("") is None
    assert recording_path("x" * 100) is None
    # '$' 앵커는 끝 개행을 허용하므로 fullmatch로 차단되는지 회귀 확인
    assert recording_path("abc\n") is None


def _mock_proc() -> MagicMock:
    proc = MagicMock()
    proc.returncode = None
    proc.stdin = MagicMock()
    proc.stdin.is_closing.return_value = False
    proc.stdin.drain = AsyncMock()
    proc.wait = AsyncMock(return_value=0)
    return proc


@pytest.fixture
def rec(tmp_path, monkeypatch) -> LiveAudioRecorder:
    monkeypatch.setattr(lr.settings, "live_record_dir", str(tmp_path))
    monkeypatch.setattr(lr.settings, "live_record_enabled", True)
    return LiveAudioRecorder()


async def test_start_write_stop_lifecycle(rec, monkeypatch, tmp_path):
    proc = _mock_proc()
    monkeypatch.setattr(lr.asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))

    await rec.start("ch8", "meeting-1")
    assert rec.is_recording("ch8")
    assert (tmp_path / "meeting-1.mp3").exists()

    await rec.write("ch8", b"\x00\x01" * 100)
    proc.stdin.write.assert_called_once()
    proc.stdin.drain.assert_awaited_once()

    await rec.stop("ch8")
    proc.stdin.close.assert_called_once()
    proc.wait.assert_awaited()
    assert not rec.is_recording("ch8")


async def test_write_failure_stops_recording_without_raising(rec, monkeypatch):
    """인코더가 죽어도 write는 예외를 올리지 않고 즉시 등록 해제한다 (STT 루프 비차단)."""
    proc = _mock_proc()
    proc.stdin.drain = AsyncMock(side_effect=BrokenPipeError("dead"))
    monkeypatch.setattr(lr.asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))

    await rec.start("ch8", "meeting-1")
    await rec.write("ch8", b"\x00\x01")  # 예외 없이 통과해야 함
    assert not rec.is_recording("ch8")  # write 복귀 시점에 이미 해제됨
    await asyncio.sleep(0.05)  # 분리된 정리 태스크 수행 대기
    proc.kill.assert_called()


async def test_duplicate_meeting_recording_is_rejected(rec, monkeypatch):
    """같은 meeting을 두 채널이 동시에 녹음하면 파일이 손상되므로 두 번째는 거부."""
    proc = _mock_proc()
    spawn = AsyncMock(return_value=proc)
    monkeypatch.setattr(lr.asyncio, "create_subprocess_exec", spawn)

    await rec.start("ch1", "meeting-1")
    await rec.start("ch2", "meeting-1")  # 동일 meeting → 거부

    assert rec.is_recording("ch1")
    assert not rec.is_recording("ch2")
    assert spawn.await_count == 1


async def test_concurrent_start_same_channel_no_zombie(rec, monkeypatch):
    """동시 start()가 채널 잠금으로 직렬화되어 좀비 인코더가 남지 않는다."""
    procs = [_mock_proc(), _mock_proc()]
    spawn = AsyncMock(side_effect=procs)
    monkeypatch.setattr(lr.asyncio, "create_subprocess_exec", spawn)

    await asyncio.gather(rec.start("ch8", "meeting-1"), rec.start("ch8", "meeting-1"))

    # 두 번째 start가 첫 번째 인코더를 정리(직렬화) → 활성 1개, 좀비 0개
    assert rec.is_recording("ch8")
    assert procs[0].stdin.close.called  # 먼저 등록된 쪽이 정리됨
    await rec.stop("ch8")


def test_prune_old_recordings(tmp_path, monkeypatch):
    """보존 기간 초과 mp3는 삭제, 최신 파일은 유지."""
    import os
    import time as _time

    monkeypatch.setattr(lr.settings, "live_record_dir", str(tmp_path))
    monkeypatch.setattr(lr.settings, "live_record_retention_days", 7)
    old = tmp_path / "old.mp3"
    new = tmp_path / "new.mp3"
    old.write_bytes(b"x")
    new.write_bytes(b"y")
    # 사이드카(.offset/.sessions)도 함께 지워져야 무한 누적이 없다.
    old.with_suffix(".offset").write_text("0.0", encoding="utf-8")
    old.with_suffix(".sessions").write_text('{"clock": 0.0, "byte": 0}\n', encoding="utf-8")
    stale = _time.time() - 8 * 86400
    os.utime(old, (stale, stale))

    lr._prune_old_recordings()

    assert not old.exists()
    assert not old.with_suffix(".offset").exists()
    assert not old.with_suffix(".sessions").exists()
    assert new.exists()


async def test_disabled_via_settings(rec, monkeypatch):
    monkeypatch.setattr(lr.settings, "live_record_enabled", False)
    spawn = AsyncMock()
    monkeypatch.setattr(lr.asyncio, "create_subprocess_exec", spawn)
    await rec.start("ch8", "meeting-1")
    spawn.assert_not_awaited()
    assert not rec.is_recording("ch8")


async def test_unsafe_meeting_id_skips_recording(rec, monkeypatch):
    spawn = AsyncMock()
    monkeypatch.setattr(lr.asyncio, "create_subprocess_exec", spawn)
    await rec.start("ch8", "../../evil")
    spawn.assert_not_awaited()


async def test_restart_same_channel_replaces_recording(rec, monkeypatch):
    proc1, proc2 = _mock_proc(), _mock_proc()
    spawn = AsyncMock(side_effect=[proc1, proc2])
    monkeypatch.setattr(lr.asyncio, "create_subprocess_exec", spawn)

    await rec.start("ch8", "meeting-1")
    await rec.start("ch8", "meeting-2")  # 재시작 → 이전 인코더 정리
    proc1.stdin.close.assert_called_once()
    assert rec.is_recording("ch8")
    await rec.stop("ch8")


# ─── 다운로드 API ─────────────────────────────────────────────────────────


def test_download_recording_endpoint(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr(lr.settings, "live_record_dir", str(tmp_path))
    client = TestClient(app)

    # 404: 파일 없음
    r = client.get("/api/meetings/no-such-meeting/recording")
    assert r.status_code == 404

    # 404: 경로 조작 시도 (FastAPI 라우팅 또는 식별자 검증이 차단)
    r = client.get("/api/meetings/..%2F..%2Fetc/recording")
    assert r.status_code in (404, 422)

    # 200: 파일 존재
    (tmp_path / "meeting-ok.mp3").write_bytes(b"\xff\xfb" + b"\x00" * 64)
    r = client.get("/api/meetings/meeting-ok/recording")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/mpeg")
    assert r.content[:2] == b"\xff\xfb"

    # HEAD: 프런트 사전 점검용 (FastAPI get은 HEAD 미지원 405 → 전용 라우트)
    r = client.head("/api/meetings/meeting-ok/recording")
    assert r.status_code == 200
    assert r.headers["content-length"] == "66"
    r = client.head("/api/meetings/no-such-meeting/recording")
    assert r.status_code == 404


def test_offset_sidecar_written_for_new_file_and_kept_on_append(tmp_path, monkeypatch):
    """새 녹음 파일이면 오디오-초 오프셋 사이드카 기록, 재개(append)면 유지."""
    import asyncio as _asyncio

    monkeypatch.setattr(lr.settings, "live_record_dir", str(tmp_path))
    monkeypatch.setattr(lr.settings, "live_record_enabled", True)
    rec = LiveAudioRecorder()
    proc1, proc2 = _mock_proc(), _mock_proc()
    monkeypatch.setattr(lr.asyncio, "create_subprocess_exec", AsyncMock(side_effect=[proc1, proc2]))

    async def run():
        await rec.start("ch8", "meeting-1", start_offset_sec=123.45)
        # 파일에 데이터가 쌓였다고 가정
        (tmp_path / "meeting-1.mp3").write_bytes(b"\xff\xfb" * 100)
        await rec.stop("ch8")
        # 재개 — 오프셋 999를 넘겨도 기존 사이드카 유지
        await rec.start("ch8", "meeting-1", start_offset_sec=999.0)
        await rec.stop("ch8")

    _asyncio.get_event_loop_policy().new_event_loop().run_until_complete(run()) if False else _asyncio.run(run())

    assert lr.recording_offset("meeting-1") == 123.45


def test_recording_offset_defaults_to_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(lr.settings, "live_record_dir", str(tmp_path))
    assert lr.recording_offset("no-sidecar") == 0.0


def test_recording_meta_and_range_endpoints(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr(lr.settings, "live_record_dir", str(tmp_path))
    client = TestClient(app)

    payload = bytes(range(256)) * 4  # 1024 bytes
    (tmp_path / "meeting-r.mp3").write_bytes(payload)
    (tmp_path / "meeting-r.offset").write_text("42.50", encoding="utf-8")

    # meta (사이드카 존재 → 정확한 오프셋. .sessions 없으면 빈 목록)
    r = client.get("/api/meetings/meeting-r/recording/meta")
    assert r.status_code == 200
    assert r.json() == {
        "exists": True,
        "size_bytes": 1024,
        "bytes_per_sec": 6000,
        "start_offset_sec": 42.5,
        "sessions": [],
    }

    # .sessions 인덱스가 있으면 구간별 (clock, byte) 매핑을 그대로 노출한다
    (tmp_path / "meeting-r.sessions").write_text(
        '{"clock": 42.5, "byte": 0}\n{"clock": 100.0, "byte": 6000}\n', encoding="utf-8"
    )
    r = client.get("/api/meetings/meeting-r/recording/meta")
    assert r.status_code == 200
    assert r.json()["sessions"] == [
        {"clock": 42.5, "byte": 0},
        {"clock": 100.0, "byte": 6000},
    ]

    # 일반 GET: Accept-Ranges 광고
    r = client.get("/api/meetings/meeting-r/recording")
    assert r.status_code == 200
    assert r.headers["accept-ranges"] == "bytes"
    assert len(r.content) == 1024

    # Range: 중간 구간
    r = client.get("/api/meetings/meeting-r/recording", headers={"Range": "bytes=100-199"})
    assert r.status_code == 206
    assert r.headers["content-range"] == "bytes 100-199/1024"
    assert r.content == payload[100:200]

    # Range: suffix
    r = client.get("/api/meetings/meeting-r/recording", headers={"Range": "bytes=-50"})
    assert r.status_code == 206
    assert r.content == payload[-50:]

    # Range: 끝 미지정
    r = client.get("/api/meetings/meeting-r/recording", headers={"Range": "bytes=1000-"})
    assert r.status_code == 206
    assert r.content == payload[1000:]

    # Range: 범위 밖 → 416
    r = client.get("/api/meetings/meeting-r/recording", headers={"Range": "bytes=2000-"})
    assert r.status_code == 416


def test_recording_meta_offset_fallback_from_audio_clock(tmp_path, monkeypatch):
    """사이드카 없는 레거시 파일은 STT 진행 중이면 오디오 시계로 오프셋을 추정한다."""
    from fastapi.testclient import TestClient

    import app.services.openai_realtime_stt as rt
    from app.main import app

    monkeypatch.setattr(lr.settings, "live_record_dir", str(tmp_path))
    # 60000 bytes @6000B/s = 10초 분량
    (tmp_path / "meeting-legacy.mp3").write_bytes(b"\xff" * 60000)

    class _StubSvc:
        def audio_clock_for_meeting(self, meeting_id):
            return 110.0 if meeting_id == "meeting-legacy" else None

    monkeypatch.setattr(rt, "_channel_stt_service", _StubSvc())

    client = TestClient(app)
    r = client.get("/api/meetings/meeting-legacy/recording/meta")
    assert r.status_code == 200
    body = r.json()
    # 오프셋 ≈ 110 - 60000/6000 = 100초
    assert body["start_offset_sec"] == 100.0


def test_recording_sessions_index(tmp_path, monkeypatch):
    """녹음 시작마다 (시계, 바이트) 세션 인덱스가 append된다 — 시계 되감김 대응."""
    import asyncio as _asyncio

    monkeypatch.setattr(lr.settings, "live_record_dir", str(tmp_path))
    monkeypatch.setattr(lr.settings, "live_record_enabled", True)
    rec = LiveAudioRecorder()
    procs = [_mock_proc(), _mock_proc()]
    monkeypatch.setattr(lr.asyncio, "create_subprocess_exec", AsyncMock(side_effect=procs))

    async def run():
        await rec.start("ch8", "meeting-s", start_offset_sec=100.0)
        (tmp_path / "meeting-s.mp3").write_bytes(b"\xff" * 6000)  # 1초 분량 기록됐다고 가정
        await rec.stop("ch8")
        # 재시작 — 시계가 되감겨도(90.0) 새 세션 엔트리가 기록됨
        await rec.start("ch8", "meeting-s", start_offset_sec=90.0)
        await rec.stop("ch8")

    _asyncio.run(run())

    sessions = lr.recording_sessions("meeting-s")
    assert sessions == [
        {"clock": 100.0, "byte": 0},
        {"clock": 90.0, "byte": 6000},
    ]
