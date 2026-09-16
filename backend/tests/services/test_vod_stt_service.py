"""VodSttService 단위 테스트 (OpenAI gpt-4o-transcribe-diarize 배치).

Deepgram 제거 후 OpenAI 배치 전사 경로 + 재사용 헬퍼(숫자변환/문장분리/병합/화자라벨)를 검증.
"""

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import vod_stt_service as vod
from app.services.vod_stt_service import (
    SttTaskStatus,
    VodSttService,
    _is_filler,
    _speaker_label,
    add_sentence_breaks,
    convert_korean_numerals,
)


# ─── 재사용 헬퍼 ──────────────────────────────────────────────────────

def test_is_filler_removes_backchannel_tokens():
    # 영어 추임새/백채널 → 필터
    for t in ["Mm.", "mm", "Yeah.", "yeah,", "Oh.", "ah", "Uh", "Um", "Hmm", "Mhm", "yeah", "Ohh"]:
        assert _is_filler(t), f"{t!r} should be filler"
    # 한글 hum → 필터
    for t in ["음", "음.", "흠", "으음"]:
        assert _is_filler(t), f"{t!r} should be filler"
    # 빈/공백/구두점만 → 필터
    for t in ["", "  ", "...", "?"]:
        assert _is_filler(t)


def test_is_filler_keeps_meaningful_text():
    # 의미 있는 짧은 한국어 답변/내용 → 보존
    for t in ["예", "네", "예.", "아니요", "동의합니다.", "1,500만 원", "2026년", "이상입니다."]:
        assert not _is_filler(t), f"{t!r} should be kept"


def test_speaker_label():
    assert _speaker_label("A") == "화자 1"
    assert _speaker_label("B") == "화자 2"
    assert _speaker_label(None) is None
    assert _speaker_label("") is None


def test_convert_korean_numerals():
    assert convert_korean_numerals("제삼백팔십칠회") == "제387회"
    assert convert_korean_numerals("삼백오십명") == "350명"
    assert "사과" in convert_korean_numerals("사과")  # 단독 글자(문맥 없음)는 변환 안 함


def test_convert_korean_numerals_preserves_money_amounts():
    """아라비아 숫자 + 단위("5,777억")는 변환하지 않아야 함 (예결위 금액 손상 방지).

    회귀 가드: 단위 글자(억/조/천만)는 한글 숫자 글자이기도 해서 과거 단독 단위를
    "100000000" 등으로 잘못 변환해 금액을 망가뜨렸다(예: "30억"→"30100000000").
    """
    # 단위-only(일~구 없음) 토큰은 그대로 유지
    assert convert_korean_numerals("기정액 40조 5,777억 원") == "기정액 40조 5,777억 원"
    assert convert_korean_numerals("총 8,793억 원을 감액") == "총 8,793억 원을 감액"
    assert convert_korean_numerals("30억 원 감액") == "30억 원 감액"
    assert convert_korean_numerals("1억 5천만 원") == "1억 5천만 원"
    assert convert_korean_numerals("1,424만 도민") == "1,424만 도민"
    # "100000000" 같은 손상 흔적이 절대 생기지 않아야 함
    assert "100000000" not in convert_korean_numerals(
        "1조 6,222억 원 증액된 41조 6,799억 원"
    )
    # 정당한 한글 숫자 변환은 계속 동작
    assert convert_korean_numerals("삼백팔십칠") == "387"
    assert convert_korean_numerals("제390회") == "제390회"


def test_add_sentence_breaks():
    out = add_sentence_breaks("회의를 시작하겠습니다 성원이 되었으므로")
    assert "시작하겠습니다.\n" in out


def test_merge_short_utterances_none_safe_confidence():
    subs = [
        {"meeting_id": "m", "text": "짧다", "start_time": 0.0, "end_time": 1.0, "speaker": "화자 1", "confidence": None},
        {"meeting_id": "m", "text": "이어지는 발언입니다", "start_time": 1.2, "end_time": 4.0, "speaker": "화자 1", "confidence": None},
    ]
    merged = VodSttService._merge_short_utterances(subs)
    assert len(merged) == 1  # 같은 화자 + 짧은 앞 자막 → 병합
    assert merged[0]["confidence"] is None  # None-safe (산술 오류 없음)
    assert merged[0]["end_time"] == 4.0


def test_merge_keeps_different_speakers():
    subs = [
        {"meeting_id": "m", "text": "충분히 긴 첫 번째 화자의 발언입니다", "start_time": 0.0, "end_time": 5.0, "speaker": "화자 1", "confidence": None},
        {"meeting_id": "m", "text": "충분히 긴 두 번째 화자의 발언입니다", "start_time": 5.5, "end_time": 9.0, "speaker": "화자 2", "confidence": None},
    ]
    merged = VodSttService._merge_short_utterances(subs)
    assert len(merged) == 2  # 화자 다르면 병합 안 함


# ─── OpenAI 배치 전사 파싱 ────────────────────────────────────────────

async def test_transcribe_openai_parses_segments(monkeypatch):
    monkeypatch.setattr(vod.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(vod.settings, "vod_diarize_enable_second_pass", False)
    monkeypatch.setattr(vod.settings, "vod_use_diarization", True)

    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.write(b"\x00" * 100)
    tmp.close()
    chunk_path = Path(tmp.name)
    monkeypatch.setattr(
        VodSttService, "_extract_audio_chunks",
        AsyncMock(return_value=[(chunk_path, 0.0, 120.0)]),
    )

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create = AsyncMock(return_value=SimpleNamespace(
        duration=8.0,
        segments=[
            {"start": 1.0, "end": 4.0, "speaker": "A", "text": "안녕하세요 위원장입니다"},
            {"start": 5.0, "end": 8.0, "speaker": "B", "text": "네 말씀하십시오"},
        ],
    ))
    monkeypatch.setattr(vod, "AsyncOpenAI", lambda api_key=None: mock_client)

    svc = VodSttService()
    task = SttTaskStatus(task_id="t", meeting_id="m1")
    subs, duration = await svc._transcribe_openai("m1", Path("dummy.mp4"), task, dictionary=None)

    assert duration == 8.0
    assert len(subs) == 2
    assert subs[0]["speaker"] == "화자 1"
    assert subs[0]["start_time"] == 1.0
    assert "안녕하세요" in subs[0]["text"]
    assert subs[1]["speaker"] == "화자 2"
    _, kwargs = mock_client.audio.transcriptions.create.call_args
    assert kwargs["model"] == vod.settings.diarize_model
    assert kwargs["response_format"] == "diarized_json"
    assert kwargs["language"] == "ko"
    assert not chunk_path.exists()  # 처리 후 청크 삭제됨


async def test_transcribe_openai_all_chunks_fail_raises(monkeypatch):
    """모든 청크 전사 실패 시 조용히 빈 자막을 반환하지 않고 예외를 낸다.

    회귀 가드: 과거엔 청크 실패를 'except: continue'로 조용히 건너뛰어, 큰 청크가 전부
    타임아웃되면 회의가 status=ended인데 자막만 비거나 일부만 남는 문제가 있었다.
    """
    monkeypatch.setattr(vod.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(vod.settings, "vod_diarize_enable_second_pass", False)
    monkeypatch.setattr(vod.settings, "vod_use_diarization", True)
    monkeypatch.setattr(vod, "_CHUNK_RETRIES", 0)  # 재시도 백오프 없이 빠르게

    paths = []
    for _ in range(2):
        t = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        t.write(b"\x00" * 100)
        t.close()
        paths.append(Path(t.name))
    monkeypatch.setattr(
        VodSttService, "_extract_audio_chunks",
        AsyncMock(return_value=[(p, i * 120.0, 120.0) for i, p in enumerate(paths)]),
    )

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create = AsyncMock(side_effect=RuntimeError("timeout"))
    monkeypatch.setattr(vod, "AsyncOpenAI", lambda api_key=None: mock_client)

    svc = VodSttService()
    task = SttTaskStatus(task_id="t", meeting_id="m1")
    with pytest.raises(Exception, match="모든 청크"):
        await svc._transcribe_openai("m1", Path("dummy.mp4"), task, dictionary=None)
    # 실패해도 청크 임시파일은 정리됨
    assert all(not p.exists() for p in paths)


async def test_transcribe_openai_partial_failure_keeps_successful(monkeypatch):
    """일부 청크만 실패하면 성공한 청크 자막은 유지하고 task.message에 부분완료 표시."""
    monkeypatch.setattr(vod.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(vod.settings, "vod_diarize_enable_second_pass", False)
    monkeypatch.setattr(vod.settings, "vod_use_diarization", True)
    monkeypatch.setattr(vod, "_CHUNK_RETRIES", 0)

    paths = []
    for _ in range(2):
        t = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        t.write(b"\x00" * 100)
        t.close()
        paths.append(Path(t.name))
    monkeypatch.setattr(
        VodSttService, "_extract_audio_chunks",
        AsyncMock(return_value=[(p, i * 600.0, 600.0) for i, p in enumerate(paths)]),
    )

    good = SimpleNamespace(
        duration=8.0,
        segments=[{"start": 1.0, "end": 5.0, "speaker": "A", "text": "충분히 긴 정상 청크의 발언입니다"}],
    )

    calls = {"n": 0}

    async def _create(**kwargs):
        calls["n"] += 1
        # 첫 호출 성공, 둘째 호출 실패 (동시 실행이라 순서 보장 X → 호출 카운트로 분기)
        if calls["n"] == 1:
            return good
        raise RuntimeError("timeout")

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create = AsyncMock(side_effect=_create)
    monkeypatch.setattr(vod, "AsyncOpenAI", lambda api_key=None: mock_client)

    svc = VodSttService()
    task = SttTaskStatus(task_id="t", meeting_id="m1")
    subs, _ = await svc._transcribe_openai("m1", Path("dummy.mp4"), task, dictionary=None)

    assert len(subs) == 1  # 성공한 1개 청크의 자막만
    assert "부분 완료" in task.message
    assert all(not p.exists() for p in paths)


async def test_transcribe_openai_applies_chunk_offset(monkeypatch):
    """두 번째 청크의 타임스탬프는 청크별 실제 오프셋이 더해진다."""
    monkeypatch.setattr(vod.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(vod.settings, "vod_diarize_enable_second_pass", False)
    monkeypatch.setattr(vod.settings, "vod_use_diarization", True)

    paths = []
    for _ in range(2):
        t = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        t.write(b"\x00" * 100)
        t.close()
        paths.append(Path(t.name))
    # 청크0 오프셋 0, 청크1 오프셋 2400 (가변길이 청크의 실제 오프셋을 직접 지정)
    monkeypatch.setattr(
        VodSttService, "_extract_audio_chunks",
        AsyncMock(return_value=[(paths[0], 0.0, 2400.0), (paths[1], 2400.0, 2400.0)]),
    )

    mock_client = MagicMock()
    # 15자 이상 텍스트 → _merge_short_utterances의 짧은-자막 병합에 걸리지 않음
    mock_client.audio.transcriptions.create = AsyncMock(return_value=SimpleNamespace(
        duration=10.0,
        segments=[{"start": 2.0, "end": 6.0, "speaker": "A", "text": "이번 안건에 대한 상세한 설명을 드리겠습니다"}],
    ))
    monkeypatch.setattr(vod, "AsyncOpenAI", lambda api_key=None: mock_client)

    svc = VodSttService()
    task = SttTaskStatus(task_id="t", meeting_id="m1")
    subs, _ = await svc._transcribe_openai("m1", Path("dummy.mp4"), task, dictionary=None)

    starts = sorted(s["start_time"] for s in subs)
    assert len(starts) == 2
    assert starts[0] == 2.0           # 청크0: offset 0
    assert starts[1] == 2400 + 2.0    # 청크1: offset 2400


# ─── 라이브 교차참조 (시간정렬 prompt 힌트) ───────────────────────────────
def test_chunk_live_context_overlapping_only():
    """청크 시간창과 겹치는 라이브 자막만 힌트로 포함된다."""
    live = [
        {"start_time": 0.0, "end_time": 5.0, "text": "연회비로 내는 예산"},
        {"start_time": 100.0, "end_time": 105.0, "text": "다른 구간 발언"},
    ]
    # 청크[0,30] → 첫 자막만 겹침
    ctx = VodSttService._chunk_live_context(live, 0.0, 30.0)
    assert "연회비로 내는 예산" in ctx
    assert "다른 구간 발언" not in ctx
    # 청크[90,120] → 둘째 자막만
    ctx2 = VodSttService._chunk_live_context(live, 90.0, 120.0)
    assert "다른 구간 발언" in ctx2
    assert "연회비" not in ctx2


def test_chunk_live_context_empty_when_no_live():
    """라이브 자막이 없으면 빈 문자열(기존 동작 무해 유지)."""
    assert VodSttService._chunk_live_context([], 0.0, 100.0) == ""


def test_chunk_live_context_caps_length():
    """과도한 라이브 텍스트는 max_chars로 잘려 prompt 토큰 폭주를 막는다."""
    live = [{"start_time": float(i), "end_time": float(i) + 1, "text": "가" * 50}
            for i in range(20)]
    ctx = VodSttService._chunk_live_context(live, 0.0, 100.0, max_chars=120)
    # 헤더 + 일부만 (전체 1000자가 아니라 캡 근처)
    assert len(ctx) < 300


# ─── 화자구분 2-패스: 세그먼트→자막 화자 매칭 ─────────────────────────────
def test_assign_speakers_by_time_overlap():
    """diarize 세그먼트와 시간겹침이 가장 큰 화자가 자막에 부여된다(텍스트 불변)."""
    subs = [
        {"text": "안녕하십니까", "start_time": 0.0, "end_time": 4.0, "speaker": None},
        {"text": "네 답변드리겠습니다", "start_time": 5.0, "end_time": 9.0, "speaker": None},
    ]
    segments = [
        {"start": 0.0, "end": 4.5, "speaker": "이제영"},
        {"start": 4.5, "end": 10.0, "speaker": "화자 2"},
    ]
    VodSttService._assign_speakers(subs, segments)
    assert subs[0]["speaker"] == "이제영"
    assert subs[1]["speaker"] == "화자 2"
    # 텍스트는 그대로
    assert subs[0]["text"] == "안녕하십니까"


def test_assign_speakers_no_segments_is_noop():
    """화자 세그먼트가 없으면(diarize 실패 등) 화자 미부여 — 본문 자막은 유지."""
    subs = [{"text": "발언", "start_time": 0.0, "end_time": 3.0, "speaker": None}]
    VodSttService._assign_speakers(subs, [])
    assert subs[0]["speaker"] is None


def test_assign_speakers_no_overlap_leaves_none():
    """겹치는 세그먼트가 없으면 화자 미부여(엉뚱한 화자로 라벨 안 함)."""
    subs = [{"text": "발언", "start_time": 0.0, "end_time": 3.0, "speaker": None}]
    segments = [{"start": 100.0, "end": 105.0, "speaker": "이제영"}]
    VodSttService._assign_speakers(subs, segments)
    assert subs[0]["speaker"] is None


# ─── whisper 모드: 실제 세그먼트 타임스탬프 ───────────────────────────────
async def test_transcribe_openai_whisper_uses_real_segment_times(monkeypatch):
    """whisper 모드는 세그먼트의 '실제 시각'(offset 가산)을 그대로 쓴다(글자수비례 X)."""
    monkeypatch.setattr(vod.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(vod.settings, "vod_diarize_enable_second_pass", False)
    monkeypatch.setattr(vod.settings, "vod_use_diarization", False)
    monkeypatch.setattr(vod.settings, "vod_use_whisper", True)
    monkeypatch.setattr(vod, "_CHUNK_RETRIES", 0)

    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.write(b"\x00" * 100)
    tmp.close()
    chunk_path = Path(tmp.name)
    # 청크 오프셋 100초
    monkeypatch.setattr(
        VodSttService, "_extract_audio_chunks",
        AsyncMock(return_value=[(chunk_path, 100.0, 180.0)]),
    )

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create = AsyncMock(return_value=SimpleNamespace(
        duration=180.0,
        segments=[
            {"start": 5.0, "end": 12.0, "text": "충분히 긴 첫 번째 세그먼트 발언입니다"},
            {"start": 40.0, "end": 48.0, "text": "충분히 긴 두 번째 세그먼트 발언입니다"},
        ],
        text="무시되는 통짜 텍스트",
    ))
    monkeypatch.setattr(vod, "AsyncOpenAI", lambda api_key=None: mock_client)

    svc = VodSttService()
    task = SttTaskStatus(task_id="t", meeting_id="m1")
    subs, _ = await svc._transcribe_openai("m1", Path("dummy.mp4"), task, dictionary=None)

    starts = sorted(s["start_time"] for s in subs)
    assert 105.0 in starts   # offset 100 + 세그먼트 5
    assert 140.0 in starts   # offset 100 + 세그먼트 40
    _, kwargs = mock_client.audio.transcriptions.create.call_args
    assert kwargs["model"] == "whisper-1"
    assert kwargs["response_format"] == "verbose_json"
