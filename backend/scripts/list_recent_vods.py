"""KMS 최근 VOD 목록을 길이순으로 출력 (end-to-end 테스트용 후보 선정)."""
import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.kms_bulk_matcher import fetch_recent_vod_list


async def main():
    entries = await fetch_recent_vod_list()
    print(f"총 {len(entries)}건")
    entries.sort(key=lambda e: e.get("duration_seconds") or 0)
    for e in entries[:20]:
        d = e.get("duration_seconds") or 0
        print(f"{d:>6}s | {d//60:>3}m | {e.get('committee') or '-':<10} | {e['title'][:36]:<36} | {e['page_url']}")


asyncio.run(main())
