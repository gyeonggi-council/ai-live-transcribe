"""읽기 전용 진단: '본회의 생중계' 등 라이브 회의 중복 원인 조사.

삭제/수정 없음. status/created_at/channel_id 분포만 출력한다.
"""
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import get_supabase_client  # noqa: E402

sb = get_supabase_client()

# 1) ch14(본회의) 회의 전체
rows = (
    sb.table("meetings")
    .select("id, title, status, channel_id, meeting_date, created_at, updated_at, vod_url, stream_url, kms_no")
    .eq("channel_id", "ch14")
    .order("created_at", desc=False)
    .execute()
    .data
)
print(f"=== ch14(본회의) 회의 총 {len(rows)}건 ===")
by_status = Counter(r.get("status") for r in rows)
by_date = Counter(r.get("meeting_date") for r in rows)
print("status 분포:", dict(by_status))
print("meeting_date 분포:", dict(by_date))
print()
print("created_at 순 (처음 40건):")
for r in rows[:40]:
    print(
        f"  {r['created_at']}  status={r.get('status'):<10} "
        f"date={r.get('meeting_date')} kms_no={r.get('kms_no')} "
        f"vod={'Y' if r.get('vod_url') else '-'} id={r['id'][:8]}"
    )

# 2) 오늘 기준 라이브 상태 회의(모든 채널) — 유령 live 확인
today_rows = (
    sb.table("meetings")
    .select("id, title, status, channel_id, created_at")
    .eq("status", "live")
    .execute()
    .data
)
print(f"\n=== status='live' 회의 총 {len(today_rows)}건 (모든 채널) ===")
for r in today_rows:
    print(f"  {r['created_at']}  ch={r.get('channel_id')} title={r.get('title')} id={r['id'][:8]}")

# 3) 각 회의의 자막 수 (내용 있는지) — 앞 15건만
print("\n=== ch14 회의별 자막 수 (created_at 오름차순 앞 15건) ===")
for r in rows[:15]:
    cnt = (
        sb.table("subtitles")
        .select("id", count="exact")
        .eq("meeting_id", r["id"])
        .execute()
        .count
    )
    print(f"  id={r['id'][:8]} status={r.get('status'):<10} 자막={cnt}")
