# -*- coding: utf-8 -*-
"""집행부 공무원 이름 교정 (correct_staff_names) 단위 테스트.

correct_member_names와 동일 원칙(유일 퍼지매칭 시만 교체, 동점/모호 보류,
명부 밖 이름 절대 생성 금지, 정확 일치 무변경)을 staff 직책(국장/과장/…)에서 검증한다.
"""

from app.services.name_corrector import correct_member_names, correct_staff_names

# 건설교통위원회 staff 명부 발췌 (_steno_15580 실측)
STAFF = ["배성호", "윤태완", "추대운", "조정아", "한태우"]


def test_staff_misrec_corrected():
    # 실측 쌍: STT 오인식 이강옥 → 명부의 이강욱 (한 글자 차, 유일 매칭)
    staff = ["이영창", "이강욱", "차미순", "서은경", "최희숙"]
    assert (
        correct_staff_names("이강옥 국장님 답변해 주시기 바랍니다", staff)
        == "이강욱 국장님 답변해 주시기 바랍니다"
    )


def test_staff_exact_untouched():
    # 이미 명부에 정확히 있으면 손대지 않음 (부서 결합 직함 '건설국장' 포함)
    txt = "배성호 건설국장이 업무보고를 하겠습니다"
    assert correct_staff_names(txt, STAFF) == txt


def test_staff_exact_glued_department_title_untouched():
    # 이름+부서결합직함이 공백 없이 붙어도 정확한 명부 이름을 훼손하지 않는다.
    # 회귀 가드: 탐욕적 이름 그룹이 부서 접두 첫 글자를 흡수해 cand='배성호건'이 되고
    # 명부 '배성호'와 퍼지매칭(0.857)되어 교체 시 '건'이 소실되던 버그
    # ('배성호건설국장이' → '배성호설국장이').
    txt = "배성호건설국장이 보고합니다"
    assert correct_staff_names(txt, ["배성호", "윤태완"]) == txt


def test_nonstaff_person_preserved():
    # 명부에 충분히 가까운 이름이 없으면 원본 유지 (없는 이름 생성 금지)
    txt = "홍길동 국장이 참석했습니다"
    assert correct_staff_names(txt, STAFF) == txt


def test_adversarial_similar_name_ambiguous_kept():
    # 명부의 두 이름과 같은 ratio(동점) → 어느 쪽인지 모호하므로 원본 유지
    staff = ["김영호", "김영수"]
    txt = "김영주 과장님 말씀해 주시기 바랍니다"
    assert correct_staff_names(txt, staff) == txt


def test_staff_gihoekgwan_title_triggers_correction():
    # '기획관'은 staff_roster_service.STAFF_TITLE_SUFFIXES에 있는 직책 —
    # 접미사 원천 공유로 _STAFF_TITLE_RE에서도 발동해야 한다.
    # (과거 정규식 접미사 집합이 파서보다 좁아 '기획관' 직책에서 교정이 미발동)
    assert (
        correct_staff_names(
            "권주송 경제기획관님 답변해 주시기 바랍니다", ["권주성", "박노극"]
        )
        == "권주성 경제기획관님 답변해 주시기 바랍니다"
    )


def test_chair_title_never_staff_corrected():
    # [재현] '위원장' = 부서접두 '위' + 접미사 '원장'으로 _STAFF_TITLE_RE에 매칭되어
    # 위원장 이름이 staff 명부 이름으로 오염되던 결함 ('김철수 위원장'→'김철호 위원장').
    # 위원장/부위원장은 member 경로(correct_member_names) 영역 — staff 경로는 무조건 보류.
    txt = "다음은 김철수 위원장께서 말씀해 주시기 바랍니다"
    assert correct_staff_names(txt, ["김철호"]) == txt


def test_vice_chair_title_never_staff_corrected():
    # 부위원장('부위' 접두 + '원장' 접미사)도 동일 가드 — 원본 유지.
    txt = "심원순 부위원장님 의사진행 발언 있으십니까"
    assert correct_staff_names(txt, ["심원식"]) == txt


def test_legit_wonjang_staff_title_still_corrected():
    # '연수원장'/'교육원장' 같은 정당한 staff 직책('원장' 접미사)은 계속 발동한다 —
    # 가드는 endswith('위원장')만 제외한다.
    assert (
        correct_staff_names("지미송 연수원장님 보고해 주시기 바랍니다", ["지미숙"])
        == "지미숙 연수원장님 보고해 주시기 바랍니다"
    )


def test_member_path_unaffected():
    # ① 기존 위원 교정 동작 불변 (헬퍼 공유 리팩터링 회귀 가드)
    assert (
        correct_member_names("김종대 위원님 질의해 주십시오", ["김종배", "조성환"])
        == "김종배 위원님 질의해 주십시오"
    )
    # ② correct_staff_names는 '위원/의원' 호칭에 발동하지 않는다 (member 영역)
    txt = "김종대 위원님 질의해 주십시오"
    assert correct_staff_names(txt, ["김종배"]) == txt
    # ③ '전문위원'은 staff 직책 — staff 경로에서 교정된다
    assert (
        correct_staff_names("한태오 수석전문위원께서 검토보고 하시겠습니다", STAFF)
        == "한태우 수석전문위원께서 검토보고 하시겠습니다"
    )
