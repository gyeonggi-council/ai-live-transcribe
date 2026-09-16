"""glossary_service 테스트

build_glossary_terms, format_glossary_prompt, load_meeting_glossary 를 테스트합니다.
"""

from unittest.mock import MagicMock

from app.services.glossary_service import build_glossary_terms, format_glossary_prompt


def test_build_glossary_terms_dedupes_and_orders():
    terms = build_glossary_terms(
        dictionary_terms=["산회", "개의", "산회"],
        councilor_names=["김영수", "이민정"],
        bill_titles=["경기도 청년 기본소득 조례안"],
        subtitle_terms=["보건복지위원회"],
    )
    assert terms.count("산회") == 1
    assert "김영수" in terms and "이민정" in terms
    assert "경기도 청년 기본소득 조례안" in terms
    assert "보건복지위원회" in terms


def test_format_glossary_prompt_empty_returns_empty_string():
    assert format_glossary_prompt([]) == ""


def test_format_glossary_prompt_includes_terms():
    prompt = format_glossary_prompt(["산회", "김영수"])
    assert "산회" in prompt
    assert "김영수" in prompt


# ──────────────────────────────────────────────
# load_meeting_glossary 통합 테스트
# ──────────────────────────────────────────────


from app.services.glossary_service import load_meeting_glossary


def test_load_meeting_glossary_combines_sources(monkeypatch):
    supabase = MagicMock()

    def table(name):
        m = MagicMock()
        if name == "dictionary":
            m.select.return_value.limit.return_value.execute.return_value.data = [
                {"correct_text": "산회"}, {"correct_text": "개의"},
            ]
        elif name == "meetings":
            m.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
                {"committee": "보건복지위원회"}
            ]
        elif name == "bills":
            m.select.return_value.eq.return_value.execute.return_value.data = [
                {"title": "경기도 청년 조례안"}
            ]
        elif name == "subtitles":
            m.select.return_value.eq.return_value.order.return_value.execute.return_value.data = [
                {"text": "보건복지위원회 회의를 시작합니다", "speaker": "김영수"}
            ]
        return m

    supabase.table.side_effect = table

    monkeypatch.setattr(
        "app.services.glossary_service._committee_councilor_names",
        lambda sb, committee: ["김영수", "이민정"],
    )

    terms = load_meeting_glossary(supabase, "meeting-uuid")
    assert "산회" in terms
    assert "김영수" in terms
    assert "경기도 청년 조례안" in terms


def _staff_mock_supabase():
    """committee가 해석되는 회의 + 사전 1건의 supabase 목."""
    supabase = MagicMock()

    def table(name):
        m = MagicMock()
        if name == "dictionary":
            m.select.return_value.limit.return_value.execute.return_value.data = [
                {"correct_text": "산회"},
            ]
        elif name == "meetings":
            m.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
                {"committee": "건설교통위원회"}
            ]
        elif name == "bills":
            m.select.return_value.eq.return_value.execute.return_value.data = []
        elif name == "subtitles":
            m.select.return_value.eq.return_value.order.return_value.execute.return_value.data = []
        return m

    supabase.table.side_effect = table
    return supabase


def test_load_meeting_glossary_staff_injected_after_councilors(monkeypatch):
    """staff 명부(속기록 출석명단)가 의원명 바로 뒤에 주입된다 (문자 캡 보존 순위)."""
    supabase = _staff_mock_supabase()
    monkeypatch.setattr(
        "app.services.glossary_service._committee_councilor_names",
        lambda sb, committee: ["김영수"],
    )
    monkeypatch.setattr(
        "app.services.staff_roster_service.load_staff_roster",
        lambda sb, committee: [
            {"name": "배성호", "title": "국장", "department": "건설국", "full_title": "건설국장"},
        ],
    )

    terms = load_meeting_glossary(supabase, "meeting-uuid")
    assert "배성호 건설국장" in terms
    # 순서: 의원명 → staff → 용어사전 (절단 시 staff가 사전보다 먼저 보존)
    assert terms.index("김영수") < terms.index("배성호 건설국장") < terms.index("산회")


def test_load_meeting_glossary_staff_fail_soft(monkeypatch):
    """staff 명부 로드 실패는 무시되고 나머지 글로서리는 정상 반환된다."""
    supabase = _staff_mock_supabase()
    monkeypatch.setattr(
        "app.services.glossary_service._committee_councilor_names",
        lambda sb, committee: ["김영수"],
    )

    def _boom(sb, committee):
        raise RuntimeError("staff_roster 조회 실패")

    monkeypatch.setattr("app.services.staff_roster_service.load_staff_roster", _boom)

    terms = load_meeting_glossary(supabase, "meeting-uuid")
    assert "김영수" in terms
    assert "산회" in terms
    assert not any("건설국장" in t for t in terms)


def test_format_glossary_prompt_max_chars_cap():
    """max_chars 캡: 매 호출 재전송되는 라이브 경로의 prompt 토큰 비용 상한."""
    from app.services.glossary_service import format_glossary_prompt

    terms = [f"용어{i:03d}" for i in range(100)]  # 각 5자
    out = format_glossary_prompt(terms, max_chars=50)
    # 용어 부분이 50자 이내로 절단됨 (접두 문구 제외)
    joined = out.split(": ", 1)[1]
    assert len(joined) <= 50
    # 앞쪽 용어(의원명 위치)가 보존됨
    assert "용어000" in joined


def test_format_glossary_prompt_max_chars_keeps_first_term():
    """캡이 첫 용어보다 작아도 최소 1개는 유지한다."""
    from app.services.glossary_service import format_glossary_prompt

    out = format_glossary_prompt(["아주아주아주아주긴첫번째용어"], max_chars=3)
    assert "아주아주아주아주긴첫번째용어" in out


def test_format_glossary_prompt_no_cap_backward_compat():
    """max_chars 미지정 시 기존 동작(용어 수 캡만) 유지."""
    from app.services.glossary_service import format_glossary_prompt

    terms = [f"용어{i}" for i in range(300)]
    out = format_glossary_prompt(terms)
    assert "용어199" in out and "용어200" not in out
