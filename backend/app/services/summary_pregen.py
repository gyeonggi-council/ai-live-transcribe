"""요약 미리 만들기 (2026-09-15 담당자 결정 — "AI 자막이 끝나면 요약을 미리 만들어 두기").

담당자가 [요약 만들기] 를 누를 때마다 긴 회의는 구간 요약 → 병합으로 수십 초를 기다렸다. AI 자막이 끝난 회의는
api 파드가 주기적으로(기본 10분) 골라 요약해 두고, 화면은 캐시(meeting_summaries)를 바로 읽는다.

왜 주기 검사인가 — AI 자막이 끝나는 길이 여럿이다(자동 생성·관리자 배치·회의별 생성·재생성·자막/음성 업로드).
완료 지점마다 훅을 거는 대신 DB 를 보고 고르면 모든 길을 한 번에 덮고, 재시작에도 빠지는 회의가 없다.
왜 api 파드인가 — 클리퍼 파드에는 OpenAI 키가 없고, 회의별 생성 잠금(summary_service._locks)이 api 프로세스에 있어
담당자 클릭과 겹쳐도 한 번만 만든다. api 는 1개·워커 1개라 이 루프도 한 번만 돈다.

가드
  - 대상: subtitle_stage ∈ ai/reviewing/final · status=ended · 최근 max_age_days 일 · 요약이 없거나 실시간 자막으로 만든 요약
  - 자막 단계가 바뀐 뒤 settle_minutes 가 지난 회의만(meetings.updated_at) — 업로드·재생성 경로는 단계를 먼저 바꾸고 문법 교정을 뒤에 돈다
  - 하루 상한 summary_pregen_daily_limit(KST) — 담당자가 누르는 요약 한도(ai_summary_daily_limit)와 따로 센다
  - 오늘 실패한 회의는 오늘 다시 잡지 않는다(실패할 때마다 비용이 다시 나가지 않게)
  - 한 번에 한 회의씩 순서대로(최신 회의부터 — 열어 볼 가능성이 큰 순)
장부는 인메모리다(vod_auto_stt 와 같은 방식) — 재시작하면 그날 상한이 다시 찬다. 성공한 회의는 캐시가 생겨 다시 잡히지 않는다.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import settings

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
ELIGIBLE_STAGES = ("ai", "reviewing", "final")
_SCAN_ROWS = 200

_ledger: dict[str, Any] = {"day": None, "done": set(), "failed": set()}


def _ledger_for(day: date) -> dict[str, Any]:
    if _ledger["day"] != day:
        _ledger.update({"day": day, "done": set(), "failed": set()})
    return _ledger


def ledger_status(now: datetime | None = None) -> dict[str, Any]:
    day = (now or datetime.now(KST)).astimezone(KST).date()
    lg = _ledger_for(day)
    return {
        "day": day.isoformat(),
        "done": sorted(lg["done"]),
        "failed": sorted(lg["failed"]),
        "remaining": max(0, settings.summary_pregen_daily_limit - len(lg["done"]) - len(lg["failed"])),
    }


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def select_targets(supabase: Any, *, now: datetime, exclude: set[str] | frozenset[str] = frozenset()) -> list[dict]:
    """미리 요약할 회의 — 최신 회의부터."""
    today = now.astimezone(KST).date()
    cutoff = (today - timedelta(days=max(0, settings.summary_pregen_max_age_days))).isoformat()
    settled = now - timedelta(minutes=max(0, settings.summary_pregen_settle_minutes))
    rows = (
        supabase.table("meetings")
        .select("id,title,meeting_date,status,subtitle_stage,updated_at")
        .eq("status", "ended")
        .in_("subtitle_stage", list(ELIGIBLE_STAGES))
        .gte("meeting_date", cutoff)
        .order("meeting_date", desc=True)
        .limit(_SCAN_ROWS)
        .execute()
    ).data or []
    rows = [r for r in rows if r.get("id") not in exclude]
    rows = [r for r in rows if (_parse_ts(r.get("updated_at")) or now) <= settled]
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    summaries = (
        supabase.table("meeting_summaries").select("meeting_id,generated_from").in_("meeting_id", ids).execute()
    ).data or []
    have = {s["meeting_id"]: s.get("generated_from") for s in summaries}
    return [r for r in rows if r["id"] not in have or have[r["id"]] == "live"]


async def run_once(supabase: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """한 바퀴 — 오늘 남은 상한만큼 순서대로 요약한다. 결과 요약을 돌려준다(로그·테스트용)."""
    from app.services.summary_service import SummaryGenerationError, generate_meeting_summary

    now = now or datetime.now(timezone.utc)
    lg = _ledger_for(now.astimezone(KST).date())
    remaining = settings.summary_pregen_daily_limit - len(lg["done"]) - len(lg["failed"])
    result: dict[str, Any] = {"made": [], "failed": [], "skipped_limit": 0}
    if remaining <= 0:
        return result
    try:
        targets = select_targets(supabase, now=now, exclude=lg["done"] | lg["failed"])
    except Exception as e:
        logger.warning("요약 미리 만들기 대상 조회 실패(다음 주기에 재시도): %s", e)
        return result
    for m in targets:
        if remaining <= 0:
            result["skipped_limit"] += 1
            continue
        mid = m["id"]
        remaining -= 1
        try:
            summary = await generate_meeting_summary(supabase, mid, count_daily=False, replace_live=True)
            lg["done"].add(mid)
            result["made"].append(mid)
            logger.info("요약 미리 만들기 완료: %s (%s, %s자)", (m.get("title") or "")[:40], summary.model_used, summary.source_chars)
        except (SummaryGenerationError, ValueError) as e:
            lg["failed"].add(mid)
            result["failed"].append(mid)
            logger.warning("요약 미리 만들기 실패(오늘은 다시 안 함): %s — %s", (m.get("title") or "")[:40], e)
        except Exception as e:  # 예상 밖 — 루프를 죽이지 않는다
            lg["failed"].add(mid)
            result["failed"].append(mid)
            logger.exception("요약 미리 만들기 오류: %s — %s", mid, e)
    return result
