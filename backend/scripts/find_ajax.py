"""현역의원 페이지의 JS에서 의원목록 AJAX 엔드포인트를 탐색."""
import asyncio
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

BASE = "https://www.ggc.go.kr"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124"
PAGE = f"{BASE}/site/main/memberInfo/actvMmbr/list?menu=city&miDistrictCode=all"


async def main():
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as c:
        r = await c.get(PAGE, headers={"User-Agent": UA})
        html = r.text
        # 인라인 JS에서 ajax/url/.do/api 패턴
        print("=== 인라인 url/ajax/.do 단서 ===")
        for m in re.finditer(r'(url\s*[:=]\s*["\'][^"\']+["\']|\$\.(?:ajax|post|get)\([^)]{0,80}|[\'"][^\'"]*\.(?:do|json)[^\'"]*[\'"]|/api/[^\s"\'<>]+)', html):
            s = m.group(0)
            if any(k in s.lower() for k in ("mmbr", "member", "list", "api", ".do", ".json", "ajax")):
                print("  ", s[:120])
        # 외부 스크립트 파일 목록
        srcs = re.findall(r'<script[^>]+src="([^"]+)"', html)
        cand = [s for s in srcs if any(k in s.lower() for k in ("member", "mmbr", "main", "common", "list"))]
        print("=== script src 후보 ===")
        for s in cand[:15]:
            print("  ", s)
        # 후보 JS 파일에서 엔드포인트 탐색
        for s in cand[:8]:
            url = s if s.startswith("http") else BASE + s
            try:
                jr = await c.get(url, headers={"User-Agent": UA})
                js = jr.text
                hits = re.findall(r'[\'"]([^\'"]*(?:actvMmbr|Mmbr|member|memberInfo)[^\'"]*\.(?:do|json)[^\'"]*)[\'"]', js)
                hits += re.findall(r'url\s*:\s*[\'"]([^\'"]+)[\'"]', js)
                if hits:
                    print(f"=== {s} 엔드포인트 후보 ===")
                    for h in list(dict.fromkeys(hits))[:12]:
                        print("   ", h[:120])
            except Exception as e:
                print(f"  (js fetch fail {s}: {e})")


asyncio.run(main())
