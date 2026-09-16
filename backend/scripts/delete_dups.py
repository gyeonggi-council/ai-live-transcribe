"""중복 회의 정리: 백업 → 삭제 → 남길 회의 URL 정규화.

확정된 결정:
- 교육기획위: 깨끗한 821개(ae86141b) 유지, 옛 1672개(453a90ab) 삭제 → ae86141b URL을 MP4로 정규화.
- 나머지 11쌍: 빈 HLS 중복 stub 삭제, 정식 MP4 회의 유지.

기본 dry-run. --apply 시 백업 후 실제 삭제.
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import get_supabase_client
from app.services.kms_vod_resolver import normalize_vod_download_url

apply = "--apply" in sys.argv
sb = get_supabase_client()

# 삭제 대상 회의 id (11개 빈 HLS stub + 교육기획위 옛 MP4본 1개)
DELETE_IDS = [
    "9de53111-2844-4732-b4ed-df492bc4fc00",  # 건설교통 HLS
    "2873b37f-f1e4-489d-a7d2-94cf8c7e79a2",  # 안전행정 HLS
    "bf0c8ba7-3c73-457a-8428-ae6296823768",  # 경제노동 HLS
    "c4f2c7de-0202-4980-90b7-108336ed9938",  # 보건복지 HLS
    "b9133ccf-8734-4353-80fd-f8e5e344d625",  # 도시환경 HLS
    "795fb895-d551-49be-a0f9-365a58b56c51",  # 기획재정 HLS
    "17537e43-3a60-4dfa-97c4-b763a5bedb9b",  # 교육행정 HLS
    "1a1cf01f-d13f-4df0-9d63-5d82c12ceea5",  # 여성가족 HLS
    "6ec3ae1e-307c-43cc-a93f-adc138078c10",  # 미래과학 HLS
    "4576af64-5c37-48f3-bc3b-f5ec0c015966",  # 본회의 HLS
    "44eabd3f-614d-4125-a3f0-96f4fe27e33d",  # 농정해양 HLS
    "453a90ab-f2b0-4be3-b9ed-5be3b52c16a8",  # 교육기획 옛 MP4본(1672, 추임새 포함)
]
# 유지하며 URL 정규화할 회의 (교육기획 깨끗한 821본)
NORMALIZE_ID = "ae86141b-dc0b-43a2-9142-6e70d27ae4d3"

CHILD_TABLES = [
    "subtitle_comments", "subtitle_history", "subtitles", "meeting_summaries",
    "meeting_agendas", "bill_mentions", "edit_sessions", "agenda_files",
    "stenography_records", "publications",
]
BACKUP_PATH = r"C:\02_coding\260205-subsrcript\dup_backup.json"


def fetch_all(table, mid):
    """meeting_id로 전체 행 조회(1000행 제한 회피 위해 페이지네이션)."""
    try:
        out, offset, page = [], 0, 1000
        while True:
            rows = (
                sb.table(table).select("*").eq("meeting_id", mid)
                .range(offset, offset + page - 1).execute().data
            )
            out.extend(rows)
            if len(rows) < page:
                break
            offset += page
        return out
    except Exception:
        return None  # 테이블/컬럼 없음


# ── 백업 ──
backup = {}
for mid in DELETE_IDS:
    m = sb.table("meetings").select("*").eq("id", mid).execute().data
    entry = {"meeting": m[0] if m else None, "children": {}}
    for t in CHILD_TABLES:
        rows = fetch_all(t, mid)
        if rows:
            entry["children"][t] = rows
    backup[mid] = entry
    child_summary = {t: len(v) for t, v in entry["children"].items()}
    print(f"{mid}  children={child_summary}")

if apply:
    with open(BACKUP_PATH, "w", encoding="utf-8") as f:
        json.dump(backup, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n백업 저장: {BACKUP_PATH}")

    # ── 삭제 (자식 먼저, 그 다음 회의) ──
    for mid in DELETE_IDS:
        for t in CHILD_TABLES:
            if backup[mid]["children"].get(t):
                try:
                    sb.table(t).delete().eq("meeting_id", mid).execute()
                except Exception as e:
                    print(f"  WARN {t} delete({mid}): {str(e)[:80]}")
        sb.table("meetings").delete().eq("id", mid).execute()
    print(f"삭제 완료: {len(DELETE_IDS)}개 회의")

    # ── 남긴 교육기획위 URL 정규화 ──
    cur = sb.table("meetings").select("vod_url").eq("id", NORMALIZE_ID).execute().data
    if cur:
        fixed = normalize_vod_download_url(cur[0]["vod_url"])
        sb.table("meetings").update({"vod_url": fixed}).eq("id", NORMALIZE_ID).execute()
        print(f"URL 정규화: {NORMALIZE_ID} -> {fixed}")

    total = sb.table("meetings").select("id", count="exact").execute().count
    print(f"잔존 회의 수: {total}")
else:
    print("\n(dry-run — 실제 삭제하려면 --apply)")
