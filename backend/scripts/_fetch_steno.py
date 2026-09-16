# -*- coding: utf-8 -*-
"""KMS 속기 회의록(mntsViewer.do?mntsId=N) → 텍스트 추출(서버 httpx). 읽기 전용.

본문은 <div id="mntshtmlviewer"> 안에 있다. UTF-8.
사용: python scripts/_fetch_steno.py <mntsId>   →  _steno_<mntsId>.txt
"""
import re
import sys

import httpx

sys.stdout.reconfigure(encoding="utf-8")

mnts_id = sys.argv[1] if len(sys.argv) > 1 else "15577"
url = f"https://kms.ggc.go.kr/cms/mntsViewer.do?mntsId={mnts_id}"

r = httpx.get(url, timeout=60, follow_redirects=True,
              headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
html = r.content.decode("utf-8", errors="replace")
print(f"# fetched {len(r.content)} bytes, status {r.status_code}", file=sys.stderr)

# 본문 컨테이너 추출: mntshtmlviewer 시작 ~ 다음 chrome(pageTopBtn) 직전
start = re.search(r'<div\s+id=["\']mntshtmlviewer["\']', html)
if not start:
    print("# ERROR: mntshtmlviewer not found", file=sys.stderr)
    sys.exit(1)
body = html[start.end():]
end = re.search(r'<div\s+class=["\']pageTopBtn["\']', body)
if end:
    body = body[:end.start()]

# 태그 제거 → 텍스트
body = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", body, flags=re.S)
body = re.sub(r"<br\s*/?>", "\n", body)
body = re.sub(r"</(p|div|td|tr|h\d|li)>", "\n", body)
body = re.sub(r"<[^>]+>", "", body)
body = re.sub(r"&nbsp;", " ", body)
body = body.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
body = re.sub(r"&#?\w+;", "", body)
lines = [ln.strip() for ln in body.splitlines()]
lines = [ln for ln in lines if ln]
clean = "\n".join(lines)

out = f"_steno_{mnts_id}.txt"
with open(out, "w", encoding="utf-8") as f:
    f.write(clean)
hangul = len(re.findall(r"[가-힣]", clean))
print(f"# wrote {out} ({len(clean)} chars, {len(lines)} lines, {hangul} hangul)", file=sys.stderr)
print("--- first 1200 chars ---", file=sys.stderr)
print(clean[:1200], file=sys.stderr)
