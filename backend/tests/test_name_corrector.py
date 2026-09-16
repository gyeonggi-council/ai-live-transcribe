"""위원 이름 명부 교정 (name_corrector) 단위 테스트."""

from app.services.name_corrector import correct_member_names

ROSTER = ["김종배", "조성환", "김시용", "박옥분"]


def test_corrects_misrecognized_name():
    # STT 오인식 김종대 → 명부의 김종배로 교정
    assert (
        correct_member_names("김종대 위원님 나오셔서 제안설명해 주시기 바랍니다", ROSTER)
        == "김종배 위원님 나오셔서 제안설명해 주시기 바랍니다"
    )


def test_keeps_exact_roster_name():
    # 이미 명부에 정확히 있으면 손대지 않음
    assert correct_member_names("조성환 위원장입니다", ROSTER) == "조성환 위원장입니다"


def test_leaves_non_roster_name_untouched():
    # 명부에 충분히 가까운 이름이 없으면 원본 유지(없는 이름 생성 방지)
    assert correct_member_names("이재명 의원께서 발언하셨습니다", ROSTER) == (
        "이재명 의원께서 발언하셨습니다"
    )


def test_no_roster_returns_original():
    assert correct_member_names("김종대 위원", []) == "김종대 위원"


def test_does_not_corrupt_committee_name():
    # '위원회' 같은 일반 단어/위원회명은 교정 대상 아님
    txt = "도시환경위원회 제1차 회의를 개의하겠습니다"
    assert correct_member_names(txt, ROSTER) == txt


def test_corrects_multiple_mentions():
    out = correct_member_names("김종대 위원과 박옥뷴 위원이 질의했습니다", ROSTER)
    assert "김종배 위원" in out
    assert "박옥분 위원" in out


# ── 위원회명 손상 방지 (리뷰 important: '위원회'의 '위원'을 호칭으로 오인) ──────────
def test_committee_name_fragment_not_corrupted():
    # roster 위원명과 겹치는 위원회명 조각이 있어도 '위원회'는 손대지 않는다.
    roster = ["평생교"]  # 가상의 충돌형 이름
    txt = "여성가족평생교육위원회를 개의합니다"
    assert correct_member_names(txt, roster) == txt


def test_committee_word_alone_untouched():
    assert correct_member_names("운영위원회 회의입니다", ["운영수"]) == "운영위원회 회의입니다"


def test_chairperson_still_corrected():
    # 위원장은 위원(?!회)와 무관하게 계속 교정/보존되어야 한다.
    assert correct_member_names("조성환 위원장입니다", ROSTER) == "조성환 위원장입니다"
    assert correct_member_names("조성한 위원장입니다", ROSTER) == "조성환 위원장입니다"


# ── 이름 내부 공백 / 앞글자 잠식 (리뷰 important: 문자열 손상) ────────────────────
def test_spaced_name_not_duplicated():
    # 과거 버그: '김 종배 위원' → '김 김종배 위원'. 이제 깨지지 않고 정규화된다.
    out = correct_member_names("김 종배 위원", ROSTER)
    assert out == "김종배 위원"
    assert "김 김" not in out


def test_runon_preceding_char_not_eaten():
    # 과거 버그: '저는김종대 위원' → '저김종대 위원'('는' 소실). 이제 본문을 먹지 않는다.
    out = correct_member_names("저는김종대 위원", ROSTER)
    assert "저는" in out  # 앞 단어 보존


# ── 동점 모호성 (리뷰 minor: 비결정적 승자 → 안전측 미교정) ──────────────────────
def test_ambiguous_tie_left_unchanged():
    # 후보가 여러 명부 이름과 동일 ratio면 어느 위원인지 모호 → 원본 유지.
    roster = ["김영호", "김영수", "김영준"]
    out = correct_member_names("김영주 위원이 말했다", roster)
    assert out == "김영주 위원이 말했다"


# ── 알려진 한계 특성화 (리뷰 important: 정책상 현행유지 — 동작 경계를 테스트로 고정) ──
def test_known_limitation_non_roster_lookalike_is_relabeled():
    # ★알려진 한계(2026-06-09 사용자 승인 정책): 명부와 한 글자 차이의 '다른 실인물'은
    # 명부 이름으로 오교정된다. 이 동작이 의도된 트레이드오프임을 명시 고정한다.
    # 임계값/정규식을 바꿔 이 단언이 깨지면 정책 재검토가 필요하다는 신호다.
    assert correct_member_names("참고인 박옥순 위원", ROSTER) == "참고인 박옥분 위원"
