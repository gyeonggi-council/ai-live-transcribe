"""요약 미리 만들기(services/summary_pregen, 2026-09-15) — 대상 선별·하루 상한·실패 1회."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import summary_pregen as pg
from app.services.summary_service import MeetingSummary, SummaryGenerationError

NOW = datetime(2026, 9, 15, 5, 0, tzinfo=timezone.utc)  # KST 14:00
OLD = (NOW - timedelta(hours=2)).isoformat()
FRESH = (NOW - timedelta(minutes=3)).isoformat()


def _client(meetings: list[dict], summaries: list[dict]):
    client = MagicMock()
    mq = MagicMock()
    for m in ("select", "eq", "in_", "gte", "order", "limit"):
        getattr(mq, m).return_value = mq
    mq.execute.return_value = MagicMock(data=meetings)
    sq = MagicMock()
    for m in ("select", "in_"):
        getattr(sq, m).return_value = sq
    sq.execute.return_value = MagicMock(data=summaries)
    client.table.side_effect = lambda name: {"meetings": mq, "meeting_summaries": sq}[name]
    client.meetings_query = mq
    return client


def _m(mid: str, updated: str = OLD, date: str = "2026-09-14") -> dict:
    return {"id": mid, "title": f"회의 {mid}", "meeting_date": date, "status": "ended", "subtitle_stage": "ai", "updated_at": updated}


@pytest.fixture(autouse=True)
def _reset():
    pg._ledger.update({"day": None, "done": set(), "failed": set()})
    yield
    pg._ledger.update({"day": None, "done": set(), "failed": set()})


def test_select_targets_skips_summarized_fresh_and_excluded():
    client = _client(
        [_m("a"), _m("b"), _m("c", updated=FRESH), _m("d"), _m("e")],
        [{"meeting_id": "b", "generated_from": "ai"}, {"meeting_id": "d", "generated_from": "live"}],
    )
    got = [m["id"] for m in pg.select_targets(client, now=NOW, exclude={"e"})]
    # b 는 AI 요약이 있고, c 는 막 바뀌었고(교정 중일 수 있다), e 는 오늘 이미 시도 — d 는 실시간 자막 요약이라 다시 만든다
    assert got == ["a", "d"]
    # 단계·상태·기간 필터를 DB 에 건다
    q = client.meetings_query
    q.eq.assert_any_call("status", "ended")
    q.in_.assert_any_call("subtitle_stage", ["ai", "reviewing", "final"])


@pytest.mark.asyncio
async def test_run_once_respects_daily_limit_and_skips_user_counter():
    client = _client([_m("a"), _m("b"), _m("c")], [])
    gen = AsyncMock(return_value=MeetingSummary(summary_text="s", model_used="m", source_chars=10))
    with patch.object(pg.settings, "summary_pregen_daily_limit", 2), patch(
        "app.services.summary_service.generate_meeting_summary", gen
    ):
        r1 = await pg.run_once(client, now=NOW)
        r2 = await pg.run_once(client, now=NOW)
    assert r1["made"] == ["a", "b"] and r1["skipped_limit"] == 1
    assert r2 == {"made": [], "failed": [], "skipped_limit": 0}  # 오늘 상한 소진
    for call in gen.call_args_list:
        assert call.kwargs == {"count_daily": False, "replace_live": True}


@pytest.mark.asyncio
async def test_failed_meeting_is_not_retried_today():
    client = _client([_m("a")], [])
    gen = AsyncMock(side_effect=SummaryGenerationError("x"))
    with patch("app.services.summary_service.generate_meeting_summary", gen):
        r1 = await pg.run_once(client, now=NOW)
        r2 = await pg.run_once(client, now=NOW)
    assert r1["failed"] == ["a"]
    assert r2["failed"] == [] and gen.await_count == 1
    assert pg.ledger_status(NOW)["failed"] == ["a"]


@pytest.mark.asyncio
async def test_new_day_resets_ledger():
    client = _client([_m("a")], [])
    gen = AsyncMock(side_effect=SummaryGenerationError("x"))
    with patch("app.services.summary_service.generate_meeting_summary", gen):
        await pg.run_once(client, now=NOW)
        await pg.run_once(client, now=NOW + timedelta(days=1))
    assert gen.await_count == 2
