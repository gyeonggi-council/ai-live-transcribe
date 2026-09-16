#!/usr/bin/env python3
"""전국 의회 생중계 페이지 목록을 실제로 찔러 보고 만든다 (2026-09-16)

왜 손으로 적지 않는가: 의회마다 도메인 규칙이 제각각이고(`council.<시>.go.kr` ·
`<약어>council.go.kr` · `yjcc.yangju.go.kr` · `vod.ansan.go.kr` · `www.gcc.or.kr`)
사이트 개편이 잦다. 손으로 적은 목록은 반년이면 낡고, 낡았다는 사실조차 드러나지 않는다.
이 스크립트는 **재실행 가능**해서 결과를 diff 하면 무엇이 바뀌었는지 바로 보인다.

★영상 주소(m3u8)가 아니라 **생중계 페이지 주소**를 모은다.
  대부분의 의회는 방송 중일 때만 영상 주소가 드러나기 때문이다(실측).
  영상 주소는 앱의 자동 찾기(services/stream_discovery.py)가 그때 찾는다.

사용:
    python scripts/harvest_council_presets.py                 # app/data/council_presets.json 갱신
    python scripts/harvest_council_presets.py --dry-run       # 화면에만
"""

from __future__ import annotations

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "council_presets.json"

# 생중계 페이지 경로 후보 — 실측한 벤더 계열 순서
LIVE_PATHS = [
    ("/onair/onair.do", "webpot"),
    ("/kr/cast/live.do", "cast-do"),
    ("/kr/cast/live", "cast-do"),
    ("/promote/cast/live.do", "cast-do"),
    ("/minutes/cast/live", "cast-do"),
    ("/live/live_list.jsp", "jsp"),
    ("/content/onair.html", "etc"),
    ("/broadcast/", "etc"),
    ("/", "etc"),
]

# (이름, 광역/시군, 홈페이지 호스트, 생중계 전용 호스트 또는 None)
COUNCILS: list[tuple[str, str, str, str | None]] = [
    # ── 광역 17 ────────────────────────────────────────────────────────────
    ("서울특별시의회", "광역", "ms.smc.seoul.kr", None),
    ("부산광역시의회", "광역", "council.busan.go.kr", None),
    ("대구광역시의회", "광역", "council.daegu.go.kr", None),
    ("인천광역시의회", "광역", "www.icouncil.go.kr", None),
    ("광주광역시의회", "광역", "council.gwangju.go.kr", None),
    ("대전광역시의회", "광역", "council.daejeon.go.kr", None),
    ("울산광역시의회", "광역", "www.council.ulsan.kr", None),
    ("세종특별자치시의회", "광역", "council.sejong.go.kr", None),
    ("경기도의회", "광역", "www.ggc.go.kr", "live.ggc.go.kr"),
    ("강원특별자치도의회", "광역", "council.gangwon.kr", None),
    ("충청북도의회", "광역", "council.chungbuk.go.kr", None),
    ("충청남도의회", "광역", "council.chungnam.go.kr", None),
    ("전북특별자치도의회", "광역", "council.jeonbuk.kr", "live.jbstatecouncil.jeonbuk.kr"),
    ("전라남도의회", "광역", "www.jnassembly.go.kr", None),
    ("경상북도의회", "광역", "council.gb.go.kr", None),
    ("경상남도의회", "광역", "council.gyeongnam.go.kr", None),
    ("제주특별자치도의회", "광역", "www.council.jeju.kr", None),
    # ── 경기도 시·군 31 ───────────────────────────────────────────────────
    ("수원특례시의회", "경기시군", "council.suwon.go.kr", None),
    ("고양특례시의회", "경기시군", "www.goyangcouncil.go.kr", None),
    ("용인특례시의회", "경기시군", "council.yongin.go.kr", None),
    ("성남시의회", "경기시군", "www.sncouncil.go.kr", "cast.sncouncil.go.kr"),
    ("부천시의회", "경기시군", "council.bucheon.go.kr", None),
    ("화성특례시의회", "경기시군", "council.hscity.go.kr", None),
    ("안산시의회", "경기시군", "www.ansan.go.kr", "vod.ansan.go.kr"),
    ("남양주시의회", "경기시군", "www.nyjc.go.kr", None),
    ("안양시의회", "경기시군", "www.aycouncil.go.kr", None),
    ("평택시의회", "경기시군", "www.ptcouncil.go.kr", None),
    ("시흥시의회", "경기시군", "www.siheungcouncil.go.kr", "livecouncil.siheung.go.kr"),
    ("파주시의회", "경기시군", "www.pajucouncil.go.kr", None),
    ("의정부시의회", "경기시군", "www.ujbcl.go.kr", None),
    ("김포시의회", "경기시군", "www.gimpocouncil.go.kr", None),
    ("광주시의회", "경기시군", "www.gjcouncil.go.kr", None),
    ("광명시의회", "경기시군", "council.gm.go.kr", None),
    ("군포시의회", "경기시군", "www.gunpocouncil.go.kr", None),
    ("하남시의회", "경기시군", "council.hanam.go.kr", None),
    ("오산시의회", "경기시군", "www.osancouncil.go.kr", None),
    ("양주시의회", "경기시군", "yjcc.yangju.go.kr", None),
    ("이천시의회", "경기시군", "council.icheon.go.kr", None),
    ("구리시의회", "경기시군", "www.gcc.or.kr", None),
    ("안성시의회", "경기시군", "www.anseongcl.go.kr", None),
    ("포천시의회", "경기시군", "council.pocheon.go.kr", None),
    ("의왕시의회", "경기시군", "council.uiwang.go.kr", None),
    ("양평군의회", "경기시군", "www.ypcouncil.go.kr", None),
    ("여주시의회", "경기시군", "www.yeojucouncil.go.kr", None),
    ("동두천시의회", "경기시군", "council.ddc.go.kr", None),
    ("과천시의회", "경기시군", "www.gccouncil.go.kr", None),
    ("가평군의회", "경기시군", "www.gpassem.go.kr", None),
    ("연천군의회", "경기시군", "www.yca21.go.kr", None),
]

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36"}


def _get(client: httpx.Client, url: str) -> tuple[int, str, str]:
    try:
        resp = client.get(url)
        return resp.status_code, str(resp.url), resp.text[:200_000]
    except Exception as exc:                            # noqa: BLE001
        return 0, url, f"__error__ {exc}"


_HREF_RE = re.compile(r"""href=["']([^"']+)["']""", re.I)
_ANCHOR_RE = re.compile(r"""<a[^>]+href=["']([^"']+)["'][^>]*>(.{0,60}?)</a>""", re.I | re.S)
_LIVE_TEXT_RE = re.compile(r"생방송|생중계|인터넷\s*방송|의사중계|온에어|실시간\s*방송", re.I)
_LIVE_HREF_RE = re.compile(r"onair|cast/live|live_list|livePlay|broadcast|/live\b", re.I)


def _find_live_links(body: str, base: str) -> list[str]:
    """홈페이지에서 '생방송·인터넷방송' 으로 보이는 링크를 뽑는다.

    알려진 경로 후보가 다 빗나갈 때의 그물이다 — 의회마다 메뉴 구조가 제각각이라
    경로 목록만으로는 절반밖에 못 맞힌다(실측 24/48).
    """
    out: list[str] = []
    host = urlparse(base).hostname or ""
    # href 만으로도 훑는다 — <a> 안에 아이콘·span 이 겹겹이면 글자 추출이 실패해
    # 링크 자체를 놓친다(양평군의회 /assembly/kr/cast/live.do 를 그렇게 놓쳤다).
    candidates: list[tuple[str, str]] = [
        (h, "") for h in _HREF_RE.findall(body) if _LIVE_HREF_RE.search(h)
    ]
    candidates += _ANCHOR_RE.findall(body)
    for href, text in candidates:
        plain = re.sub(r"<[^>]+>", "", text).strip()
        if not (_LIVE_TEXT_RE.search(plain) or _LIVE_HREF_RE.search(href)):
            continue
        absolute = urljoin(base, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue
        # 정부 도메인 안에서만 따라간다(유튜브·네이버 링크 제외).
        # 같은 등록 도메인으로 좁히면 시흥시의회처럼 생중계가 별도 호스트
        # (livecouncil.siheung.go.kr)에 있는 곳을 놓친다.
        target = (parsed.hostname or "").lower()
        if not (target.endswith(".go.kr") or target.endswith(".or.kr") or target == host):
            continue
        if absolute not in out:
            out.append(absolute)
        if len(out) >= 10:
            break
    return out


def _looks_like_live_page(body: str) -> bool:
    """생중계 페이지인지 대충 가른다 — 404 를 200 으로 주는 사이트가 흔하다."""
    markers = ("생방송", "생중계", "인터넷방송", "onair", "m3u8", "의사중계")
    lowered = body.lower()
    return any(m.lower() in lowered for m in markers)


def probe(entry: tuple[str, str, str, str | None]) -> dict:
    name, region, home_host, live_host = entry
    result = {
        "name": name,
        "region": region,
        "homepage": f"https://{home_host}/",
        "live_page": None,
        "vendor": None,
        "http_status": None,
        "note": "",
    }
    # 인증서 체인이 부실한 공공 사이트가 많아 verify=False 로 확인만 한다(값을 신뢰하진 않는다).
    with httpx.Client(timeout=10.0, follow_redirects=True, verify=False, headers=UA) as client:
        hosts = [h for h in (live_host, home_host) if h]
        for host in hosts:
            for path, vendor in LIVE_PATHS:
                status, final_url, body = _get(client, f"https://{host}{path}")
                if status != 200 or body.startswith("__error__"):
                    continue
                if path == "/" and host == home_host:
                    continue        # 홈페이지 자체는 생중계 페이지가 아니다
                if not _looks_like_live_page(body):
                    continue
                result.update(live_page=final_url, vendor=vendor, http_status=status)
                if ".m3u8" in body:
                    result["note"] = "페이지에 영상 주소가 보입니다 — 자동 찾기가 바로 잡습니다"
                return result
        # 알려진 경로가 다 빗나갔다 — 홈페이지의 링크를 따라가 본다
        status, home_url, home_body = _get(client, f"https://{home_host}/")
        if status == 200 and not home_body.startswith("__error__"):
            for link in _find_live_links(home_body, home_url):
                status2, final_url, body2 = _get(client, link)
                if status2 != 200 or body2.startswith("__error__"):
                    continue
                if not _looks_like_live_page(body2):
                    continue
                vendor = "webpot" if "/onair/" in final_url else (
                    "cast-do" if "/cast/live" in final_url else "etc"
                )
                result.update(live_page=final_url, vendor=vendor, http_status=status2,
                              note="홈페이지의 인터넷방송 링크에서 찾았습니다")
                if ".m3u8" in body2:
                    result["note"] = "페이지에 영상 주소가 보입니다 — 자동 찾기가 바로 잡습니다"
                return result
        result["note"] = "생중계 페이지를 자동으로 찾지 못했습니다 — 주소를 직접 넣어 주세요"
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(probe, COUNCILS))

    found = sum(1 for r in rows if r["live_page"])
    payload = {
        "generated_at": date.today().isoformat(),
        "source": "backend/scripts/harvest_council_presets.py (실제 접속해 확인)",
        "note": (
            "영상 주소가 아니라 생중계 **페이지** 주소다. 대부분의 의회는 방송 중일 때만 "
            "영상 주소가 드러나므로, 페이지를 넣고 자동 찾기를 돌린다."
        ),
        "councils": rows,
    }
    print(f"확인: {found}/{len(rows)}곳에서 생중계 페이지를 찾았다")
    for r in rows:
        mark = "O" if r["live_page"] else "-"
        print(f"  {mark} {r['name']:18} {r.get('vendor') or '':8} {r['live_page'] or r['note']}")

    if args.dry_run:
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n기록: {OUT}")


if __name__ == "__main__":
    main()
