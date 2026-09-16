# -*- coding: utf-8 -*-
"""기존 AI 자막에 확장된 사전을 재적용했을 때의 변경분 미리보기(읽기 전용).

기존 자막은 생성 시 이미 dictionary.correct를 거쳤으므로, 동일 사전을 다시
적용하면 '새로 추가한 교정 쌍'이 건드리는 부분만 바뀐다 = 이번 변경의 순효과.

사용:
  python scripts/_apply_dict_dryrun.py <meeting_id>            # 미리보기(쓰기 없음)
  python scripts/_apply_dict_dryrun.py <meeting_id> --apply    # 실제 DB 반영(승인 후)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from supabase import create_client

from app.core.config import settings
from app.services.dictionary import get_default_dictionary

MEETING_ID = sys.argv[1] if len(sys.argv) > 1 else "99ae52d7-b2cf-412b-97b4-c3f50876f4ab"
APPLY = "--apply" in sys.argv

sb = create_client(settings.supabase_url, settings.supabase_key)
d = get_default_dictionary()
d.load_from_db(sb)  # 운영과 동일하게 DB 사전도 병합

rows = []
offset = 0
while True:
    r = (
        sb.table("subtitles").select("id,text,kind,start_time")
        .eq("meeting_id", MEETING_ID).eq("kind", "ai")
        .order("start_time").range(offset, offset + 999).execute()
    )
    if not r.data:
        break
    rows.extend(r.data)
    if len(r.data) < 1000:
        break
    offset += 1000

changed = []
for s in rows:
    before = s.get("text") or ""
    after = d.correct(before)
    if after != before:
        changed.append((s["id"], before, after))

print(f"# AI 자막 {len(rows)}건 중 변경 대상 {len(changed)}건")
for _id, before, after in changed:
    print(f"\n- BEFORE: {before}\n  AFTER : {after}")

if APPLY and changed:
    for _id, _before, after in changed:
        sb.table("subtitles").update({"text": after}).eq("id", _id).execute()
    print(f"\n[APPLIED] {len(changed)}건 DB 반영 완료")
elif changed:
    print(f"\n[DRY-RUN] 쓰기 없음. 반영하려면 --apply 추가.")
