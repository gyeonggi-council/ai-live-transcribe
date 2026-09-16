# -*- coding: utf-8 -*-
"""경기도의회 공식 의원 명부 시드 (data/ggc_official_roster.json)

명부는 경기도의회 홈페이지 현역의원에서 추출한 공식 데이터다
(www.ggc.go.kr > 의원소개 > 현역의원, 인명별 + 위원회별 페이지 병합).
2026-07-20: 제12대 의회(2026-06 지방선거) 166명으로 전면 갱신 — 위원회별
페이지(menu=committee&miCommitteeCode=C001~C909)에서 소속·직책(위원장 등) 수집.

★배경: 기존 councilors 57명은 '자막에서 추출'된 것이라 24명(42%)이 STT
오인식 이름이었다 (예: 김태현/김태훈 — 실존 의원은 김태형/김태희).
오염된 명부는 이름 교정기(name_corrector)가 자막 속 올바른 이름을
가짜 이름으로 '교정'하게 만들므로, 공식 명부로의 교체는 이름 정확도의
전제 조건이다.

동작:
  - 공식 142명을 name(+district) 기준으로 업서트 (동명이인 김성수 2명은
    지역구로 구분)
  - 공식 명부에 없는 기존 행은 삭제 (voiceprint 참조가 있으면 비활성화)

사용법: cd backend && python scripts/seed_councilors_official.py
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client

from app.core.config import settings

ROSTER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "ggc_official_roster.json",
)


def seed() -> None:
    with open(ROSTER_PATH, encoding="utf-8") as f:
        roster = json.load(f)
    print(f"공식 명부 로드: {len(roster)}명")

    supabase = create_client(settings.supabase_url, settings.supabase_key)
    now = datetime.now(timezone.utc).isoformat()

    existing = supabase.table("councilors").select("id,name,district").execute().data or []
    by_name: dict[str, list[dict]] = {}
    for row in existing:
        by_name.setdefault(row["name"], []).append(row)

    official_names = {m["n"] for m in roster}
    stats = {"updated": 0, "inserted": 0, "deleted": 0, "deactivated": 0}

    for m in roster:
        committees = []
        for c in m.get("c", []):
            cname, _, crole = c.partition(":")
            committees.append({"name": cname, "role": crole or "위원"})
        row = {
            "name": m["n"],
            "party": m.get("p") or None,
            "district": m.get("d") or None,
            "committees": committees,
            "is_active": True,
            "term": 12,
            "synced_at": now,
        }
        candidates = by_name.get(m["n"], [])
        # 동명이인: 같은 지역구 행 우선, 없으면 아직 안 쓴 행 하나 소비
        target = next((r for r in candidates if r.get("district") == m.get("d")), None)
        if target is None and candidates:
            target = candidates[0]
        if target is not None:
            candidates.remove(target)
            supabase.table("councilors").update(row).eq("id", target["id"]).execute()
            stats["updated"] += 1
        else:
            supabase.table("councilors").insert(row).execute()
            stats["inserted"] += 1

    # 공식 명부에 없는 기존 행 정리 (STT 오인식으로 들어온 가짜 이름들)
    vp_refs = {
        r["councilor_id"]
        for r in (
            supabase.table("councilor_voiceprints").select("councilor_id").execute().data or []
        )
    }
    for row in existing:
        if row["name"] in official_names:
            continue
        if row["id"] in vp_refs:
            supabase.table("councilors").update({"is_active": False}).eq("id", row["id"]).execute()
            stats["deactivated"] += 1
        else:
            supabase.table("councilors").delete().eq("id", row["id"]).execute()
            stats["deleted"] += 1

    print(
        f"[OK] 갱신 {stats['updated']}, 신규 {stats['inserted']}, "
        f"가짜 삭제 {stats['deleted']}, 비활성화 {stats['deactivated']}"
    )


if __name__ == "__main__":
    seed()
