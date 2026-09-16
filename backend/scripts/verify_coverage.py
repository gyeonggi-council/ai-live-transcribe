"""회의들의 자막 커버리지 검증: 개수/시작·끝 시각/단조성/추임새/화자수."""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import get_supabase_client
from app.services.vod_stt_service import _is_filler

sb = get_supabase_client()

LABELS = {
    "8ce585f8-67fb-425a-9c31-c10fd2da26f1": "도시환경(127m)",
    "b36aa957-8095-4dd3-a862-97ff14ece86e": "여성가족(74m)",
    "ffa0575a-8c90-4d94-b2f7-c1852d59311f": "미래과학(138m)",
}

for mid, label in LABELS.items():
    rows, off = [], 0
    while True:
        page = (
            sb.table("subtitles").select("start_time,speaker,text")
            .eq("meeting_id", mid).order("start_time")
            .range(off, off + 999).execute().data
        )
        rows.extend(page)
        if len(page) < 1000:
            break
        off += 1000
    if not rows:
        print(f"{label}: 자막 없음")
        continue
    mono = all(rows[i]["start_time"] >= rows[i - 1]["start_time"] for i in range(1, len(rows)))
    fillers = sum(1 for r in rows if _is_filler(r.get("text") or ""))
    speakers = len({r.get("speaker") for r in rows if r.get("speaker")})
    mn, mx = rows[0]["start_time"], rows[-1]["start_time"]
    print(
        f"{label}: count={len(rows)} 시작={mn}s 끝={round(mx)}s(={round(mx/60)}분) "
        f"monotonic={mono} 화자={speakers} 추임새={fillers}"
    )
