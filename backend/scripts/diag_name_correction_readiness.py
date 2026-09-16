"""C-2 이름교정 발동 가능성 진단 (READ-ONLY, 쓰기 없음).

C-2(name_corrector)는 회의 위원회 명부를 불러와야 발동한다. 명부 로드 경로:
  meetings.committee  ──(정확히 일치)──▶  councilors.committees[].name  (is_active=True)
둘 중 하나라도 비거나 문자열이 어긋나면 C-2는 조용히 no-op이 된다.

이 스크립트는 실제 Supabase 데이터를 읽어 "C-2가 실전에서 발동하는가"를 판정한다.
  ① councilors: 총원 / is_active / committees 배열 채워진 비율 / 위원회 분포
  ② meetings:   committee 채워진 비율 / 위원회 분포
  ③ 교차검증:   meeting 위원회별로 get_by_committee가 명부를 반환하는가(=발동 가능)

사용법(backend 디렉터리에서): python scripts/diag_name_correction_readiness.py
"""

from __future__ import annotations

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:
    pass

from app.core.database import get_supabase_client
from app.services.councilor_sync import CouncilorSyncService


def _committee_names(c: dict) -> list[str]:
    """councilor의 committees JSONB에서 위원회명 추출 (형식 방어적으로)."""
    raw = c.get("committees")
    out: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("name"):
                out.append(item["name"])
            elif isinstance(item, str):
                out.append(item)
    return out


def main() -> None:
    sb = get_supabase_client()
    svc = CouncilorSyncService(sb)

    # ① councilors
    councilors = sb.table("councilors").select("*").execute().data or []
    active = [c for c in councilors if c.get("is_active", True)]
    with_committee = [c for c in active if _committee_names(c)]
    print("=" * 64)
    print("① councilors")
    print(f"  총원={len(councilors)}  is_active={len(active)}  committees채움={len(with_committee)}")
    coun_comm = Counter(n for c in active for n in _committee_names(c))
    print(f"  councilor 위원회 종류={len(coun_comm)}")
    for name, n in coun_comm.most_common(20):
        print(f"     {n:>3}명  {name}")
    if not coun_comm:
        print("     ⚠ councilor에 committees가 전혀 없음 — C-2 명부 로드 불가!")

    # ② meetings
    meetings = sb.table("meetings").select("id,title,committee").execute().data or []
    m_with = [m for m in meetings if m.get("committee")]
    print("=" * 64)
    print("② meetings")
    print(f"  총 회의={len(meetings)}  committee채움={len(m_with)} ({len(m_with)/max(len(meetings),1):.0%})")
    meet_comm = Counter(m["committee"] for m in m_with)
    for name, n in meet_comm.most_common(20):
        print(f"     {n:>3}건  {name}")

    # ③ 교차검증: meeting 위원회별 명부 반환 여부 (= C-2 발동 가능)
    print("=" * 64)
    print("③ 교차검증 — meeting 위원회별 get_by_committee 명부 크기 (0이면 C-2 no-op)")
    ready = 0
    for name, n in meet_comm.most_common():
        try:
            roster = svc.get_by_committee(name)
        except Exception as e:
            print(f"     ❌ {name}: 조회 실패 {e}")
            continue
        rn = len(roster)
        mark = "✅" if rn else "❌"
        if rn:
            ready += 1
        sample = ", ".join(r.get("name", "?") for r in roster[:5])
        print(f"     {mark} {name}  명부={rn}명  회의={n}건  [{sample}]")
    print("=" * 64)
    print("판정")
    if not meet_comm:
        print("  ⚠ committee가 채워진 회의가 없음 → set_meeting_committees.py --apply 먼저 실행")
    elif ready == 0:
        print("  ❌ 모든 위원회에서 명부 0명 → C-2 발동 불가.")
        print("     원인: councilor.committees 미채움 또는 meeting↔councilor 위원회명 불일치.")
    elif ready < len(meet_comm):
        print(f"  ⚠ {ready}/{len(meet_comm)} 위원회만 명부 보유 — 나머지 회의는 C-2 no-op.")
    else:
        print(f"  ✅ 모든 위원회({ready}개)가 명부 보유 — C-2 실전 발동 가능.")
    print("=" * 64)


if __name__ == "__main__":
    main()
