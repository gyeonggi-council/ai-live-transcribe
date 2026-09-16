"""경기도의회 의원 명부 동기화 (실명 화자식별 전제조건)."""
import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import get_supabase_client
from app.services.councilor_sync import CouncilorSyncService


async def main():
    svc = CouncilorSyncService(get_supabase_client())
    result = await svc.sync_from_api()
    print("sync result:", result)
    # 검증: 활성 의원 수 + 위원회 분포
    rows = (
        get_supabase_client().table("councilors")
        .select("name,committee,party,active").execute().data
    )
    active = [r for r in rows if r.get("active", True)]
    print(f"councilors total={len(rows)} active={len(active)}")
    from collections import Counter
    comm = Counter((r.get("committee") or "(미지정)") for r in active)
    print("위원회별:")
    for c, n in comm.most_common(20):
        print(f"  {n:>3}  {c}")


asyncio.run(main())
