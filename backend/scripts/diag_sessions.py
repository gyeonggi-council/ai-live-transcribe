"""읽기 전용 진단: 회기(제N회) 탭이 어떻게 만들어지는지 — DB에 등록된 회의의
제목/session_no/kms_no/날짜 분포를 본다. 392회가 왜 안 뜨는지 확인용.
"""
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import get_supabase_client  # noqa: E402

sb = get_supabase_client()

# 컬럼 존재 여부 유연 처리
def select_meetings(cols):
    return sb.table("meetings").select(cols).order("meeting_date", desc=True).limit(500).execute().data

try:
    rows = select_meetings("id, title, session_no, kms_no, meeting_date, status, channel_id")
    has_session_no = True
except Exception:
    rows = select_meetings("id, title, kms_no, meeting_date, status, channel_id")
    has_session_no = False

print(f"meetings 총 조회 {len(rows)}건 (session_no 컬럼 존재={has_session_no})\n")


def extract_session(title):
    if not title:
        return None
    m = re.search(r"제\s*(\d+)\s*회", title)
    return int(m.group(1)) if m else None


# 회기 번호 분포 (프론트 sessionOf 로직 재현: 제목 우선, 없으면 session_no)
sess_counter = Counter()
for r in rows:
    s = extract_session(r.get("title"))
    if s is None:
        s = r.get("session_no")
    sess_counter[s] += 1

print("=== sessionOf() 분포 (제목→session_no) ===")
for s in sorted((k for k in sess_counter if k is not None), reverse=True):
    print(f"  제{s}회: {sess_counter[s]}건")
print(f"  회기 미상(None): {sess_counter[None]}건")

# 최근(6/25 이후) 회의 상세 — 현재 진행 회기 확인
print("\n=== 2026-06-25 이후 회의 (현재 회기 후보) ===")
recent = [r for r in rows if (r.get("meeting_date") or "") >= "2026-06-25"]
recent.sort(key=lambda r: (r.get("meeting_date") or "", r.get("channel_id") or ""))
for r in recent:
    s = extract_session(r.get("title"))
    sn = r.get("session_no") if has_session_no else "-"
    print(
        f"  {r.get('meeting_date')} ch={r.get('channel_id'):<5} "
        f"status={r.get('status'):<10} kms_no={r.get('kms_no')} "
        f"session_no={sn} 제목추출회기={s}  title={(r.get('title') or '')[:40]}"
    )

# 392 이상 명시적으로 검색
print("\n=== 제목/ session_no 에 392 이상 있는 회의 ===")
found = False
for r in rows:
    s = extract_session(r.get("title")) or (r.get("session_no") if has_session_no else None)
    if s is not None and s >= 392:
        found = True
        print(f"  제{s}회 {r.get('meeting_date')} title={(r.get('title') or '')[:50]}")
if not found:
    print("  (없음) — DB에 392회 이상 회의가 등록돼 있지 않음")
