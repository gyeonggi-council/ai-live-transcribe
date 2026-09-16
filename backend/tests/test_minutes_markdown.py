"""minutes_markdown 테스트

공식 전자회의록(hwpx_export._build_official_paragraphs)과 동일한 구조·내용을
마크다운으로 재현하는지 검증한다. 픽스처는 tests/services/test_hwpx_export.py의
공식 양식 픽스처와 동일한 형태를 사용한다.
"""

from app.services.hwpx_export import _build_official_paragraphs
from app.services.minutes_markdown import build_official_markdown

MEETING = {
    "title": "제391회 제3차 경제노동위원회 [2026-06-16]",
    "meeting_date": "2026-06-16",
}

GROUPED = [
    {"speaker": "허원 위원장", "start_time": 2.0, "end_time": 40.0,
     "texts": ["회의를 개의하겠습니다."]},
    {"speaker": "허원 위원장", "start_time": 41.0, "end_time": 90.0,
     "texts": ["이어지는 발언."]},
    {"speaker": "건설국장", "start_time": 91.0, "end_time": 120.0,
     "texts": ["제안설명 드리겠습니다."]},
]

AGENDAS = [{"order_num": 1, "title": "2026년도 제1회 경기도 추가경정예산안"}]


def test_title_three_lines_are_markdown_headings():
    """제목 3줄(제N회 경기도의회 / 위원회 회의록 / 제N호)이 헤딩으로 생성된다."""
    md = build_official_markdown(MEETING, GROUPED, AGENDAS)
    lines = md.splitlines()
    assert "# 제391회 경기도의회" in lines
    assert "## 경제노동위원회 회의록" in lines
    assert "### 제 3 호" in lines


def test_header_office_date_place():
    """경기도의회사무처/일시/장소가 hwpx와 동일한 문자열로 들어간다."""
    md = build_official_markdown(MEETING, GROUPED, AGENDAS)
    assert "경기도의회사무처" in md
    assert "일  시: 2026년 6월 16일(화)" in md
    assert "장  소: 경제노동위원회 회의실" in md


def test_agenda_sections():
    """의사일정/심사된 안건 헤더(굵게) + 안건 목록이 두 섹션 모두에 들어간다."""
    md = build_official_markdown(MEETING, GROUPED, AGENDAS)
    assert "**의사일정**" in md
    assert "**심사된 안건**" in md
    assert md.count("1. 2026년도 제1회 경기도 추가경정예산안") == 2


def test_agenda_placeholder_when_missing():
    """안건 미등록 시 hwpx와 동일한 안내 문구를 넣는다."""
    md = build_official_markdown(MEETING, GROUPED, None)
    assert "(안건 정보가 등록되지 않았습니다.)" in md


def test_opening_line():
    """(개의) 라인이 본문 시작 전에 들어간다."""
    md = build_official_markdown(MEETING, GROUPED, AGENDAS)
    assert "(개의)" in md


def test_speaker_paragraphs_and_repeated_speaker_suppression():
    """발언은 '○ 화자'(굵게) 단락 + 본문 단락. 같은 화자 연속 시 화자 표기 생략."""
    md = build_official_markdown(MEETING, GROUPED, AGENDAS)
    # 연속 2개 그룹(허원 위원장)에서 머리표는 1번만
    assert md.count("○ 허원 위원장") == 1
    assert "**○ 허원 위원장**" in md
    assert md.count("○ 건설국장") == 1
    # 발언 텍스트는 모두 보존
    assert "회의를 개의하겠습니다." in md
    assert "이어지는 발언." in md
    assert "제안설명 드리겠습니다." in md


def test_attendance_footer():
    """말미 출석위원/출석공무원 명단(hwpx와 동일 규칙)."""
    md = build_official_markdown(MEETING, GROUPED, AGENDAS)
    assert "출석위원(1명)" in md
    assert "허원" in md
    assert "출석공무원(1명)" in md
    assert "건설국장" in md


def test_kind_fallback_from_subtitles():
    """제목에 회의종류가 없으면 자막 개의 멘트에서 정례회/임시회를 보강(hwpx와 동일)."""
    grouped = [
        {"speaker": "화자 1", "start_time": 0.0, "end_time": 30.0,
         "texts": ["성원이 되었으므로 제391회 경기도의회 정례회 제3차 경제노동위원회 "
                   "회의를 개의하겠습니다."]},
    ]
    md = build_official_markdown(MEETING, grouped, AGENDAS)
    assert "# 제391회 경기도의회(정례회)" in md.splitlines()


def test_empty_grouped_placeholder():
    """자막이 없으면 hwpx와 동일한 안내 문구."""
    md = build_official_markdown(MEETING, [], AGENDAS)
    assert "(자막 데이터가 없습니다.)" in md


def test_ai_notice_included():
    """AI 자동 생성 안내 문구가 말미에 포함된다(hwpx와 동일 내용)."""
    md = build_official_markdown(MEETING, GROUPED, AGENDAS)
    assert "AI 음성인식으로 자동 생성된 초안" in md


def test_full_parity_with_hwpx_paragraphs():
    """hwpx 공식 문단(_build_official_paragraphs)의 모든 비어있지 않은 텍스트가
    마크다운에도 그대로(부분 문자열로) 존재해야 한다 — 내용 동일성 보증."""
    md = build_official_markdown(MEETING, GROUPED, AGENDAS)
    for text, _bold, _center in _build_official_paragraphs(MEETING, GROUPED, AGENDAS):
        if text:
            assert text in md, f"hwpx 문단 누락: {text!r}"
