"""DiarizeService 단위 테스트 (경로 B).

실제 OpenAI API 없이 화자 라벨 매핑·WAV 래핑·세그먼트 매칭을 검증한다.
"""

import wave
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import diarize_service as ds
from app.services.diarize_service import DiarizeService, _ChannelBuffer


# ─── 헬퍼 함수 ───────────────────────────────────────────────────────────

def test_speaker_label_letters_to_numbers():
    assert ds._speaker_label("A") == "화자 1"
    assert ds._speaker_label("B") == "화자 2"
    assert ds._speaker_label("Z") == "화자 26"
    assert ds._speaker_label("a") == "화자 1"  # 소문자도 정규화


def test_speaker_label_known_names_passthrough():
    assert ds._speaker_label("위원장") == "위원장"
    assert ds._speaker_label("chair") == "chair"


def test_speaker_label_empty_or_none():
    assert ds._speaker_label(None) is None
    assert ds._speaker_label("") is None
    assert ds._speaker_label("   ") is None


def test_pcm_to_wav_roundtrip():
    pcm = b"\x00\x01" * 100  # 100 frames (mono 16-bit)
    wav = ds._pcm_to_wav(pcm, 24000)
    assert wav[:4] == b"RIFF"
    with wave.open(BytesIO(wav), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 24000
        assert wf.getnframes() == 100


def test_attr_reads_dict_and_object():
    assert ds._attr({"x": 5}, "x") == 5
    assert ds._attr(SimpleNamespace(x=7), "x") == 7
    assert ds._attr({"x": 5}, "missing", "d") == "d"
    assert ds._attr(None, "x", "d") == "d"


# ─── ingest_pcm 버퍼링/flush 트리거 ─────────────────────────────────────

def test_ingest_pcm_triggers_flush_when_full(monkeypatch):
    monkeypatch.setattr(ds.settings, "diarize_buffer_seconds", 0.1)
    monkeypatch.setattr(ds.settings, "openai_realtime_audio_rate", 24000)
    svc = DiarizeService()
    svc._enabled = True
    flushed: list[str] = []
    monkeypatch.setattr(svc, "_flush", lambda cid: flushed.append(cid))

    # 0.1초 = 24000*2*0.1 = 4800 bytes 임계. 그 이상을 한 번에 넣으면 flush 트리거.
    svc.ingest_pcm("ch8", "m1", b"\x00" * 5000, 0.0)
    assert flushed == ["ch8"]


def test_ingest_pcm_no_flush_below_threshold(monkeypatch):
    monkeypatch.setattr(ds.settings, "diarize_buffer_seconds", 5.0)
    monkeypatch.setattr(ds.settings, "openai_realtime_audio_rate", 24000)
    svc = DiarizeService()
    svc._enabled = True
    flushed: list[str] = []
    monkeypatch.setattr(svc, "_flush", lambda cid: flushed.append(cid))

    svc.ingest_pcm("ch8", "m1", b"\x00" * 5000, 0.0)  # 0.1초 << 5초
    assert flushed == []
    assert "ch8" in svc._buffers


def test_ingest_pcm_disabled_noop():
    svc = DiarizeService()
    svc._enabled = False
    svc.ingest_pcm("ch8", "m1", b"\x00" * 10000, 0.0)
    assert "ch8" not in svc._buffers


# ─── _apply_segments 매칭 + speaker 부여 ────────────────────────────────

class _ChainMock:
    """Supabase 체이닝(.table().select().eq().gte().lte().order().execute()
    + .table().update().eq().execute())을 흉내내고 update payload를 기록."""

    def __init__(self, data):
        self._data = data
        self.updates: list[dict] = []

    def table(self, *a, **k):
        return self

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def lte(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def update(self, payload):
        self.updates.append(payload)
        return self

    def execute(self):
        return SimpleNamespace(data=self._data)


async def test_apply_segments_assigns_speaker(monkeypatch):
    monkeypatch.setattr(ds.settings, "openai_realtime_audio_rate", 24000)
    monkeypatch.setattr(ds.settings, "diarize_match_tolerance_seconds", 2.0)

    candidate = {"id": "sub1", "start_time": 1.0, "end_time": 4.0, "speaker": None}
    chain = _ChainMock([candidate])
    monkeypatch.setattr(ds, "get_supabase_client", lambda: chain)

    mock_manager = MagicMock()
    mock_manager.broadcast_corrected_subtitle = AsyncMock()
    monkeypatch.setattr(ds, "manager", mock_manager)

    svc = DiarizeService()
    # 4초치 PCM 버퍼 (window_end 계산용)
    buf = _ChannelBuffer(channel_id="ch8", meeting_id="m1", chunk_start_offset=0.0)
    buf.data = bytearray(b"\x00" * (24000 * 2 * 4))

    # diarize 세그먼트: 화자 A, 0.5~3.5초 → 자막[1.0~4.0]과 2.5초 겹침
    segments = [{"start": 0.5, "end": 3.5, "speaker": "A", "text": "안건을 상정합니다"}]

    await svc._apply_segments(buf, segments)

    # DB에 speaker 갱신
    assert chain.updates == [{"speaker": "화자 1"}]
    # WebSocket으로 speaker 브로드캐스트 (텍스트는 건드리지 않음)
    mock_manager.broadcast_corrected_subtitle.assert_awaited_once()
    room, payload = mock_manager.broadcast_corrected_subtitle.await_args.args
    assert room == "ch8"
    assert payload["id"] == "sub1"
    assert payload["speaker"] == "화자 1"
    assert payload["source"] == "diarize"
    assert "corrected_text" not in payload  # 텍스트 미변경


async def test_known_speakers_passed_to_diarize_api(monkeypatch):
    """등록된 의원 목소리가 있으면 diarize 호출에 extra_body(known_speaker_*)가 실린다."""
    monkeypatch.setattr(ds.settings, "openai_realtime_audio_rate", 24000)

    # voiceprint_service가 회의에 등록된 화자 1명을 반환하도록
    monkeypatch.setattr(
        ds.voiceprint_service, "get_known_speakers_for_meeting",
        lambda mid: [("김민수", "data:audio/wav;base64,QUJD")],
    )

    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(segments=[])  # 빈 세그먼트 → _apply_segments 스킵

    svc = DiarizeService()
    client = MagicMock()
    client.audio.transcriptions.create = fake_create
    svc._client = client

    buf = _ChannelBuffer(channel_id="ch8", meeting_id="m1", chunk_start_offset=0.0)
    buf.data = bytearray(b"\x00" * (24000 * 2 * 3))  # 3초
    await svc._transcribe_and_apply(buf)

    assert "extra_body" in captured
    assert captured["extra_body"]["known_speaker_names"] == ["김민수"]
    assert captured["extra_body"]["known_speaker_references"] == ["data:audio/wav;base64,QUJD"]
    # cue tracker 상태가 없으므로 위원회 정적 폴백 경로 캐시에 저장됨
    assert svc._static_known["ch8"] == [("김민수", "data:audio/wav;base64,QUJD")]


def test_dynamic_known_speakers_from_cue(monkeypatch):
    """cue tracker가 현재 known councilor를 주면 voiceprint를 동적 조립한다."""
    monkeypatch.setattr(ds.speaker_cue_tracker, "current_known_councilor_ids", lambda ch: ["c0", "c1"])
    vp = {"c0": ("정몽주", "data:audio/wav;base64,Q0hBSVI="), "c1": ("김민수", "data:audio/wav;base64,QUJD")}
    monkeypatch.setattr(ds.voiceprint_service, "get_voiceprint_for_councilor", lambda cid: vp.get(cid))
    svc = DiarizeService()
    out = svc._get_known_speakers("ch8", "m1")
    assert out == [("정몽주", "data:audio/wav;base64,Q0hBSVI="), ("김민수", "data:audio/wav;base64,QUJD")]
    # 두 번째 호출은 캐시 사용 (get_voiceprint 재호출 없이도 동일)
    assert svc._vp_cache["c1"] == ("김민수", "data:audio/wav;base64,QUJD")


async def test_official_relabel_in_questioning_turn(monkeypatch):
    """위원 질의 턴에서 익명(A) 화자는 집행부 라벨로 보정된다."""
    monkeypatch.setattr(ds.settings, "openai_realtime_audio_rate", 24000)
    monkeypatch.setattr(ds.settings, "diarize_match_tolerance_seconds", 2.0)
    monkeypatch.setattr(ds.speaker_cue_tracker, "in_questioning_turn", lambda ch: True)
    monkeypatch.setattr(ds.speaker_cue_tracker, "current_official_label", lambda ch: "집행부 보건복지국장")

    candidate = {"id": "sub1", "start_time": 1.0, "end_time": 4.0, "speaker": None}
    chain = _ChainMock([candidate])
    monkeypatch.setattr(ds, "get_supabase_client", lambda: chain)
    mock_manager = MagicMock()
    mock_manager.broadcast_corrected_subtitle = AsyncMock()
    monkeypatch.setattr(ds, "manager", mock_manager)

    svc = DiarizeService()
    buf = _ChannelBuffer(channel_id="ch8", meeting_id="m1", chunk_start_offset=0.0)
    buf.data = bytearray(b"\x00" * (24000 * 2 * 4))
    segments = [{"start": 0.5, "end": 3.5, "speaker": "A", "text": "답변 드리겠습니다"}]  # 익명 A

    await svc._apply_segments(buf, segments)
    assert chain.updates == [{"speaker": "집행부 보건복지국장"}]


async def test_no_known_speakers_no_extra_body(monkeypatch):
    """등록된 화자가 없으면 extra_body 없이 호출한다(순번 라벨 폴백)."""
    monkeypatch.setattr(ds.settings, "openai_realtime_audio_rate", 24000)
    monkeypatch.setattr(ds.voiceprint_service, "get_known_speakers_for_meeting", lambda mid: [])

    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(segments=[])

    svc = DiarizeService()
    client = MagicMock()
    client.audio.transcriptions.create = fake_create
    svc._client = client
    buf = _ChannelBuffer(channel_id="ch8", meeting_id="m1", chunk_start_offset=0.0)
    buf.data = bytearray(b"\x00" * (24000 * 2 * 3))
    await svc._transcribe_and_apply(buf)

    assert "extra_body" not in captured


async def test_apply_segments_skips_when_speaker_unchanged(monkeypatch):
    monkeypatch.setattr(ds.settings, "openai_realtime_audio_rate", 24000)
    monkeypatch.setattr(ds.settings, "diarize_match_tolerance_seconds", 2.0)

    candidate = {"id": "sub1", "start_time": 1.0, "end_time": 4.0, "speaker": "화자 1"}
    chain = _ChainMock([candidate])
    monkeypatch.setattr(ds, "get_supabase_client", lambda: chain)
    mock_manager = MagicMock()
    mock_manager.broadcast_corrected_subtitle = AsyncMock()
    monkeypatch.setattr(ds, "manager", mock_manager)

    svc = DiarizeService()
    buf = _ChannelBuffer(channel_id="ch8", meeting_id="m1", chunk_start_offset=0.0)
    buf.data = bytearray(b"\x00" * (24000 * 2 * 4))
    segments = [{"start": 0.5, "end": 3.5, "speaker": "A", "text": "x"}]

    await svc._apply_segments(buf, segments)
    # 이미 "화자 1"이므로 갱신/브로드캐스트 없음
    assert chain.updates == []
    mock_manager.broadcast_corrected_subtitle.assert_not_awaited()
