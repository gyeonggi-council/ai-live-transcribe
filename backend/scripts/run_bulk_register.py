"""KMS 일괄 등록 실행 (등록만, AI 비용 0) — [VOD 일괄 등록] 버튼과 동일.
새 로직으로 392회처럼 변환 전 회기를 제목·회기만 먼저 등록한다.
"""
import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import get_supabase_client  # noqa: E402
from app.services.kms_bulk_matcher import match_and_update  # noqa: E402


async def main():
    sb = get_supabase_client()
    res = await match_and_update(sb, regenerate_subtitles=False, pages=3)
    print("=== 일괄 등록 결과 ===")
    for k in ("kms_entries", "pending", "matched_count", "created_count",
              "promoted_count", "duplicate_count", "unmatched_count", "error_count"):
        print(f"  {k}: {res.get(k)}")
    if res.get("promoted"):
        print("\n[회기 먼저 표시(영상 변환 대기)]")
        for p in res["promoted"]:
            print(f"  - {p.get('new_title') or p.get('title')} ({p.get('reason')})")
    if res.get("created"):
        print("\n[신규 등록(영상 연결됨)]")
        for c in res["created"]:
            print(f"  - {c.get('title')}")
    if res.get("errors"):
        print("\n[오류]")
        for e in res["errors"][:10]:
            print(f"  - {e.get('title')}: {str(e.get('error'))[:80]}")


asyncio.run(main())
