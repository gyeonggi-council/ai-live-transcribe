"""OpenAiRealtimeSttService 단위 테스트 (경로 A).

실제 WS/ffmpeg 없이 세션 설정·자막 방출·이벤트 분기를 검증한다.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import openai_realtime_stt as rt
from app.services.openai_realtime_stt import OpenAiRealtimeSttService


class _FakeWS:
    """async for 로 미리 정의된 메시지를 흘려보내는 가짜 WebSocket."""

    def __init__(self, messages: list[str]):
        self._messages = messages

    def __aiter__(self):
        async def gen():
            for m in self._messages:
                yield m
        return gen()


@pytest.fixture
def svc() -> OpenAiRealtimeSttService:
    return OpenAiRealtimeSttService()


def test_build_session_update_manual_commit(svc, monkeypatch):
    """turn_detection='none' → null + transcription 세션 구조."""
    monkeypatch.setattr(rt.settings, "openai_realtime_turn_detection", "none")
    monkeypatch.setattr(rt.settings, "openai_realtime_stt_model", "gpt-realtime-whisper")
    monkeypatch.setattr(rt.settings, "openai_realtime_audio_rate", 24000)

    msg = svc._build_session_update()
    assert msg["type"] == "session.update"
    session = msg["session"]
    assert session["type"] == "transcription"
    audio_in = session["audio"]["input"]
    assert audio_in["format"] == {"type": "audio/pcm", "rate": 24000}
    assert audio_in["transcription"] == {"model": "gpt-realtime-whisper", "language": "ko"}
    assert audio_in["turn_detection"] is None


def test_build_session_update_server_vad(svc, monkeypatch):
    """turn_detection='server_vad' → server_vad 객체."""
    monkeypatch.setattr(rt.settings, "openai_realtime_turn_detection", "server_vad")
    monkeypatch.setattr(rt.settings, "openai_realtime_stt_model", "gpt-4o-transcribe")

    msg = svc._build_session_update()
    td = msg["session"]["audio"]["input"]["turn_detection"]
    assert td["type"] == "server_vad"
    assert "threshold" in td and "silence_duration_ms" in td


async def test_emit_subtitle_broadcasts_with_no_speaker(svc, monkeypatch):
    """완료 전사 → subtitle_created broadcast (speaker=None) + DB persist."""
    mock_manager = MagicMock()
    mock_manager.broadcast_subtitle = AsyncMock()
    monkeypatch.setattr(rt, "manager", mock_manager)

    mock_supabase = MagicMock()
    monkeypatch.setattr(rt, "get_supabase_client", lambda: mock_supabase)

    ch = "ch8"
    meeting_uuid = "11111111-1111-1111-1111-111111111111"
    svc._meeting_ids[ch] = meeting_uuid

    # start/end는 commit 윈도우에서 산출되어 _emit_subtitle에 명시적으로 전달됨
    await svc._emit_subtitle(ch, "안녕하세요 위원장입니다", 4.0, 10.0)
    await asyncio.sleep(0.05)  # fire-and-forget persist 태스크 실행 대기

    mock_manager.broadcast_subtitle.assert_awaited_once()
    room, payload = mock_manager.broadcast_subtitle.await_args.args
    assert room == ch
    sub = payload["subtitle"]
    assert sub["speaker"] is None
    assert sub["meeting_id"] == meeting_uuid
    assert sub["start_time"] == 4.0
    assert sub["end_time"] == 10.0
    assert "안녕하세요" in sub["text"]
    # DB persist 호출됨 (meeting_id != channel_id 이므로)
    assert mock_supabase.table.called


async def test_receive_transcripts_routes_delta_and_completed(svc, monkeypatch):
    """delta → interim broadcast, completed → subtitle_created."""
    mock_manager = MagicMock()
    mock_manager.broadcast_interim_subtitle = AsyncMock()
    mock_manager.broadcast_subtitle = AsyncMock()
    monkeypatch.setattr(rt, "manager", mock_manager)
    monkeypatch.setattr(rt, "get_supabase_client", lambda: MagicMock())

    ch = "ch8"
    svc._meeting_ids[ch] = ch  # 채널 ID = meeting → persist 스킵
    svc._audio_sec[ch] = 6.0
    svc._last_end_sec[ch] = 0.0

    messages = [
        json.dumps({
            "type": "conversation.item.input_audio_transcription.delta",
            "delta": "의사일정",
        }),
        json.dumps({
            "type": "conversation.item.input_audio_transcription.completed",
            "transcript": "의사일정 제1항을 상정합니다.",
        }),
        json.dumps({"type": "session.updated"}),
    ]
    await svc._receive_transcripts(ch, _FakeWS(messages))
    await asyncio.sleep(0.01)

    mock_manager.broadcast_interim_subtitle.assert_awaited()
    interim_room, interim_payload = mock_manager.broadcast_interim_subtitle.await_args.args
    assert interim_room == ch
    assert "의사일정" in interim_payload["text"]

    mock_manager.broadcast_subtitle.assert_awaited_once()
    _, created_payload = mock_manager.broadcast_subtitle.await_args.args
    assert "상정합니다" in created_payload["subtitle"]["text"]
    assert created_payload["subtitle"]["speaker"] is None


def test_active_channels_property(svc):
    """active_channels는 실행 중(미완료) 태스크의 채널만 반환."""
    done_task = MagicMock()
    done_task.done.return_value = True
    running_task = MagicMock()
    running_task.done.return_value = False
    svc._active_tasks = {"ch1": done_task, "ch2": running_task}
    assert svc.active_channels == ["ch2"]


def test_build_session_update_omits_prompt_for_whisper_model(svc, monkeypatch):
    """gpt-realtime-whisper 는 transcription.prompt 미지원 → 글로서리가 있어도 prompt 키 제외.

    (prompt를 넣으면 OpenAI가 invalid_value로 세션을 끊어 무한 재연결 → 자막 0건이 되는 회귀 방지)
    """
    import app.services.openai_realtime_stt as rt
    monkeypatch.setattr(rt.settings, "openai_realtime_turn_detection", "none")
    monkeypatch.setattr(rt.settings, "openai_realtime_stt_model", "gpt-realtime-whisper")
    svc._glossary_prompts["ch8"] = "표기 일치: 산회, 김영수"
    msg = svc._build_session_update("ch8")
    transcription = msg["session"]["audio"]["input"]["transcription"]
    assert "prompt" not in transcription


def test_build_session_update_includes_prompt_for_supporting_model(svc, monkeypatch):
    """prompt를 지원하는 모델(gpt-4o-transcribe 계열)에서는 글로서리 prompt가 포함된다."""
    import app.services.openai_realtime_stt as rt
    monkeypatch.setattr(rt.settings, "openai_realtime_turn_detection", "none")
    monkeypatch.setattr(rt.settings, "openai_realtime_stt_model", "gpt-4o-transcribe")
    svc._glossary_prompts["ch8"] = "표기 일치: 산회, 김영수"
    msg = svc._build_session_update("ch8")
    transcription = msg["session"]["audio"]["input"]["transcription"]
    assert transcription.get("prompt") == "표기 일치: 산회, 김영수"


def test_build_session_update_no_prompt_when_empty(svc, monkeypatch):
    """채널 글로서리가 비어 있으면 transcription 세션에 prompt 키가 없다."""
    import app.services.openai_realtime_stt as rt
    monkeypatch.setattr(rt.settings, "openai_realtime_turn_detection", "none")
    svc._glossary_prompts["ch8"] = ""
    msg = svc._build_session_update("ch8")
    transcription = msg["session"]["audio"]["input"]["transcription"]
    assert "prompt" not in transcription
