"""특정 회차(예: 제389회) 회의 일괄 정리: 조회 → 백업 → 삭제.

delete_dups.py의 검증된 패턴(백업 → 자식 테이블 → meetings) 재사용.
title 에 '제{N}회' 가 포함된 모든 회의를 대상으로 한다.

사용법:
    python scripts/delete_session.py 389            # dry-run (목록만 출력, 삭제 안 함)
    python scripts/delete_session.py 389 --apply    # 백업 후 실제 삭제

★기본 dry-run. --apply 가 있어야만 실제로 삭제한다.
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import get_supabase_client

# ── 인자 파싱 ──
args = [a for a in sys.argv[1:] if not a.startswith("--")]
if not args:
    print("회차 번호를 주세요. 예: python scripts/delete_session.py 389 [--apply]")
    sys.exit(1)
session_no = args[0].strip()
apply = "--apply" in sys.argv

sb = get_supabase_client()

# meeting_id 컬럼으로 묶인 자식 테이블 (delete_dups.py와 동일 + 검증된 목록)
CHILD_TABLES = [
    "subtitle_comments", "subtitle_history", "subtitles", "meeting_summaries",
    "meeting_agendas", "meeting_participants", "bill_mentions", "edit_sessions",
    "agenda_files", "stenography_lines", "stenography_edit_history",
    "stenography_records", "transcript_publications", "publications",
]
# meeting_context_id 컬럼을 쓰는 특수 테이블 (ON DELETE CASCADE 없음 → 수동 정리)
CONTEXT_TABLES = [("ai_conversations", "meeting_context_id")]

BACKUP_PATH = str(Path(__file__).resolve().parent.parent.parent / f"session_{session_no}_backup.json")


def fetch_all(table, col, val):
    """col=val로 전체 행 조회(1000행 제한 회피 페이지네이션). 테이블/컬럼 없으면 None."""
    try:
        out, offset, page = [], 0, 1000
        while True:
            rows = (
                sb.table(table).select("*").eq(col, val)
                .range(offset, offset + page - 1).execute().data
            )
            out.extend(rows)
            if len(rows) < page:
                break
            offset += page
        return out
    except Exception:
        return None  # 테이블/컬럼 없음


# ── 대상 회의 조회 (title 에 '제389회' 포함) ──
pattern = f"%제{session_no}회%"
meetings = (
    sb.table("meetings").select("id,title,meeting_date,status,vod_url,stream_url")
    .ilike("title", pattern).order("meeting_date").execute().data
)

if not meetings:
    # '제' 없이 '389회' 만 들어간 케이스도 확인
    alt = (
        sb.table("meetings").select("id,title,meeting_date,status,vod_url,stream_url")
        .ilike("title", f"%{session_no}회%").execute().data
    )
    print(f"'제{session_no}회' 매칭 0건. (참고: '{session_no}회' 매칭 {len(alt)}건)")
    for m in alt:
        print(f"  - {m['title']}  ({m.get('meeting_date')})  id={m['id']}")
    if not alt:
        sys.exit(0)
    print("\n→ title 형식이 예상과 달라 자동 진행하지 않음. 사람이 확인 필요.")
    sys.exit(0)

print(f"제{session_no}회 매칭 회의: {len(meetings)}건\n")
delete_ids = []
for m in meetings:
    mid = m["id"]
    delete_ids.append(mid)
    has_vod = "VOD" if m.get("vod_url") else ("HLS" if m.get("stream_url") else "-")
    # 자식 행 수 요약 (자막만 빠르게 카운트)
    subs = fetch_all("subtitles", "meeting_id", mid)
    sub_n = len(subs) if subs else 0
    print(f"  [{has_vod}] {m['title']}")
    print(f"        date={m.get('meeting_date')}  status={m.get('status')}  자막={sub_n}  id={mid}")

print(f"\n대상 회의 {len(delete_ids)}건.")

if not apply:
    print("\n(dry-run — 실제 삭제하려면 끝에 --apply 추가)")
    sys.exit(0)

# ── 백업 ──
print("\n백업 중...")
backup = {}
for mid in delete_ids:
    m = sb.table("meetings").select("*").eq("id", mid).execute().data
    entry = {"meeting": m[0] if m else None, "children": {}}
    for t in CHILD_TABLES:
        rows = fetch_all(t, "meeting_id", mid)
        if rows:
            entry["children"][t] = rows
    for t, col in CONTEXT_TABLES:
        rows = fetch_all(t, col, mid)
        if rows:
            entry["children"][f"{t}({col})"] = rows
    backup[mid] = entry

with open(BACKUP_PATH, "w", encoding="utf-8") as f:
    json.dump(backup, f, ensure_ascii=False, indent=2, default=str)
print(f"백업 저장: {BACKUP_PATH}")

# ── 삭제 (자식 먼저, 그 다음 회의) ──
for mid in delete_ids:
    for t in CHILD_TABLES:
        try:
            sb.table(t).delete().eq("meeting_id", mid).execute()
        except Exception as e:
            print(f"  WARN {t} delete({mid}): {str(e)[:80]}")
    for t, col in CONTEXT_TABLES:
        try:
            sb.table(t).delete().eq(col, mid).execute()
        except Exception as e:
            print(f"  WARN {t} delete({mid}): {str(e)[:80]}")
    sb.table("meetings").delete().eq("id", mid).execute()

print(f"삭제 완료: {len(delete_ids)}개 회의")

total = sb.table("meetings").select("id", count="exact").execute().count
print(f"잔존 회의 수: {total}")
