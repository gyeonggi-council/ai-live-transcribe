"""vod_auto_stt — VOD 등록 직후 자동 생성: 대상 선정 · 하루 장부 · 가드 · 알림 · kick."""

import asyncio
from datetime import date, datetime
from unittest.mock import MagicMock

import pytest

from app.services import stt_batch_queue
from app.services import vod_auto_stt as auto
from app.services.vod_auto_stt import KST, select_targets


@pytest.fixture(autouse=True)
def _clean_state():
    auto._reset_for_tests()
    stt_batch_queue._reset_for_tests()
    yield
    auto._reset_for_tests()
    stt_batch_queue._reset_for_tests()


# ─── 대상 선정 ─────────────────────────────────────────────────────────


class _Query:
    """supabase-py 체인 흉내 — 어떤 메서드든 self, execute() 는 준비된 rows."""

    def __init__(self, rows):
        self._rows = rows
        self.calls: list[tuple] = []
        self.not_ = self

    def __getattr__(self, name):
        def _m(*args, **kwargs):
            self.calls.append((name, args))
            return self
        return _m

    def execute(self):
        r = MagicMock()
        r.data = list(self._rows)
        return r


def _sb(rows):
    sb = MagicMock()
    sb.table.return_value = _Query(rows)
    return sb


def _row(mid, d, stage="none", vod="https://kms/x.mp4", status="ended"):
    return {"id": mid, "title": mid, "meeting_date": d, "vod_url": vod, "status": status, "subtitle_stage": stage}


def test_select_targets_filters_stage_processing_and_cap():
    rows = [
        _row("a", "2026-09-01"),                 # 대상
        _row("b", "2026-09-01", stage="draft"),  # 대상 (실시간 초안만 있음)
        _row("c", "2026-09-02", stage="ai"),     # 이미 AI 자막 있음 → 제외
        _row("d", "2026-09-02", stage="final"),  # 속기 검토본 → 보존
        _row("e", "2026-09-02", stage=None),     # NULL 은 none 취급 → 대상
        _row("f", "2026-09-02"),                 # 처리 중 → 제외
        _row("g", "2026-09-02"),                 # 상한 초과
    ]
    sb = _sb(rows)
    picked = select_targets(
        sb, today=date(2026, 9, 3), max_age_days=3, limit=3,
        is_processing_fn=lambda mid: mid == "f",
    )
    assert [p["id"] for p in picked] == ["a", "b", "e"]
    # 조회 조건: vod_url 있음 · ended · 기간 하한 · 오래된 순
    q = sb.table.return_value
    assert ("is_", ("vod_url", "null")) in q.calls
    assert ("eq", ("status", "ended")) in q.calls
    assert ("gte", ("meeting_date", "2026-08-31")) in q.calls


def test_select_targets_empty():
    assert select_targets(_sb([]), today=date(2026, 9, 3), max_age_days=3, limit=10,
                          is_processing_fn=lambda _: False) == []


def test_select_targets_zero_limit_does_not_query():
    sb = _sb([_row("a", "2026-09-02")])
    assert select_targets(sb, today=date(2026, 9, 3), max_age_days=3, limit=0,
                          is_processing_fn=lambda _: False) == []
    sb.table.assert_not_called()


def test_select_targets_scan_window_is_not_tied_to_limit():
    # 남은 상한이 1건이어도 오래된 'ai' 행들 뒤에 있는 새 대상을 찾아야 한다
    # (예전 limit*3 창이면 앞의 'ai' 3행에서 끝나 못 봤다).
    rows = [_row(f"old{i}", "2026-09-01", stage="ai") for i in range(8)] + [_row("new", "2026-09-02")]
    sb = _sb(rows)
    picked = select_targets(sb, today=date(2026, 9, 3), max_age_days=3, limit=1,
                            is_processing_fn=lambda _: False)
    assert [p["id"] for p in picked] == ["new"]
    assert ("limit", (auto._SCAN_ROWS,)) in sb.table.return_value.calls


def test_select_targets_skips_excluded():
    sb = _sb([_row("a", "2026-09-01"), _row("b", "2026-09-02")])
    picked = select_targets(sb, today=date(2026, 9, 3), max_age_days=3, limit=10,
                            is_processing_fn=lambda _: False, exclude={"a"})
    assert [p["id"] for p in picked] == ["b"]


# ─── run_once ──────────────────────────────────────────────────────────


def _settings(monkeypatch, limit=10, days=3):
    from app.core.config import settings
    monkeypatch.setattr(settings, "vod_auto_stt_daily_limit", limit)
    monkeypatch.setattr(settings, "vod_auto_stt_max_age_days", days)


async def test_run_once_registers_then_generates_and_notifies(monkeypatch):
    _settings(monkeypatch)
    sb = _sb([_row("a", "2026-09-02"), _row("b", "2026-09-02")])
    register_calls = []

    async def register(supabase, **kw):
        register_calls.append(kw)
        return {"created_count": 1, "matched_count": 2, "promoted_count": 0}

    batch_calls = []

    async def run_batch(ids, factory, *, source):
        batch_calls.append((ids, source))
        return {"done": ["a"], "failed": [{"meeting_id": "b", "reason": "x"}]}

    notify = MagicMock()
    recorded = []
    s = await auto.run_once(
        lambda: sb, register=register, run_batch=run_batch, notify=notify,
        is_processing_fn=lambda _: False, record=recorded.append,
        now=datetime(2026, 9, 3, 4, 0, tzinfo=KST),
    )
    assert register_calls == [{"regenerate_subtitles": False, "pages": 2}]  # 등록만, AI 비용 0
    assert batch_calls == [(["a", "b"], "auto")]
    assert s["done"] == ["a"] and len(s["failed"]) == 1
    assert s["registered_created"] == 1 and s["registered_matched"] == 2
    assert recorded and recorded[0]["ran_at"].startswith("2026-09-03T04:00")
    notify.assert_called_once()
    args = notify.call_args.args
    assert args[1] == "vod_auto_stt" and args[2] == "AI 자막 자동 생성"
    assert "성공 1" in args[3] and "실패 1" in args[3]
    assert "실패: b" in args[3]  # 어느 회의가 왜 실패했는지 알림에서 바로 보인다
    assert s["trigger"] == "manual"


async def test_run_once_register_failure_does_not_block_generation(monkeypatch):
    _settings(monkeypatch)
    sb = _sb([_row("a", "2026-09-02")])

    async def register(supabase, **kw):
        raise RuntimeError("KMS 목록 가져오기 실패")

    async def run_batch(ids, factory, *, source):
        return {"done": ids, "failed": []}

    notify = MagicMock()
    s = await auto.run_once(lambda: sb, register=register, run_batch=run_batch, notify=notify,
                            is_processing_fn=lambda _: False, record=lambda _: None,
                            now=datetime(2026, 9, 3, 4, 0, tzinfo=KST))
    assert s["register_error"] and s["done"] == ["a"]
    assert "등록 오류" in notify.call_args.args[3]


async def test_run_once_skips_when_batch_running(monkeypatch):
    _settings(monkeypatch)
    sb = _sb([_row("a", "2026-09-02")])

    async def register(supabase, **kw):
        return {}

    async def run_batch(ids, factory, *, source):
        return None  # 그 사이 관리자 버튼이 큐를 잡았다

    notify = MagicMock()
    recorded = []
    now = datetime(2026, 9, 3, 10, 0, tzinfo=KST)
    s = await auto.run_once(lambda: sb, register=register, run_batch=run_batch, notify=notify,
                            is_processing_fn=lambda _: False, record=recorded.append, now=now)
    assert s["skipped_reason"] == "batch_running" and s["done"] == []
    notify.assert_not_called()   # 30분마다 돌므로 건너뜀은 알림 없이 기록만 — 다음 주기에 다시 본다
    assert recorded
    # 시도한 적이 없으니 장부에서 되돌린다 — 상한을 먹지 않고 다음 주기에 다시 잡힌다
    assert auto.ledger_status(now)["started"] == []
    assert auto.ledger_status(now)["remaining"] == 10


async def test_run_once_quiet_when_nothing_to_do(monkeypatch):
    _settings(monkeypatch)
    sb = _sb([])

    async def register(supabase, **kw):
        return {"created_count": 0, "matched_count": 0, "promoted_count": 0}

    run_batch = MagicMock()
    notify = MagicMock()
    recorded = []
    s = await auto.run_once(lambda: sb, register=register, run_batch=run_batch, notify=notify,
                            is_processing_fn=lambda _: False, record=recorded.append,
                            now=datetime(2026, 9, 3, 4, 0, tzinfo=KST))
    assert s["skipped_reason"] == "no_targets"
    run_batch.assert_not_called()
    notify.assert_not_called()      # 할 일이 없으면 알림으로 시끄럽게 하지 않는다
    assert recorded                 # 그래도 실행 기록은 남는다


async def test_run_once_dry_run_only_lists_targets(monkeypatch):
    _settings(monkeypatch)
    sb = _sb([_row("a", "2026-09-02")])
    register = MagicMock()
    run_batch = MagicMock()
    notify = MagicMock()
    s = await auto.run_once(lambda: sb, register=register, run_batch=run_batch, notify=notify,
                            is_processing_fn=lambda _: False, record=lambda _: None,
                            now=datetime(2026, 9, 3, 4, 0, tzinfo=KST), dry_run=True)
    assert [t["id"] for t in s["targets"]] == ["a"]
    assert s["skipped_reason"] == "dry_run"
    register.assert_not_called()
    run_batch.assert_not_called()
    notify.assert_not_called()


# ─── 하루 장부 (등록 직후 자동 — 2026-09-10) ─────────────────────────────


def _ok_batch(calls):
    async def run_batch(ids, factory, *, source):
        calls.append(list(ids))
        return {"done": list(ids), "failed": []}
    return run_batch


async def _run(sb, run_batch, now, **kw):
    return await auto.run_once(
        lambda: sb, run_batch=run_batch, notify=kw.pop("notify", MagicMock()),
        is_processing_fn=lambda _: False, record=lambda _: None, now=now,
        skip_register=True, **kw,
    )


async def test_skip_register_does_not_call_register(monkeypatch):
    _settings(monkeypatch)
    register = MagicMock()
    calls = []
    s = await auto.run_once(lambda: _sb([_row("a", "2026-09-02")]), register=register,
                            run_batch=_ok_batch(calls), notify=MagicMock(),
                            is_processing_fn=lambda _: False, record=lambda _: None,
                            now=datetime(2026, 9, 3, 10, 0, tzinfo=KST), skip_register=True)
    register.assert_not_called()      # 등록 루프가 방금 등록했다
    assert calls == [["a"]] and s["trigger"] == "register_loop"


async def test_daily_limit_counts_across_runs(monkeypatch):
    _settings(monkeypatch, limit=2)
    now = datetime(2026, 9, 3, 10, 0, tzinfo=KST)
    calls = []
    # 첫 주기: 1건 → 오늘 1/2
    await _run(_sb([_row("a", "2026-09-02")]), _ok_batch(calls), now)
    # 다음 주기: 새로 VOD 붙은 2건 중 남은 상한 1건만
    s = await _run(_sb([_row("b", "2026-09-02"), _row("c", "2026-09-02")]), _ok_batch(calls), now)
    assert calls == [["a"], ["b"]]
    assert s["daily_remaining"] == 0
    # 그다음 주기: 상한을 채웠으니 생성하지 않는다
    s = await _run(_sb([_row("c", "2026-09-02")]), _ok_batch(calls), now)
    assert s["skipped_reason"] == "daily_limit" and calls == [["a"], ["b"]]


async def test_failed_meeting_not_retried_same_day(monkeypatch):
    _settings(monkeypatch)
    now = datetime(2026, 9, 3, 10, 0, tzinfo=KST)
    calls = []

    async def fail_batch(ids, factory, *, source):
        calls.append(list(ids))
        return {"done": [], "failed": [{"meeting_id": i, "reason": "다운로드 실패"} for i in ids]}

    await _run(_sb([_row("a", "2026-09-02")]), fail_batch, now)
    assert auto.ledger_status(now)["failed"] == ["a"]
    # 30분 뒤 — 여전히 stage none 이지만 오늘은 다시 잡지 않는다 (실패할 때마다 비용이 나간다)
    s = await _run(_sb([_row("a", "2026-09-02")]), fail_batch, now.replace(minute=30))
    assert s["skipped_reason"] == "no_targets" and calls == [["a"]]
    # 다음 날엔 다시 시도한다 (최근 3일 안)
    await _run(_sb([_row("a", "2026-09-02")]), fail_batch, datetime(2026, 9, 4, 7, 0, tzinfo=KST))
    assert calls == [["a"], ["a"]]


async def test_ledger_resets_on_new_kst_day(monkeypatch):
    _settings(monkeypatch, limit=1)
    calls = []
    await _run(_sb([_row("a", "2026-09-02")]), _ok_batch(calls), datetime(2026, 9, 3, 22, 0, tzinfo=KST))
    s = await _run(_sb([_row("b", "2026-09-03")]), _ok_batch(calls), datetime(2026, 9, 4, 6, 5, tzinfo=KST))
    assert calls == [["a"], ["b"]] and s["daily_remaining"] == 0


async def test_quiet_notification_when_nothing_generated(monkeypatch):
    _settings(monkeypatch)
    notify = MagicMock()
    s = await _run(_sb([]), MagicMock(), datetime(2026, 9, 3, 10, 0, tzinfo=KST), notify=notify)
    assert s["skipped_reason"] == "no_targets"
    notify.assert_not_called()


# ─── kick — 등록 루프가 부르는 진입점 ────────────────────────────────────


async def test_kick_returns_none_while_batch_running():
    assert stt_batch_queue._claim(["x"], "manual")  # 관리자 버튼 배치가 도는 중
    assert auto.kick(lambda: _sb([])) is None


async def test_kick_starts_background_run_and_does_not_double_start(monkeypatch):
    _settings(monkeypatch)
    started = asyncio.Event()
    release = asyncio.Event()
    seen = []

    async def fake_run_once(factory, **kw):
        seen.append(kw)
        started.set()
        await release.wait()
        return {}

    monkeypatch.setattr(auto, "run_once", fake_run_once)
    task = auto.kick(lambda: _sb([]))
    assert task is not None
    await started.wait()
    assert seen == [{"skip_register": True}]
    # 배치가 큐를 잡기 전이라도 두 번째 kick 은 새로 띄우지 않는다
    assert auto.kick(lambda: _sb([])) is None
    release.set()
    await task
    assert auto.kick(lambda: _sb([])) is not None  # 끝났으면 다음 주기에 다시 뜬다
    await auto._task
