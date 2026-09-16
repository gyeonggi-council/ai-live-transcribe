"""현역의원 페이지 HTML 구조 진단 (스크래핑 전 확인)."""
import asyncio
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

BASE = "https://www.ggc.go.kr"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124"
URL = f"{BASE}/site/main/memberInfo/actvMmbr/list"


async def main():
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as c:
        r = await c.get(URL, params={"menu": "city", "miDistrictCode": "all", "cp": "1"},
                        headers={"User-Agent": UA})
    html = r.text
    print(f"status={r.status_code} len={len(html)}")
    # 의원 상세 링크/코드 패턴
    codes = re.findall(r'miCode["\'=\s:]+(\d+)', html)
    print("miCode 출현:", len(codes), "예:", codes[:8])
    algebra = re.findall(r'miAlgebra["\'=\s:]+(\d+)', html)
    print("miAlgebra 예:", algebra[:4])
    # 이름 후보: <strong>/<em>/class에 name 들어간 태그
    names = re.findall(r'<(?:strong|em|p|span|b|a)[^>]*>\s*([가-힣]{2,4})\s*</', html)
    uniq = list(dict.fromkeys(names))
    print(f"한글 2~4자 태그텍스트 후보 {len(uniq)}개:", uniq[:25])
    # 페이지네이션/총원 단서
    for kw in ["총", "명", "page", "cp=", "paging", "miAlgebra", "위원회"]:
        idx = html.find(kw)
        if idx > 0:
            print(f"  '{kw}' 주변:", re.sub(r'\s+', ' ', html[idx-40:idx+60]))
    # 의원 카드/리스트 컨테이너 클래스 단서
    classes = re.findall(r'class="([^"]*(?:member|mmbr|profile|card|list|name)[^"]*)"', html, re.I)
    print("관련 class:", list(dict.fromkeys(classes))[:15])


asyncio.run(main())
