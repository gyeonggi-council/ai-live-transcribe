# -*- coding: utf-8 -*-
"""회의 AI 자막을 시간순 텍스트로 덤프(속기 대조용). 읽기 전용.

사용: python scripts/_fetch_ai_subs.py <meeting_id> [live|ai]  →  _ai_<id8>[_<kind>].txt
(kind 를 주면 그 종류만, 없으면 prefer_ai_subtitles 규칙 — 기존 동작)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

# ★create_client(url, key) 직접 호출 금지 — 스키마 옵션(subtitle)이 빠져 PostgREST 가
#   PGRST106 으로 전 요청을 거부한다(2026-09-05 파드 실측). 앱과 같은 팩토리를 쓴다.
from app.core.database import get_supabase_client
from app.services.subtitle_select import prefer_ai_subtitles

MEETING_ID = sys.argv[1] if len(sys.argv) > 1 else "99ae52d7-b2cf-412b-97b4-c3f50876f4ab"
tag = MEETING_ID[:8]
KIND = sys.argv[2] if len(sys.argv) > 2 else None  # live|ai — 한 회의에 둘이 공존할 때 고른다

sb = get_supabase_client()

rows = []
offset = 0
while True:
    r = (sb.table("subtitles").select("*").eq("meeting_id", MEETING_ID)
         .order("start_time").range(offset, offset + 999).execute())
    if not r.data:
        break
    rows.extend(r.data)
    if len(r.data) < 1000:
        break
    offset += 1000

kinds = {}
for s in rows:
    kinds[s.get("kind")] = kinds.get(s.get("kind"), 0) + 1
print(f"# {tag}: total {len(rows)}, kinds {kinds}", file=sys.stderr)

subs = [s for s in rows if s.get("kind") == KIND] if KIND else prefer_ai_subtitles(rows)


def hms(t):
    t = int(t or 0)
    return f"{t//3600:02d}:{(t%3600)//60:02d}:{t%60:02d}"


out = [f"[{hms(s.get('start_time'))}] {s.get('speaker') or '?'}: {s.get('text','')}" for s in subs]
fn = f"_ai_{tag}_{KIND}.txt" if KIND else f"_ai_{tag}.txt"
with open(fn, "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print(f"# wrote {fn} ({len(subs)} lines)", file=sys.stderr)
