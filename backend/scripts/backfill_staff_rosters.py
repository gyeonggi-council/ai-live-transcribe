# -*- coding: utf-8 -*-
"""위원회별 최근 임시속기록에서 집행부 명부(staff_roster) 백필.

KMS 최근목록(MntsLatelyList)에서 위원회별 최신 속기록을 찾아 본문을 받고,
출석 명단(출석공무원/출석전문위원)을 파싱해 staff_roster에 upsert한다.

사용:
    python scripts/backfill_staff_rosters.py                    # dry-run: 파싱 결과 출력만
    python scripts/backfill_staff_rosters.py --apply            # 실제 upsert (마이그레이션 024 적용 후)
    python scripts/backfill_staff_rosters.py --reset --apply    # staff_roster 전체 삭제 후 재백필
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import httpx

from app.services.staff_roster_service import (
    parse_steno_attendance,
    staff_glossary_terms,
    upsert_staff_roster,
)
from app.services.steno_service import _LIST_URL, _UA, _parse_list, fetch_steno_text


async def _latest_mnts_by_committee() -> dict[str, dict]:
    """최근목록에서 위원회별 최신 속기록 1건씩 (목록은 최신순 — 첫 등장이 최신)."""
    async with httpx.AsyncClient(timeout=30.0) as cli:
        r = await cli.get(_LIST_URL, headers=_UA, follow_redirects=True)
    entries = _parse_list(r.content.decode("utf-8", errors="replace"))
    latest: dict[str, dict] = {}
    for e in entries:
        committee = e.get("committee")
        if committee and committee not in latest:
            latest[committee] = e
    return latest


async def main() -> None:
    parser = argparse.ArgumentParser(description="위원회별 staff_roster 백필")
    parser.add_argument(
        "--apply", action="store_true",
        help="실제 upsert 수행 (기본은 dry-run: 파싱 결과 출력만)",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="백필 전 staff_roster 전체 삭제 (파서 개선 후 오염 행 정리용, --apply 필요)",
    )
    args = parser.parse_args()

    if args.reset and not args.apply:
        parser.error("--reset 은 --apply 와 함께 사용해야 합니다 (dry-run에서는 삭제 안 함).")

    latest = await _latest_mnts_by_committee()
    if not latest:
        print("최근 임시속기록 목록이 비어 있습니다.")
        return

    supabase = None
    if args.apply:
        from app.core.database import get_supabase_client
        supabase = get_supabase_client()

    if args.reset and supabase is not None:
        # Supabase REST delete 는 필터가 필수 — name 은 NOT NULL 이라 전체 행 매칭
        deleted = (
            supabase.table("staff_roster").delete().neq("name", "").execute().data
        )
        print(f"--reset: staff_roster {len(deleted or [])}행 삭제")

    total = 0
    for committee, info in sorted(latest.items()):
        mntsid = info["mntsid"]
        text = await fetch_steno_text(mntsid)
        if not text:
            print(f"[{committee}] mntsId={mntsid}: 본문 없음 — 건너뜀")
            continue
        entries = parse_steno_attendance(text)
        if not entries:
            print(f"[{committee}] mntsId={mntsid}: 출석 명단 없음 — 건너뜀")
            continue
        print(f"[{committee}] mntsId={mntsid} ({info.get('date')}): {len(entries)}명")
        for term in staff_glossary_terms(entries, cap=100):
            print(f"    {term}")
        if args.apply:
            n = upsert_staff_roster(supabase, committee, entries, source_mntsid=mntsid)
            total += n
            print(f"    → upsert {n}행")

    if args.apply:
        print(f"완료: 총 {total}행 upsert")
    else:
        print("dry-run 완료 (--apply 로 실제 upsert)")


if __name__ == "__main__":
    asyncio.run(main())
