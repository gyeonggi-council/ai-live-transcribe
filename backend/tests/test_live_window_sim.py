"""live_window_sim — 운영 창 분절 규칙의 오프라인 재현 (2026-09-14, 창 축소 실험의 도구).

핵심 단언: 같은 합성 PCM 을 실제 `LiveBatchSttService._maybe_flush` 에 0.5초씩 먹였을 때와 시뮬레이터의 컷
(창 시작·길이)이 같다 — 규칙을 복제한 코드가 운영과 갈라지면 실험 결과가 운영을 대표하지 못한다.
"""

import asyncio
import os
import sys
from array import array

import pytest

from app.services import live_batch_stt as lb
from app.services.live_batch_stt import LiveBatchSttService

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from live_window_sim import LiveWindowSimulator  # noqa: E402

RATE = 24000
BYPS = RATE * 2


def _silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(RATE * seconds)


def _loud(seconds: float, amplitude: int = 3000) -> bytes:
    n = int(RATE * seconds)
    return array("h", [amplitude if i % 2 == 0 else -amplitude for i in range(n)]).tobytes()


def _drive(sim: LiveWindowSimulator, api_sec: float = 0.0) -> list[tuple[float, float, str]]:
    out = []
    gen = sim.windows()
    try:
        win = next(gen)
        while True:
            out.append((round(win.start_sec, 2), round(len(win.pcm) / BYPS, 2), win.reason))
            win = gen.send(api_sec)
    except StopIteration:
        pass
    return out


def test_continuous_speech_cuts_at_window():
    """연속 발화 30초 (8,4) → 8초 창 셋 + 잔여 6초 eof. 균일 발화라 조용한 지점이 없어 창 끝에서 자른다."""
    sim = LiveWindowSimulator(_loud(30.0), RATE, window=8.0, min_flush=4.0)
    wins = _drive(sim)
    assert [w[2] for w in wins] == ["window", "window", "window", "eof"]
    assert [w[1] for w in wins] == [8.0, 8.0, 8.0, 6.0]
    assert [w[0] for w in wins] == [0.0, 8.0, 16.0, 24.0]
    s = sim.stats()
    assert s["windows"] == 4 and s["reasons"] == {"window": 3, "eof": 1}
    # API 0 이면 ready_lag = 창 길이(컷 시점 버퍼) — 8초 창은 8.0
    assert s["ready_lag_p50"] == 8.0 and s["window_mean"] == 7.5


def test_pause_flush_at_sentence_boundary():
    """발화 5초 + 무음 1초 → min_flush(4) 를 넘긴 뒤 꼬리 0.6초 무음에서 조기 flush ('pause')."""
    sim = LiveWindowSimulator(_loud(5.0) + _silence(1.0) + _loud(2.0), RATE, window=12.0, min_flush=4.0)
    wins = _drive(sim)
    assert wins[0][2] == "pause" and wins[0][0] == 0.0
    # 0.5초 청크 단위 판정: 5.0 발화 뒤 무음 0.6초가 꼬리에 차는 첫 청크 경계(5.5초 뒤 6.0초)에서 자른다
    assert 5.5 <= wins[0][1] <= 6.0


def test_silent_window_dropped_without_api_and_without_inflight():
    """무음 창은 API 없이 버린다 — 시뮬레이터도 창을 내지 않고 silent_windows 만 센다."""
    sim = LiveWindowSimulator(_silence(13.0) + _loud(3.0), RATE, window=12.0, min_flush=6.0)
    wins = _drive(sim)
    assert sim.silent_windows >= 1
    assert all(w[2] != "silent" for w in wins)
    # 무음 6초씩 두 번 버려지고(pause 컷 → 발화 없음), 남은 무음 1초 + 발화 3초가 EOF 잔여로 나간다
    assert wins[-1][2] == "eof" and wins[-1][1] == pytest.approx(4.0, abs=0.01)


def test_inflight_delays_next_cut_and_inflates_ready_lag():
    """API 3초 동안은 판정하지 않는다 → 다음 컷이 늦어지고 그 창의 ready_lag 는 (컷까지 쌓인 버퍼) + API 가 된다."""
    sim = LiveWindowSimulator(_loud(24.0), RATE, window=8.0, min_flush=4.0)
    wins = _drive(sim, api_sec=3.0)
    # 첫 창 8초 → 3초 뒤(11초 시점) 재판정: 버퍼 3초(<8) → 16초 시점에 둘째 창 → 19초 → 24초 시점 셋째 창(버퍼 8)
    assert [w[1] for w in wins] == [8.0, 8.0, 8.0]
    assert [w[2] for w in wins] == ["window", "window", "window"]
    s = sim.stats()
    assert s["ready_lag_p50"] == 11.0  # 8 + 3
    assert s["api_sec_p50"] == 3.0


def test_api_completion_mid_chunk_reevaluates_with_buffer_at_that_moment():
    """API 가 0.5초 청크 경계 사이에 끝나면 운영은 그 순간의 버퍼로 재판정한다 — 첫 창 8초·API 6.2초 뒤 무음이면
    두 번째 창은 (8초를 채우지 않고) 완료 시점의 6.2초 버퍼가 pause 조기 방출된다 (Codex 09-14)."""
    pcm = _loud(8.0) + _loud(2.0) + _silence(12.0)
    sim = LiveWindowSimulator(pcm, RATE, window=8.0, min_flush=4.0)
    wins = _drive(sim, api_sec=6.2)
    assert wins[0] == (0.0, 8.0, "window")
    # 완료 시점 t=14.2 의 버퍼 = 8.0~14.2 (발화 2초 + 무음 4.2초) → 꼬리 무음이라 pause 컷 6.2초
    assert wins[1][2] == "pause" and wins[1][0] == 8.0 and wins[1][1] == pytest.approx(6.2, abs=0.01)


def test_eof_remainder_under_one_second_is_dropped():
    sim = LiveWindowSimulator(_loud(8.5), RATE, window=8.0, min_flush=4.0)
    wins = _drive(sim)
    assert [w[1] for w in wins] == [8.0]


async def test_matches_production_maybe_flush(monkeypatch):
    """★같은 PCM 을 실제 _maybe_flush 에 0.5초씩 먹인 컷 = 시뮬레이터 컷 (API 0초)."""
    monkeypatch.setattr(lb.settings, "live_batch_window_seconds", 8.0)
    monkeypatch.setattr(lb.settings, "live_batch_min_flush_seconds", 4.0)
    pcm = (
        _loud(5.0) + _silence(1.0) + _loud(9.0, 2000) + _silence(0.2) + _loud(0.5)
        + _silence(2.0) + _loud(3.0, 4000) + _silence(1.0) + _loud(1.2)
    )

    svc = LiveBatchSttService()
    ch = "chX"
    got: list[tuple[float, float]] = []

    # 실제 _transcribe_window 를 돌린다(in-flight 해제와 finally 의 재판정까지 운영 그대로) — API 만 빈 결과로 대체
    from unittest.mock import AsyncMock, MagicMock

    svc._client = MagicMock()
    svc._client.audio.transcriptions.create = AsyncMock(return_value=MagicMock(text=""))
    orig = svc._transcribe_window

    async def recording_transcribe(channel_id, meeting_id, window_pcm, start_sec, dur, gen):
        got.append((round(start_sec, 2), round(len(window_pcm) / BYPS, 2)))
        await orig(channel_id, meeting_id, window_pcm, start_sec, dur, gen)

    monkeypatch.setattr(svc, "_transcribe_window", recording_transcribe)
    svc._buffers[ch] = bytearray()
    svc._buffer_start[ch] = 0.0
    svc._audio_sec[ch] = 0.0
    svc._generation[ch] = 1  # 세션 세대 — 없으면 finally 가 고아로 보고 in-flight 를 안 풀어 두 번째 컷이 영영 안 온다
    chunk = int(0.5 * BYPS)
    for pos in range(0, len(pcm), chunk):
        piece = pcm[pos:pos + chunk]
        svc._buffers[ch].extend(piece)
        svc._audio_sec[ch] += len(piece) / BYPS
        svc._maybe_flush(ch)
        await asyncio.sleep(0)  # 전사 스텁 완료 → finally 의 재판정까지 돌린다
        await asyncio.sleep(0)
    await svc._flush_remaining(ch)

    sim = LiveWindowSimulator(pcm, RATE, window=8.0, min_flush=4.0)
    wins = _drive(sim)
    assert [(w[0], w[1]) for w in wins] == got
    assert len(got) >= 3
