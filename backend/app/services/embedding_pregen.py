"""자막 조각 임베딩 채우기 (2026-09-15) — 끝난 회의의 조각을 만들어 두어 AI 대화가 "뜻으로 찾기"를 쓸 수 있게.

summary_pregen 과 같은 모양(주기 검사·하루 장부·실패 1회). 다른 점:
  - 생중계 회의가 하나라도 있으면 그 바퀴는 쉰다 — PostgREST 연결 5개를 생중계 자막 입력과 나눠 쓴다
  - 대상: status=ended · 자막이 있는 단계(draft·ai·reviewing·final) · 단계가 바뀐 뒤 settle 분 지남 ·
          상태 행이 없거나, 회의가 상태보다 나중에 바뀌었거나, 실시간 자막으로 만든 조각인데 AI 자막이 생긴 회의
  - 한 회의씩 순서대로(최신 회의부터). 한 회의 = 조각 약 200개 = 임베딩 4번 + 저장 5번, 10초 안팎
장부는 인메모리다 — 재시작하면 그날 상한이 다시 찬다. 조각이 이미 최신이면 index_meeting 이 아무것도 안 한다(비용 0).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import settings

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
ELIGIBLE_STAGES = ("draft", "ai", "reviewing", "final")
AI_STAGES = {"ai", "reviewing", "final"}
_SCAN_ROWS = 300
_PER_RUN = 30                 # 한 바퀴 최대 회의 수 — 생중계 시작을 자주 확인하려고 짧게 끊는다
# 속기 교정처럼 자막만 고치면 meetings.updated_at 이 안 바뀐다(Codex 검토) — 하루 한 번은 자막 지문을 다시 대조한다.
# 안 바뀌었으면 index_meeting 이 비용 없이 확인 시각만 올린다.
_RECHECK = timedelta(hours=24)

_ledger: dict[str, Any] = {"day": None, "done": set(), "failed": set()}


def _ledger_for(day: date) -> dict[str, Any]:
    if _ledger["day"] != day:
        _ledger.update({"day": day, "done": set(), "failed": set()})
    return _ledger


def ledger_status(now: datetime | None = None) -> dict[str, Any]:
    day = (now or datetime.now(KST)).astimezone(KST).date()
    lg = _ledger_for(day)
    return {"day": day.isoformat(), "done": len(lg["done"]), "failed": sorted(lg["failed"]),
            "remaining": max(0, settings.embed_pregen_daily_limit - len(lg["done"]) - len(lg["failed"]))}


def _ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def any_live(supabase: Any) -> bool:
    return bool(supabase.table("meetings").select("id").eq("status", "live").limit(1).execute().data)


def select_targets(supabase: Any, *, now: datetime, exclude: set[str] | frozenset[str] = frozenset()) -> list[dict]:
    settled = now - timedelta(minutes=max(0, settings.embed_pregen_settle_minutes))
    rows = (
        supabase.table("meetings")
        .select("id,title,meeting_date,status,subtitle_stage,updated_at")
        .eq("status", "ended")
        .in_("subtitle_stage", list(ELIGIBLE_STAGES))
        .order("meeting_date", desc=True)
        .limit(_SCAN_ROWS)
        .execute()
    ).data or []
    rows = [r for r in rows if r.get("id") not in exclude and (_ts(r.get("updated_at")) or now) <= settled]
    if not rows:
        return []
    states = (
        supabase.table("subtitle_chunk_state").select("meeting_id,kind,indexed_at,model")
        .in_("meeting_id", [r["id"] for r in rows]).execute()
    ).data or []
    by_id = {s["meeting_id"]: s for s in states}
    out = []
    for r in rows:
        st = by_id.get(r["id"])
        indexed = _ts(st.get("indexed_at")) if st else None
        if (st is None or st.get("model") != settings.rag_embedding_model or indexed is None
                or (_ts(r.get("updated_at")) and _ts(r["updated_at"]) > indexed)
                or (st.get("kind") == "live" and r.get("subtitle_stage") in AI_STAGES)
                or now - indexed > _RECHECK):
            out.append(r)
    return out


async def run_once(supabase: Any, *, now: datetime | None = None) -> dict[str, Any]:
    from app.services.subtitle_embeddings import index_meeting

    now = now or datetime.now(timezone.utc)
    lg = _ledger_for(now.astimezone(KST).date())
    result: dict[str, Any] = {"indexed": [], "failed": [], "skipped_live": False}
    remaining = settings.embed_pregen_daily_limit - len(lg["done"]) - len(lg["failed"])
    if remaining <= 0:
        return result
    try:
        if await asyncio.to_thread(any_live, supabase):
            result["skipped_live"] = True
            return result
        targets = await asyncio.to_thread(select_targets, supabase, now=now, exclude=lg["done"] | lg["failed"])
    except Exception as e:
        logger.warning("조각 임베딩 대상 조회 실패(다음 주기에 재시도): %s", e)
        return result
    for m in targets[:min(remaining, _PER_RUN)]:
        mid = m["id"]
        try:
            if await asyncio.to_thread(any_live, supabase):   # 도는 사이 생중계가 시작됐으면 멈춘다
                result["skipped_live"] = True
                break
            info = await asyncio.to_thread(index_meeting, supabase, mid)
            if info.get("skipped"):
                continue              # 자막이 그대로라 비용 0 — 하루 상한을 깎지 않는다
            lg["done"].add(mid)
            result["indexed"].append(mid)
            logger.info("조각 임베딩: %s %s", (m.get("title") or "")[:40], info)
        except Exception as e:
            msg = str(e)
            if any(code in msg for code in ("PGRST205", "PGRST202", "42P01", "does not exist")):
                # 036 적용 전·pgrst 재시작 전 — 회의 탓이 아니니 실패로 적지 않고 이 바퀴만 멈춘다
                logger.warning("조각 임베딩 표가 아직 없다(036 적용·pgrst 재시작 필요): %s", msg[:160])
                break
            lg["failed"].add(mid)
            result["failed"].append(mid)
            logger.warning("조각 임베딩 실패(오늘은 다시 안 함): %s — %s", (m.get("title") or "")[:40], e)
    return result
