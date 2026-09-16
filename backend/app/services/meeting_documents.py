"""부서별 회의 문서 — 담당자가 [문서 만들기]를 눌렀을 때만 만든다 (2026-09-15 담당자 요청·결정).

직원들이 회의 뒤 손으로 만들어 제출하던 문서를 회의 자막·요구자료로 초안까지 만든다. 서식은 담당자가 올린
기관이 쓰는 한글 서식 3종(업무보고 모니터링 · 자료요구 목록 · 요구자료 표지)을 표로 재현한다.
  monitoring    [서식1] 의원명(정당,지역) | 질 의 내 용 | 답 변 | 부서 — 의원 질의 턴마다 AI(루나 low)가 요지를 뽑는다
  datareq-list  [서식2] 연번 | 의원명 | 요 구 내 용 | 제출여부(빈칸) | 부서 — 자료요구(material_requests)에서, AI 없음
  datareq-cover [서식3] 【 ○○○ 의원 】 건명·내용·"□ 위 자료는 붙임과 같습니다."·자료 문의 표 — 요구 1건당 1장, 부서 묶음은 ZIP
  press         보도자료(일반 형식, 서식 없음) — 회의 요약으로 AI 초안, 인용은 자막 원문에 그대로 있을 때만
결정(9-15): 버튼으로만 · 표에 발언 시각 넣지 않음 · 권한은 요약과 같게(로그인 AI 역할 + 의회망) · 위원회 약칭 표 · 조국혁신당 '조'.
부서는 답변자 직함에서 뽑는다(인사과장→인사과, 김기덕 AI의정혁신팀장→AI의정혁신팀, 사무처장→의회사무처). 직원 명단(staff_roster)은 직함만 있어 보조로만 쓴다.
"""
from __future__ import annotations

import asyncio
import html
import io
import json
import logging
import re
import time
import zipfile
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

COMMITTEE_SHORT = {
    "의회운영위원회": "운영위", "기획재정위원회": "기재위", "안전행정위원회": "안행위", "도시환경위원회": "도환위",
    "경제노동위원회": "경노위", "보건복지위원회": "보복위", "문화체육관광위원회": "문체위", "농정해양위원회": "농해위",
    "건설교통위원회": "건교위", "교육행정위원회": "교행위", "여성가족평생교육위원회": "여가교위", "미래과학협력위원회": "미과위",
    "예산결산특별위원회": "예결위", "경기도청예산결산특별위원회": "예결위", "경기도교육청예산결산특별위원회": "예결위",
}
PARTY_SHORT = {"더불어민주당": "민", "국민의힘": "국", "조국혁신당": "조", "개혁신당": "개", "진보당": "진", "무소속": "무"}

_MEMBER_TOKENS = {"위원", "의원", "위원장", "부위원장", "의장", "부의장"}
_SUMMON_RE = re.compile(r"[가-힣]{2,4}\s*(?:의원|위원)님")
_TURN_END_RE = re.compile(r"(?:의원|위원|부위원장)님[,.\s]*(?:정말\s*)?(?:수고|고생)\s*(?:많이\s*)?하셨")
# 직함 → 부서 (앞이 긴 것부터)
_DEPT_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^(?:의회)?사무처장$"), "의회사무처"),
    (re.compile(r"^(?:수석)?전문위원$"), "전문위원실"),
    (re.compile(r"^대변인$"), "대변인"),
    (re.compile(r"^(.+)본부장$"), r"\1본부"),
    (re.compile(r"^(.+)센터장$"), r"\1센터"),
    (re.compile(r"^(.+)국장$"), r"\1국"),
    (re.compile(r"^(.+)과장$"), r"\1과"),
    (re.compile(r"^(.+)팀장$"), r"\1팀"),
    (re.compile(r"^(.+)실장$"), r"\1실"),
    (re.compile(r"^(.+)원장$"), r"\1원"),
    (re.compile(r"^(.+(?:담당관|협치관|기획관|정책관|감사관|조사관))$"), r"\1"),
]

_roster_cache: dict[str, dict] | None = None


# ── 표기 보조(순수) ─────────────────────────────────────────────────────────────
def committee_short(committee: str | None) -> str:
    c = re.sub(r"\s+", "", committee or "")
    return COMMITTEE_SHORT.get(c, c.replace("위원회", "위") if c else "회의")


def district_short(district: str | None) -> str:
    d = (district or "").strip()
    if "비례" in d:
        return "비례"
    m = re.match(r"^(\S+?)(?:시|군|구)?\s*제\s*(\d+)\s*선거구$", d)
    if m:
        return f"{m.group(1)}{m.group(2)}"
    m = re.match(r"^(\S+?)(?:시|군|구)\s*선거구$", d)
    return m.group(1) if m else d


def _official_roster() -> dict[str, dict]:
    """이름 → {n, p(정당), d(선거구)}. 저장소의 JSON 이 먼저, 없으면 DB councilors(현직).
    운영 이미지에는 backend/data 가 들어가지 않는다(Dockerfile 이 app·migrations 만 복사 — 2026-09-15 배포에서 확인)."""
    global _roster_cache
    if _roster_cache is None:
        data: dict[str, dict] = {}
        try:
            p = Path(__file__).resolve().parents[2] / "data" / "ggc_official_roster.json"
            data = {x["n"]: x for x in json.loads(p.read_text(encoding="utf-8")) if x.get("n")}
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning("의원 명단 JSON 읽기 실패: %s", e)
        if not data:
            try:
                from app.core.database import get_supabase

                rows = (get_supabase().table("councilors").select("name, party, district")
                        .eq("is_active", True).limit(1000).execute().data or [])
                data = {r["name"]: {"n": r["name"], "p": r.get("party"), "d": r.get("district")} for r in rows if r.get("name")}
            except Exception as e:  # 명단이 없어도 이름만으로 쓴다(다음 호출에 다시 시도)
                logger.warning("의원 명단 DB 조회 실패: %s", e)
                return {}
        _roster_cache = data
    return _roster_cache


def councilor_short(name: str) -> str:
    """'장한별' → '장한별 (민,수원4)' — 명단에 없으면 이름만."""
    row = _official_roster().get((name or "").strip())
    if not row:
        return name
    party = PARTY_SHORT.get(row.get("p") or "", (row.get("p") or "")[:1])
    dist = district_short(row.get("d"))
    inner = ",".join(x for x in (party, dist) if x)
    return f"{name} ({inner})" if inner else name


def _split_label(label: str) -> tuple[str, str]:
    """발언자 표기 → (이름, 직함). '진용국 사무처장'·'사무처장 진용국'·'김기덕 AI의정혁신팀장' 모두."""
    toks = (label or "").split()
    if len(toks) >= 2:
        a, b = toks[0], " ".join(toks[1:])
        if re.fullmatch(r"[가-힣]{2,4}", a) and not any(r.match(a) for r, _ in _DEPT_RULES):
            return a, b.replace(" ", "")
        return toks[-1], "".join(toks[:-1])
    return "", (toks[0] if toks else "")


def is_member_label(label: str | None) -> bool:
    toks = set((label or "").split())
    return bool(toks & {"위원", "의원"}) and not (toks & {"위원장", "부위원장", "의장", "부의장"})


def is_chair_label(label: str | None) -> bool:
    toks = set((label or "").split())
    return bool(toks & {"위원장", "의장"})


_TITLE_WORD = r"[가-힣A-Za-z0-9]{1,18}?(?:팀장|과장|국장|담당관|기획관|협치관|정책관|본부장|실장|센터장|사무처장|대변인)"
_INTRO_RES = [
    re.compile(rf"(?P<title>{_TITLE_WORD})\s*(?P<name>[가-힣]{{2,4}})입니다"),
    re.compile(rf"(?P<name>[가-힣]{{2,4}})\s+(?P<title>{_TITLE_WORD})입니다"),
]


def intro_titles(subs: list[dict]) -> dict[str, str]:
    """자막 속 자기소개·간부 소개에서 이름 → 직함("AI 의정혁신팀장 김기덕입니다", "박호순 의정국장입니다").
    발언자 표기가 "김기덕 팀장"·"이호구 홍보기관"처럼 부서를 알 수 없을 때 쓴다. 같은 이름은 긴 직함을 남긴다."""
    out: dict[str, str] = {}
    for sub in subs:
        text = re.sub(r"(?<=[A-Za-z])\s+(?=[가-힣])|(?<=[가-힣])\s+(?=[가-힣]*(?:팀장|과장|국장)입니다)", "", sub.get("text") or "")
        for rx in _INTRO_RES:
            for m in rx.finditer(text):
                name, title = m.group("name"), m.group("title").replace(" ", "")
                if len(title) > len(out.get(name, "")):
                    out[name] = title
    return out


def department_of_label(label: str | None, staff_titles: dict[str, str] | None = None) -> str | None:
    """답변자 표기 → 부서. 의원·위원장·'화자 N'·부서를 알 수 없는 표기는 None.
    표기의 직함으로 못 정하면(“김기덕 팀장”) 이름으로 직원 명단·자기소개의 직함을 찾아 본다."""
    if not label or is_member_label(label) or is_chair_label(label) or re.search(r"\d", label):
        return None
    name, title = _split_label(label)
    for cand in (title, (staff_titles or {}).get(name, "")):
        for rule, repl in _DEPT_RULES:
            if cand and rule.match(cand):
                dept = rule.sub(repl, cand)
                if len(dept) >= 2:
                    return dept
    return None


def label_departments(subs: list[dict], staff_titles: dict[str, str] | None = None) -> tuple[list[str], dict[str, str]]:
    """자막 발언자 표기에서 부서 목록(많이 나온 순)과 정규화 표. 음성 인식이 한 글자 틀린 드문 표기
    ('의장국'↔'의정국')는 자주 나온 비슷한 부서로 합친다(자모 유사도 0.8, 끝 글자 같을 때)."""
    from app.services.name_match import jamo

    counts: dict[str, int] = {}
    for sub in subs:
        d = department_of_label(sub.get("speaker"), staff_titles)
        if d:
            counts[d] = counts.get(d, 0) + 1
    ordered = sorted(counts, key=lambda d: -counts[d])
    canon: dict[str, str] = {}
    kept: list[str] = []
    for d in ordered:
        near = next((k for k in kept if k[-1] == d[-1] and len(k) == len(d) and counts[d] < counts[k]
                     and SequenceMatcher(None, jamo(d), jamo(k)).ratio() >= 0.85), None)
        canon[d] = near or d
        if not near:
            kept.append(d)
    return kept, canon


def canonical_department(dept: str, known: list[str], canon: dict[str, str]) -> str:
    """부서 표기 → 정규 부서. 표에 없어도(AI 가 적은 답변자 표기) 끝 글자·길이가 같고 자모가 비슷한 기존 부서로 맞춘다."""
    from app.services.name_match import jamo

    if dept in canon:
        return canon[dept]
    return next((k for k in known if k[-1] == dept[-1] and len(k) == len(dept)
                 and SequenceMatcher(None, jamo(dept), jamo(k)).ratio() >= 0.8), dept)


def normalize_department(raw: str | None, known: list[str]) -> str:
    """자유 표기('의회 사무처', '소통협치관, 의회 사무처') → 알려진 부서 이름. 못 맞추면 첫 표기 그대로(없으면 '미분류')."""
    first = re.split(r"[,/·및]", raw or "")[0]
    c = re.sub(r"\s+", "", first)
    if not c:
        return "미분류"
    if c in known:
        return c
    for k in known:
        if c in k or k in c:
            return k
    best = max(known, key=lambda k: SequenceMatcher(None, c, k).ratio(), default=None)
    if best and SequenceMatcher(None, c, best).ratio() >= 0.7:
        return best
    return c


def _cell(text: str) -> str:
    return html.escape((text or "").strip()).replace("\n", "<br>")


def _date_parts(meeting: dict) -> tuple[str, str]:
    """('260914', "'26.9.14")"""
    try:
        d = datetime.fromisoformat(str(meeting.get("meeting_date"))[:10])
    except ValueError:
        d = datetime.now(KST)
    return d.strftime("%y%m%d"), f"'{d.strftime('%y')}.{d.month}.{d.day}"


def _has_report(meeting: dict, agendas: list[dict]) -> bool:
    return "업무보고" in (meeting.get("title") or "") or any("업무보고" in (a.get("title") or "") for a in agendas)


# ── 의원 질의 턴 ────────────────────────────────────────────────────────────────
def member_turns(subs: list[dict]) -> list[dict]:
    """의원 발언부터 다음 의원 발언 전까지 한 턴(공무원 답변 포함). 위원장의 짧은 끼어들기는 턴에 남기고,
    다른 의원을 부르거나 끝인사("…위원님 수고하셨습니다")·80자 이상 진행 발언이면 턴을 닫는다."""
    turns: list[dict] = []
    cur: dict | None = None
    for s in subs:
        lab = s.get("speaker") or ""
        text = s.get("text") or ""
        if is_member_label(lab):
            name = lab.split()[0]
            if cur and cur["member"] == name:
                cur["rows"].append(s)
                continue
            cur = {"member": name, "rows": [s]}
            turns.append(cur)
        elif cur is not None:
            if is_chair_label(lab) and (len(text) >= 80 or _SUMMON_RE.search(text) or _TURN_END_RE.search(text)):
                cur = None
                continue
            cur["rows"].append(s)
    out = []
    for t in turns:
        answered = any(not is_member_label(r.get("speaker")) and not is_chair_label(r.get("speaker")) for r in t["rows"])
        chars = sum(len(r.get("text") or "") for r in t["rows"])
        if answered or chars >= 200:
            out.append(t)
    return out


_MONITOR_PROMPT = """당신은 경기도의회 위원회 회의 모니터링 담당자입니다. 주어진 것은 회의 자막 중 의원 질의 턴들이며 각 턴은 [턴 N] 으로 시작합니다.
턴마다 다음 JSON 항목을 만드세요.
{"items":[{"turn":N,"question":"○ 질의 요지","answer":"○ 답변 요지","answerer":"답변한 사람의 발언자 표기 그대로(예: 진용국 사무처장)"}]}
규칙:
- 개조식으로 짧게(항목당 1~2문장, "~함/~요청/~지적" 체). 질의가 여러 개면 줄을 바꿔 ○ 를 붙여 최대 3개.
- 답변이 없으면 answer 와 answerer 는 빈 문자열.
- 원문에 없는 내용·수치·이름을 만들지 마세요. 인사·절차 발언만 있는 턴은 items 에서 빼세요.
- 한국어, 유효한 JSON 만 출력."""

_extract_cache: dict[str, tuple[float, str, list[dict]]] = {}
_EXTRACT_TTL = 6 * 3600
_daily: dict[str, int] = {}


def _reserve_daily() -> None:
    day = datetime.now(KST).date().isoformat()
    for k in [k for k in _daily if k != day]:
        del _daily[k]
    if _daily.get(day, 0) >= settings.doc_extract_daily_limit:
        raise DocumentLimitError(f"오늘 AI 문서 생성 한도({settings.doc_extract_daily_limit}건)를 다 썼습니다. 내일 다시 시도해 주세요.")
    _daily[day] = _daily.get(day, 0) + 1


class DocumentLimitError(Exception):
    pass


class NoDataError(Exception):
    pass


_UNIT_CHARS = 6000


def _turn_units(k: int, t: dict) -> list[str]:
    """턴을 AI 입력 단위로 — 6,000자를 넘는 턴은 자르지 않고 여러 단위로 나눈다(뒤쪽 답변이 빠지던 것, Codex 검토).
    나뉜 단위는 같은 턴 번호로 가고, 각 단위의 항목이 모두 표에 들어간다."""
    head = f"[턴 {k}] {t['member']} 위원"
    units: list[str] = []
    cur: list[str] = []
    size = len(head)
    for r in t["rows"]:
        line = f"{r.get('speaker') or '화자 미확인'}: {r.get('text') or ''}"
        while len(line) > _UNIT_CHARS - len(head) - 20:          # 한 줄이 너무 길면 줄 자체를 나눈다
            cut = _UNIT_CHARS - len(head) - 20
            if cur:
                units.append("\n".join([head + (" (이어서)" if units else "")] + cur))
                cur, size = [], len(head)
            units.append("\n".join([head + (" (이어서)" if units else ""), line[:cut]]))
            line = line[cut:]
        if cur and size + len(line) + 1 > _UNIT_CHARS:
            units.append("\n".join([head + (" (이어서)" if units else "")] + cur))
            cur, size = [], len(head)
        cur.append(line)
        size += len(line) + 1
    if cur:
        units.append("\n".join([head + (" (이어서)" if units else "")] + cur))
    return units


async def extract_monitoring(subs: list[dict], fingerprint: str, meeting_id: str,
                             staff_titles: dict[str, str] | None = None) -> list[dict]:
    """[{member, question, answer, answerer, department, start_time}] — 회의·자막 지문별 6시간 캐시(부서만 바꿔 받으면 비용 0)."""
    from app.services.summary_service import _call_openai_json

    # 같은 회의를 여러 사람이 동시에 받으면 추출은 한 번만 — 잠금 안에서 캐시를 다시 본다(Codex 검토)
    async with _locks.setdefault(meeting_id, asyncio.Lock()):
        hit = _extract_cache.get(meeting_id)
        if hit and hit[1] == fingerprint and time.monotonic() - hit[0] < _EXTRACT_TTL:
            return hit[2]
        return await _extract_monitoring_locked(subs, fingerprint, meeting_id, staff_titles)


_locks: dict[str, asyncio.Lock] = {}


async def _extract_monitoring_locked(subs: list[dict], fingerprint: str, meeting_id: str,
                                     staff_titles: dict[str, str] | None) -> list[dict]:
    from app.services.summary_service import _call_openai_json

    turns = member_turns(subs)
    if not turns:
        raise NoDataError("의원 질의가 있는 구간을 찾지 못했습니다.")
    staff_titles = {**intro_titles(subs), **{k: v for k, v in (staff_titles or {}).items() if v}}
    known_depts, canon = label_departments(subs, staff_titles)
    _reserve_daily()
    batches: list[list[str]] = []
    cur: list[str] = []
    size = 0
    for k, t in enumerate(turns):
        for unit in _turn_units(k, t):
            if cur and size + len(unit) > _UNIT_CHARS:
                batches.append(cur)
                cur, size = [], 0
            cur.append(unit)
            size += len(unit)
    if cur:
        batches.append(cur)
    sem = asyncio.Semaphore(8)

    async def one(batch: list[str]) -> list[dict]:
        async with sem:
            user = "\n\n".join(batch)
            try:
                parsed = await _call_openai_json(
                    _MONITOR_PROMPT, user, model=settings.summary_map_model, max_tokens=4000, timeout=90.0,
                    reasoning_effort=settings.summary_map_reasoning_effort)
            except Exception as e:  # 한 묶음 실패는 다시 한 번
                logger.warning("모니터링 추출 재시도: %s", e)
                parsed = await _call_openai_json(
                    _MONITOR_PROMPT, user, model=settings.summary_map_model, max_tokens=4000, timeout=90.0,
                    reasoning_effort=settings.summary_map_reasoning_effort)
            return [i for i in (parsed.get("items") or []) if isinstance(i, dict)]

    results = await asyncio.gather(*(one(b) for b in batches))
    items: list[dict] = []
    for got in results:
        for it in got:
            try:
                k = int(it.get("turn"))
            except (TypeError, ValueError):
                continue
            if not (0 <= k < len(turns)) or not str(it.get("question") or "").strip():
                continue
            t = turns[k]
            answerer = str(it.get("answerer") or "").strip()
            # 답변자가 둘 이상이면("이민재 총무과장, 박호순 의정국장") 부서도 각각 — 부서별로 뽑으면 양쪽에 다 나온다
            depts = []
            for a in re.split(r"\s*(?:,|·|/|및|와|과)\s+|\s*,\s*", answerer):
                d = department_of_label(a.strip(), staff_titles)
                if d:
                    d = canonical_department(d, known_depts, canon)
                    if d not in depts:
                        depts.append(d)
            if not depts:  # 답변자 표기를 못 읽으면 그 턴의 첫 공무원 표기
                first = next((department_of_label(r.get("speaker"), staff_titles) for r in t["rows"]
                              if department_of_label(r.get("speaker"), staff_titles)), None)
                depts = [canonical_department(first, known_depts, canon)] if first else []
            items.append({"member": t["member"], "question": str(it["question"]).strip(),
                          "answer": str(it.get("answer") or "").strip(), "answerer": answerer,
                          "departments": depts or ["미분류"], "department": ", ".join(depts) or "미분류",
                          "start_time": t["rows"][0].get("start_time")})
    items.sort(key=lambda x: x["start_time"] or 0)
    _extract_cache[meeting_id] = (time.monotonic(), fingerprint, items)
    return items


# ── 문서 마크다운(순수) ────────────────────────────────────────────────────────
def _title_table(text: str) -> str:
    """제목 한 줄을 1×1 표로 — 서식([서식1]·[서식2])이 제목을 문단이 아니라 **표 칸**에 담는다.

    그래야 서식 프로필의 첫 표(제목 상자: 테두리·음영·19pt 경기천년제목)가 여기에 붙는다.
    `# 제목` 헤딩으로 두면 프로필 표 순번이 밀려 본표 서식까지 함께 어긋난다.
    """
    # 따옴표는 이스케이프하지 않는다 — 제목의 '26.9.14 가 &#x27; 로 바뀌면 읽기 나쁘다.
    return "<table>\n<tr><td>%s</td></tr>\n</table>" % html.escape(text.strip(), quote=False)


def body_rows(markdown: str) -> int:
    """본표(마지막 <table>)의 행 수 — 서식 프로필의 행 수를 여기에 맞춘다."""
    blocks = markdown.split("<table>")
    return blocks[-1].count("<tr>") if len(blocks) > 1 else 0

def monitoring_markdown(meeting: dict, agendas: list[dict], items: list[dict], department: str | None) -> tuple[str, str]:
    """(마크다운, 파일 제목). 같은 의원이 이어지면 의원명 칸을 합친다(rowspan)."""
    short = committee_short(meeting.get("committee"))
    ymd, dot = _date_parts(meeting)
    kind = "업무보고 " if _has_report(meeting, agendas) else ""
    rows = [i for i in items if not department or department in (i.get("departments") or [i["department"]])]
    if not rows:
        raise NoDataError(f"'{department}' 부서에 답변한 질의가 없습니다." if department else "모니터링할 질의가 없습니다.")
    # 부서 이름은 파일명에만 넣는다 — 서식에는 그런 줄이 없다(2026-09-16 서식 실측).
    head = _title_table(f"{short} {kind}모니터링({dot})") + "\n\n"
    out = ["<table>", "<tr><th>의원명</th><th>질 의 내 용</th><th>답 변</th><th>부서</th></tr>"]
    k = 0
    while k < len(rows):
        j = k
        while j + 1 < len(rows) and rows[j + 1]["member"] == rows[k]["member"]:
            j += 1
        span = j - k + 1
        for idx in range(k, j + 1):
            r = rows[idx]
            name_cell = ""
            if idx == k:
                who = councilor_short(r["member"]).replace(" (", "<br>(")
                name_cell = f'<td rowspan="{span}">{who}</td>' if span > 1 else f"<td>{who}</td>"
            out.append(f"<tr>{name_cell}<td>{_cell(r['question'])}</td><td>{_cell(r['answer'])}</td>"
                       f"<td>{_cell(r['department'])}</td></tr>")
        k = j + 1
    out.append("</table>")
    title = f"{ymd} {short} 모니터링({kind.strip() or '회의'})" + (f"_{department}" if department else "")
    return head + "\n".join(out) + "\n", title


def datareq_rows(requests: list[dict], known_depts: list[str], department: str | None) -> list[dict]:
    rows = []
    for r in sorted(requests, key=lambda x: x.get("start_time") or 0):
        if r.get("status") == "dismissed":
            continue
        dept = normalize_department(r.get("department"), known_depts)
        if department and dept != department:
            continue
        name = (r.get("councilor_name") or (r.get("speaker") or "").split(" ")[0] or "").strip()
        rows.append({**r, "dept": dept, "name": name})
    return rows


def datareq_list_markdown(meeting: dict, agendas: list[dict], rows: list[dict], department: str | None) -> tuple[str, str]:
    if not rows:
        raise NoDataError("자료요구가 없습니다. 회의 화면의 [요구자료] 탭에서 요구자료 찾기를 먼저 해 주세요.")
    short = committee_short(meeting.get("committee"))
    ymd, dot = _date_parts(meeting)
    kind = "업무보고 " if _has_report(meeting, agendas) else ""
    out = [_title_table(f"{short} {kind}자료요구 목록({dot}.)"), ""]
    out += ["<table>", "<tr><th>연번</th><th>의원명</th><th>요 구 내 용</th><th>제출여부</th><th>부서</th></tr>"]
    for n, r in enumerate(rows, 1):
        who = councilor_short(r["name"]).replace(" (", "<br>(") if r["name"] else ""
        out.append(f"<tr><td>{n}</td><td>{who}</td><td>{_cell(r.get('summary') or r.get('request_text') or '')}</td>"
                   f"<td></td><td>{_cell(r['dept'])}</td></tr>")
    out.append("</table>")
    title = f"{ymd} {short} 자료요구 목록" + (f"_{department}" if department else "")
    return "\n".join(out) + "\n", title


def cover_fill(req: dict) -> tuple[dict, list[dict], str]:
    """요구자료 표지 — (라벨 값, 블록 편집, 파일 제목).

    이 문서만 마크다운을 안 쓴다. [서식3] 파일 자체에 값을 채우면(ggc_doc `/fill`)
    글꼴·표·여백이 원본 그대로라 서식과 100% 같다.
      values : 표 안의 라벨-값 칸(건명·내용)
      edits  : 표 밖 문단 — 【 ㅇㅇㅇ 의원 】 은 라벨이 아니라 제목 줄이라 블록 번호로 바꾼다(첫 블록).
    """
    name = (req.get("name") or req.get("councilor_name") or "").strip() or "ㅇㅇㅇ"
    subject = (req.get("summary") or "").strip() or "요구자료"
    body = (req.get("request_text") or req.get("summary") or "").strip()
    values = {"건명": subject, "내용": body}
    edits = [{"blockIndex": 0, "newText": f"【 {name} 의원 】"}]
    safe = re.sub(r'[\\/:*?"<>|]+', " ", subject)[:40].strip()
    return values, edits, f"[표지] {name} 의원 요구자료({safe})"


def cover_markdown(req: dict) -> tuple[str, str]:
    """[서식3] 파일을 못 쓸 때의 대비책(이미지에 서식이 없거나 /fill 이 실패했을 때)."""
    name = (req.get("name") or req.get("councilor_name") or "").strip() or "ㅇㅇㅇ"
    subject = (req.get("summary") or "").strip() or "요구자료"
    body = (req.get("request_text") or req.get("summary") or "").strip()
    md = "\n".join([
        f"# 【 {name} 의원 】", "",
        "<table>",
        f"<tr><th>건명</th><td>{_cell(subject)}</td></tr>",
        f"<tr><th>내용</th><td>{_cell(body)}</td></tr>",
        "</table>", "",
        "□ 위 자료는 붙임과 같습니다.", "",
        "<table>",
        '<tr><th rowspan="3">자료<br>문의</th><th>구 분</th><th>직 위(급)</th><th>성 명</th><th>전 화</th></tr>',
        "<tr><td>담당사무관</td><td>ㅇㅇ팀장</td><td></td><td></td></tr>",
        "<tr><td>담 당 자</td><td>주무관</td><td></td><td></td></tr>",
        "</table>", "",
    ])
    safe = re.sub(r'[\\/:*?"<>|]+', " ", subject)[:40].strip()
    return md, f"[표지] {name} 의원 요구자료({safe})"


def zip_bytes(files: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files:
            n, k = name, 2
            while n in used:
                n = f"{name[:-5]} ({k}).hwpx"
                k += 1
            used.add(n)
            z.writestr(n, data)
    return buf.getvalue()


def quote_in_speaker(quote: dict, subs: list[dict]) -> bool:
    """인용문이 **그 발언자**의 이어진 자막 안에 그대로 있는가(공백 무시). 다른 사람의 문장이면 False."""
    who = (str(quote.get("speaker") or "").split() or [""])[0]
    text = re.sub(r"\s+", "", str(quote.get("text") or ""))
    if not who or len(text) < 4:
        return False
    runs: list[str] = []
    cur, prev = [], None
    for sub in subs:
        name = ((sub.get("speaker") or "").split() or [""])[0]
        if name != prev and cur:
            runs.append("".join(cur))
            cur = []
        if name == who:
            cur.append(re.sub(r"\s+", "", sub.get("text") or ""))
        prev = name if name == who else None
    if cur:
        runs.append("".join(cur))
    return any(text in r for r in runs)


_PRESS_PROMPT = """당신은 경기도의회 보도자료 작성 담당자입니다. 주어진 회의 요약과 주요 결정으로 보도자료 초안을 JSON 으로 만드세요.
{"title":"제목(35자 이내)","subtitles":["부제 1","부제 2"],"lead":"리드 문단(누가·언제·무엇을, 2~3문장)",
 "paragraphs":["본문 문단", "..."],"quote":{"speaker":"발언자 표기","text":"자막에 있는 말 그대로"}}
규칙: 요약·자막에 없는 사실·수치를 만들지 마세요. 본문은 3~5문단. 인용은 아래 '발언 원문 후보'에 있는 문장만 그대로 쓰고, 마땅치 않으면 quote 는 null.
한국어, 유효한 JSON 만 출력."""


async def press_release(meeting: dict, summary: dict, subs: list[dict]) -> tuple[str, str]:
    from app.services.summary_service import _call_openai_json

    if not summary or not summary.get("summary_text"):
        raise NoDataError("회의 요약이 없습니다. 요약을 먼저 만들어 주세요.")
    _reserve_daily()
    short = committee_short(meeting.get("committee"))
    ymd, _ = _date_parts(meeting)
    quotes = [f"{s.get('speaker')}: {s.get('text')}" for s in subs
              if len(s.get("text") or "") >= 40 and is_member_label(s.get("speaker"))][:60]
    user = "\n".join([
        f"회의: {meeting.get('title')} ({meeting.get('meeting_date')}) · 위원회: {meeting.get('committee') or ''}",
        "요약: " + (summary.get("summary_text") or ""),
        "안건별: " + " / ".join(f"{a.get('title')}: {a.get('summary')}" for a in (summary.get("agenda_summaries") or [])),
        "주요 결정: " + " / ".join(summary.get("key_decisions") or []),
        "후속 조치: " + " / ".join(summary.get("action_items") or []),
        "발언 원문 후보:", *quotes,
    ])[:12000]
    p = await _call_openai_json(_PRESS_PROMPT, user, model=settings.summary_model, max_tokens=4000, timeout=90.0,
                                reasoning_effort=settings.summary_reasoning_effort)
    quote = p.get("quote") if isinstance(p.get("quote"), dict) else None
    if quote and not quote_in_speaker(quote, subs):
        quote = None                     # 그 발언자의 자막에 그대로 없는 인용은 버린다(남의 말을 이 의원 인용으로 넣지 않게)
    d = str(meeting.get("meeting_date") or "")[:10]
    lines = [
        "<table>",
        "<tr><th>보도자료</th><td>AI 초안 — 사실 확인 필요</td></tr>",
        f"<tr><th>배포일시</th><td>{html.escape(d)}</td></tr>",
        f"<tr><th>담당부서</th><td>{html.escape(meeting.get('committee') or '')}</td></tr>",
        "<tr><th>담당자</th><td></td></tr>", "<tr><th>연락처</th><td></td></tr>",
        "</table>", "",
        f"# {str(p.get('title') or meeting.get('title') or '').strip()}", "",
    ]
    lines += [f"- {str(s).strip()}" for s in (p.get("subtitles") or []) if str(s).strip()][:3]
    lines += ["", str(p.get("lead") or "").strip(), ""]
    for para in p.get("paragraphs") or []:
        if str(para).strip():
            lines += [f"□ {str(para).strip()}", ""]
    if quote:
        lines += [f"○ {str(quote.get('speaker') or '').strip()}: \"{str(quote.get('text')).strip()}\"", ""]
    return "\n".join(lines), f"{ymd} {short} 보도자료(초안)"
