# -*- coding: utf-8 -*-
"""의원 프로필 보강 — 경기도의회 홈페이지에서 위원회 명부·약력을 가져온다.

의원정보 API(`councilor_sync`)가 주는 것은 이름·정당·선거구·사진뿐이다. 화면에서 필요한
나머지 둘은 홈페이지에만 있다:

  1. **위원회별 명부와 직책** — `/site/main/memberInfo/actvMmbr/list?menu=committee&miCommitteeCode={code}`
     상임위 13곳뿐 아니라 **예산결산특별위원회·윤리특별위원회(E020·E030·G007)** 도 여기에만 있다.
     `data/committee_rosters.json` 에 특별위원회가 0명으로 비어 있던 자리가 이것이다.
  2. **약력** — `/site/lwmkr/blog/{member_no}/12` 의 "약력 및 경력" 목록.

HTML 을 파싱하지만 BeautifulSoup 을 새로 들이지 않는다 — 대상 마크업이 `<ul class="memberList3">`
카드 반복 한 종류라 정규식으로 충분하고, 구조가 바뀌면 **빈 결과**가 나오지 도중에 틀린 값을
내지 않는다(호출부는 전부 fail-soft).
"""

from __future__ import annotations

import asyncio
import html as html_mod
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GGC_BASE = "https://www.ggc.go.kr"
_LIST_PATH = "/site/main/memberInfo/actvMmbr/list?menu=committee&miCommitteeCode={code}"
_BLOG_PATH = "/site/lwmkr/blog/{no}/12"

# 홈페이지는 기본 UA 요청을 차단한다(본문 대신 "보안 정책에 의해 차단" HTML 을 200 으로 돌려준다).
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": GGC_BASE + "/",
}

_TIMEOUT = 30.0

# 카드 한 장: 사진 · 이름+직책 · 정당 · 선거구 · 소속위원회직 · 의원홈페이지 링크
_CARD_RE = re.compile(
    r'<li>\s*<div class="img fl">.*?src="(?P<photo>[^"]+)".*?'
    r'<p class="f22[^"]*">(?P<name>[^<]+)<span class="f15">(?P<role>[^<]*)</span>.*?'
    r'<ul class="list_style01">(?P<meta>.*?)</ul>'
    r'(?:.*?href="(?P<home>/site/lwmkr/blog/\d+[^"]*)")?'
    r'.*?</li>',
    re.S,
)
_META_RE = re.compile(r'<li[^>]*>([^<]+)</li>')
_TAG_RE = re.compile(r"<[^>]+>")


def _text(s: str) -> str:
    return html_mod.unescape(_TAG_RE.sub(" ", s or "")).replace("\xa0", " ").strip()


def _abs(url: str | None) -> str | None:
    if not url:
        return None
    return url if url.startswith("http") else GGC_BASE + url


async def _get(client: httpx.AsyncClient, path: str) -> str:
    resp = await client.get(GGC_BASE + path, headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def parse_committee_page(html: str) -> list[dict[str, Any]]:
    """위원회 명단 페이지 HTML → [{name, role, party, district, photo_url, member_no}]."""
    body = html
    i = body.find('memberList3')
    if i > 0:
        body = body[i:]
    out: list[dict[str, Any]] = []
    for m in _CARD_RE.finditer(body):
        name = _text(m.group("name"))
        if not name or len(name) > 20:
            continue
        meta = [_text(x) for x in _META_RE.findall(m.group("meta") or "")]
        meta = [x for x in meta if x]
        home = m.group("home")
        no = None
        if home:
            mm = re.search(r"/blog/(\d+)", home)
            no = mm.group(1) if mm else None
        out.append({
            "name": name,
            "role": _text(m.group("role")) or "위원",
            "party": meta[0] if len(meta) > 0 else None,
            "district": meta[1] if len(meta) > 1 else None,
            "photo_url": _abs(m.group("photo")),
            "member_no": no,
            "homepage_url": _abs(home),
        })
    return out


def parse_career(html: str) -> list[str]:
    """의원 홈페이지 HTML → 약력 문자열 목록.

    본문은 `<div id="lawmakStory">` 한 곳이다. 그 안이 운영에서는 `<br>` 구분이고 개발환경에서는
    `<p>` 구분이라고 페이지 주석이 직접 밝히고 있어 **둘 다** 끊어 준다.
    """
    m = re.search(r'id="lawmakStory"[^>]*>(.*?)</div>', html, re.S)
    if not m:
        return []
    body = m.group(1)
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
    parts = re.split(r"</p>|<br\s*/?>", body, flags=re.I)
    items: list[str] = []
    for raw in parts:
        t = _text(raw)
        if 2 <= len(t) <= 200:
            items.append(t)
    seen: set[str] = set()
    uniq = [x for x in items if not (x in seen or seen.add(x))]
    return uniq[:40]


def parse_committee_positions(html: str) -> list[str]:
    """의원 홈페이지의 현재 위원회 직책 목록(`- 기획재정위원회 위원장`)."""
    m = re.search(r'<ul class="area main_01_content2_02">(.*?)</ul>', html, re.S)
    if not m:
        return []
    out = []
    for raw in re.findall(r"<li[^>]*>(.*?)</li>", m.group(1), re.S):
        t = _text(raw).lstrip("-").strip()
        if t:
            out.append(t)
    return out


async def fetch_committee_roster(code: str) -> list[dict[str, Any]]:
    """위원회 코드(C105·E020 …)로 명부를 가져온다. 실패 시 []."""
    if not code:
        return []
    try:
        async with httpx.AsyncClient() as client:
            html = await _get(client, _LIST_PATH.format(code=code))
        rows = parse_committee_page(html)
        if not rows:
            logger.warning("위원회 명부 파싱 결과 0명 — code=%s (마크업 변경 가능성)", code)
        return rows
    except Exception as e:
        logger.warning("위원회 명부 조회 실패 code=%s: %s", code, e)
        return []


async def fetch_career(member_no: str) -> dict[str, list[str]]:
    """의원 홈페이지 번호로 약력·위원회 직책을 가져온다. 실패 시 빈 목록."""
    if not member_no:
        return {"career": [], "positions": []}
    try:
        async with httpx.AsyncClient() as client:
            html = await _get(client, _BLOG_PATH.format(no=member_no))
        return {"career": parse_career(html), "positions": parse_committee_positions(html)}
    except Exception as e:
        logger.warning("약력 조회 실패 member_no=%s: %s", member_no, e)
        return {"career": [], "positions": []}


async def fetch_all_rosters(codes: list[str], concurrency: int = 3) -> dict[str, list[dict[str, Any]]]:
    """여러 위원회 명부를 제한된 동시성으로 가져온다(홈페이지 부담 최소화)."""
    sem = asyncio.Semaphore(concurrency)

    async def one(code: str) -> tuple[str, list[dict[str, Any]]]:
        async with sem:
            return code, await fetch_committee_roster(code)

    pairs = await asyncio.gather(*(one(c) for c in codes))
    return {c: rows for c, rows in pairs}


# ─── 위원회 명부 해석 (DB + 홈페이지 보강) ────────────────────────────────────
_roster_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_ROSTER_TTL = 6 * 3600


def _cache_get(key: str) -> list[dict[str, Any]] | None:
    import time as _t
    hit = _roster_cache.get(key)
    if hit and (_t.time() - hit[0]) < _ROSTER_TTL:
        return hit[1]
    return None


def _cache_put(key: str, rows: list[dict[str, Any]]) -> None:
    import time as _t
    _roster_cache[key] = (_t.time(), rows)


async def resolve_committee_members(
    supabase: Any, committee: str, committee_code: str | None = None
) -> list[dict[str, Any]]:
    """위원회 이름(+코드)으로 위원 명단을 만든다.

    상임위는 `councilors.committees` 로 충분하지만 **예산결산특별위원회·윤리특별위원회**는
    그 필드에 없다 — 의원정보 API 가 상임위만 주기 때문이다. 그래서 DB 로 찾지 못하면
    홈페이지 명단 페이지(코드 E020 등)를 읽어 **이름으로 DB 의원과 이어 붙인다**.
    사진·id 는 DB 것을 쓰고 직책은 홈페이지 것을 쓴다.
    """
    from app.services.councilor_sync import CouncilorSyncService

    svc = CouncilorSyncService(supabase)
    rows = svc.get_by_committee(committee) or []
    if rows:
        out = []
        for r in rows:
            role = "위원"
            for c in (r.get("committees") or []):
                if isinstance(c, dict) and _norm_name(c.get("name")) == _norm_name(committee):
                    role = c.get("role") or "위원"
                    break
            out.append({**r, "role": role})
        return _sort_by_role(out)

    if not committee_code:
        return []
    cached = _cache_get(committee_code)
    if cached is not None:
        return cached

    scraped = await fetch_committee_roster(committee_code)
    if not scraped:
        return []
    all_rows = svc.get_all_active() or []
    by_name = {_norm_name(r.get("name")): r for r in all_rows}
    out = []
    for m in scraped:
        db = by_name.get(_norm_name(m["name"]))
        if db:
            out.append({**db, "role": m["role"]})
        else:
            out.append({
                "id": None, "name": m["name"], "party": m["party"], "district": m["district"],
                "committees": [], "profile_image_url": m["photo_url"], "role": m["role"],
            })
    out = _sort_by_role(out)
    _cache_put(committee_code, out)
    return out


def _norm_name(x: str | None) -> str:
    return (x or "").replace(" ", "")


def _role_rank(role: str) -> int:
    role = role or ""
    if "위원장" in role and "부" not in role:
        return 0
    if "부위원장" in role:
        return 1
    return 2


def _sort_by_role(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: (_role_rank(r.get("role", "")), r.get("name") or ""))
