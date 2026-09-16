"""특정 회의의 자막을 삭제 (재실행 전 정리)."""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import get_supabase_client

mid = sys.argv[1]
sb = get_supabase_client()
before = sb.table("subtitles").select("id", count="exact").eq("meeting_id", mid).execute()
sb.table("subtitles").delete().eq("meeting_id", mid).execute()
after = sb.table("subtitles").select("id", count="exact").eq("meeting_id", mid).execute()
print(f"deleted: before={before.count} after={after.count}")
