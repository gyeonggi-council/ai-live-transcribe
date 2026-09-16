"""자막 보유 회의를 위원회별로 묶어 전사 텍스트를 파일로 덤프 (명부 추출용).

본회의/위원회 없음/자막 적은 회의는 제외. 같은 위원회의 여러 회의는 합침.
출력: <OUTDIR>/<idx>_<committee>.txt + manifest.json
"""
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import get_supabase_client

OUTDIR = Path(os.environ.get("GGC_EXTRACT_DIR", tempfile.gettempdir())) / "ggc_extract"
OUTDIR.mkdir(parents=True, exist_ok=True)
for _old in OUTDIR.glob("*.txt"):  # 이전 덤프 정리(위원회명 변경 시 잔재 방지)
    _old.unlink()
MAX_CHARS = 16000  # 위원회당 전사 텍스트 상한(이름은 반복 등장 → 충분)
_COMM_RE = re.compile(r"([가-힣]{2,}?(?:특별위원회|위원회))")

sb = get_supabase_client()


def committee_of(title: str) -> str | None:
    t = title or ""
    if "본회의" in t:
        return None
    m = _COMM_RE.search(t.replace(" ", ""))
    if not m:
        return None
    c = m.group(1)
    c = re.sub(r"^(차|회)", "", c)      # 제N차/제N회 잔재 제거
    c = re.sub(r"^경기도청", "", c)      # 예결위 명칭 정규화
    return c


def fetch_subs(mid: str) -> list[dict]:
    out, off = [], 0
    while True:
        rows = (
            sb.table("subtitles").select("speaker,text,start_time")
            .eq("meeting_id", mid).order("start_time").range(off, off + 999).execute().data
        )
        out.extend(rows)
        if len(rows) < 1000:
            break
        off += 1000
    return out


meetings = sb.table("meetings").select("id,title").execute().data
by_comm: dict[str, list[str]] = defaultdict(list)
for m in meetings:
    comm = committee_of(m.get("title"))
    if not comm:
        continue
    n = sb.table("subtitles").select("id", count="exact").eq("meeting_id", m["id"]).execute().count or 0
    if n < 40:
        continue
    by_comm[comm].append(m["id"])

manifest = []
for i, (comm, mids) in enumerate(sorted(by_comm.items())):
    lines = []
    for mid in mids:
        for s in fetch_subs(mid):
            sp = s.get("speaker") or "?"
            lines.append(f"{sp}: {s.get('text', '')}")
    text = "\n".join(lines)
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
    fp = OUTDIR / f"{i:02d}_{comm}.txt"
    fp.write_text(text, encoding="utf-8")
    manifest.append({"committee": comm, "file": str(fp), "meetings": len(mids), "chars": len(text)})
    print(f"{comm}: {len(mids)}개 회의, {len(text)}자 -> {fp.name}")

(OUTDIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nmanifest: {OUTDIR / 'manifest.json'} ({len(manifest)} 위원회)")
