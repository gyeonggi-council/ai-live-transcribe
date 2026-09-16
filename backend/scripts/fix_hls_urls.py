"""vod_url이 KMS HLS(.m3u8/_definst_)인 회의를 찾아 직접 MP4로 교정.

사용: python scripts/fix_hls_urls.py [--apply]
  기본 dry-run. --apply 시 실제 업데이트.
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import get_supabase_client
from app.services.kms_vod_resolver import normalize_vod_download_url

apply = "--apply" in sys.argv
sb = get_supabase_client()

rows = sb.table("meetings").select("id,title,vod_url").execute().data
affected = [
    r for r in rows
    if r.get("vod_url") and ("_definst_" in r["vod_url"] or r["vod_url"].endswith(".m3u8"))
]
print(f"전체 회의={len(rows)}  HLS vod_url 회의={len(affected)}")
updated, dup, err = 0, 0, 0
for r in affected:
    fixed = normalize_vod_download_url(r["vod_url"])
    print(f"  {r['id']}  {(r.get('title') or '')[:24]}")
    print(f"     before: {r['vod_url']}")
    print(f"     after : {fixed}")
    if apply:
        try:
            sb.table("meetings").update({"vod_url": fixed}).eq("id", r["id"]).execute()
            updated += 1
        except Exception as e:
            msg = str(e)
            if "23505" in msg or "duplicate key" in msg:
                dup += 1
                print("     SKIP: 동일 MP4 URL 회의가 이미 존재 (중복 회의 행)")
            else:
                err += 1
                print(f"     ERR: {msg[:120]}")
if apply:
    print(f"UPDATED={updated} DUP_SKIP={dup} ERR={err} (총 {len(affected)})")
elif affected:
    print("(dry-run — 교정하려면 --apply)")
