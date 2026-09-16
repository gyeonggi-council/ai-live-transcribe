# -*- coding: utf-8 -*-
"""의회 홈페이지 파싱 (services/councilor_profile, 2026-09-16).

마크업이 바뀌면 **빈 결과**가 나와야 한다 — 틀린 이름이 나오는 것보다 낫다.
"""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "councilor_profile", Path(__file__).resolve().parents[2] / "app" / "services" / "councilor_profile.py")
cp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cp)

COMMITTEE_HTML = """
<ul class="memberList3 clear">
  <li>
    <div class="img fl"><img class="img-thumbnail" alt="김창식위원장" src="/site/main/gwstorage/PhotoPath/family554_org^jpg" /></div>
    <div class="text fl">
      <p class="f22 blue3">김창식<span class="f15">위원장</span></p>
      <ul class="list_style01">
        <li class="f15 m0">더불어민주당</li>
        <li class="f15 m0">남양주시 제5선거구</li>
        <li class="f15 m0">기획재정위원회위원장</li>
      </ul>
      <a href="/site/lwmkr/blog/11026/12" class="btn btn_gray mt_15" target="_blank">의원홈페이지</a>
    </div>
  </li>
  <li>
    <div class="img fl"><img class="img-thumbnail" alt="손희정부위원장" src="/site/main/gwstorage/PhotoPath/sonhj67_org^jpg" /></div>
    <div class="text fl">
      <p class="f22 blue3">손희정<span class="f15">부위원장</span></p>
      <ul class="list_style01">
        <li class="f15 m0">더불어민주당</li>
        <li class="f15 m0">파주시 제2선거구</li>
      </ul>
      <a href="/site/lwmkr/blog/10063/12" class="btn btn_gray mt_15" target="_blank">의원홈페이지</a>
    </div>
  </li>
</ul>
"""

CAREER_HTML = """
<ul class="area main_01_content2_02"><li>- 기획재정위원회 위원장</li></ul>
<div class="main_01_content2_01">&lt;약력 및 경력&gt;</div>
<div id="lawmakStory" class="main_01_content2_02">
  <!-- 운영데이터는 <br> 구분처리함 -->
  <p>(現) 제12대 경기도의원</p><p>(現) 청학고등학교 운영위원</p><p>(前) 제11대 경기도의원</p>
</div>
"""


def test_committee_page_gives_name_role_party_district_and_member_no():
    rows = cp.parse_committee_page(COMMITTEE_HTML)
    assert [r["name"] for r in rows] == ["김창식", "손희정"]
    assert rows[0]["role"] == "위원장"
    assert rows[0]["party"] == "더불어민주당"
    assert rows[0]["district"] == "남양주시 제5선거구"
    assert rows[0]["member_no"] == "11026"
    assert rows[0]["photo_url"].startswith("https://www.ggc.go.kr/")
    assert rows[1]["role"] == "부위원장"


def test_career_and_positions():
    assert cp.parse_career(CAREER_HTML) == [
        "(現) 제12대 경기도의원", "(現) 청학고등학교 운영위원", "(前) 제11대 경기도의원",
    ]
    assert cp.parse_committee_positions(CAREER_HTML) == ["기획재정위원회 위원장"]


def test_unknown_markup_returns_empty_not_garbage():
    assert cp.parse_committee_page("<html><body>바뀐 화면</body></html>") == []
    assert cp.parse_career("<html><body>바뀐 화면</body></html>") == []
    assert cp.parse_committee_positions("<html></html>") == []


def test_role_sorting_puts_chair_first():
    rows = [{"name": "나", "role": "위원"}, {"name": "가", "role": "부위원장"}, {"name": "다", "role": "위원장"}]
    assert [r["name"] for r in cp._sort_by_role(rows)] == ["다", "가", "나"]
