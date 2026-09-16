"""중복 회의(같은 영상에 m3u8 행 + mp4 행) 조사 리포트.

normalize_vod_download_url로 정규화한 MP4 URL이 같은 회의들을 묶어,
각 회의의 자막 수/상태/생성시각/관련 데이터를 보여준다. (조사 전용 — 삭제하지 않음)
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import get_supabase_client
from app.services.kms_vod_resolver import normalize_vod_download_url

sb = get_supabase_client()
rows = sb.table("meetings").select(
    "id,title,vod_url,status,created_at,duration_seconds"
).execute().data


def count(table: str, mid: str) -> int:
    try:
        r = sb.table(table).select("id", count="exact").eq("meeting_id", mid).execute()
        return r.count or 0
    except Exception:
        return -1  # 테이블 없거나 컬럼 다름


groups = defaultdict(list)
for r in rows:
    url = r.get("vod_url")
    if not url:
        continue
    groups[normalize_vod_download_url(url)].append(r)

dups = {k: v for k, v in groups.items() if len(v) > 1}
print(f"전체 회의={len(rows)}  중복 그룹={len(dups)}  (그룹 내 회의 합계={sum(len(v) for v in dups.values())})")
for key, members in dups.items():
    print(f"\n=== {key}")
    for r in members:
        is_hls = "_definst_" in (r["vod_url"] or "") or (r["vod_url"] or "").endswith(".m3u8")
        subs = count("subtitles", r["id"])
        summ = count("meeting_summaries", r["id"])
        agd = count("meeting_agendas", r["id"])
        sten = count("stenography_records", r["id"])
        bill = count("bill_mentions", r["id"])
        print(
            f"  {'HLS' if is_hls else 'MP4'} id={r['id']} subs={subs} summary={summ} "
            f"agenda={agd} steno={sten} bill={bill} status={r['status']} "
            f"created={(r.get('created_at') or '')[:19]}"
        )
        print(f"       title={(r.get('title') or '')[:40]}")
