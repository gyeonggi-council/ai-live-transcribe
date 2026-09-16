"""오늘 ch14(본회의) 라이브 깜빡임으로 생긴 '빈 유령 회의'만 정리한다.

대상 조건(모두 충족): channel_id=ch14 · meeting_date=오늘 · kms_no IS NULL ·
자막(subtitles) 0건. 자막이 하나라도 있으면 절대 건드리지 않는다.

기본 dry-run. --apply 시 백업(JSON) 후 자식행 → 회의 순으로 삭제.
사용: python scripts/cleanup_ghost_live_meetings.py [--date YYYY-MM-DD] [--apply]
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import get_supabase_client  # noqa: E402

apply = "--apply" in sys.argv
target_date = date.today().isoformat()
if "--date" in sys.argv:
    target_date = sys.argv[sys.argv.index("--date") + 1]

CHANNEL_ID = "ch14"
CHILD_TABLES = [
    "subtitle_comments", "subtitle_history", "subtitles", "meeting_summaries",
    "meeting_agendas", "bill_mentions", "edit_sessions", "agenda_files",
    "stenography_records", "material_requests", "publications",
]
BACKUP_PATH = str(Path(__file__).resolve().parent.parent / f"ghost_cleanup_backup_{target_date}.json")

sb = get_supabase_client()


def subtitle_count(mid: str) -> int:
    return (
        sb.table("subtitles").select("id", count="exact").eq("meeting_id", mid).execute().count
    )


def fetch_children(mid: str) -> dict:
    out = {}
    for t in CHILD_TABLES:
        try:
            rows = sb.table(t).select("*").eq("meeting_id", mid).execute().data
            if rows:
                out[t] = rows
        except Exception:
            pass  # 테이블/컬럼 없음
    return out


# ── 대상 도출 ──
rows = (
    sb.table("meetings")
    .select("id, title, status, created_at, kms_no, vod_url")
    .eq("channel_id", CHANNEL_ID)
    .eq("meeting_date", target_date)
    .is_("kms_no", "null")
    .order("created_at", desc=False)
    .execute()
    .data
)

targets, kept = [], []
for r in rows:
    cnt = subtitle_count(r["id"])
    (targets if cnt == 0 else kept).append((r, cnt))

print(f"=== {target_date} ch14 kms_no-미등록 회의 {len(rows)}건 ===")
print(f"[삭제 대상] 자막 0건 유령 {len(targets)}건:")
for r, cnt in targets:
    print(f"  DEL id={r['id'][:8]} status={r.get('status'):<8} created={r['created_at']} 자막={cnt}")
print(f"[보존] 자막 있는 {len(kept)}건:")
for r, cnt in kept:
    print(f"  KEEP id={r['id'][:8]} status={r.get('status'):<8} created={r['created_at']} 자막={cnt}")

if not targets:
    print("\n삭제할 유령 회의가 없습니다.")
    sys.exit(0)

if not apply:
    print("\n(dry-run — 실제 삭제하려면 --apply)")
    sys.exit(0)

# ── 백업 ──
backup = {}
for r, _ in targets:
    mid = r["id"]
    backup[mid] = {"meeting": r, "children": fetch_children(mid)}
with open(BACKUP_PATH, "w", encoding="utf-8") as f:
    json.dump(backup, f, ensure_ascii=False, indent=2, default=str)
print(f"\n백업 저장: {BACKUP_PATH}")

# ── 삭제 (자식 먼저, 그 다음 회의) ──
for r, _ in targets:
    mid = r["id"]
    for t, child_rows in backup[mid]["children"].items():
        try:
            sb.table(t).delete().eq("meeting_id", mid).execute()
            print(f"  - {t} {len(child_rows)}행 삭제 ({mid[:8]})")
        except Exception as e:
            print(f"  WARN {t} delete({mid[:8]}): {str(e)[:80]}")
    sb.table("meetings").delete().eq("id", mid).execute()
    print(f"  회의 삭제 {mid[:8]}")

remaining = (
    sb.table("meetings").select("id", count="exact")
    .eq("channel_id", CHANNEL_ID).eq("meeting_date", target_date).execute().count
)
print(f"\n삭제 완료: {len(targets)}건. {target_date} ch14 잔존 회의: {remaining}건")
