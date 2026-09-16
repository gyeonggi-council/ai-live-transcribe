"""라이브 자막 GPT 교정(live_corrector) 단위 테스트.

GPT 호출은 모킹 — 배치 교정→브로드캐스트, 무변경/실패 시 pending 해제 흐름을 검증한다.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.live_corrector import LiveCorrector, _Pending, _parse_corrections


# ── 파싱 (순수) ───────────────────────────────────────────────────────
def test_parse_corrections_valid():
    assert _parse_corrections('{"0":"가","1":"나"}', 2) == {"0": "가", "1": "나"}


def test_parse_corrections_bad_json_is_none():
    assert _parse_corrections("not json", 2) is None


def test_parse_corrections_non_dict_is_none():
    assert _parse_corrections("[1,2]", 2) is None


def test_parse_corrections_empty_is_none():
    assert _parse_corrections("{}", 2) is None


def test_parse_corrections_ignores_out_of_range_index():
    # n=2 → 인덱스 0,1만 채택, "2"는 무시
    assert _parse_corrections('{"0":"가","2":"다"}', 2) == {"0": "가"}


# ── enqueue 게이트 ────────────────────────────────────────────────────
def test_enqueue_disabled_is_noop():
    lc = LiveCorrector()
    lc._enabled = False
    lc.enqueue("ch14", "m1", "s1", "텍스트")
    assert "ch14" not in lc._states


def test_enqueue_blank_text_is_noop():
    lc = LiveCorrector()
    lc._enabled = True
    lc.enqueue("ch14", "m1", "s1", "   ")
    assert "ch14" not in lc._states


# ── 배치 교정 적용 ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_correct_and_apply_broadcasts_corrections():
    lc = LiveCorrector()
    lc._enabled = True
    batch = [
        _Pending("ch14", "m1", "s1", "16명 중 찬성 86명"),
        _Pending("ch14", "m1", "s2", "스물 선포합니다"),
    ]
    lc._call_gpt = AsyncMock(return_value={"0": "61명 중 찬성 56명", "1": "가결을 선포합니다"})

    with patch("app.services.live_corrector.manager") as mgr, \
         patch("app.services.live_corrector.get_supabase_client"), \
         patch("app.services.live_corrector.load_meeting_glossary", return_value=[]):
        mgr.broadcast_corrected_subtitle = AsyncMock()
        mgr.broadcast_correction_failed = AsyncMock()
        await lc._correct_and_apply("ch14", batch)

    assert mgr.broadcast_corrected_subtitle.await_count == 2
    sent = {c.args[1]["id"]: c.args[1]["corrected_text"] for c in mgr.broadcast_corrected_subtitle.await_args_list}
    assert sent["s1"] == "61명 중 찬성 56명"
    assert sent["s2"] == "가결을 선포합니다"


@pytest.mark.asyncio
async def test_no_change_clears_pending():
    lc = LiveCorrector()
    lc._enabled = True
    batch = [_Pending("ch14", "m1", "s1", "동일한 텍스트입니다")]
    lc._call_gpt = AsyncMock(return_value={"0": "동일한 텍스트입니다"})

    with patch("app.services.live_corrector.manager") as mgr, \
         patch("app.services.live_corrector.get_supabase_client"), \
         patch("app.services.live_corrector.load_meeting_glossary", return_value=[]):
        mgr.broadcast_corrected_subtitle = AsyncMock()
        mgr.broadcast_correction_failed = AsyncMock()
        await lc._correct_and_apply("ch14", batch)

    mgr.broadcast_corrected_subtitle.assert_not_awaited()
    mgr.broadcast_correction_failed.assert_awaited_once()


@pytest.mark.asyncio
async def test_gpt_failure_clears_pending():
    lc = LiveCorrector()
    lc._enabled = True
    batch = [_Pending("ch14", "m1", "s1", "텍스트")]
    lc._call_gpt = AsyncMock(return_value=None)

    with patch("app.services.live_corrector.manager") as mgr, \
         patch("app.services.live_corrector.get_supabase_client"), \
         patch("app.services.live_corrector.load_meeting_glossary", return_value=[]):
        mgr.broadcast_corrected_subtitle = AsyncMock()
        mgr.broadcast_correction_failed = AsyncMock()
        await lc._correct_and_apply("ch14", batch)

    mgr.broadcast_corrected_subtitle.assert_not_awaited()
    mgr.broadcast_correction_failed.assert_awaited_once()


def test_enqueue_channel_only_session_is_noop():
    """meeting 미연결(채널-only) 세션은 교정 비용만 발생 → 스킵."""
    lc = LiveCorrector()
    lc._enabled = True
    lc.enqueue("ch14", "ch14", "s1", "텍스트")  # meeting_id == room_id
    lc.enqueue("ch14", "", "s2", "텍스트")      # meeting 없음
    assert "ch14" not in lc._states
