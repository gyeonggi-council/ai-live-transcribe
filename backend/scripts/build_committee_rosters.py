# -*- coding: utf-8 -*-
"""data/committee_rosters.json 재생성 — ggc.go.kr 위원회별 페이지 크롤

★이 파일은 roster_loader가 councilors DB보다 우선하는 신뢰원천이다.
의회 명부가 바뀌면(선거·사보임) 반드시 이 스크립트로 재생성해야 한다 —
DB(seed_councilors_official.py)만 갱신하면 라이브 교정·VOD 화자귀속이
여전히 옛 위원장/위원 이름을 쓴다 (2026-07-20 조성환/김창식 사고).

사용법: cd backend && python scripts/build_committee_rosters.py
"""
import json
import os
import re
import sys
import urllib.request

BASE = "https://www.ggc.go.kr"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "data", "committee_rosters.json")

CARD_RE = re.compile(
    r'class="f22[^"]*">\s*([가-힣]{2,5})\s*(?:<span class="f15">([^<]*)</span>)?\s*</p>')
NAV_RE = re.compile(
    r'href="/site/main/memberInfo/actvMmbr/list\?menu=committee&(?:amp;)?miCommitteeCode=([A-Z]\d+)">([^<]+)</a>')

ROLE_ORDER = {"위원장": 0, "부위원장": 1}


def get(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", errors="replace")


def main() -> None:
    nav_html = get(f"{BASE}/site/main/memberInfo/actvMmbr/list?menu=committee&miCommitteeCode=C001")
    committees = {}
    for m in NAV_RE.finditer(nav_html):
        committees[m.group(1)] = re.sub(r"\s+", " ", m.group(2)).strip()

    out: dict = {}
    for code, cname in committees.items():
        html = nav_html if code == "C001" else get(
            f"{BASE}/site/main/memberInfo/actvMmbr/list?menu=committee&miCommitteeCode={code}")
        members = []
        seen = set()
        for m in CARD_RE.finditer(html):
            name, badge = m.group(1), (m.group(2) or "").strip()
            if name in seen:
                continue
            seen.add(name)
            members.append({"name": name, "role": badge or "위원"})
        members.sort(key=lambda x: (ROLE_ORDER.get(x["role"], 2), x["name"]))
        out[cname] = {"code": code, "members": members}
        print(f"{code} {cname}: {len(members)}명"
              + (f" (위원장 {members[0]['name']})" if members and members[0]['role'] == '위원장' else ""))

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[OK] 저장: {OUT} — 위원회 {len(out)}개")


if __name__ == "__main__":
    main()
