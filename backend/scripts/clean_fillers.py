"""기존 자막에서 추임새/백채널 토큰을 골라 삭제 (재실행 없이 정리).

사용: python scripts/clean_fillers.py <meeting_id> [--apply]
  기본은 dry-run(미삭제). --apply 시 실제 삭제.
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import get_supabase_client
from app.services.vod_stt_service import _is_filler

mid = sys.argv[1]
apply = "--apply" in sys.argv
sb = get_supabase_client()

rows = (
    sb.table("subtitles").select("id,start_time,text,speaker")
    .eq("meeting_id", mid).order("start_time").execute().data
)
fillers = [r for r in rows if _is_filler(r.get("text") or "")]
print(f"total={len(rows)} fillers={len(fillers)}")
for r in fillers[:40]:
    print(f"  {r['start_time']:>8}s [{r.get('speaker')}] {r['text']!r}")
if len(fillers) > 40:
    print(f"  ... (+{len(fillers) - 40} more)")

if apply and fillers:
    ids = [r["id"] for r in fillers]
    for i in range(0, len(ids), 100):
        sb.table("subtitles").delete().in_("id", ids[i:i + 100]).execute()
    after = sb.table("subtitles").select("id", count="exact").eq("meeting_id", mid).execute()
    print(f"DELETED {len(ids)} → remaining={after.count}")
elif fillers:
    print("(dry-run — 삭제하려면 --apply)")
