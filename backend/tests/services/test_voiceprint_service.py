"""VoiceprintService 단위 테스트 — 실명 화자 식별 등록/선택."""

import io
import wave
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import voiceprint_service as vp
from app.services.voiceprint_service import VoiceprintError, VoiceprintService


def _make_wav(seconds: float, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


# ─── 헬퍼 ────────────────────────────────────────────────────────────

def test_first_committee():
    assert vp._first_committee([{"name": "보건복지위원회", "role": "위원"}]) == "보건복지위원회"
    assert vp._first_committee([{"role": "위원"}]) is None
    assert vp._first_committee([]) is None
    assert vp._first_committee(None) is None
    assert vp._first_committee("그냥문자열") is None


def test_wav_duration_ms():
    assert abs(vp._wav_duration_ms(_make_wav(3.0)) - 3000) < 50
    assert vp._wav_duration_ms(b"not a wav") == 0


# ─── 가짜 Supabase ──────────────────────────────────────────────────

class _Q:
    def __init__(self, supa, table):
        self.supa, self.table = supa, table

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def insert(self, row):
        self.supa.inserts.append((self.table, row))
        return self

    def update(self, row):
        self.supa.updates.append((self.table, row))
        return self

    def delete(self):
        return self

    def execute(self):
        return SimpleNamespace(data=self.supa.data.get(self.table, []))


class _FakeSupa:
    def __init__(self, data):
        self.data = data
        self.inserts = []
        self.updates = []

    def table(self, name):
        return _Q(self, name)


# ─── get_known_speakers_for_meeting ─────────────────────────────────

def test_known_speakers_disabled(monkeypatch):
    monkeypatch.setattr(vp.settings, "diarize_known_speakers_enabled", False)
    svc = VoiceprintService()
    assert svc.get_known_speakers_for_meeting("m1") == []


def test_known_speakers_no_committee(monkeypatch):
    monkeypatch.setattr(vp.settings, "diarize_known_speakers_enabled", True)
    supa = _FakeSupa({"meetings": [{"committee": None, "channel_id": None}]})
    monkeypatch.setattr(vp, "get_supabase_client", lambda: supa)
    svc = VoiceprintService()
    assert svc.get_known_speakers_for_meeting("m1") == []


def test_known_speakers_returns_data_urls(monkeypatch):
    monkeypatch.setattr(vp.settings, "diarize_known_speakers_enabled", True)
    monkeypatch.setattr(vp.settings, "diarize_max_known_speakers", 4)
    supa = _FakeSupa({
        "meetings": [{"committee": "보건복지위원회", "channel_id": None}],
        "councilor_voiceprints": [
            {"councilor_name": "김민수", "sample_format": "audio/wav", "sample_b64": "QUJD"},
            {"councilor_name": "이영희", "sample_format": "audio/wav", "sample_b64": "WFla"},
        ],
    })
    monkeypatch.setattr(vp, "get_supabase_client", lambda: supa)
    svc = VoiceprintService()
    result = svc.get_known_speakers_for_meeting("m1")
    assert result == [
        ("김민수", "data:audio/wav;base64,QUJD"),
        ("이영희", "data:audio/wav;base64,WFla"),
    ]


# ─── enroll_from_bytes ──────────────────────────────────────────────

async def test_enroll_too_short(monkeypatch):
    monkeypatch.setattr(vp.settings, "voiceprint_min_seconds", 2.0)
    monkeypatch.setattr(vp, "_to_wav_16k_mono", AsyncMock(return_value=_make_wav(1.0)))
    supa = _FakeSupa({"councilors": [{"id": "c1", "name": "김민수", "committees": [{"name": "보건복지위원회"}]}]})
    monkeypatch.setattr(vp, "get_supabase_client", lambda: supa)
    svc = VoiceprintService()
    with pytest.raises(VoiceprintError):
        await svc.enroll_from_bytes("c1", b"rawaudio")
    assert supa.inserts == []  # 너무 짧으면 저장 안 함


async def test_enroll_success_inserts_base64(monkeypatch):
    monkeypatch.setattr(vp.settings, "voiceprint_min_seconds", 2.0)
    monkeypatch.setattr(vp.settings, "voiceprint_max_seconds", 10.0)
    monkeypatch.setattr(vp, "_to_wav_16k_mono", AsyncMock(return_value=_make_wav(5.0)))
    supa = _FakeSupa({
        "councilors": [{"id": "c1", "name": "김민수", "committees": [{"name": "보건복지위원회", "role": "위원"}]}],
        "councilor_voiceprints": [],  # 기존 없음 → insert 경로
    })
    monkeypatch.setattr(vp, "get_supabase_client", lambda: supa)
    svc = VoiceprintService()
    result = await svc.enroll_from_bytes("c1", b"rawaudio", source="upload")

    assert result["councilor_name"] == "김민수"
    assert result["committee"] == "보건복지위원회"
    assert abs(result["duration_ms"] - 5000) < 100
    assert len(supa.inserts) == 1
    table, row = supa.inserts[0]
    assert table == "councilor_voiceprints"
    assert row["councilor_id"] == "c1"
    assert row["councilor_name"] == "김민수"
    assert row["committee"] == "보건복지위원회"
    assert row["sample_b64"]  # base64 저장됨
    assert row["sample_format"] == "audio/wav"


async def test_enroll_unknown_councilor(monkeypatch):
    monkeypatch.setattr(vp, "_to_wav_16k_mono", AsyncMock(return_value=_make_wav(5.0)))
    supa = _FakeSupa({"councilors": []})  # 의원 없음
    monkeypatch.setattr(vp, "get_supabase_client", lambda: supa)
    svc = VoiceprintService()
    with pytest.raises(VoiceprintError):
        await svc.enroll_from_bytes("nope", b"rawaudio")
