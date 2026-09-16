"""vod_url이 있고 자막이 0개인 회의를 최근순으로 출력 (STT 대상 선정)."""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import get_supabase_client

sb = get_supabase_client()
rows = sb.table("meetings").select(
    "id,title,vod_url,status,meeting_date,duration_seconds,created_at"
).execute().data


def subcount(mid):
    return sb.table("subtitles").select("id", count="exact").eq("meeting_id", mid).execute().count or 0


cand = []
for r in rows:
    if not r.get("vod_url"):
        continue
    n = subcount(r["id"])
    if n == 0:
        cand.append(r)

cand.sort(key=lambda r: (r.get("meeting_date") or "", r.get("created_at") or ""), reverse=True)
print(f"자막 0 + vod_url 있는 회의: {len(cand)}건 (최근순)")
for r in cand[:12]:
    d = r.get("duration_seconds")
    dm = f"{round(d/60)}분" if d else "?"
    print(f"  {r.get('meeting_date')}  {dm:>5}  {r['status']:<10}  {r['id']}  {(r.get('title') or '')[:30]}")
