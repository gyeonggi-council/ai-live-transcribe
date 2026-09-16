"""읽기 전용: KMS '최근회의영상' 목록을 지금 그대로 크롤해 출력.
392회가 KMS에 올라와 있는지, MP4 변환이 됐는지 확인한다. DB 변경 없음.
"""
import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.kms_bulk_matcher import fetch_recent_vod_list  # noqa: E402
from app.services.kms_vod_resolver import resolve_kms_vod_url  # noqa: E402


async def main():
    entries = await fetch_recent_vod_list(pages=4)
    print(f"KMS 최근회의영상 크롤 결과: {len(entries)}건\n")
    entries.sort(key=lambda e: (e.get("meeting_date") or "", e.get("list_num") or 0), reverse=True)
    for e in entries:
        print(
            f"  #{e.get('list_num'):<5} {e.get('meeting_date')} "
            f"제{e.get('session_no')}회 {e.get('session_order')}차 "
            f"midx={e.get('kms_midx')}  {e.get('title')}"
        )

    # 392회(또는 최신 날짜) 항목의 MP4 변환 여부 확인 — 상위 3건만 resolve 시도
    print("\n=== 최신 3건 MP4 변환 가능 여부 (resolve_kms_vod_url) ===")
    for e in entries[:3]:
        try:
            mp4 = await resolve_kms_vod_url(e["page_url"])
            print(f"  midx={e.get('kms_midx')} {e.get('title')[:30]} → OK {mp4[:70]}")
        except Exception as ex:
            print(f"  midx={e.get('kms_midx')} {e.get('title')[:30]} → 변환실패: {str(ex)[:80]}")


asyncio.run(main())
