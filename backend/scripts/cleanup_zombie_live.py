"""좀비 라이브 회의 정리: 어제 이전 날짜인데 status='live'로 남은 회의를 ended로.

현재 방송 중인 회의(오늘/어제 날짜)는 건드리지 않는다. 기본 dry-run.
사용: python scripts/cleanup_zombie_live.py [--apply]
"""
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import get_supabase_client  # noqa: E402

apply = "--apply" in sys.argv
sb = get_supabase_client()

# 오늘/어제까지는 진행 중일 수 있으므로 제외 — 그보다 오래된 live만 좀비로 간주
cutoff = (date.today() - timedelta(days=1)).isoformat()

rows = (
    sb.table("meetings")
    .select("id, title, channel_id, meeting_date, status")
    .eq("status", "live")
    .execute()
    .data
)
zombies = [r for r in rows if (r.get("meeting_date") or "9999") < cutoff]

print(f"status='live' 회의 {len(rows)}건, 그 중 좀비(<{cutoff}) {len(zombies)}건")
for r in rows:
    tag = "ZOMBIE→ended" if r in zombies else "유지(최근)"
    print(f"  [{tag}] {r.get('meeting_date')} ch={r.get('channel_id')} {r.get('title')} id={r['id'][:8]}")

if not zombies:
    print("\n정리할 좀비 없음.")
    sys.exit(0)
if not apply:
    print("\n(dry-run — 실제 정리하려면 --apply)")
    sys.exit(0)

now = datetime.now(timezone.utc).isoformat()
for r in zombies:
    sb.table("meetings").update({"status": "ended", "updated_at": now}).eq("id", r["id"]).execute()
    print(f"  ended 처리: {r['id'][:8]} ({r.get('title')})")
print(f"\n좀비 {len(zombies)}건 정리 완료.")
