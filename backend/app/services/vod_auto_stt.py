"""VOD 등록 직후 AI 자막 자동 생성 (2026-09-03 새벽 1회 → 2026-09-10 등록 직후).

KMS 등록 루프(`main._kms_auto_register_loop`, 30분마다)가 한 바퀴 돌 때마다 `kick()` 이 불린다:
  ① 배치 큐가 이미 돌고 있으면 아무것도 안 한다 — 다음 주기에 다시 본다
  ② VOD 가 있고 AI 자막이 아직 없는 최근 회의를 고른다 (오늘 남은 상한 · 오늘 이미 시도한 회의 제외)
  ③ 관리자 버튼과 **같은 배치 큐**(`stt_batch_queue`)로 순차 생성한다 — 백그라운드라 등록 루프를 막지 않는다
  ④ 결과를 `last_auto_run` 에 남기고, 실제로 생성했을 때만 알림(notifications)을 만든다

왜 등록 직후인가 — 2026-09-10 실측: 9-09 회의 3건의 VOD 가 09:06 에 붙었는데 생성은 매일 07:00
1회뿐이라 다음 날 07:00 까지 약 22시간 "VOD 등록됨" 에 머물렀고, 그 사이 관리자가 버튼을 눌러야 했다.
사용자 결정(2026-09-10): "VOD 가 등록되면 바로 생성" — 생중계 중이어도. 대신 무거운 하위 프로세스는
`app.core.proc_priority` 로 생중계 STT 뒤에 선다.

가드 — 2026-06-12 에 AI 자막을 수동으로 돌린 이유(버튼 한 번에 다수 회의 유료 전사 → 비용 폭증)를
잊지 않기 위한 장치:
  - 하루 상한 `vod_auto_stt_daily_limit` (기본 10, ≈$4/일) — KST 날짜별 장부로 센다
  - 최근 `vod_auto_stt_max_age_days` 일 이내 회의만 (기본 3 — 과거 회기 무더기 방지)
  - `subtitle_stage` 가 none/draft 인 것만 — 속기사 검토본(reviewing/final)은 건드리지 않는다
  - 생중계·처리 중 회의 제외, 배치 큐가 이미 돌고 있으면 이번 주기는 건너뛴다
  - **자동으로 한 번 시도한 회의는 그날 다시 잡지 않는다** — 30분마다 재시도하면 실패할 때마다 전사
    비용이 다시 나간다. 다음 날(기간 안이면) 다시 잡히고, 급하면 관리자 버튼으로 재시도한다.

장부는 인메모리다 — 재시작(배포)하면 비어 상한이 다시 찬다. 성공한 회의는 stage=ai 라 다시 잡히지
않으므로 영향은 "그날 상한 재충전" 과 "실패한 회의 1회 재시도" 뿐이다. 배포가 도는 배치를 끊으면
그 회의는 기동 때 `reset_orphaned_processing` 으로 풀려 처음부터 다시 전사된다(비용 한 번 더).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any, Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
NOTIFICATION_TYPE = "vod_auto_stt"
NOTIFICATION_TITLE = "AI 자막 자동 생성"

# 자동 생성 대상이 되는 단계 — 검토본(reviewing/final)은 보존 (vod_stt_service._should_promote_to_ai 와 동일 규칙)
ELIGIBLE_STAGES = ("none", "draft")

# 대상 조회 창 — 상한과 분리한다. 남은 상한이 1~2건일 때 `limit*3` 으로 자르면 오래된 'ai' 행이
# 창을 채워 새로 VOD 가 붙은 회의를 못 봤다. 기간(max_age_days)이 이미 경계라 넉넉해도 된다.
_SCAN_ROWS = 200

# 하루 장부 (KST 날짜별) — started: 오늘 자동으로 시도한 회의(상한 계산·재시도 방지), failed: 그중 실패
_ledger: dict[str, Any] = {"day": None, "started": set(), "failed": set()}

# kick 이 띄운 태스크 — 참조를 쥐고 있어야 GC 되지 않고, 배치가 큐를 잡기 전의 틈에 두 번 뜨지 않는다
_task: Optional[asyncio.Task] = None


def _ledger_for(day: date) -> dict[str, Any]:
    if _ledger["day"] != day:
        _ledger.update({"day": day, "started": set(), "failed": set()})
    return _ledger


def ledger_status(now: Optional[datetime] = None) -> dict[str, Any]:
    """오늘 장부 스냅샷 (관리자 상태 API 용)."""
    from app.core.config import settings

    day = (now or datetime.now(KST)).astimezone(KST).date()
    lg = _ledger_for(day)
    return {
        "day": day.isoformat(),
        "started": sorted(lg["started"]),
        "failed": sorted(lg["failed"]),
        "remaining": max(0, settings.vod_auto_stt_daily_limit - len(lg["started"])),
    }


def select_targets(
    supabase: Any,
    *,
    today: date,
    max_age_days: int,
    limit: int,
    is_processing_fn: Callable[[str], bool],
    exclude: frozenset[str] | set[str] = frozenset(),
) -> list[dict[str, Any]]:
    """자동 생성 대상 회의를 고른다 (오래된 회의부터, 최대 `limit` 건).

    조건: vod_url 있음 · status=ended · subtitle_stage ∈ none/draft(NULL 은 none 취급)
          · meeting_date ≥ today − max_age_days · 처리 중 아님 · `exclude` 에 없음
    """
    if limit <= 0:
        return []
    cutoff = (today - timedelta(days=max(0, max_age_days))).isoformat()
    result = (
        supabase.table("meetings")
        .select("id,title,meeting_date,vod_url,status,subtitle_stage")
        .not_.is_("vod_url", "null")
        .eq("status", "ended")
        .gte("meeting_date", cutoff)
        .order("meeting_date", desc=False)
        .limit(_SCAN_ROWS)
        .execute()
    )
    rows: list[dict[str, Any]] = list(result.data or [])
    picked: list[dict[str, Any]] = []
    for r in rows:
        if not r.get("vod_url") or r["id"] in exclude:
            continue
        stage = r.get("subtitle_stage") or "none"
        if stage not in ELIGIBLE_STAGES:
            continue
        if is_processing_fn(r["id"]):
            continue
        picked.append(r)
        if len(picked) >= limit:
            break
    return picked


def _summarize(
    *,
    ran_at: str,
    trigger: str,
    register: Optional[dict[str, Any]],
    register_error: Optional[str],
    targets: list[dict[str, Any]],
    batch: Optional[dict[str, Any]],
    skipped_reason: Optional[str],
    daily_remaining: int,
) -> dict[str, Any]:
    reg = register or {}
    return {
        "ran_at": ran_at,
        "trigger": trigger,  # "register_loop"(30분 등록 루프) | "manual"(관리자 지금 실행)
        "registered_created": int(reg.get("created_count") or 0),
        "registered_matched": int(reg.get("matched_count") or 0),
        "registered_promoted": int(reg.get("promoted_count") or 0),
        "register_error": register_error,
        "targets": [{"id": t["id"], "title": t.get("title")} for t in targets],
        "done": list((batch or {}).get("done") or []),
        "failed": list((batch or {}).get("failed") or []),
        "skipped_reason": skipped_reason,
        "daily_remaining": daily_remaining,
    }


def _notification_message(s: dict[str, Any]) -> str:
    parts = []
    if s["trigger"] == "manual":
        parts.append(
            f"등록 신규 {s['registered_created']}·매칭 {s['registered_matched']}·변환대기 {s['registered_promoted']}"
        )
    parts.append(f"AI 자막 생성 성공 {len(s['done'])}·실패 {len(s['failed'])}")
    titles = {t["id"]: t.get("title") or t["id"] for t in s["targets"]}
    for f in s["failed"][:2]:
        mid = f.get("meeting_id")
        parts.append(f"실패: {titles.get(mid, mid)} — {str(f.get('reason') or '')[:60]}")
    if s.get("skipped_reason") and s["skipped_reason"] != "no_targets":
        parts.append(f"건너뜀: {s['skipped_reason']}")
    if s.get("register_error"):
        parts.append(f"등록 오류: {s['register_error'][:80]}")
    return " / ".join(parts)


async def run_once(
    supabase_factory: Callable[[], Any],
    *,
    register: Optional[Callable[..., Awaitable[dict[str, Any]]]] = None,
    run_batch: Optional[Callable[..., Awaitable[Optional[dict[str, Any]]]]] = None,
    notify: Optional[Callable[..., Any]] = None,
    is_processing_fn: Optional[Callable[[str], bool]] = None,
    record: Optional[Callable[[dict[str, Any]], None]] = None,
    now: Optional[datetime] = None,
    dry_run: bool = False,
    skip_register: bool = False,
) -> dict[str, Any]:
    """(등록 →) 대상 선정 → 생성 1회. 각 단계는 독립 — 등록이 실패해도 생성은 시도한다.

    skip_register=True 는 등록 루프가 방금 등록을 끝낸 뒤 부를 때(`kick`).
    dry_run=True 면 등록·생성 없이 대상 목록만 돌려준다 (배포 뒤 검증용, 장부도 건드리지 않는다).
    """
    from app.core.config import settings

    if register is None:
        from app.services.kms_bulk_matcher import match_and_update as register
    if run_batch is None:
        from app.services.stt_batch_queue import run_batch
    if notify is None:
        from app.services.notification_service import create_notification_record as notify
    if is_processing_fn is None:
        from app.services.vod_stt_service import is_processing as is_processing_fn
    if record is None:
        from app.services.stt_batch_queue import record_auto_run as record

    now = now or datetime.now(KST)
    today = now.astimezone(KST).date()
    ran_at = now.astimezone(KST).isoformat(timespec="seconds")
    supabase = supabase_factory()
    ledger = _ledger_for(today)
    limit = settings.vod_auto_stt_daily_limit

    register_result: Optional[dict[str, Any]] = None
    register_error: Optional[str] = None
    if not dry_run and not skip_register:
        try:
            register_result = await register(supabase, regenerate_subtitles=False, pages=2)
        except Exception as e:  # 등록 실패가 생성 단계를 막지 않는다
            register_error = str(e)
            logger.warning("VOD 자동 자막: KMS 등록 실패 (생성은 계속) — %s", e)

    remaining = max(0, limit - len(ledger["started"]))
    targets = select_targets(
        supabase,
        today=today,
        max_age_days=settings.vod_auto_stt_max_age_days,
        limit=remaining,
        is_processing_fn=is_processing_fn,
        exclude=set(ledger["started"]),
    )

    batch_result: Optional[dict[str, Any]] = None
    skipped_reason: Optional[str] = None
    if dry_run:
        skipped_reason = "dry_run"
    elif remaining <= 0:
        skipped_reason = "daily_limit"
    elif not targets:
        skipped_reason = "no_targets"
    else:
        ids = [t["id"] for t in targets]
        ledger["started"].update(ids)
        logger.info("VOD 자동 자막: %d건 생성 시작 (오늘 %d/%d)", len(ids), len(ledger["started"]), limit)
        batch_result = await run_batch(ids, supabase_factory, source="auto")
        if batch_result is None:  # 그 사이 관리자 버튼이 큐를 잡았다 — 시도한 적 없으니 장부에서 되돌린다
            ledger["started"].difference_update(ids)
            skipped_reason = "batch_running"
        else:
            ledger["failed"].update(
                f["meeting_id"] for f in batch_result.get("failed") or [] if f.get("meeting_id")
            )

    summary = _summarize(
        ran_at=ran_at,
        trigger="register_loop" if skip_register else "manual",
        register=register_result,
        register_error=register_error,
        targets=targets,
        batch=batch_result,
        skipped_reason=skipped_reason,
        daily_remaining=max(0, limit - len(ledger["started"])),
    )
    if dry_run:
        return summary

    record(summary)
    # 알림은 실제로 생성했을 때만 — 30분마다 "할 일 없음·건너뜀" 이 알림함에 쌓이지 않게
    if summary["done"] or summary["failed"] or register_error:
        try:
            notify(supabase, NOTIFICATION_TYPE, NOTIFICATION_TITLE, _notification_message(summary))
        except Exception as e:
            logger.debug("VOD 자동 자막: 알림 생성 실패 (무시) — %s", e)
    if skipped_reason in (None, "daily_limit") or register_error:
        logger.info("VOD 자동 자막: %s", _notification_message(summary))
    return summary


def kick(supabase_factory: Callable[[], Any]) -> Optional[asyncio.Task]:
    """등록 루프가 한 바퀴 돈 뒤 부른다 — 생성할 것이 있으면 백그라운드로 띄우고 바로 돌아온다.

    배치 큐가 이미 돌고 있으면(관리자 버튼·직전 자동 배치) None — 다음 주기에 다시 본다.
    """
    global _task
    from app.services.stt_batch_queue import is_running

    if is_running() or (_task is not None and not _task.done()):
        return None
    _task = asyncio.create_task(
        run_once(supabase_factory, skip_register=True), name="vod-auto-stt"
    )
    return _task


def _reset_for_tests() -> None:
    global _task
    _ledger.update({"day": None, "started": set(), "failed": set()})
    _task = None
