"""회의 제목에서 위원회를 추출해 meetings.committee를 채운다 (실명화 suggest용)."""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import get_supabase_client

_RE = re.compile(r"([가-힣]{2,}?(?:특별위원회|위원회))")


def committee_of(title):
    t = title or ""
    if "본회의" in t:
        return None
    m = _RE.search(t.replace(" ", ""))
    if not m:
        return None
    c = re.sub(r"^(차|회)", "", m.group(1))
    c = re.sub(r"^경기도청", "", c)
    return c


apply = "--apply" in sys.argv
sb = get_supabase_client()
rows = sb.table("meetings").select("id,title,committee").execute().data
n = 0
for r in rows:
    derived = committee_of(r.get("title"))
    if derived and r.get("committee") != derived:
        print(f"  {(r.get('committee') or '∅'):>12} -> {derived}   {(r.get('title') or '')[:30]}")
        if apply:
            sb.table("meetings").update({"committee": derived}).eq("id", r["id"]).execute()
        n += 1
print(f"{'updated' if apply else 'would update'}: {n}건" + ("" if apply else "  (--apply)"))
