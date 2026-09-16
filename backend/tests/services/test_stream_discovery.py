"""생중계 페이지 → 영상 주소 자동 찾기 (2026-09-16)

⚠ 실제 서버를 부르지 않는다. 고정 HTML 픽스처만 쓴다 — 외부 사이트가 바뀌면
   테스트가 우리 코드와 무관하게 깨지고, CI 가 남의 서버를 두드리게 된다.
"""

from pathlib import Path

import pytest

from app.core.url_guard import FetchResult
from app.services import stream_discovery as sd

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "discovery"


def _fake_fetch(pages: dict[str, str]):
    async def _fetch(url, **kwargs):
        if url not in pages:
            raise RuntimeError(f"404 {url}")
        return FetchResult(url=url, status_code=200, text=pages[url], content_type="text/html")

    return _fetch


@pytest.mark.asyncio
async def test_webpot_concat_template_is_expanded(monkeypatch):
    """경기도의회 계열 — 주소가 자바스크립트 문자열 결합으로만 있어도 찾아낸다.

    실제 페이지의 규칙: var streamUrl = "https://" + ip + "/live/" + ch + "/playlist.m3u8"
    """
    html = (FIXTURES / "webpot_onair.html").read_text(encoding="utf-8")
    page = "https://example.org/onair/onair.do"
    monkeypatch.setattr(sd, "safe_fetch", _fake_fetch({page: html}))

    result = await sd.discover_channels(page)

    urls = {c.m3u8_url for c in result.candidates}
    assert "https://stream01.cdn.gov-ntruss.com/live/ch14/playlist.m3u8" in urls
    assert "https://stream02.cdn.gov-ntruss.com/live/ch7/playlist.m3u8" in urls
    assert result.vendor == "webpot"

    # 채널 이름을 목록의 글자에서 가져온다
    by_id = {c.suggested_id: c for c in result.candidates}
    assert by_id["ch14"].name == "본회의"
    assert by_id["ch7"].name == "안전행정위원회"


@pytest.mark.asyncio
async def test_page_without_stream_returns_actionable_warning(monkeypatch):
    """방송이 꺼져 있으면 주소가 없다 — 그냥 '실패' 가 아니라 다음 할 일을 알려준다."""
    html = (FIXTURES / "no_stream.html").read_text(encoding="utf-8")
    page = "https://example.org/kr/cast/live.do"
    monkeypatch.setattr(sd, "safe_fetch", _fake_fetch({page: html}))

    result = await sd.discover_channels(page)

    assert result.candidates == []
    assert any("방송 중" in w for w in result.warnings)
    assert any("직접 붙여넣" in w for w in result.warnings)
    # 무엇을 읽었는지 근거를 남긴다
    assert result.fetched and result.fetched[0]["status"] == 200


@pytest.mark.asyncio
async def test_literal_m3u8_is_found(monkeypatch):
    page = "https://example.org/live"
    html = '<video><source src="https://cdn.example.org/live/a1/playlist.m3u8"></video>'
    monkeypatch.setattr(sd, "safe_fetch", _fake_fetch({page: html}))

    result = await sd.discover_channels(page)
    assert [c.m3u8_url for c in result.candidates] == [
        "https://cdn.example.org/live/a1/playlist.m3u8"
    ]


@pytest.mark.asyncio
async def test_scripts_from_other_domains_are_not_followed(monkeypatch):
    """다른 도메인의 스크립트는 따라가지 않는다 — 탐지기를 남의 서버 조회에 쓰지 못하게."""
    page = "https://council.example.org/onair/onair.do"
    html = '<script src="https://evil.example.net/x.js"></script><script src="/js/ok.js"></script>'
    pages = {page: html, "https://council.example.org/js/ok.js": "// nothing"}
    monkeypatch.setattr(sd, "safe_fetch", _fake_fetch(pages))

    result = await sd.discover_channels(page)
    read = [f["url"] for f in result.fetched]
    assert "https://evil.example.net/x.js" not in read
    assert "https://council.example.org/js/ok.js" in read
