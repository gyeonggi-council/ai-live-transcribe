# -*- coding: utf-8 -*-
"""KMS 공식 발언자 인덱스 — 데스크톱 추출기 ggc_core 이식분 검증

실측 응답(2026-09-03, midx 138270)을 픽스처로 쓴다. KMS 는 브라우저 UA 가 없으면
200 + HTML 오류 페이지를 돌려주므로 "JSON 아님 → 빈 목록" 이 핵심 분기다.
"""

import json

import httpx
import pytest

from app.services import kms_angun_service as kms
from app.services.kms_vod_resolver import KMS_BROWSER_HEADERS

ANGUN_138270 = [
    {"m_sec": "00", "m_code": "", "m_mbr": "C", "m_min": "00", "m_hour": "00", "m_pos": "0",
     "m_angun": "제392회 임시회 제2차 건설교통위원회 회의 개의"},
    {"m_sec": "46", "m_code": "10027", "m_mbr": "A", "m_min": "00", "m_hour": "00", "m_pos": "46",
     "m_angun": "1. 업무보고의 건"},
    {"m_sec": "23", "m_code": "", "m_mbr": "N", "m_min": "01", "m_hour": "00", "m_pos": "83",
     "m_angun": "간부소개 및 업무보고(건설국장 배성호)"},
    {"m_sec": "34", "m_code": "12057", "m_mbr": "M", "m_min": "24", "m_hour": "00", "m_pos": "1474",
     "m_angun": "자료요구(김지호 위원)"},
    {"m_sec": "05", "m_code": "12202", "m_mbr": "M", "m_min": "25", "m_hour": "00", "m_pos": "1505",
     "m_angun": "자료요구(윤순옥 위원)"},
    {"m_sec": "00", "m_code": "12052", "m_mbr": "M", "m_min": "26", "m_hour": "00", "m_pos": "1560",
     "m_angun": "자료요구(김순현 위원)"},
    {"m_sec": "52", "m_code": "12202", "m_mbr": "M", "m_min": "26", "m_hour": "00", "m_pos": "1612",
     "m_angun": "자료요구(윤순옥 위원)"},
]

HTML_BLOCK_PAGE = "<html><head><meta charset=\"euc-kr\"></head><body>차단</body></html>"


@pytest.fixture(autouse=True)
def _clear_cache():
    kms.clear_cache()
    yield
    kms.clear_cache()


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestFetchAngun:
    @pytest.mark.asyncio
    async def test_sends_browser_headers_and_parses(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["ua"] = request.headers.get("user-agent")
            seen["referer"] = request.headers.get("referer")
            seen["url"] = str(request.url)
            return httpx.Response(200, text=json.dumps(ANGUN_138270, ensure_ascii=False))

        async with _client(handler) as c:
            items = await kms.fetch_angun("138270", client=c)

        assert seen["ua"] == KMS_BROWSER_HEADERS["User-Agent"]
        assert seen["referer"] == KMS_BROWSER_HEADERS["Referer"]
        assert "listAngunXhr.do?midx=138270" in seen["url"]
        assert [i["pos"] for i in items] == [0, 46, 83, 1474, 1505, 1560, 1612]
        assert items[3]["code"] == "12057" and items[3]["title"] == "자료요구(김지호 위원)"
        assert items[3]["time"] == "00:24:34"

    @pytest.mark.asyncio
    async def test_html_block_page_returns_empty(self):
        async with _client(lambda r: httpx.Response(200, text=HTML_BLOCK_PAGE)) as c:
            assert await kms.fetch_angun("138270", client=c) == []

    @pytest.mark.asyncio
    async def test_http_error_returns_empty(self):
        async with _client(lambda r: httpx.Response(500, text="x")) as c:
            assert await kms.fetch_angun("138270", client=c) == []

    @pytest.mark.asyncio
    async def test_non_numeric_midx_skips_network(self):
        async def boom(r):  # pragma: no cover
            raise AssertionError("network must not be called")

        async with _client(boom) as c:
            assert await kms.fetch_angun("abc", client=c) == []

    @pytest.mark.asyncio
    async def test_cache_hit_skips_second_request(self):
        calls = {"n": 0}

        def handler(r):
            calls["n"] += 1
            return httpx.Response(200, text=json.dumps(ANGUN_138270, ensure_ascii=False))

        async with _client(handler) as c:
            await kms.fetch_angun("138270", client=c)
            await kms.fetch_angun("138270", client=c)
        assert calls["n"] == 1


class TestBuildSpeakers:
    def test_end_is_next_pos_and_last_is_duration(self):
        items = kms.parse_angun(ANGUN_138270)
        speakers = kms.build_speakers(items, duration=2000)
        by_name = {s["name"]: s for s in speakers}
        yoon = by_name["윤순옥"]
        assert [ (s["start"], s["end"]) for s in yoon["segments"] ] == [(1505, 1560), (1612, 2000)]
        assert yoon["code"] == "12202"
        assert all(s["named"] for s in yoon["segments"])

    def test_code_only_items_are_unnamed_procedural(self):
        items = kms.parse_angun(ANGUN_138270)
        speakers = kms.build_speakers(items, duration=2000)
        procedural = [s for s in speakers if s["code"] == "10027"]
        assert len(procedural) == 1
        assert procedural[0]["name"] == ""           # 호출자가 채우거나 버린다
        assert procedural[0]["segments"][0]["named"] is False

    def test_items_without_name_or_code_are_skipped(self):
        items = kms.parse_angun(ANGUN_138270)
        speakers = kms.build_speakers(items, duration=2000)
        titles = [seg["title"] for s in speakers for seg in s["segments"]]
        assert "간부소개 및 업무보고(건설국장 배성호)" not in titles
        assert "제392회 임시회 제2차 건설교통위원회 회의 개의" not in titles

    def test_sorted_by_total_desc(self):
        items = kms.parse_angun(ANGUN_138270)
        speakers = kms.build_speakers(items, duration=2000)
        totals = [s["total_seconds"] for s in speakers]
        assert totals == sorted(totals, reverse=True)


class TestPadAndMerge:
    def test_overlap_rule(self):
        segs = [{"start": 100, "end": 130}, {"start": 131, "end": 160}, {"start": 200, "end": 220}]
        out = kms.pad_and_merge(segs, 0, 0, duration=1000)
        assert out == [{"start": 100.0, "end": 160.0}, {"start": 200.0, "end": 220.0}]

    def test_pad_clamps_to_zero_and_duration(self):
        out = kms.pad_and_merge([{"start": 2, "end": 995}], 5, 10, duration=1000)
        assert out == [{"start": 0.0, "end": 1000.0}]


class TestEnrich:
    def test_uses_councilor_directory_not_kms_photo(self):
        roster = [{"id": "c1", "name": "김지호", "party": "더불어민주당", "district": "부천시",
                   "profile_image_url": "https://www.ggc.go.kr/photo/1.jpg"}]
        speakers = [{"name": "김지호", "party": None, "district": None,
                     "photo_url": None, "councilor_id": None}]
        kms.enrich_with_councilors(speakers, roster)
        assert speakers[0]["party"] == "더불어민주당"
        assert speakers[0]["photo_url"].startswith("https://www.ggc.go.kr/")
        assert speakers[0]["councilor_id"] == "c1"

    def test_fuzzy_match_survives_stt_typo(self):
        roster = [{"id": "c1", "name": "윤순옥"}, {"id": "c2", "name": "박은주"}]
        assert kms.match_councilor("윤순욱", roster)["id"] == "c1"
        assert kms.match_councilor("홍길동", roster) is None

    def test_fuzzy_tie_is_unresolved(self):
        """실측(2026-09-04 1차 본회의): STT '김해철' 은 김회철·김철환 어느 쪽과도 한 글자 차이.
        아무나 고르면 다른 의원의 클립이 된다 → None (호출자가 옆 단서로 정한다)."""
        roster = [{"id": "c1", "name": "김회철"}, {"id": "c2", "name": "김철환"}, {"id": "c3", "name": "박은주"}]
        assert kms.match_councilor("김해철", roster) is None
        ranked = kms.rank_councilors("김해철", roster)
        assert [c["name"] for _, c in ranked] == ["김회철", "김철환"]
        assert ranked[0][0] == pytest.approx(ranked[1][0])

    def test_exact_match_with_namesake_picks_first_row(self):
        roster = [{"id": "c1", "name": "김성태"}, {"id": "c2", "name": "김성태"}]
        assert kms.match_councilor("김성태", roster)["id"] == "c1"
        assert kms.rank_councilors("김성태", roster)[0][0] == 1.0

class TestRoleFirstTitle:
    def test_role_before_name_is_named_segment(self):
        """실측(윤리특위 138289): '위원장 인사(위원장 유종상)' — 직책이 앞에 온다."""
        items = kms.parse_angun([
            {"m_pos": "385", "m_code": "11013", "m_mbr": "M", "m_angun": "위원장 인사(위원장 유종상)"},
            {"m_pos": "459", "m_code": "11013", "m_mbr": "A", "m_angun": "2. 부위원장 선출의 건"},
        ])
        sp = kms.build_speakers(items, duration=600)
        assert sp[0]["name"] == "유종상" and sp[0]["role"] == "위원장"
        assert [s["named"] for s in sp[0]["segments"]] == [True, False]
        assert kms.find_name("자료요구(김지호 위원)") == ("김지호", "위원")
        assert kms.find_name("1. 업무보고의 건") is None
