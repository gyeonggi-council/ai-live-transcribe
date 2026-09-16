# -*- coding: utf-8 -*-
"""기존 회의에 의회 홈페이지(KMS) 목록 번호(kms_no) 백필.

KMS 최근회의영상 목록을 가져와 우리 DB 회의와 (날짜 + 위원회명 + 차수)로
정밀 매칭해 kms_no, kms_midx를 채운다. kms_midx 기반 매칭만으로는 과거
제목매칭으로 들어온 회의(midx=None)를 못 채우므로 제목 파싱으로 보완한다.

사용법: cd backend && python scripts/backfill_kms_no.py
"""
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from app.core.database import get_supabase_client
from app.services.kms_bulk_matcher import fetch_recent_vod_list

_COMMITTEE_RE = re.compile(r"([가-힣]+위원회|본회의)")
_ORDER_RE = re.compile(r"제\s*(\d+)\s*차")


def _key(committee: str | None, order, date: str) -> tuple:
    comm = (committee or "").replace(" ", "")
    return (date, comm, order)


async def main() -> None:
    sb = get_supabase_client()
    entries = await fetch_recent_vod_list(pages=2)
    # KMS 매칭 인덱스: (date, committee, order) -> entry
    kms_index: dict[tuple, dict] = {}
    for e in entries:
        kms_index[_key(e.get("committee"), e.get("session_order"), e["meeting_date"])] = e

    # vod_url 있는(=실제 회의) + 최근 회의 대상
    meetings = (
        sb.table("meetings")
        .select("id,title,meeting_date,kms_no,kms_midx,vod_url")
        .gte("meeting_date", "2026-06-01")
        .limit(300)
        .execute()
        .data
        or []
    )

    updated = 0
    skipped = 0
    nomatch = []
    for m in meetings:
        if m.get("kms_no"):
            skipped += 1
            continue
        title = m.get("title") or ""
        comm_match = _COMMITTEE_RE.search(title)
        order_match = _ORDER_RE.search(title)
        committee = comm_match.group(1) if comm_match else None
        order = int(order_match.group(1)) if order_match else None
        entry = kms_index.get(_key(committee, order, m["meeting_date"]))
        if not entry:
            if m.get("vod_url"):  # 영상 있는데 번호 매칭 실패만 보고
                nomatch.append(f"{m['meeting_date']} {title[:36]}")
            continue
        payload = {"kms_no": entry["list_num"]}
        if not m.get("kms_midx") and entry.get("kms_midx"):
            payload["kms_midx"] = str(entry["kms_midx"])
        sb.table("meetings").update(payload).eq("id", m["id"]).execute()
        updated += 1
        print(f"  no={entry['list_num']} <- {title[:42]}")

    print(f"\n[OK] 번호 채움 {updated}건, 이미 있음 {skipped}건, KMS 미매칭 {len(nomatch)}건")
    for s in nomatch:
        print("  (미매칭) " + s)


if __name__ == "__main__":
    asyncio.run(main())
