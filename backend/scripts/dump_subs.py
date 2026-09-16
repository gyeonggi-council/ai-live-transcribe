"""특정 회의의 자막을 로컬 API에서 가져와 UTF-8 JSON으로 덤프 (검수용)."""
import json
import os
import sys
import tempfile
import urllib.request

mid = sys.argv[1] if len(sys.argv) > 1 else None
base = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8012"
url = f"{base}/api/meetings/{mid}/subtitles?limit=500"
with urllib.request.urlopen(url, timeout=30) as r:
    data = json.loads(r.read().decode("utf-8"))

items = data.get("items") if isinstance(data, dict) else data
items = items or []
out = {
    "count": len(items),
    "speakers": sorted({(s.get("speaker") or "∅") for s in items}),
    "items": [
        {
            "i": idx,
            "start": s.get("start_time"),
            "end": s.get("end_time"),
            "speaker": s.get("speaker"),
            "text": s.get("text"),
        }
        for idx, s in enumerate(items)
    ],
}
path = os.path.join(tempfile.gettempdir(), "ggc_subs.json")
with open(path, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(f"count={out['count']} speakers={out['speakers']}")
print(f"written: {path}")
