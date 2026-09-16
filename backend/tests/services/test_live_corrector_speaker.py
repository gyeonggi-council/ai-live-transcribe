# -*- coding: utf-8 -*-
"""라이브 자막 화자 표시(live_corrector 화자 피기백) 테스트.

GPT 호출은 모킹 — v2 객체 스키마({"0":{"t","s"}}) 파싱, 레거시 문자열 스키마
하위호환, 화자 검증(명부 밖 'OO 위원' 거부 → 직전 화자 유지), prev_speaker
배치 간 연속성, speaker 포함 DB update/브로드캐스트를 검증한다.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.live_corrector import (
    LiveCorrector,
    _ChannelState,
    _Pending,
    _parse_corrections,
)


def _prepared(room_id: str = "ch1", roster_names: set[str] | None = None):
    """스피커 컨텍스트가 이미 로드된 LiveCorrector 준비 (lazy 로드 스킵)."""
    lc = LiveCorrector()
    lc._enabled = True
    st = lc._states.setdefault(room_id, _ChannelState())
    st.glossary_prompt = ""  # 글로서리 lazy 로드 스킵
    st.roster_block = "명부"  # None 아님 → 명부 lazy 로드 스킵
    st.staff_block = ""
    st.roster_names = set(roster_names if roster_names is not None else {"홍길동"})
    return lc, st


def _fake_manager():
    mgr = MagicMock()
    mgr.broadcast_corrected_subtitle = AsyncMock()
    mgr.broadcast_correction_failed = AsyncMock()
    return mgr


# ── 파서: v2 객체 스키마 + 레거시 하위호환 ─────────────────────────────
def test_parse_object_schema():
    out = _parse_corrections('{"0":{"t":"교정문","s":"홍길동 위원"}}', 1)
    assert out == {"0": {"t": "교정문", "s": "홍길동 위원"}}


def test_parse_legacy_string_schema_backcompat():
    # 레거시 dict-of-strings 응답도 그대로 수용 (방어적)
    assert _parse_corrections('{"0":"가","1":"나"}', 2) == {"0": "가", "1": "나"}


# ── 화자 검증: 명부 밖 'OO 위원' 거부 → 직전 화자 유지 ────────────────
@pytest.mark.asyncio
async def test_invalid_speaker_rejected_keeps_prev():
    lc, st = _prepared()
    batch = [_Pending("ch1", "m1", "s1", "발언 내용입니다")]
    # 명부({홍길동}) 밖 이름 + '위원' 호칭 → 거부되어야 함 (없는 위원 생성 금지)
    lc._call_gpt = AsyncMock(return_value={"0": {"t": "발언 내용입니다", "s": "김가짜 위원"}})

    with patch("app.services.live_corrector.manager", _fake_manager()) as mgr, \
         patch("app.services.live_corrector.get_supabase_client"):
        await lc._correct_and_apply("ch1", batch)

    assert st.prev_speaker == "위원장"  # 기본값 유지 (무효 화자로 갱신 안 됨)
    payload = mgr.broadcast_corrected_subtitle.await_args.args[1]
    assert payload["speaker"] == "위원장"  # 직전 화자로 폴백
    assert "corrected_text" not in payload  # 텍스트 무변경


# ── 텍스트 무변경 + 유효 화자 → speaker 포함 브로드캐스트 ─────────────
@pytest.mark.asyncio
async def test_broadcast_carries_speaker_without_text_change(monkeypatch):
    import app.services.live_corrector as mod

    lc, st = _prepared()
    batch = [_Pending("ch1", "m1", "s1", "예 그렇습니다")]
    lc._call_gpt = AsyncMock(return_value={"0": {"t": "예 그렇습니다", "s": "홍길동 위원"}})

    mgr = _fake_manager()
    monkeypatch.setattr(mod, "manager", mgr)
    monkeypatch.setattr(mod, "get_supabase_client", MagicMock())
    await lc._correct_and_apply("ch1", batch)

    mgr.broadcast_correction_failed.assert_not_awaited()  # 실패 처리 아님
    payload = mgr.broadcast_corrected_subtitle.await_args.args[1]
    assert payload["id"] == "s1"
    assert payload["speaker"] == "홍길동 위원"
    assert "corrected_text" not in payload  # 텍스트는 무변경
    assert st.prev_speaker == "홍길동 위원"  # 유효 화자 → prev 갱신


# ── prev_speaker 배치 간 연속성 ───────────────────────────────────────
@pytest.mark.asyncio
async def test_prev_speaker_persists_across_batches():
    lc, st = _prepared()

    with patch("app.services.live_corrector.manager", _fake_manager()) as mgr, \
         patch("app.services.live_corrector.get_supabase_client"):
        # 배치 1: 유효 화자 → prev 갱신
        lc._call_gpt = AsyncMock(return_value={"0": {"t": "", "s": "홍길동 위원"}})
        await lc._correct_and_apply("ch1", [_Pending("ch1", "m1", "s1", "질의하겠습니다")])
        assert st.prev_speaker == "홍길동 위원"

        # 배치 2: 단서 없음(s 빈값) → 직전 화자 유지가 새 배치에도 적용
        lc._call_gpt = AsyncMock(return_value={"0": {"t": "", "s": ""}})
        await lc._correct_and_apply("ch1", [_Pending("ch1", "m1", "s2", "계속 말씀드립니다")])

    payload = mgr.broadcast_corrected_subtitle.await_args.args[1]
    assert payload["id"] == "s2"
    assert payload["speaker"] == "홍길동 위원"


# ── staff 명부 화자 검증 (6a) ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_staff_speaker_accepted_with_staff_names():
    """staff_names가 로드돼 있으면 '이름+집행부 직책' 화자가 검증을 통과한다.

    과거 live_corrector가 _valid_speaker에 staff_names를 전달하지 않아
    staff 명부 실명 화자가 검증 경로에서 인정되지 않던 결함 가드.
    """
    lc, st = _prepared()
    st.staff_names = frozenset({"권주성"})
    batch = [_Pending("ch1", "m1", "s1", "답변드리겠습니다")]
    lc._call_gpt = AsyncMock(
        return_value={"0": {"t": "답변드리겠습니다", "s": "권주성 경제기획관"}}
    )

    with patch("app.services.live_corrector.manager", _fake_manager()) as mgr, \
         patch("app.services.live_corrector.get_supabase_client"):
        await lc._correct_and_apply("ch1", batch)

    payload = mgr.broadcast_corrected_subtitle.await_args.args[1]
    assert payload["speaker"] == "권주성 경제기획관"
    assert st.prev_speaker == "권주성 경제기획관"


@pytest.mark.asyncio
async def test_ensure_speaker_context_loads_staff_names(monkeypatch):
    """_ensure_speaker_context가 staff_roster에서 staff_names 집합을 함께 적재한다."""
    import app.services.live_corrector as mod

    lc = LiveCorrector()
    st = lc._states.setdefault("ch1", _ChannelState())
    entries = [
        {"name": "권주성", "title": "기획관", "department": None, "full_title": "경제기획관"},
        {"name": "배성호", "title": "국장", "department": "건설국", "full_title": "건설국장"},
    ]
    monkeypatch.setattr(mod, "get_supabase_client", MagicMock())
    monkeypatch.setattr(
        mod.LiveCorrector, "_resolve_committee", staticmethod(lambda room, mid: "경제노동위원회")
    )
    monkeypatch.setattr(mod, "load_committee_with_roles", lambda sb, c: [{"name": "홍길동", "role": "위원장"}])
    monkeypatch.setattr(mod, "load_staff_roster", lambda sb, c: entries)

    await lc._ensure_speaker_context(st, "ch1", "m1")

    assert st.staff_names == frozenset({"권주성", "배성호"})
    assert st.roster_names == {"홍길동"}


# ── diarize 경합 가드 (6b) ────────────────────────────────────────────
@pytest.mark.asyncio
async def test_diarize_enabled_skips_speaker_piggyback(monkeypatch):
    """diarize_enabled=True 구성이면 화자 피기백 전체 생략 — diarize 라벨이 권위.

    텍스트 교정은 그대로 적용되지만 DB update/브로드캐스트에 speaker 필드가
    포함되지 않고 prev_speaker도 갱신되지 않는다.
    """
    import app.services.live_corrector as mod

    monkeypatch.setattr(mod.settings, "diarize_enabled", True)
    lc, st = _prepared()
    batch = [_Pending("ch1", "m1", "s1", "예 그렇 습니다")]
    lc._call_gpt = AsyncMock(return_value={"0": {"t": "예 그렇습니다", "s": "홍길동 위원"}})

    updates: list[dict] = []

    class _Query:
        def __init__(self, payload):
            self.payload = payload

        def eq(self, _key, _value):
            return self

        def execute(self):
            updates.append(self.payload)
            return MagicMock(data=[])

    class _Table:
        def update(self, payload):
            return _Query(payload)

    class _Supabase:
        def table(self, _name):
            return _Table()

    monkeypatch.setattr(mod, "get_supabase_client", lambda: _Supabase())
    mgr = _fake_manager()
    monkeypatch.setattr(mod, "manager", mgr)
    await lc._correct_and_apply("ch1", batch)

    payload = mgr.broadcast_corrected_subtitle.await_args.args[1]
    assert payload["corrected_text"] == "예 그렇습니다"  # 텍스트 교정은 유지
    assert "speaker" not in payload  # 화자 피기백 생략
    assert updates == [{"text": "예 그렇습니다"}]  # DB update에도 speaker 없음
    assert st.prev_speaker == "위원장"  # prev_speaker 미갱신


@pytest.mark.asyncio
async def test_diarize_enabled_no_change_fails_pending(monkeypatch):
    """diarize on + 텍스트 무변경(화자만 온 응답) → pending 해제(no change)."""
    import app.services.live_corrector as mod

    monkeypatch.setattr(mod.settings, "diarize_enabled", True)
    lc, st = _prepared()
    batch = [_Pending("ch1", "m1", "s1", "예 그렇습니다")]
    lc._call_gpt = AsyncMock(return_value={"0": {"t": "예 그렇습니다", "s": "홍길동 위원"}})

    mgr = _fake_manager()
    monkeypatch.setattr(mod, "manager", mgr)
    monkeypatch.setattr(mod, "get_supabase_client", MagicMock())
    await lc._correct_and_apply("ch1", batch)

    mgr.broadcast_corrected_subtitle.assert_not_awaited()
    mgr.broadcast_correction_failed.assert_awaited_once()


# ── DB update에 speaker 포함 ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_db_update_includes_speaker(monkeypatch):
    import app.services.live_corrector as mod

    lc, st = _prepared()
    batch = [_Pending("ch1", "m1", "s1", "16명 중 찬성 86명")]
    lc._call_gpt = AsyncMock(
        return_value={"0": {"t": "61명 중 찬성 56명", "s": "홍길동 위원"}}
    )

    updates: list[tuple[str, dict]] = []

    class _Query:
        def __init__(self, payload):
            self.payload = payload
            self.sid = None

        def eq(self, _key, value):
            self.sid = value
            return self

        def execute(self):
            updates.append((self.sid, self.payload))
            return MagicMock(data=[])

    class _Table:
        def update(self, payload):
            return _Query(payload)

    class _Supabase:
        def table(self, _name):
            return _Table()

    monkeypatch.setattr(mod, "get_supabase_client", lambda: _Supabase())
    monkeypatch.setattr(mod, "manager", _fake_manager())
    await lc._correct_and_apply("ch1", batch)

    assert updates and updates[0][0] == "s1"
    assert updates[0][1] == {"text": "61명 중 찬성 56명", "speaker": "홍길동 위원"}
