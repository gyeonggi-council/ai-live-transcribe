# -*- coding: utf-8 -*-
"""접속 통계 — 기록 정책과 집계 (2026-09-16 담당자 요청).

**IP 를 저장하지 않는다.** 요청이 들어온 순간 `council_network.site_label()` 로 접속처 이름
(무선인터넷·의회사무처(직원)·…·외부)으로 바꾸고 그 이름만 `access_events` 에 넣는다.
User-Agent 원문·사용자 이름/ID 도 넣지 않는다(기기 구분 pc/mobile/tablet 과 역할만).

집계는 마이그레이션 033 의 뷰 4개가 GROUP BY 를 해 주고(PostgREST 는 못 한다) 여기서는
날짜 범위로 읽어 합칠 뿐이다. 표가 없거나 뷰가 아직 없으면 **빈 통계**를 돌려준다 —
통계 때문에 화면이 죽지 않게(021 site_visits 와 같은 원칙).

`.table()` 을 여기서 직접 부르는 것은 stats.py 와 같은 결이다(리포지토리 계층으로 옮긴 라우터는
meetings·subtitles·notifications·minutes 넷뿐 — docs/architecture/backend-layering.md).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from supabase import Client

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

TABLE = "access_events"
V_DAILY = "v_access_daily"
V_HOURLY = "v_access_hourly"
V_MEETING = "v_access_meeting"
V_FEATURE = "v_access_feature"

# 기록하는 행동. 프런트가 보내는 값이 이 목록에 없으면 버린다.
KINDS = {
    "page": "화면 열람",
    "watch_live": "생중계 시청",
    "watch_vod": "회의 영상 시청",
    "search": "자막 검색",
    "ai": "AI 질문",
    "download": "영상·회의록 받기",
    "record": "녹음 듣기",
    "login_prompt": "앱 로그인 안내",
}

WATCH_KINDS = ("watch_live", "watch_vod")
# 시청 신호 1건이 뜻하는 시간(초). 프런트가 5분마다 보낸다.
WATCH_TICK_SECONDS = 300

# 같은 브라우저의 같은 행동을 이 초 안에 또 보내면 버린다(새로고침 연타·중복 탭).
_DEDUPE_SECONDS = {
    "page": 30,
    "watch_live": 240,
    "watch_vod": 240,
    "search": 5,
    "ai": 5,
    "download": 5,
    "record": 5,
    "login_prompt": 600,  # 안내 화면을 본 것 — 새로고침 연타를 10분에 한 번으로 묶는다
}
_seen: dict[str, float] = {}
_SEEN_MAX = 20000

# 한 접속처가 한 시간에 넣을 수 있는 행 수(장난·오작동 보호). 넘으면 조용히 버린다.
_HOURLY_CAP = 2000
_hourly: dict[str, tuple[int, int]] = {}


def now_kst() -> datetime:
    return datetime.now(KST)


def _dedupe(key: str, kind: str) -> bool:
    """True 면 '방금 같은 것을 받았다' — 버린다."""
    window = _DEDUPE_SECONDS.get(kind, 5)
    now = time.monotonic()
    last = _seen.get(key)
    if last is not None and now - last < window:
        return True
    if len(_seen) > _SEEN_MAX:  # 오래된 것부터 버린다(단일 파드, 재시작하면 비어도 무해)
        cutoff = now - 3600
        for k in [k for k, v in _seen.items() if v < cutoff]:
            _seen.pop(k, None)
        if len(_seen) > _SEEN_MAX:
            _seen.clear()
    _seen[key] = now
    return False


def _over_cap(site_label: str) -> bool:
    hour = int(time.time() // 3600)
    slot, count = _hourly.get(site_label, (hour, 0))
    if slot != hour:
        slot, count = hour, 0
    count += 1
    _hourly[site_label] = (slot, count)
    return count > _HOURLY_CAP


def device_of(user_agent: str) -> str:
    """User-Agent → pc|mobile|tablet. 원문은 저장하지 않는다."""
    ua = (user_agent or "").lower()
    if "ipad" in ua or ("android" in ua and "mobile" not in ua) or "tablet" in ua:
        return "tablet"
    if "mobi" in ua or "iphone" in ua or "android" in ua:
        return "mobile"
    return "pc"


def record_event(
    supabase: Client,
    *,
    kind: str,
    site_label: str,
    visitor_key: str | None,
    device: str,
    role: str,
    meeting_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> bool:
    """접속 이벤트 1건 기록. 기록했으면 True, 버렸으면 False. 예외를 밖으로 내지 않는다."""
    if kind not in KINDS:
        return False
    key = f"{visitor_key or site_label}|{kind}|{meeting_id or ''}|{(detail or {}).get('path', '')}"
    if _dedupe(key, kind):
        return False
    if _over_cap(site_label):
        logger.warning("접속 기록 시간당 상한 초과 — 버림 (접속처 %s)", site_label)
        return False

    now = now_kst()
    row = {
        "visit_date": now.date().isoformat(),
        "hour_kst": now.hour,
        "weekday_kst": now.weekday(),
        "site_label": site_label,
        "kind": kind,
        "device": device,
        "role": role,
        "seconds": WATCH_TICK_SECONDS if kind in WATCH_KINDS else 0,
        "visitor_key": visitor_key,
    }
    if meeting_id:
        row["meeting_id"] = meeting_id
    if detail:
        row["detail"] = detail
    try:
        supabase.table(TABLE).insert(row).execute()
        return True
    except Exception:
        logger.warning("access_events insert 실패 (마이그레이션 033 미적용?)", exc_info=True)
        return False


# ─── 집계 ────────────────────────────────────────────────────────────────────


def _rows(supabase: Client, view: str, start: str, extra_eq: tuple[str, str] | None = None) -> list[dict]:
    try:
        query = supabase.table(view).select("*").gte("visit_date", start)
        if extra_eq:
            query = query.eq(extra_eq[0], extra_eq[1])
        res = query.limit(20000).execute()
        return res.data or []
    except Exception:
        logger.warning("%s 조회 실패 (마이그레이션 033 미적용?)", view, exc_info=True)
        return []


def _num(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def first_collected_date(supabase: Client) -> str | None:
    """상세 기록이 쌓이기 시작한 날 — 화면에 '언제부터의 숫자인가'를 밝히기 위해."""
    try:
        res = (
            supabase.table(TABLE)
            .select("visit_date")
            .order("visit_date", desc=False)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0].get("visit_date")
    except Exception:
        logger.warning("access_events 첫 날짜 조회 실패", exc_info=True)
    return None


def now_watching(supabase: Client) -> int:
    """최근 5분 안에 시청 신호를 보낸 브라우저 수."""
    since = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    try:
        res = (
            supabase.table(TABLE)
            .select("visitor_key,kind")
            .gte("occurred_at", since)
            .limit(5000)
            .execute()
        )
    except Exception:
        return 0
    keys = {
        row.get("visitor_key")
        for row in (res.data or [])
        if row.get("kind") in WATCH_KINDS and row.get("visitor_key")
    }
    return len(keys)


def _meeting_titles(supabase: Client, ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    try:
        res = (
            supabase.table("meetings")
            .select("id,title,meeting_date,status")
            .in_("id", ids)
            .execute()
        )
        return {str(row["id"]): row for row in (res.data or [])}
    except Exception:
        logger.warning("회의 제목 조회 실패", exc_info=True)
        return {}


def build_stats(supabase: Client, days: int, site: str | None = None) -> dict:
    """접속 통계 한 묶음. site 를 주면 그 접속처만(드릴다운)."""
    days = max(1, min(days, 365))
    today = now_kst().date()
    start = (today - timedelta(days=days - 1)).isoformat()

    daily_rows = _rows(supabase, V_DAILY, start, ("site_label", site) if site else None)
    feature_rows = _rows(supabase, V_FEATURE, start, ("site_label", site) if site else None)
    meeting_rows = _rows(supabase, V_MEETING, start, ("site_label", site) if site else None)
    hourly_rows = [] if site else _rows(supabase, V_HOURLY, start)
    if site:
        # 시간대는 접속처별 뷰가 없다 — 원본에서 그 접속처만 센다(기간이 짧아 가볍다)
        hourly_rows = _site_hourly(supabase, start, site)

    # 일별
    by_date: dict[str, dict] = {}
    for row in daily_rows:
        d = str(row.get("visit_date"))
        acc = by_date.setdefault(d, {"date": d, "visitors": 0, "page_views": 0, "watch_seconds": 0, "login_prompts": 0})
        acc["visitors"] += _num(row.get("visitors"))
        acc["page_views"] += _num(row.get("page_views"))
        acc["watch_seconds"] += _num(row.get("watch_seconds"))
        acc["login_prompts"] += _num(row.get("login_prompts"))
    daily = [by_date.get((today - timedelta(days=i)).isoformat()) or
             {"date": (today - timedelta(days=i)).isoformat(), "visitors": 0, "page_views": 0,
              "watch_seconds": 0, "login_prompts": 0}
             for i in range(days - 1, -1, -1)]

    # 접속처
    by_site: dict[str, dict] = {}
    for row in daily_rows:
        label = str(row.get("site_label") or "외부")
        acc = by_site.setdefault(label, {"label": label, "visitors": 0, "page_views": 0, "watch_seconds": 0,
                                         "login_prompts": 0})
        acc["visitors"] += _num(row.get("visitors"))
        acc["page_views"] += _num(row.get("page_views"))
        acc["watch_seconds"] += _num(row.get("watch_seconds"))
        acc["login_prompts"] += _num(row.get("login_prompts"))
    sites = sorted(by_site.values(), key=lambda s: (-s["visitors"], s["label"]))
    visitors_total = sum(s["visitors"] for s in sites) or 0
    for s in sites:
        s["share"] = round(s["visitors"] / visitors_total * 100, 1) if visitors_total else 0.0

    # 시간대·요일
    hour_counts = [0] * 24
    week_hour = [[0] * 24 for _ in range(7)]
    for row in hourly_rows:
        hour = _num(row.get("hour_kst"))
        weekday = _num(row.get("weekday_kst"))
        visitors = _num(row.get("visitors"))
        if 0 <= hour < 24:
            hour_counts[hour] += visitors
            if 0 <= weekday < 7:
                week_hour[weekday][hour] += visitors

    # 기능·기기
    by_kind: dict[str, dict] = {}
    by_device: dict[str, int] = {}
    for row in feature_rows:
        kind = str(row.get("kind") or "")
        if kind in KINDS:
            acc = by_kind.setdefault(kind, {"kind": kind, "label": KINDS[kind], "events": 0, "visitors": 0})
            acc["events"] += _num(row.get("events"))
            acc["visitors"] += _num(row.get("visitors"))
        if kind != "login_prompt":
            device = str(row.get("device") or "pc")
            by_device[device] = by_device.get(device, 0) + _num(row.get("visitors"))
    features = sorted(by_kind.values(), key=lambda f: -f["events"])
    devices = [{"device": d, "visitors": v} for d, v in sorted(by_device.items(), key=lambda kv: -kv[1])]

    # 회의별
    by_meeting: dict[str, dict] = {}
    for row in meeting_rows:
        mid = str(row.get("meeting_id") or "")
        if not mid:
            continue
        acc = by_meeting.setdefault(mid, {"meeting_id": mid, "viewers": 0, "watch_seconds": 0})
        acc["viewers"] += _num(row.get("viewers"))
        acc["watch_seconds"] += _num(row.get("watch_seconds"))
    top_meetings = sorted(by_meeting.values(), key=lambda m: -m["watch_seconds"])[:10]
    titles = _meeting_titles(supabase, [m["meeting_id"] for m in top_meetings])
    for m in top_meetings:
        info = titles.get(m["meeting_id"], {})
        m["title"] = info.get("title") or "(제목 없음)"
        m["meeting_date"] = info.get("meeting_date")

    today_str = today.isoformat()
    today_row = by_date.get(today_str, {"visitors": 0, "page_views": 0, "watch_seconds": 0, "login_prompts": 0})
    watch_seconds_total = sum(d["watch_seconds"] for d in daily)
    prompt_total = sum(d["login_prompts"] for d in daily)

    return {
        "days": days,
        "from": start,
        "to": today_str,
        "site": site,
        "today": {
            "visitors": today_row["visitors"],
            "page_views": today_row["page_views"],
            "watch_seconds": today_row["watch_seconds"],
        },
        "now_watching": now_watching(supabase),
        "totals": {
            "visitors": visitors_total,
            "page_views": sum(d["page_views"] for d in daily),
            "watch_seconds": watch_seconds_total,
            "avg_daily_visitors": round(visitors_total / days, 1),
            "login_prompts": prompt_total,
        },
        "daily": daily,
        "sites": sites,
        "hourly": [{"hour": h, "visitors": hour_counts[h]} for h in range(24)],
        "weekday_hour": week_hour,
        "features": features,
        "devices": devices,
        "meetings": top_meetings,
        "insights": _insights(daily, sites, hour_counts, devices, features, watch_seconds_total),
        "detail_since": first_collected_date(supabase),
    }


def _site_hourly(supabase: Client, start: str, site: str) -> list[dict]:
    """드릴다운용 — 한 접속처의 시간대. 원본에서 필요한 칸만 읽어 파이썬에서 센다."""
    try:
        res = (
            supabase.table(TABLE)
            .select("hour_kst,weekday_kst,visitor_key,kind")
            .gte("visit_date", start)
            .eq("site_label", site)
            .limit(20000)
            .execute()
        )
    except Exception:
        return []
    seen: dict[tuple[int, int], set] = {}
    for row in res.data or []:
        if row.get("kind") == "login_prompt":
            continue
        key = (_num(row.get("weekday_kst")), _num(row.get("hour_kst")))
        seen.setdefault(key, set()).add(row.get("visitor_key"))
    return [
        {"weekday_kst": wd, "hour_kst": hour, "visitors": len(keys)}
        for (wd, hour), keys in seen.items()
    ]


def _insights(
    daily: list[dict],
    sites: list[dict],
    hour_counts: list[int],
    devices: list[dict],
    features: list[dict],
    watch_seconds_total: int,
) -> list[str]:
    """운영 판단에 바로 쓰이는 문장 셋. 숫자가 없으면 만들지 않는다."""
    out: list[str] = []
    total_visitors = sum(h for h in hour_counts)
    if total_visitors:
        busiest = max(range(24), key=lambda h: hour_counts[h])
        window = sum(hour_counts[max(0, busiest - 1):busiest + 2])
        share = round(window / total_visitors * 100)
        quietest = min(range(7, 24), key=lambda h: hour_counts[h])
        out.append(
            f"접속이 가장 몰리는 때는 {busiest}시 무렵입니다(앞뒤 1시간까지 전체의 {share}%). "
            f"낮에 손봐야 하면 {quietest}시가 가장 한산합니다."
        )
    if sites:
        outside = next((s for s in sites if s["label"] == "외부"), None)
        if outside and outside.get("share"):
            inside = round(100 - outside["share"], 1)
            out.append(
                f"접속의 {outside['share']}%가 의회 밖(외부)이고 의회 안에서 오는 접속은 {inside}% 입니다."
            )
    mobile = sum(d["visitors"] for d in devices if d["device"] in ("mobile", "tablet"))
    device_total = sum(d["visitors"] for d in devices)
    if device_total:
        out.append(
            f"휴대폰·태블릿 접속이 {round(mobile / device_total * 100)}% 입니다"
            + ("  — 모바일 화면을 먼저 살피는 편이 좋습니다." if mobile * 2 > device_total else ".")
        )
    if watch_seconds_total:
        hours = round(watch_seconds_total / 3600, 1)
        out.append(f"이 기간에 회의 영상을 본 시간은 모두 {hours}시간입니다.")
    return out[:4]


def purge_old(supabase: Client, keep_days: int = 180) -> int:
    """보존 기간이 지난 기록을 지운다. 지운 날짜 수를 돌려준다(하루 한 번 호출)."""
    cutoff = (now_kst().date() - timedelta(days=keep_days)).isoformat()
    try:
        supabase.table(TABLE).delete().lt("visit_date", cutoff).execute()
        return 1
    except Exception:
        logger.warning("access_events 정리 실패", exc_info=True)
        return 0


def today_iso() -> str:
    return now_kst().date().isoformat()


__all__ = [
    "KINDS",
    "WATCH_KINDS",
    "WATCH_TICK_SECONDS",
    "build_stats",
    "device_of",
    "purge_old",
    "record_event",
    "today_iso",
]
