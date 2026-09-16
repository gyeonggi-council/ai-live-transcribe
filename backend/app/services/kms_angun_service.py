# -*- coding: utf-8 -*-
"""KMS 공식 발언자 인덱스 — 데스크톱 추출기 ggc_core.py 의 fetch_angun/build_speakers 이식

KMS(kms.ggc.go.kr) 영상회의록 페이지의 안건·발언 인덱스(listAngunXhr.do)를 읽어
의원별 발언 구간을 만든다. 구간 끝 = 다음 항목의 시작(m_pos), 마지막은 영상 길이.

실측(2026-09-03, midx 138270):
    {"m_sec":"00","m_code":"12057","m_mbr":"M","m_min":"24","m_hour":"00",
     "m_pos":"1474","m_angun":"자료요구(김지호 위원)"}
    m_mbr: M=의원 발언 · A=안건(코드=관련 의원) · N=집행부 · C=개의/산회
브라우저 UA·Referer 가 없으면 200 이지만 본문이 HTML 오류 페이지다(2026-07-21 이후) —
JSON 파싱 실패를 "인덱스 없음"으로 조용히 처리한다(fail-soft).
"""

from __future__ import annotations

import json
import logging
import re
import time
from difflib import SequenceMatcher
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.services.kms_vod_resolver import KMS_BROWSER_HEADERS

logger = logging.getLogger(__name__)

KMS_BASE = "https://kms.ggc.go.kr"
ANGUN_URL = KMS_BASE + "/caster/player/listAngunXhr.do?midx={midx}"
MEMBER_URL = KMS_BASE + "/pxdo/member_info.xdo?mcode={mcode}&daesu={daesu}"
DAESU_CHAIN = ("12", "11")

# 제목 안의 "(홍길동 위원)" — ggc_core.py:31 그대로. KMS 는 "위원장 인사(위원장 유종상)" 처럼
# 직책이 앞에 오는 표기도 쓴다(2026-09-03 실측, 윤리특위 138289) → 두 순서를 모두 받는다.
NAME_RE = re.compile(r"\(([가-힣]{2,10})\s*(위원장|부위원장|위원|의원|의장|부의장)\)")
_ROLE_FIRST_RE = re.compile(r"\((위원장|부위원장|위원|의원|의장|부의장)\s*([가-힣]{2,10})\)")


def find_name(title: str):
    """제목에서 (이름, 직책). '(홍길동 위원)' 과 '(위원장 홍길동)' 둘 다. 없으면 None."""
    m = NAME_RE.search(title or "")
    if m:
        return m.group(1), m.group(2)
    m = _ROLE_FIRST_RE.search(title or "")
    if m:
        return m.group(2), m.group(1)
    return None
_MEMBER_NAME_RE = re.compile(r"성\s*명\s*:\s*([가-힣]+)")

_ANGUN_CACHE: dict[str, tuple[float, list[dict]]] = {}
_MEMBER_NAME_CACHE: dict[str, Optional[str]] = {}


def clear_cache() -> None:
    _ANGUN_CACHE.clear()
    _MEMBER_NAME_CACHE.clear()


def _to_float(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def parse_angun(raw: Any) -> list[dict]:
    """KMS JSON 배열 → [{pos, time, title, code, mbr}] 시간순. 비-list 는 []."""
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for a in raw:
        if not isinstance(a, dict):
            continue
        out.append({
            "pos": _to_float(a.get("m_pos")),
            "time": f"{a.get('m_hour', '00')}:{a.get('m_min', '00')}:{a.get('m_sec', '00')}",
            "title": str(a.get("m_angun") or "").strip(),
            "code": str(a.get("m_code") or "").strip(),
            "mbr": str(a.get("m_mbr") or "").strip(),
        })
    out.sort(key=lambda x: x["pos"])
    return out


async def fetch_angun(midx: str, *, client: httpx.AsyncClient | None = None) -> list[dict]:
    """midx → 발언 인덱스. 실패·차단 페이지·비-list → [] (fail-soft). 인프로세스 TTL 캐시."""
    midx = str(midx or "").strip()
    if not midx.isdigit():
        return []
    ttl = max(0, settings.clip_index_cache_seconds)
    hit = _ANGUN_CACHE.get(midx)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]

    own = client is None
    client = client or httpx.AsyncClient(timeout=10.0)
    try:
        resp = await client.get(ANGUN_URL.format(midx=midx), headers=KMS_BROWSER_HEADERS)
        if resp.status_code != 200:
            logger.info("KMS 인덱스 응답 %s (midx=%s)", resp.status_code, midx)
            return []
        try:
            data = json.loads(resp.text)
        except ValueError:
            logger.info("KMS 인덱스가 JSON 이 아니다 — UA 차단 페이지일 수 있음 (midx=%s)", midx)
            return []
        items = parse_angun(data)
    except (httpx.HTTPError, OSError) as e:
        logger.info("KMS 인덱스 조회 실패 (midx=%s): %s", midx, e)
        return []
    finally:
        if own:
            await client.aclose()
    if items:
        _ANGUN_CACHE[midx] = (time.monotonic(), items)
    return items


async def fetch_member_name(mcode: str, *, client: httpx.AsyncClient | None = None) -> Optional[str]:
    """의원 코드 → 이름 (KMS member_info, 대수 12→11 폴백). 실패 시 None, 캐시."""
    mcode = str(mcode or "").strip()
    if not mcode:
        return None
    if mcode in _MEMBER_NAME_CACHE:
        return _MEMBER_NAME_CACHE[mcode]
    own = client is None
    client = client or httpx.AsyncClient(timeout=8.0)
    name: Optional[str] = None
    try:
        for daesu in DAESU_CHAIN:
            try:
                resp = await client.get(MEMBER_URL.format(mcode=mcode, daesu=daesu),
                                        headers=KMS_BROWSER_HEADERS)
            except (httpx.HTTPError, OSError):
                continue
            m = _MEMBER_NAME_RE.search(resp.text or "")
            if m:
                name = m.group(1)
                break
    finally:
        if own:
            await client.aclose()
    _MEMBER_NAME_CACHE[mcode] = name
    return name


def build_speakers(angun: list[dict], duration: float | None) -> list[dict]:
    """안건 인덱스를 의원별로 묶는다 (ggc_core.build_speakers 의 순수 부분).

    named=True  : 제목에 의원 이름이 있는 실제 발언 구간 (기본 선택)
    named=False : 같은 의원 코드가 붙은 의사진행/안건 항목 (기본 해제)
    이름이 끝내 없는 그룹(코드만 있고 명명된 항목이 없음)은 name="" 로 남긴다 —
    호출자가 fetch_member_name 으로 채우거나 버린다.
    """
    groups: dict[str, dict] = {}
    for i, a in enumerate(angun):
        if i + 1 < len(angun):
            end = angun[i + 1]["pos"]
        else:
            end = duration if duration else a["pos"]
        nm = find_name(a["title"])
        if not nm and not a["code"]:
            continue
        key = a["code"] or f"nm:{nm[0]}"
        g = groups.get(key)
        if g is None:
            g = groups[key] = {
                "key": key, "code": a["code"],
                "name": nm[0] if nm else "", "role": nm[1] if nm else "",
                "party": None, "district": None, "photo_url": None, "councilor_id": None,
                "segments": [], "total_seconds": 0.0,
            }
        if nm and not g["name"]:
            g["name"], g["role"] = nm[0], nm[1]
        seconds = max(0.0, float(end) - float(a["pos"]))
        g["segments"].append({
            "idx": i, "start": float(a["pos"]), "end": float(end), "seconds": seconds,
            "time": a["time"], "title": a["title"], "named": bool(nm),
        })
        g["total_seconds"] += seconds
    return sorted(groups.values(), key=lambda g: -g["total_seconds"])


def _norm(s: str) -> str:
    return (s or "").replace(" ", "")


def norm_name(name: str) -> str:
    return _norm(name)


def rank_councilors(name: str, councilors: list[dict], threshold: float = 0.75) -> list[tuple[float, dict]]:
    """이름 → [(점수, 명부 행)] 점수 내림차순. 정확 일치는 1.0, 나머지는 difflib 퍼지(STT 오인식 견딤).

    한글 이름은 3음절이 대부분이라 한 글자 오인식이 ratio 0.667 이다 —
    성(첫 글자)과 글자수가 같으면 0.1 을 얹어 통과시키고, 아니면 threshold(0.75) 를 요구한다.
    """
    n = _norm(name)
    if not n:
        return []
    ranked: list[tuple[float, dict]] = []
    for c in councilors:
        cand = _norm(str(c.get("name") or ""))
        if not cand:
            continue
        if cand == n:
            r = 1.0
        else:
            r = SequenceMatcher(None, n, cand).ratio()
            if cand[0] == n[0] and len(cand) == len(n):
                r = min(0.999, r + 0.1)
        if r >= threshold:
            ranked.append((r, c))
    ranked.sort(key=lambda t: -t[0])
    return ranked


def match_councilor(name: str, councilors: list[dict], threshold: float = 0.75) -> Optional[dict]:
    """이름 → 명부 행. 정확 일치 우선(동명이인이면 명부 첫 행), 없으면 퍼지.

    퍼지 결과가 동점이면 None — STT '김해철' 은 김회철·김철환 어느 쪽과도 한 글자 차이라
    아무나 고르면 다른 의원의 클립이 된다(2026-09-04 1차 본회의 실측).
    """
    ranked = rank_councilors(name, councilors, threshold)
    if not ranked:
        return None
    top_r = ranked[0][0]
    if len(ranked) > 1 and top_r < 1.0 and abs(top_r - ranked[1][0]) < 1e-9:
        return None
    return ranked[0][1]


def enrich_with_councilors(speakers: list[dict], councilors: list[dict]) -> list[dict]:
    """이름 키 매칭으로 party/district/photo_url/councilor_id/committees 를 채운다 (KMS 사진은 쓰지 않는다)."""
    for g in speakers:
        c = match_councilor(g.get("name") or "", councilors)
        if not c:
            continue
        g["party"] = c.get("party") or None
        g["district"] = c.get("district") or None
        g["photo_url"] = c.get("profile_image_url") or None
        g["councilor_id"] = c.get("id")
        # 소속 위원회 [{name, role}] — 카드에 겸임 상임위를 띄운다(2026-09-11 담당자 요청). 응답 키 **추가**만 —
        # 설치형 exe 가 읽는 기존 키는 그대로다(clip-index 응답은 계약)
        g["committees"] = [
            {"name": str(x.get("name") or "").strip(), "role": str(x.get("role") or "위원").strip()}
            for x in (c.get("committees") or []) if isinstance(x, dict) and str(x.get("name") or "").strip()
        ]
    return speakers


def pad_and_merge(segs: list[dict], pad_before: float, pad_after: float,
                  duration: float | None) -> list[dict]:
    """앞뒤 여유 적용 + 겹치는(1초 이내 인접 포함) 구간 병합. ggc_core.pad_and_merge 그대로.

    구간에 `no`(그 의원 구간 목록의 순번 = 파일 이름의 번호)가 있으면 따라가고,
    겹쳐서 합쳐진 구간은 앞 구간의 번호를 쓴다.
    """
    padded = sorted(
        ({"start": max(0.0, float(s["start"]) - float(pad_before)),
          "end": (min(float(duration), float(s["end"]) + float(pad_after))
                  if duration else float(s["end"]) + float(pad_after)),
          **({"no": int(s["no"])} if s.get("no") else {})}
         for s in segs),
        key=lambda s: s["start"])
    merged: list[dict] = []
    for s in padded:
        if merged and s["start"] <= merged[-1]["end"] + 1:
            merged[-1]["end"] = max(merged[-1]["end"], s["end"])
        else:
            merged.append(dict(s))
    return merged
