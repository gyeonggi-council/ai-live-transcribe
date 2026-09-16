"""의사일정 수집 서비스 — 경기도의회 의정캘린더에서 회기·회의·안건을 가져온다.

왜 필요했나 (2026-08-31):
  라이브 회의가 `"{위원회명} 생중계"` 라는 제목으로만 생겨 **어느 회기에도 속하지 못했다.**
  회의 목록은 제목의 '제N회'로 회기를 묶는데(frontend `vod/page.tsx`), 그 문자열이 없으니
  라이브 회의가 목록에서 미아가 됐다. 앞으로 열릴 회의를 미리 알 방법도 없었다.

두 출처를 역할로 나눠 쓴다 — 하나로는 부족하다:
  1) live.ggc.go.kr `getOnairListTodayData.do` (JSON) → adTh(회차)·adCha(차수)가 **정본**.
     구조화돼 있어 파싱이 안전하지만 안건도 회기 종류(임시회/정례회)도 없다.
  2) www.ggc.go.kr 의정캘린더 (HTML) → 시간·안건·회기 종류 + **월 단위 예정**이 여기에만 있다.

파싱 방식이 두 곳에서 다른 것은 의도다:
  - **월 달력은 정규식**으로 `fn_calList(DD,'CODE')` 링크만 훑는다. `<li class="day schdl schdl ">`
    처럼 클래스가 중복·공백으로 흔들리고, 휴회일에도 `schdl` 이 붙어(9/4~9/17 실측)
    DOM 구조를 믿으면 오탐한다. 링크는 흔들리지 않는다.
  - **일자 상세는 HTMLParser**. `<td class="left">` 안에 `<br/>` 로 줄이 나뉘어 있어
    정규식으로는 안건을 깔끔히 못 가른다.

의존성을 새로 넣지 않았다 — 표 하나 읽자고 BeautifulSoup 를 들이지 않는다.
이 백엔드에는 HTML 파서 의존성이 하나도 없고, 그 상태를 유지한다.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Iterable, Optional

import httpx

from app.core.channels import get_all_channels
from app.services.channel_status import ONAIR_API_URL

logger = logging.getLogger(__name__)

CALENDAR_URL = "https://www.ggc.go.kr/site/main/schedule/list/{date}/ALL"

# 의회 홈페이지는 기본 UA 로 요청하면 보안정책 안내 페이지를 200 으로 돌려준다.
# 브라우저 UA 를 보내야 실제 문서가 온다(KMS 에서도 겪은 동일한 함정).
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

HTTP_TIMEOUT = 20.0

# 달력의 위원회 링크 — javascript:fn_calList(01,'A011')
_CAL_LINK_RE = re.compile(
    r"fn_calList\(\s*0*(\d{1,2})\s*,\s*'([A-Za-z]\w*)'\s*\)", re.IGNORECASE
)
# 안건 문구에서 회기 — "제393회 임시회 회기 결정"
_SESSION_RE = re.compile(r"제\s*(\d{2,4})\s*회\s*(임시회|정례회)?")
# 안건 줄머리 — "1. ", "2) "
_AGENDA_NUM_RE = re.compile(r"^\s*\d+\s*[.)]\s*")

# 유효한 위원회 코드 — 채널 설정이 아는 코드만 받는다.
# 달력에는 우리가 방송을 받지 않는 코드도 나오는데, 그것까지 저장하면
# 화면에 '알 수 없는 위원회' 줄이 생긴다.
# ★모듈 상수가 아니라 함수다 — 채널이 DB 에서 오므로 import 시점에 계산하면
#   (캐시가 아직 비어 있어) **빈 집합으로 굳어** 수집한 의사일정을 전부 버린다.
#   그러면 라이브 회의 제목의 회기·차수가 사라진다.
def _known_codes() -> set[str]:
    return {c["code"] for c in get_all_channels() if c.get("code")}


# ──────────────────────────────────────────────────────────────────────────
# 파싱
# ──────────────────────────────────────────────────────────────────────────
class _DayTableParser(HTMLParser):
    """일자 상세표(`table.calendar_tb`)의 `<tr class="{코드} table_tr">` 를 읽는다.

    행 구조(실측 2026-09-01):
        <tr class="A011 table_tr">
          <td>본회의</td>
          <td> 11:00 </td>
          <td class="left">□ 본회의(11:00)<br/>1. 제393회 임시회 회기 결정<br/>2. …</td>
        </tr>

    세 번째 칸은 `<br/>` 가 줄바꿈이므로 텍스트를 모을 때 개행으로 바꿔 둔다.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, Any]] = []
        self._code: Optional[str] = None
        self._cells: list[str] = []
        self._buf: list[str] = []
        self._in_td = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        a = dict(attrs)
        if tag == "tr":
            classes = (a.get("class") or "").split()
            # class="A011 table_tr" — 첫 토큰이 위원회 코드
            if "table_tr" in classes:
                self._code = next((c for c in classes if c != "table_tr"), None)
                self._cells = []
        elif tag == "td" and self._code:
            self._in_td = True
            self._buf = []
        elif tag == "br" and self._in_td:
            self._buf.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        # <br/> 는 handle_starttag 가 아니라 이쪽으로 온다
        if tag == "br" and self._in_td:
            self._buf.append("\n")
        else:
            self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self._in_td:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._in_td:
            self._in_td = False
            self._cells.append("".join(self._buf))
        elif tag == "tr" and self._code:
            if len(self._cells) >= 3:
                self.rows.append(
                    {
                        "committee_code": self._code,
                        "committee_name": _clean(self._cells[0]),
                        "start_time": _clean(self._cells[1]) or None,
                        "agenda_items": _split_agenda(self._cells[2]),
                        "agenda_raw": _clean(self._cells[2].replace("\n", " ")),
                    }
                )
            self._code = None
            self._cells = []


def _clean(text: str) -> str:
    """공백·비가시 문자를 한 칸으로 접어 다듬는다."""
    return re.sub(r"[\s ]+", " ", text or "").strip()


def _split_agenda(cell: str) -> list[str]:
    """처리안건 칸을 안건 목록으로 가른다.

    `□ 본회의(11:00)` 는 안건이 아니라 그 칸의 머리글이라 버린다.
    번호가 붙은 줄이 하나도 없으면(형식이 다른 위원회) 머리글 아닌 줄을 그대로 쓴다.
    """
    lines = [_clean(x) for x in (cell or "").split("\n")]
    lines = [x for x in lines if x]
    numbered = [_AGENDA_NUM_RE.sub("", x) for x in lines if _AGENDA_NUM_RE.match(x)]
    if numbered:
        return numbered
    return [x for x in lines if not x.startswith("□")]


def parse_day_html(html: str) -> list[dict[str, Any]]:
    """일자 페이지 HTML → 그날의 회의 목록. 아는 위원회 코드만 남긴다."""
    parser = _DayTableParser()
    parser.feed(html)
    out = []
    for row in parser.rows:
        if row["committee_code"] not in _known_codes():
            logger.debug("의사일정: 모르는 위원회 코드 건너뜀 %s", row["committee_code"])
            continue
        session_no, session_kind = _extract_session(row["agenda_raw"])
        row["session_no"] = session_no
        row["session_kind"] = session_kind
        out.append(row)
    return out


def _extract_session(text: str) -> tuple[Optional[int], Optional[str]]:
    """안건 문구에서 회기 번호와 종류를 뽑는다 — '제393회 임시회' → (393, '임시회')."""
    m = _SESSION_RE.search(text or "")
    if not m:
        return None, None
    return int(m.group(1)), m.group(2)


def parse_month_html(html: str) -> dict[int, list[tuple[str, str]]]:
    """월 달력 HTML → {일(day): [(위원회코드, 위원회명), …]}.

    링크만 본다 — `<li>` 의 class 는 휴회일에도 `schdl` 이 붙어 믿을 수 없다(9/4~9/17 실측).
    """
    result: dict[int, list[tuple[str, str]]] = {}
    for m in _CAL_LINK_RE.finditer(html):
        day, code = int(m.group(1)), m.group(2)
        if code.upper() == "ALL" or code not in _known_codes():
            continue  # 'ALL' 은 그 날짜를 여는 링크일 뿐 회의가 아니다
        # 링크 텍스트가 위원회명
        tail = html[m.end() : m.end() + 300]
        name_m = re.search(r">\s*([^<>]{1,40}?)\s*<", tail)
        name = _clean(name_m.group(1)) if name_m else code
        result.setdefault(day, [])
        if not any(c == code for c, _ in result[day]):
            result[day].append((code, name))
    return result


# ──────────────────────────────────────────────────────────────────────────
# 수집
# ──────────────────────────────────────────────────────────────────────────
async def fetch_calendar_html(client: httpx.AsyncClient, target: date) -> str:
    resp = await client.get(
        CALENDAR_URL.format(date=target.isoformat()),
        headers={"User-Agent": BROWSER_UA, "Referer": "https://www.ggc.go.kr/"},
    )
    resp.raise_for_status()
    return resp.text


async def fetch_onair(client: httpx.AsyncClient, target: date) -> dict[str, dict[str, int]]:
    """생중계 일정 API → {위원회코드: {session_no, session_order}}. 회차·차수의 정본."""
    try:
        resp = await client.post(
            ONAIR_API_URL,
            data={"ymd": target.isoformat()},
            headers={
                "Referer": "https://live.ggc.go.kr/",
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest",
                "User-Agent": BROWSER_UA,
                "Accept": "application/json, text/javascript, */*; q=0.01",
            },
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:  # 일정 API 가 죽어도 달력만으로 계속 간다
        logger.warning("의사일정: 생중계 일정 API 실패 (%s): %s", target, e)
        return {}

    out: dict[str, dict[str, int]] = {}
    for item in data or []:
        code = item.get("adCode") or ""
        if not code:
            continue
        out[code] = {
            "session_no": item.get("adTh") or None,
            "session_order": item.get("adCha") or None,
        }
    return out


def agenda_hash(row: dict[str, Any]) -> str:
    """내용 해시 — 이 값이 같으면 '바뀐 것이 없다'."""
    payload = json.dumps(
        {
            "name": row.get("committee_name"),
            "time": row.get("start_time"),
            "session_no": row.get("session_no"),
            "session_order": row.get("session_order"),
            "kind": row.get("session_kind"),
            "agenda": row.get("agenda_items") or [],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


async def collect(days_ahead: int = 7, today: Optional[date] = None) -> list[dict[str, Any]]:
    """오늘부터 days_ahead 일까지의 의사일정을 모은다 (DB 접근 없음 — 순수 수집).

    월 달력을 먼저 받아 **회의가 있는 날만** 상세를 조회한다. 빈 날까지 두드리면
    의회 홈페이지에 하루 7번씩 무의미한 요청을 보내게 된다.
    """
    today = today or date.today()
    targets = [today + timedelta(days=i) for i in range(max(1, days_ahead))]

    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        # 1) 걸치는 달(보통 1~2개)의 달력으로 '회의 있는 날'을 추린다
        months = sorted({(d.year, d.month) for d in targets})
        has_meeting: set[date] = set()
        for year, month in months:
            probe = next(d for d in targets if (d.year, d.month) == (year, month))
            try:
                html = await fetch_calendar_html(client, probe)
            except Exception as e:
                logger.warning("의사일정: 달력 조회 실패 (%d-%02d): %s", year, month, e)
                continue
            for day in parse_month_html(html).keys():
                try:
                    d = date(year, month, day)
                except ValueError:
                    continue
                if d in targets:
                    has_meeting.add(d)

        if not has_meeting:
            logger.info("의사일정: %s ~ %s 예정된 회의 없음", targets[0], targets[-1])
            return []

        # 2) 회의가 있는 날만 상세 + 회차·차수 보강
        for d in sorted(has_meeting):
            try:
                html = await fetch_calendar_html(client, d)
            except Exception as e:
                logger.warning("의사일정: 일자 조회 실패 (%s): %s", d, e)
                continue
            onair = await fetch_onair(client, d)
            for row in parse_day_html(html):
                sched = onair.get(row["committee_code"], {})
                # 회차는 생중계 API 가 정본, 안건 문구는 폴백
                row["session_no"] = sched.get("session_no") or row.get("session_no")
                row["session_order"] = sched.get("session_order")
                row["schedule_date"] = d.isoformat()
                rows.append(row)

    _fill_session_kind(rows)
    for row in rows:
        row["agenda_hash"] = agenda_hash(row)
    return rows


def _fill_session_kind(rows: list[dict[str, Any]]) -> None:
    """같은 회기의 다른 날에서 회기 종류(임시회/정례회)를 옮겨 채운다.

    회기 종류는 **개회일 안건에만** 적힌다 — '1. 제393회 임시회 회기 결정'. 이튿날부터는
    '1. 대집행부 질문' 뿐이라(실측 2026-09-02·03) 그날만 보면 종류를 알 수 없다.
    화면이 "제393회 임시회"라고 일관되게 쓰려면 회기 번호로 이어 줘야 한다.
    """
    kind_by_session = {
        r["session_no"]: r["session_kind"]
        for r in rows
        if r.get("session_no") and r.get("session_kind")
    }
    for row in rows:
        if not row.get("session_kind"):
            row["session_kind"] = kind_by_session.get(row.get("session_no"))


# ──────────────────────────────────────────────────────────────────────────
# 저장 — 안건은 수시로 바뀐다. 매번 다시 맞춘다.
# ──────────────────────────────────────────────────────────────────────────
def _upsert(supabase, rows: list[dict[str, Any]], dates: Iterable[str]) -> dict[str, int]:
    """수집 결과를 DB 에 반영한다.

    `changed_at` 과 `synced_at` 을 나눈 것이 요점이다 — **"방금 확인했다"와 "안건이
    바뀌었다"는 다른 사건**이다. 30분마다 도는 루프가 매번 changed_at 을 밀면
    화면에서 "언제 바뀐 일정인지"를 영영 알 수 없다.
    """
    now = datetime.now(timezone.utc).isoformat()
    stat = {"added": 0, "changed": 0, "unchanged": 0, "cancelled": 0}

    date_list = sorted(set(dates))
    existing_rows = (
        supabase.table("assembly_schedule")
        .select("id, schedule_date, committee_code, agenda_hash, is_cancelled")
        .in_("schedule_date", date_list)
        .execute()
        .data
        or []
    )
    by_key = {(r["schedule_date"][:10], r["committee_code"]): r for r in existing_rows}
    seen: set[tuple[str, str]] = set()

    for row in rows:
        key = (row["schedule_date"], row["committee_code"])
        seen.add(key)
        payload = {
            "schedule_date": row["schedule_date"],
            "committee_code": row["committee_code"],
            "committee_name": row["committee_name"],
            "start_time": row.get("start_time"),
            "session_no": row.get("session_no"),
            "session_order": row.get("session_order"),
            "session_kind": row.get("session_kind"),
            "agenda_items": row.get("agenda_items") or [],
            "agenda_hash": row["agenda_hash"],
            "is_cancelled": False,
            "synced_at": now,
        }
        prev = by_key.get(key)
        if prev is None:
            payload["changed_at"] = now
            supabase.table("assembly_schedule").insert(payload).execute()
            stat["added"] += 1
            continue

        if prev.get("agenda_hash") == row["agenda_hash"] and not prev.get("is_cancelled"):
            # 내용 동일 — 확인 시각만 갱신한다
            supabase.table("assembly_schedule").update({"synced_at": now}).eq(
                "id", prev["id"]
            ).execute()
            stat["unchanged"] += 1
            continue

        payload["changed_at"] = now
        supabase.table("assembly_schedule").update(payload).eq("id", prev["id"]).execute()
        stat["changed"] += 1
        logger.info(
            "의사일정 변경: %s %s (%s) — 안건 %d건",
            row["schedule_date"],
            row["committee_name"],
            row["committee_code"],
            len(row.get("agenda_items") or []),
        )

    # 달력에서 사라진 것 — 지우지 않고 취소로 표시한다. 사라졌다는 사실도 정보다.
    for key, prev in by_key.items():
        if key in seen or prev.get("is_cancelled"):
            continue
        supabase.table("assembly_schedule").update(
            {"is_cancelled": True, "changed_at": now, "synced_at": now}
        ).eq("id", prev["id"]).execute()
        stat["cancelled"] += 1
        logger.info("의사일정 취소 감지: %s %s", key[0], key[1])

    return stat


def _refresh_live_meeting_titles(supabase, rows: list[dict[str, Any]]) -> int:
    """오늘 이미 만들어진 라이브 회의의 회차가 바뀌었으면 제목까지 함께 고친다.

    회차·차수는 회의 당일에도 바뀐다(1차 종료 후 2차 편성). 일정만 갱신하고 회의를
    두면 목록의 회기 묶음이 어긋난 채로 남는다.
    """
    from app.core.channels import get_channel_by_code
    from app.services.live_meeting import build_live_title

    updated = 0
    today = date.today().isoformat()
    for row in rows:
        if row["schedule_date"] != today or not row.get("session_no"):
            continue
        channel = get_channel_by_code(row["committee_code"])
        if not channel:
            continue
        try:
            res = (
                supabase.table("meetings")
                .select("id, title, session_no, session_order")
                .eq("channel_id", channel["id"])
                .eq("meeting_date", today)
                .is_("kms_no", "null")
                .eq("status", "live")
                .limit(1)
                .execute()
            )
            if not res.data:
                continue
            m = res.data[0]
            if m.get("session_no") == row["session_no"] and m.get("session_order") == row.get(
                "session_order"
            ):
                continue
            title = build_live_title(
                channel["name"], row["session_no"], row.get("session_order"), today
            )
            supabase.table("meetings").update(
                {
                    "title": title,
                    "session_no": row["session_no"],
                    "session_order": row.get("session_order"),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            ).eq("id", m["id"]).execute()
            updated += 1
            logger.info("의사일정: 진행 중 회의 제목 갱신 — %s", title)
        except Exception as e:
            logger.warning("의사일정: 회의 제목 갱신 실패 (%s): %s", row["committee_code"], e)
    return updated


async def sync(days_ahead: int = 7) -> dict[str, int]:
    """수집 → 저장. 실패해도 예외를 밖으로 내보내지 않는다.

    일정 수집이 자막 파이프라인을 막는 일은 없어야 한다.
    """
    try:
        rows = await collect(days_ahead=days_ahead)
    except Exception as e:
        logger.warning("의사일정 수집 실패: %s", e)
        return {"added": 0, "changed": 0, "unchanged": 0, "cancelled": 0, "error": 1}

    today = date.today()
    dates = [(today + timedelta(days=i)).isoformat() for i in range(max(1, days_ahead))]

    try:
        from app.core.database import get_supabase_client

        supabase = get_supabase_client()
        stat = await asyncio.to_thread(_upsert, supabase, rows, dates)
        stat["title_updated"] = await asyncio.to_thread(
            _refresh_live_meeting_titles, supabase, rows
        )
        return stat
    except Exception as e:
        logger.warning("의사일정 저장 실패: %s", e)
        return {"added": 0, "changed": 0, "unchanged": 0, "cancelled": 0, "error": 1}
