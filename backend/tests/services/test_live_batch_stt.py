"""LiveBatchSttService 단위 테스트 (라이브 배치 STT — live_stt_mode="batch").

실제 ffmpeg/HLS/OpenAI 없이 윈도우 컷·무음 스킵·문장 분리·전사 방출·팩토리 분기를 검증한다.
"""

import asyncio
from array import array
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.services.openai_realtime_stt as rt
from app.services import live_batch_stt as lb
from app.services.live_batch_stt import (
    LiveBatchSttService,
    _find_quiet_cut,
    _window_rms,
    split_sentences_with_timestamps,
    time_sentences,
)

RATE = 24000
BYPS = RATE * 2


def _silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(RATE * seconds)


def _loud(seconds: float, amplitude: int = 3000) -> bytes:
    n = int(RATE * seconds)
    return array("h", [amplitude if i % 2 == 0 else -amplitude for i in range(n)]).tobytes()


@pytest.fixture
def svc() -> LiveBatchSttService:
    return LiveBatchSttService()


# ─── 순수 함수 ───────────────────────────────────────────────────────────


def test_cut_search_seconds_scales_with_window():
    """조용한 컷 탐색 꼬리는 창 길이에 비례 — 12초 창은 옛 절대값 2.5 그대로, 8초 창은 1.67, 하한 1.5."""
    assert lb._cut_search_seconds(12.0) == pytest.approx(2.5)
    assert lb._cut_search_seconds(8.0) == pytest.approx(8.0 * 2.5 / 12.0)
    assert lb._cut_search_seconds(4.0) == 1.5


def test_window_rms_silent_vs_loud():
    assert _window_rms(_silence(1.0)) == 0.0
    assert _window_rms(_loud(1.0)) > 1000


def test_find_quiet_cut_prefers_silent_gap():
    """윈도우 꼬리의 무음 구간 안에서 컷 지점을 고른다 (단어 중간 절단 방지)."""
    # 0~13.5초 발화, 13.5~14.0초 무음, 14.0~16초 발화
    pcm = _loud(13.5) + _silence(0.5) + _loud(2.0)
    cut = _find_quiet_cut(pcm, RATE, window_seconds=15.0)
    cut_sec = cut / BYPS
    assert 13.4 <= cut_sec <= 14.1
    assert cut % 2 == 0  # 샘플 경계


def test_find_quiet_cut_short_buffer_returns_end():
    pcm = _loud(3.0)
    cut = _find_quiet_cut(pcm, RATE, window_seconds=15.0)
    assert cut == len(pcm)


def test_find_quiet_cut_uniform_speech_cuts_at_window_end():
    """조용한 지점이 없는 연속 발화는 윈도우 끝에서 자른다 (불필요한 조기 컷 방지)."""
    pcm = _loud(16.0)
    cut = _find_quiet_cut(pcm, RATE, window_seconds=15.0)
    assert cut == int(15.0 * BYPS)


def test_split_sentences_proportional():
    text = "의사일정 제1항을 상정합니다 다음은 보고사항을 말씀드리겠습니다"
    out = split_sentences_with_timestamps(text, 10.0, 25.0)
    assert len(out) == 2
    # 타임스탬프 연속 + 전체 구간 보존
    assert out[0][1] == 10.0
    assert out[0][2] == out[1][1]
    assert out[1][2] == 25.0
    assert "상정합니다" in out[0][0]
    assert "말씀드리겠습니다" in out[1][0]


def test_split_sentences_empty():
    assert split_sentences_with_timestamps("", 0.0, 15.0) == []


def test_time_sentences_start_at_speech_not_window_start():
    """창이 쉼으로 시작하면 첫 문장은 말이 시작된 곳에 선다 — 예전엔 창 시작(쉼)에 서서
    의원 발언이 끝난 뒤 다음 자막이 말보다 먼저 떴다 (2026-09-11 ch60)."""
    pcm = _silence(3.0) + _loud(6.0) + _silence(1.0)
    out = time_sentences(["의사일정 제1항을 상정합니다.", "보고사항을 말씀드리겠습니다."], 100.0, 110.0, pcm, RATE)
    assert out[0][1] == pytest.approx(103.0, abs=0.11)
    assert 103.0 < out[1][1] < 109.0
    assert out[0][2] == out[1][1]
    assert out[-1][2] == pytest.approx(109.0, abs=0.11)  # 꼬리 무음은 빼고 끝난다


def test_time_sentences_ignore_short_noise_before_speech():
    """앞뒤가 쉼인 0.3초 미만 소리(책상·마이크 잡음)에 첫 문장을 맞추지 않는다."""
    pcm = _loud(0.2) + _silence(2.0) + _loud(4.0)
    out = time_sentences(["네, 질의하시기 바랍니다."], 0.0, 6.2, pcm, RATE)
    assert out[0][1] == pytest.approx(2.2, abs=0.11)


def test_time_sentences_split_voiced_time_by_chars_across_pauses():
    """글자 비례는 말소리가 난 시간에만 — 가운데 쉼(2초)은 어느 문장의 몫도 아니다."""
    pcm = _loud(4.0) + _silence(2.0) + _loud(4.0)
    out = time_sentences(["가나다라", "마바사아"], 0.0, 10.0, pcm, RATE)
    assert out[1][1] == pytest.approx(6.0, abs=0.11)  # 글자 반 = 말소리 4초 지점 = 쉼 뒤 첫 소리


def test_time_sentences_without_speech_falls_back_to_window():
    out = time_sentences(["가나다", "라마바"], 0.0, 6.0, _silence(6.0), RATE)
    assert [(o[1], o[2]) for o in out] == [(0.0, 3.0), (3.0, 6.0)]


# ─── 윈도우 flush ─────────────────────────────────────────────────────────


async def test_maybe_flush_skips_silent_window_without_api(svc, monkeypatch):
    """무음 윈도우는 API 호출 없이 폐기되고 silence_skipped만 증가한다."""
    monkeypatch.setattr(lb.settings, "live_batch_window_seconds", 15.0)
    monkeypatch.setattr(lb.settings, "live_batch_silence_rms", 250)
    ch = "ch8"
    svc._client = MagicMock()
    svc._meeting_ids[ch] = ch
    svc._buffers[ch] = bytearray(_silence(16.0))
    svc._buffer_start[ch] = 0.0
    svc._silence_skipped[ch] = 0

    svc._maybe_flush(ch)

    assert svc._silence_skipped[ch] == 1
    assert ch not in svc._inflight
    svc._client.audio.transcriptions.create.assert_not_called()
    # 버퍼는 컷만큼 소비되고 시계는 전진
    assert svc._buffer_start[ch] > 0.0


async def test_maybe_flush_carries_remainder_and_sets_inflight(svc, monkeypatch):
    """발화 윈도우는 전사 태스크를 띄우고, 컷 이후 나머지는 버퍼에 남는다."""
    monkeypatch.setattr(lb.settings, "live_batch_window_seconds", 15.0)
    ch = "ch8"
    svc._meeting_ids[ch] = ch
    svc._buffers[ch] = bytearray(_loud(18.0))
    svc._buffer_start[ch] = 100.0

    started: list[tuple] = []

    async def fake_transcribe(channel_id, meeting_id, pcm, start_sec, dur, gen):
        started.append((channel_id, meeting_id, len(pcm), start_sec, dur))
        svc._inflight.discard(channel_id)

    monkeypatch.setattr(svc, "_transcribe_window", fake_transcribe)
    svc._maybe_flush(ch)
    await asyncio.sleep(0.05)

    assert len(started) == 1
    _, _, pcm_len, start_sec, dur = started[0]
    assert start_sec == 100.0
    # 컷은 12.5~15초 사이(꼬리 탐색 구간) → 나머지가 버퍼에 이월
    assert 12.0 <= dur <= 15.1
    assert len(svc._buffers[ch]) == int(18.0 * BYPS) - pcm_len
    assert abs(svc._buffer_start[ch] - (100.0 + dur)) < 0.01


async def test_pause_flush_triggers_early(svc, monkeypatch):
    """발화 멈춤(무음 꼬리)이 감지되면 윈도우를 기다리지 않고 조기 flush한다 (지연 단축)."""
    monkeypatch.setattr(lb.settings, "live_batch_window_seconds", 7.0)
    monkeypatch.setattr(lb.settings, "live_batch_min_flush_seconds", 3.0)
    monkeypatch.setattr(lb.settings, "live_batch_pause_flush_seconds", 0.6)
    ch = "ch8"
    svc._meeting_ids[ch] = ch
    # 4초 발화 + 0.8초 무음 꼬리 (총 4.8초 < 윈도우 7초)
    svc._buffers[ch] = bytearray(_loud(4.0) + _silence(0.8))
    svc._buffer_start[ch] = 0.0

    started: list[float] = []

    async def fake_transcribe(channel_id, meeting_id, pcm, start_sec, dur, gen):
        started.append(dur)
        svc._inflight.discard(channel_id)

    monkeypatch.setattr(svc, "_transcribe_window", fake_transcribe)
    svc._maybe_flush(ch)
    await asyncio.sleep(0.05)

    assert len(started) == 1
    assert 4.5 <= started[0] <= 5.0  # 버퍼 전체가 조기 flush됨


async def test_no_pause_flush_during_continuous_speech(svc, monkeypatch):
    """연속 발화 중(무음 꼬리 없음)에는 윈도우 도달 전까지 flush하지 않는다."""
    monkeypatch.setattr(lb.settings, "live_batch_window_seconds", 7.0)
    monkeypatch.setattr(lb.settings, "live_batch_min_flush_seconds", 3.0)
    ch = "ch8"
    svc._buffers[ch] = bytearray(_loud(5.0))
    svc._buffer_start[ch] = 0.0
    before = len(svc._buffers[ch])

    svc._maybe_flush(ch)
    assert len(svc._buffers[ch]) == before  # 버퍼 유지


def test_has_speech_detects_brief_utterance_in_long_silence():
    """긴 무음에 묻힌 짧은 발언도 발화로 판정한다 — 평균 RMS 방식의 누락 문제 회귀."""
    from app.services.live_batch_stt import _has_speech, _window_rms

    pcm = _silence(6.0) + _loud(0.7) + _silence(0.5)
    # 평균 RMS는 임계(250) 근처/이하로 떨어질 수 있지만 최대 블록 기준은 발화를 잡는다
    assert _has_speech(pcm, RATE) is True
    assert _has_speech(_silence(7.0), RATE) is False
    # 비교: 짧은 발언의 평균 RMS 희석 정도 확인 (문서화 목적)
    assert _window_rms(pcm) < _window_rms(_loud(0.7))


async def test_brief_speech_in_silence_force_flush_is_transcribed(svc, monkeypatch):
    """강제 flush(스트림 정지) 시 무음+짧은 발언 버퍼가 스킵되지 않고 전사된다."""
    monkeypatch.setattr(lb.settings, "live_batch_window_seconds", 7.0)
    ch = "ch8"
    svc._meeting_ids[ch] = ch
    svc._buffers[ch] = bytearray(_silence(4.0) + _loud(0.7))
    svc._buffer_start[ch] = 0.0
    svc._silence_skipped[ch] = 0

    called: list[int] = []

    async def fake_transcribe(channel_id, meeting_id, pcm, start_sec, dur, gen):
        called.append(len(pcm))
        svc._inflight.discard(channel_id)

    monkeypatch.setattr(svc, "_transcribe_window", fake_transcribe)
    svc._maybe_flush(ch, force=True)
    await asyncio.sleep(0.05)

    assert len(called) == 1  # 전사됨 (스킵 아님)
    assert svc._silence_skipped[ch] == 0


async def test_maybe_flush_noop_while_inflight(svc, monkeypatch):
    """전사 in-flight 중에는 새 flush를 시작하지 않는다 (순서 보존)."""
    monkeypatch.setattr(lb.settings, "live_batch_window_seconds", 15.0)
    ch = "ch8"
    svc._buffers[ch] = bytearray(_loud(16.0))
    svc._buffer_start[ch] = 0.0
    svc._inflight.add(ch)
    before = len(svc._buffers[ch])

    svc._maybe_flush(ch)
    assert len(svc._buffers[ch]) == before  # 버퍼 유지


# ─── 전사 + 자막 방출 ─────────────────────────────────────────────────────


async def test_transcribe_window_emits_sentence_subtitles(svc, monkeypatch):
    """전사 결과가 문장 단위 자막으로 분리되어 브로드캐스트 + DB 저장된다."""
    mock_manager = MagicMock()
    mock_manager.broadcast_subtitle = AsyncMock()
    monkeypatch.setattr(lb, "manager", mock_manager)
    mock_supabase = MagicMock()
    monkeypatch.setattr(lb, "get_supabase_client", lambda: mock_supabase)
    cue = MagicMock()
    cue.roster_names.return_value = []
    monkeypatch.setattr(lb, "speaker_cue_tracker", cue)
    corrector = MagicMock()
    monkeypatch.setattr(lb, "live_corrector", corrector)

    ch = "ch8"
    meeting_uuid = "11111111-1111-1111-1111-111111111111"
    svc._meeting_ids[ch] = meeting_uuid
    svc._glossary_prompts[ch] = "표기를 이 목록과 일치시키세요: 산회, 김영수"
    svc._prev_tail[ch] = ""
    svc._inflight.add(ch)

    result = MagicMock()
    result.text = "의사일정 제1항을 상정합니다 다음 안건을 말씀드리겠습니다"
    svc._client = MagicMock()
    svc._client.audio.transcriptions.create = AsyncMock(return_value=result)
    svc._generation[ch] = 1

    await svc._transcribe_window(ch, meeting_uuid, _loud(15.0), 30.0, 15.0, gen=1)
    await asyncio.sleep(0.05)  # fire-and-forget persist 대기

    # 글로서리 prompt가 전사 호출에 포함됨
    kwargs = svc._client.audio.transcriptions.create.await_args.kwargs
    assert kwargs["model"] == lb.settings.live_batch_model
    assert kwargs["language"] == "ko"
    assert "산회" in kwargs["prompt"]

    # 문장 2개 → 자막 2건 브로드캐스트
    assert mock_manager.broadcast_subtitle.await_count == 2
    first_room, first_payload = mock_manager.broadcast_subtitle.await_args_list[0].args
    assert first_room == ch
    sub = first_payload["subtitle"]
    assert sub["meeting_id"] == meeting_uuid
    assert sub["speaker"] is None
    assert sub["start_time"] == 30.0
    assert "상정합니다" in sub["text"]
    last_sub = mock_manager.broadcast_subtitle.await_args_list[1].args[1]["subtitle"]
    assert last_sub["end_time"] == 45.0

    # 교정 큐 적재 + DB persist + 문맥 꼬리 갱신 + inflight 해제
    assert corrector.enqueue.call_count == 2
    assert mock_supabase.table.called
    assert "말씀드리겠습니다" in svc._prev_tail[ch]
    assert ch not in svc._inflight


async def test_transcribe_window_includes_prev_tail_context(svc, monkeypatch):
    """직전 윈도우 전사 꼬리가 다음 호출의 prompt 문맥으로 이어진다."""
    monkeypatch.setattr(lb, "manager", MagicMock(broadcast_subtitle=AsyncMock()))
    monkeypatch.setattr(lb, "get_supabase_client", lambda: MagicMock())
    cue = MagicMock()
    cue.roster_names.return_value = []
    monkeypatch.setattr(lb, "speaker_cue_tracker", cue)
    monkeypatch.setattr(lb, "live_corrector", MagicMock())

    ch = "ch8"
    svc._meeting_ids[ch] = ch
    svc._glossary_prompts[ch] = ""
    svc._prev_tail[ch] = "지난 윈도우 마지막 발언입니다"

    result = MagicMock()
    result.text = "이어지는 발언입니다"
    svc._client = MagicMock()
    svc._client.audio.transcriptions.create = AsyncMock(return_value=result)
    svc._generation[ch] = 1

    await svc._transcribe_window(ch, ch, _loud(15.0), 0.0, 15.0, gen=1)

    kwargs = svc._client.audio.transcriptions.create.await_args.kwargs
    assert "지난 윈도우 마지막 발언입니다" in kwargs["prompt"]


async def test_transcribe_window_api_failure_restores_buffer(svc, monkeypatch):
    """전사 API 실패 시 윈도우 오디오를 버퍼 앞에 되돌려 영구 유실을 막는다."""
    mock_manager = MagicMock(broadcast_subtitle=AsyncMock())
    monkeypatch.setattr(lb, "manager", mock_manager)

    ch = "ch8"
    svc._meeting_ids[ch] = ch
    svc._inflight.add(ch)
    svc._generation[ch] = 1
    failed_pcm = _loud(15.0)
    # 실패 윈도우 이후 새로 쌓인 버퍼 (시간적으로 연속)
    svc._buffers[ch] = bytearray(_loud(3.0))
    svc._buffer_start[ch] = 15.0
    svc._client = MagicMock()
    svc._client.audio.transcriptions.create = AsyncMock(side_effect=RuntimeError("quota"))

    await svc._transcribe_window(ch, ch, failed_pcm, 0.0, 15.0, gen=1)
    await asyncio.sleep(0.05)

    mock_manager.broadcast_subtitle.assert_not_awaited()
    assert "quota" in svc._last_error[ch]
    assert ch not in svc._inflight
    # 실패 pcm이 버퍼 앞에 복원되고 시작 오프셋이 되돌아감 → 쿨다운 후 재전사
    assert len(svc._buffers[ch]) == len(failed_pcm) + int(3.0 * BYPS)
    assert svc._buffer_start[ch] == 0.0
    # 쿨다운(FAILURE_RETRY_SECONDS) 덕에 즉시 재시도(핫 루프)하지 않는다
    assert svc._client.audio.transcriptions.create.await_count == 1


async def test_transcribe_window_stale_generation_discards_result(svc, monkeypatch):
    """stop/재시작으로 세대가 바뀐 고아 태스크의 결과는 폐기된다 (유령 자막 방지)."""
    mock_manager = MagicMock(broadcast_subtitle=AsyncMock())
    monkeypatch.setattr(lb, "manager", mock_manager)

    ch = "ch8"
    svc._generation[ch] = 2  # 신세대 — 태스크의 gen=1은 stale
    svc._inflight.add(ch)
    result = MagicMock()
    result.text = "유령 자막입니다"
    svc._client = MagicMock()
    svc._client.audio.transcriptions.create = AsyncMock(return_value=result)

    await svc._transcribe_window(ch, ch, _loud(15.0), 0.0, 15.0, gen=1)

    mock_manager.broadcast_subtitle.assert_not_awaited()
    # 고아 태스크는 신세대의 in-flight 게이트를 풀지 않는다
    assert ch in svc._inflight


async def test_stop_flushes_remaining_buffer(svc, monkeypatch):
    """stop()은 잔여 버퍼(방송 종료 직전 발언)를 최종 1회 전사한다."""
    flushed: list[tuple] = []

    async def fake_transcribe(channel_id, meeting_id, pcm, start_sec, dur, gen):
        flushed.append((channel_id, meeting_id, len(pcm), start_sec, dur))

    monkeypatch.setattr(svc, "_transcribe_window", fake_transcribe)
    ch = "ch8"
    svc._meeting_ids[ch] = "m-1"
    svc._generation[ch] = 1
    svc._buffers[ch] = bytearray(_loud(6.0))
    svc._buffer_start[ch] = 120.0
    svc._edge_wall[ch] = 1.0  # 벽시계 상태 — stop 뒤 남으면 다음 세션의 edge_lag 가 옛 값에서 시작한다

    await svc.stop(ch)

    assert len(flushed) == 1
    assert ch not in svc._edge_wall
    _, meeting_id, pcm_len, start_sec, _dur = flushed[0]
    assert meeting_id == "m-1"
    assert pcm_len == int(6.0 * BYPS)
    assert start_sec == 120.0
    # 정리 완료 + 세대 증가 (고아 무효화)
    assert ch not in svc._buffers
    assert svc._generation[ch] == 2


async def test_stop_skips_silent_remaining_buffer(svc, monkeypatch):
    """stop() 잔여 버퍼가 무음이면 최종 전사를 생략한다 (비용 0)."""
    transcribe = AsyncMock()
    monkeypatch.setattr(svc, "_transcribe_window", transcribe)
    ch = "ch8"
    svc._buffers[ch] = bytearray(_silence(6.0))
    svc._buffer_start[ch] = 0.0

    await svc.stop(ch)
    transcribe.assert_not_awaited()


# ─── 공개 인터페이스 / 팩토리 ─────────────────────────────────────────────


def test_active_channels_property(svc):
    done_task = MagicMock()
    done_task.done.return_value = True
    running_task = MagicMock()
    running_task.done.return_value = False
    svc._active_tasks = {"ch1": done_task, "ch2": running_task}
    assert svc.active_channels == ["ch2"]


def test_get_debug_info_shape(svc):
    info = svc.get_debug_info("ch9")
    assert info["engine"] == "openai_batch"
    assert info["model"] == lb.settings.live_batch_model
    assert "buffered_sec" in info and "silence_skipped" in info and "api_calls" in info
    assert info["edge_lag_sec"] is None  # 세그먼트를 본 적 없음


def test_factory_dispatches_by_live_stt_mode(monkeypatch):
    """get_channel_stt_service는 live_stt_mode에 따라 batch/realtime 엔진을 반환한다."""
    monkeypatch.setattr(rt, "_channel_stt_service", None)
    monkeypatch.setattr(rt.settings, "live_stt_mode", "batch")
    assert isinstance(rt.get_channel_stt_service(), LiveBatchSttService)

    monkeypatch.setattr(rt, "_channel_stt_service", None)
    monkeypatch.setattr(rt.settings, "live_stt_mode", "realtime")
    assert isinstance(rt.get_channel_stt_service(), rt.OpenAiRealtimeSttService)


# ─── 프롬프트 에코 중복 제거 ──────────────────────────────────────────────


def test_strip_overlap_drops_full_duplicate():
    """윈도우 전체가 직전 텍스트의 반복(에코)이면 통째로 폐기."""
    from app.services.live_batch_stt import _strip_overlap

    assert _strip_overlap("위원장님 고은정 위원입니다", "고은정") == ""
    assert _strip_overlap("이의 없으십니까? 가결되었음을 선포합니다", "가결되었음을 선포합니다") == ""


def test_strip_overlap_trims_prefix_echo():
    """직전 꼬리의 접미사가 현재 접두사로 반복되면 겹친 만큼 절단."""
    from app.services.live_batch_stt import _strip_overlap

    prev = "다음은 보충질의 순서입니다"
    cur = "보충질의 순서입니다 질의하실 위원님 계십니까"
    assert _strip_overlap(prev, cur) == "질의하실 위원님 계십니까"


def test_strip_overlap_keeps_distinct_text():
    from app.services.live_batch_stt import _strip_overlap

    prev = "지출승인의 건에 대한 질의 답변을 종결하겠습니다"
    cur = "13시까지 정회를 선포합니다"
    assert _strip_overlap(prev, cur) == cur
    assert _strip_overlap("", cur) == cur


async def test_transcribe_window_drops_echo_duplicate(svc, monkeypatch):
    """직전 윈도우와 동일한 전사 결과는 자막으로 방출되지 않는다."""
    mock_manager = MagicMock(broadcast_subtitle=AsyncMock())
    monkeypatch.setattr(lb, "manager", mock_manager)
    cue = MagicMock()
    cue.roster_names.return_value = []
    monkeypatch.setattr(lb, "speaker_cue_tracker", cue)
    monkeypatch.setattr(lb, "live_corrector", MagicMock())

    ch = "ch8"
    svc._meeting_ids[ch] = ch
    svc._generation[ch] = 1
    svc._prev_tail[ch] = "위원장님 고은정 위원입니다"

    result = MagicMock()
    result.text = "고은정"  # 직전 꼬리에 그대로 포함 → 에코
    svc._client = MagicMock()
    svc._client.audio.transcriptions.create = AsyncMock(return_value=result)

    await svc._transcribe_window(ch, ch, _loud(8.0), 0.0, 8.0, gen=1)

    mock_manager.broadcast_subtitle.assert_not_awaited()
    assert svc._dup_skipped[ch] == 1
    # prev_tail은 유지 (다음 윈도우 비교 기준)
    assert svc._prev_tail[ch] == "위원장님 고은정 위원입니다"


# ─── 재시작 중복 방지 (백로그 스킵) ────────────────────────────────────────


def test_is_quick_restart_detection():
    """마지막 자막이 최근이면 빠른 재시작(백로그 스킵), 오래됐으면 정상 재개."""
    from datetime import datetime, timedelta, timezone

    recent = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()

    assert LiveBatchSttService._is_quick_restart(recent) is True
    assert LiveBatchSttService._is_quick_restart(old) is False
    assert LiveBatchSttService._is_quick_restart(None) is False
    assert LiveBatchSttService._is_quick_restart("not-a-date") is False
    # Z 접미사(UTC) 포맷도 처리
    z_recent = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat().replace("+00:00", "Z")
    assert LiveBatchSttService._is_quick_restart(z_recent) is True


async def test_feed_segments_skips_backlog_on_quick_restart(svc, monkeypatch):
    """빠른 재시작 시 첫 폴링의 백로그 세그먼트를 ffmpeg에 먹이지 않는다 (중복 방지)."""
    ch = "ch8"
    svc._skip_backlog[ch] = True

    parser = MagicMock()
    parser.fetch_segments = AsyncMock(return_value=["seg1.ts", "seg2.ts"])
    parser.get_new_segments = MagicMock(return_value=["seg1.ts", "seg2.ts"])

    proc = MagicMock()
    proc.returncode = None
    proc.stdin = MagicMock()
    proc.stdin.drain = AsyncMock()

    http = MagicMock()
    http.get = AsyncMock()

    task = asyncio.create_task(svc._feed_segments(ch, "http://x/playlist.m3u8", parser, http, proc))
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # 백로그는 파서에 기록만 되고 다운로드/ffmpeg 공급은 안 됨
    http.get.assert_not_awaited()
    proc.stdin.write.assert_not_called()
    assert svc._skip_backlog[ch] is False  # 1회성 소진


# ─── start() 동시 호출 직렬화 (고아 세션 이중기동 방지) ────────────────────


async def test_concurrent_start_serialized(svc, monkeypatch):
    """동시 start()가 직렬화된다 — 이중 기동 시 고아 세션이 공유 오디오 시계를
    2배속으로 오염시키고 전사 비용이 2배가 되는 사고(2026-06-12) 회귀 방지."""
    overlap = {"current": 0, "max": 0}

    async def fake_locked(channel_id, stream_url, *, meeting_id=None):
        overlap["current"] += 1
        overlap["max"] = max(overlap["max"], overlap["current"])
        await asyncio.sleep(0.05)
        overlap["current"] -= 1

    monkeypatch.setattr(svc, "_start_locked", fake_locked)
    await asyncio.gather(
        svc.start("ch9", "http://example/p.m3u8"),
        svc.start("ch9", "http://example/p.m3u8"),
    )
    assert overlap["max"] == 1  # 절대 겹치지 않아야 한다


async def test_stale_generation_session_self_terminates(svc, monkeypatch):
    """세대 토큰이 바뀐 고아 세션은 _run을 다시 부르지 않고 즉시 종료한다."""
    ch = "ch9"
    svc._generation[ch] = 1

    ran = []

    async def fake_run(channel_id, stream_url, parser, gen=-1):
        ran.append(gen)
        # 첫 세션 실행 중 새 세션이 세대를 올린 상황을 재현
        svc._generation[ch] = 2

    monkeypatch.setattr(svc, "_run", fake_run)
    # 재연결 루프: 1회 실행 후 세대 불일치를 감지하고 sleep 없이 반환해야 한다
    await asyncio.wait_for(
        svc._run_with_reconnect(ch, "http://example/p.m3u8", MagicMock()),
        timeout=3.0,
    )
    assert ran == [1]  # 고아 부활(두 번째 _run 호출) 없음


# ─── 자막 생성 상태 방송 (서버 단일 진실) ─────────────────────────────────


def test_build_status_payload_states(svc, monkeypatch):
    """generating(최근 방출)/listening(스트림만 살아있음)/idle(정지) 판정."""
    import time as _time

    ch = "ch8"
    running_task = MagicMock()
    running_task.done.return_value = False
    svc._active_tasks = {ch: running_task}
    now = _time.monotonic()

    # generating: 5초 전 자막 방출
    svc._last_emit_wall[ch] = now - 5.0
    svc._last_pcm_time[ch] = now - 1.0
    svc._emit_gaps[ch] = [10.0, 12.0, 14.0]
    svc._audio_sec[ch] = 1234.56
    p = svc._build_status_payload(ch)
    assert p["state"] == "generating"
    assert 4.0 <= p["seconds_since_subtitle"] <= 6.0
    assert p["avg_interval"] == 12.0
    # 동기화 앵커: 자막 타임라인과 같은 시계의 현재 오디오 초
    assert p["audio_clock"] == 1234.6
    # 시청자 수 (WS 룸 연결 수 — 테스트 환경은 0)
    assert p["viewers"] == 0

    # listening: 방출은 오래됐지만 PCM은 살아 있음 (무음 발언 대기)
    svc._last_emit_wall[ch] = now - 60.0
    p = svc._build_status_payload(ch)
    assert p["state"] == "listening"

    # idle: PCM도 끊김 (정회/종료)
    svc._last_pcm_time[ch] = now - 30.0
    p = svc._build_status_payload(ch)
    assert p["state"] == "idle"

    # idle: STT 자체가 미가동
    svc._active_tasks = {}
    p = svc._build_status_payload(ch)
    assert p["state"] == "idle"


def test_reset_orphaned_processing():
    """기동 시 고아 'processing' 회의를 ended로 복구한다 (재시작 후 영구 '생성 중' 방지)."""
    from unittest.mock import MagicMock as _MM

    from app.services.vod_stt_service import reset_orphaned_processing

    sb = _MM()
    sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
        {"id": "m1"}, {"id": "m2"},
    ]
    assert reset_orphaned_processing(sb) == 2
    sb.table.assert_called_with("meetings")
    sb.table.return_value.update.assert_called_with({"status": "ended"})
    sb.table.return_value.update.return_value.eq.assert_called_with("status", "processing")


# ─── HLS 세그먼트 링 버퍼 (접속 즉시 20초 전에서 재생 시작하기 위한 보관분) ─────


def test_hls_ring_keeps_contiguous_segments_and_serves_window(svc: LiveBatchSttService):
    for seq in range(10, 15):
        svc._remember_segment("ch7", seq, 2.0, f"https://cdn/x_{seq}.ts", b"\x47" * 3)
    _, _, entries = svc.get_hls_window("ch7")
    assert [e[0] for e in entries] == [10, 11, 12, 13, 14]
    assert svc.get_hls_segment("ch7", 12) == b"\x47" * 3
    assert svc.get_hls_segment("ch7", 99) is None
    assert svc.get_hls_window("chX") == (None, None, [])


def test_hls_ring_resets_on_sequence_break(svc: LiveBatchSttService):
    """Wowza 재시작으로 chunklist 가 바뀌면 seq 가 끊긴다 — 불연속 재생목록을 만들지 않게 비운다."""
    for seq in (10, 11, 12):
        svc._remember_segment("ch7", seq, 2.0, "u", b"a")
    svc._remember_segment("ch7", 500, 2.0, "u", b"b")
    _, _, entries = svc.get_hls_window("ch7")
    assert [e[0] for e in entries] == [500]


def test_hls_ring_is_bounded(svc: LiveBatchSttService):
    for seq in range(0, 100):
        svc._remember_segment("ch7", seq, 2.0, "u", b"a")
    _, _, entries = svc.get_hls_window("ch7")
    assert len(entries) == lb.HLS_RING_SEGMENTS
    assert entries[-1][0] == 99


async def test_feed_segments_stamps_each_segment_with_its_audio_clock(svc):
    """보관 세그먼트마다 '첫 음성의 자막 시계' 를 싣는다 (재생목록 PDT 가 된다).
    AAC 프레임을 못 세는 내용(TS 아님)이면 EXTINF 길이로 더한다."""
    ch = "ch8"
    svc._fed_clock[ch] = 100.0
    parser = MagicMock()
    parser.fetch_segments = AsyncMock(return_value=["s1.ts", "s2.ts"])
    parser.get_new_segments = MagicMock(return_value=["s1.ts", "s2.ts"])
    parser.entries = {"s1.ts": (7, 2.0), "s2.ts": (8, 1.5)}
    proc = MagicMock()
    proc.returncode = None
    proc.stdin.drain = AsyncMock()
    http = MagicMock()
    http.get = AsyncMock(return_value=MagicMock(content=b"not-ts"))

    task = asyncio.create_task(svc._feed_segments(ch, "http://x/playlist.m3u8", parser, http, proc))
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    _, _, entries = svc.get_hls_window(ch)
    assert [(e[0], e[3]) for e in entries] == [(7, 100.0), (8, 102.0)]
    assert svc._fed_clock[ch] == 103.5
    # 엣지 벽시계 = 이 폴링에서 새 세그먼트를 본 순간 (edge_lag 계측의 기준, 2026-09-14) — _fed_clock 과 같은 스냅숏
    import time as _time
    assert 0.0 <= _time.monotonic() - svc._edge_wall[ch] < 1.0
    # 디코더가 아직 아무것도 안 내놓았으면 edge_lag = (fed − audio) + 경과 ≈ 3.5 + 0.1
    svc._audio_sec[ch] = 100.0
    assert 3.5 <= svc._edge_lag_now(ch) < 4.5
