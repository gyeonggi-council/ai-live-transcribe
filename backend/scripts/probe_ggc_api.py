"""경기도의회 의원 API 응답 진단."""
import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

URL = "https://www.ggc.go.kr/site/main/api/portaltoggc/ggcmemrecinfoview/onclick/"
KEY = "ggcmemrecinfoview"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


async def probe(label, method, url, **kw):
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as c:
            r = await c.request(method, url, **kw)
        body = r.text
        print(f"[{label}] {method} {r.status_code} ct={r.headers.get('content-type')} len={len(body)}")
        print("   head:", repr(body[:180]))
    except Exception as e:
        print(f"[{label}] ERR: {e}")


async def main():
    h = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
    await probe("GET ?key", "GET", URL, params={"key": KEY}, headers=h)
    await probe("GET no-key", "GET", URL, headers=h)
    await probe("POST ?key", "POST", URL, params={"key": KEY}, headers=h)
    await probe("POST body", "POST", URL, data={"key": KEY}, headers=h)
    # 흔한 대안 경로들
    await probe("no-trailing-slash", "GET", URL.rstrip("/"), params={"key": KEY}, headers=h)


asyncio.run(main())
