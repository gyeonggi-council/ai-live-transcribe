"""경기도의회 의원 API — AJAX 헤더/대체 엔드포인트 재진단."""
import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

BASE = "https://www.ggc.go.kr"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124"


async def probe(label, method, url, **kw):
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as c:
            r = await c.request(method, url, **kw)
        body = r.text
        looks_json = body.strip()[:1] in ("{", "[")
        print(f"[{label}] {method} {r.status_code} ct={r.headers.get('content-type')} len={len(body)} json={looks_json}")
        if looks_json or len(body) < 250:
            print("   head:", repr(body[:220]))
    except Exception as e:
        print(f"[{label}] ERR: {e}")


async def main():
    ajax = {
        "User-Agent": UA,
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE}/site/main/memberInfo/actvMmbr/list?menu=city&miDistrictCode=all",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    orig = f"{BASE}/site/main/api/portaltoggc/ggcmemrecinfoview/onclick/"
    await probe("orig GET+ajax", "GET", orig, params={"key": "ggcmemrecinfoview"}, headers=ajax)
    await probe("orig POST+ajax", "POST", orig, params={"key": "ggcmemrecinfoview"}, headers=ajax)
    # 현역의원 목록 API 추정 후보들
    for path in [
        "/site/main/api/portaltoggc/ggcmemrecinfo/list",
        "/site/main/memberInfo/actvMmbr/listJson",
        "/site/main/memberInfo/actvMmbr/list.json",
        "/site/main/api/portaltoggc/actvMmbr/list",
        "/site/main/api/portaltoggc/ggcmem/list",
    ]:
        await probe(path, "GET", BASE + path, params={"menu": "city", "miDistrictCode": "all"}, headers=ajax)


asyncio.run(main())
