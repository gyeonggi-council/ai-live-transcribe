"""AI 자막이 있는데 subtitle_stage가 잘못된 회의를 'ai'로 백필.

조건: status=ended + 자막 1개 이상 + subtitle_stage in (none/null, draft) → 'ai'.
(reviewing/final은 보존.) 기본 dry-run, --apply 시 실제 업데이트.
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import get_supabase_client

apply = "--apply" in sys.argv
sb = get_supabase_client()

# 이번 세션에 VOD 배치 전사한 회의(확실히 'ai' 품질) — draft여도 승격 허용
SESSION_BATCH_IDS = {
    "0c0f4fbb-e023-4c52-970b-02704e04ad75",  # 예결위(첫 테스트)
    "20409c40-9777-4808-b7d3-a5ced557a5fb",  # 보건복지
    "ae86141b-dc0b-43a2-9142-6e70d27ae4d3",  # 교육기획
    "8ce585f8-67fb-425a-9c31-c10fd2da26f1",  # 도시환경
    "b36aa957-8095-4dd3-a862-97ff14ece86e",  # 여성가족
    "ffa0575a-8c90-4d94-b2f7-c1852d59311f",  # 미래과학
}

rows = sb.table("meetings").select("id,title,status,subtitle_stage").execute().data
fixed = []
for r in rows:
    stage = (r.get("subtitle_stage") or "none")
    if r.get("status") != "ended" or stage not in ("none", "draft"):
        continue
    # 안전 기준: 'none'인데 자막 있음(명백한 버그) 또는 이번 세션 배치본만 승격.
    # 그 외 draft(라이브 생중계 등)는 보존.
    if stage != "none" and r["id"] not in SESSION_BATCH_IDS:
        continue
    n = sb.table("subtitles").select("id", count="exact").eq("meeting_id", r["id"]).execute().count or 0
    if n > 0:
        fixed.append((r, stage, n))

print(f"교정 대상: {len(fixed)}건")
for r, stage, n in fixed:
    print(f"  {stage:>5} → ai  ({n}자막)  {(r.get('title') or '')[:34]}  {r['id']}")
    if apply:
        sb.table("meetings").update({"subtitle_stage": "ai"}).eq("id", r["id"]).execute()
print("UPDATED" if apply else "(dry-run — --apply 로 적용)")
