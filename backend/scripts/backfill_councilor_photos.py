# -*- coding: utf-8 -*-
"""의원 사진 URL 백필 — ggc.go.kr 위원회별 페이지에서 수집해 profile_image_url 갱신

명부 시드(seed_councilors_official.py)는 사진을 다루지 않으므로,
제12대 전면 교체 후 신규 의원의 사진 URL을 이 스크립트로 채운다.
매칭: (이름, 선거구) → 실패 시 이름 단독(유일할 때만).

사용법: cd backend && python scripts/backfill_councilor_photos.py
"""
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client

from app.core.config import settings

BASE = "https://www.ggc.go.kr"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
COMMITTEE_CODES = [
    "C001", "C105", "C205", "C301", "C501", "C601", "C701",
    "C807", "C901", "C9043", "C905", "C908", "C909",
    "E020", "E030", "G007",
]

CARD_RE = re.compile(
    r'<img class="img-thumbnail"[^>]*src="([^"]+)"[^>]*/?>\s*'
    r'[\s\S]{0,400}?class="f22[^"]*">\s*([가-힣]{2,5})\s*(?:<span class="f15">[^<]*</span>)?\s*</p>'
    r'\s*<ul class="list_style01">([\s\S]*?)</ul>')
LI_RE = re.compile(r'<li class="f15 m0">\s*([^<]+?)\s*</li>')


def get(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", errors="replace")


def main() -> None:
    photos: dict[tuple[str, str], str] = {}
    for code in COMMITTEE_CODES:
        html = get(f"{BASE}/site/main/memberInfo/actvMmbr/list?menu=committee&miCommitteeCode={code}")
        for m in CARD_RE.finditer(html):
            src, name, body = m.group(1), m.group(2), m.group(3)
            lis = [re.sub(r"\s+", " ", x).strip() for x in LI_RE.findall(body)]
            district = next((x for x in lis if "선거구" in x or "비례" in x), "")
            if src and "noImage" not in src:
                photos[(name, district)] = src if src.startswith("http") else BASE + src
    print(f"수집: 사진 {len(photos)}건")

    supabase = create_client(settings.supabase_url, settings.supabase_key)
    rows = supabase.table("councilors").select("id,name,district,profile_image_url").eq(
        "is_active", True).execute().data or []
    by_name: dict[str, list[dict]] = {}
    for r in rows:
        by_name.setdefault(r["name"], []).append(r)

    updated = skipped = missing = 0
    for (name, district), url in photos.items():
        cands = by_name.get(name, [])
        target = next((r for r in cands if (r.get("district") or "") == district), None)
        if target is None and len(cands) == 1:
            target = cands[0]
        if target is None:
            missing += 1
            continue
        if target.get("profile_image_url") == url:
            skipped += 1
            continue
        supabase.table("councilors").update({"profile_image_url": url}).eq(
            "id", target["id"]).execute()
        updated += 1
    print(f"[OK] 갱신 {updated}, 동일 {skipped}, DB에 없음 {missing}")


if __name__ == "__main__":
    main()
