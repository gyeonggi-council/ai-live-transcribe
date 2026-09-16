# -*- coding: utf-8 -*-
"""GGC 위원회별 위원 명부 스크레이퍼 → data/committee_rosters.json.

경기도의회 홈페이지의 위원회별 현직 위원 명부를 신뢰원천으로 수집한다.
회의의 위원회가 정해지면 '그 위원회 위원만'을 이름 교정(name_corrector)·
글로서리 바이어스에 사용하기 위함(사용자 요구: 위원회 소속 위원만 참석).

페이지 구조: 위원 사진 <img class="img-thumbnail" alt="<이름><직책>"> 에서
이름+직책을 추출. 직책 ∈ {위원장, 부위원장, 위원}.

사용법: cd backend && python scripts/scrape_committee_rosters.py
"""
import json
import os
import re
import sys
import time

import httpx

# 위원회 코드 → 정식 명칭 (GGC 사이트 확인, 2026-06-16)
COMMITTEES: dict[str, str] = {
    "C001": "의회운영위원회",
    "C105": "기획재정위원회",
    "C205": "경제노동위원회",
    "C301": "안전행정위원회",
    "C501": "문화체육관광위원회",
    "C601": "농정해양위원회",
    "C701": "보건복지위원회",
    "C807": "건설교통위원회",
    "C901": "도시환경위원회",
    "C9043": "미래과학협력위원회",
    "C905": "여성가족평생교육위원회",
    "C908": "교육기획위원회",
    "C909": "교육행정위원회",
    "E020": "경기도청 예산결산특별위원회",
    "E030": "경기도교육청 예산결산특별위원회",
    "G007": "윤리특별위원회",
}

_URL = "https://www.ggc.go.kr/site/main/memberInfo/actvMmbr/list?menu=committee&miCommitteeCode={code}"
_ALT_RE = re.compile(r'class="img-thumbnail"\s+alt="([^"]+)"')
# 긴 직책부터 매칭(부위원장 > 위원장 > 위원). 간사 등 추가 직책 대비.
_ROLES = ["부위원장", "위원장", "간사", "위원"]


def _split_name_role(alt: str) -> tuple[str, str]:
    alt = alt.strip()
    for role in _ROLES:
        if alt.endswith(role):
            return alt[: -len(role)].strip(), role
    return alt, ""


def scrape_one(client: httpx.Client, code: str) -> list[dict]:
    r = client.get(_URL.format(code=code), timeout=20,
                   headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    members: list[dict] = []
    seen: set[str] = set()
    for alt in _ALT_RE.findall(r.text):
        name, role = _split_name_role(alt)
        if name and name not in seen:
            seen.add(name)
            members.append({"name": name, "role": role})
    return members


def main() -> None:
    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "data", "committee_rosters.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    result: dict = {}
    with httpx.Client(follow_redirects=True) as client:
        for code, name in COMMITTEES.items():
            try:
                members = scrape_one(client, code)
                result[name] = {"code": code, "members": members}
                print(f"[OK] {name} ({code}): {len(members)}명 — "
                      f"{', '.join(m['name'] for m in members)}")
            except Exception as e:
                print(f"[FAIL] {name} ({code}): {e}", file=sys.stderr)
            time.sleep(0.3)  # 예의상 간격
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    total = sum(len(v["members"]) for v in result.values())
    print(f"\n[저장] {out_path} — {len(result)}개 위원회, 총 {total}명(중복 포함)")


if __name__ == "__main__":
    main()
