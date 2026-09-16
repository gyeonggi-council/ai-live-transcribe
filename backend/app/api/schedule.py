"""의사일정 조회 API — 실시간 방송 대시보드의 '다가오는 일정' 섹션이 쓴다.

의회 홈페이지가 대외 공표하는 공개 정보를 그대로 옮긴 것이므로 인증을 걸지 않는다
(같은 이유로 채널 목록·방송 상태도 무인증이다).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query

from app.core.database import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


@router.get("/upcoming")
async def get_upcoming(
    days: int = Query(7, ge=1, le=31, description="오늘부터 몇 일치를 볼지"),
    include_today: bool = Query(True, description="오늘을 포함할지"),
) -> dict:
    """오늘부터 `days` 일 사이의 의사일정을 날짜별로 묶어 돌려준다.

    화면이 "언제 기준인지"를 보여줄 수 있도록 `synced_at`(마지막 확인)과
    `changed_at`(내용이 실제로 바뀐 시각)을 함께 낸다 — 안건은 수시로 바뀐다.
    """
    today = date.today()
    start = today if include_today else today + timedelta(days=1)
    end = today + timedelta(days=days - 1)
    if end < start:
        return {"from": start.isoformat(), "to": start.isoformat(), "days": [], "synced_at": None}

    try:
        res = (
            get_supabase_client()
            .table("assembly_schedule")
            .select("*")
            .gte("schedule_date", start.isoformat())
            .lte("schedule_date", end.isoformat())
            .order("schedule_date")
            .execute()
        )
        rows = res.data or []
    except Exception as e:
        logger.error("의사일정 조회 실패: %s", e)
        raise HTTPException(status_code=503, detail="의사일정을 불러오지 못했습니다.")

    by_date: dict[str, list[dict]] = {}
    for r in rows:
        d = (r.get("schedule_date") or "")[:10]
        if not d:
            continue
        by_date.setdefault(d, []).append(
            {
                "committee_code": r.get("committee_code"),
                "committee_name": r.get("committee_name"),
                "start_time": r.get("start_time"),
                "session_no": r.get("session_no"),
                "session_order": r.get("session_order"),
                "session_kind": r.get("session_kind"),
                "agenda_items": r.get("agenda_items") or [],
                "is_cancelled": bool(r.get("is_cancelled")),
                "changed_at": r.get("changed_at"),
            }
        )

    # 시간순 — 시간 표기가 없는 회의는 뒤로
    for items in by_date.values():
        items.sort(key=lambda x: (x["start_time"] is None, x["start_time"] or "", x["committee_name"] or ""))

    synced = max((r.get("synced_at") or "" for r in rows), default="") or None
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "synced_at": synced,
        "days": [{"date": d, "items": by_date[d]} for d in sorted(by_date)],
    }
