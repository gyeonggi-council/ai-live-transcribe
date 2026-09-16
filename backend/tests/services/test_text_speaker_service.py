# -*- coding: utf-8 -*-
"""텍스트 기반 화자 귀속 단위 테스트."""
import json

import pytest

from app.services import text_speaker_service as ts

ROSTER = [
    {"name": "이제영", "role": "위원장"},
    {"name": "심홍순", "role": "부위원장"},
    {"name": "김철현", "role": "위원"},
]
NAMES = {m["name"] for m in ROSTER}

# staff_roster 항목 형식 (staff_roster_service.parse_steno_attendance 출력)
STAFF = [
    {"name": "배성호", "title": "국장", "department": "건설국", "full_title": "건설국장"},
    {"name": "윤태완", "title": "국장", "department": "교통국", "full_title": "교통국장"},
]


def test_valid_speaker_roster_member():
    assert ts._valid_speaker("이제영 위원장", NAMES) == "이제영 위원장"
    assert ts._valid_speaker("김철현 위원", NAMES) == "김철현 위원"


def test_valid_speaker_executive_titles():
    assert ts._valid_speaker("디지털혁신과장", NAMES) == "디지털혁신과장"
    assert ts._valid_speaker("AI국장", NAMES) == "AI국장"
    assert ts._valid_speaker("미래성장산업국장", NAMES) == "미래성장산업국장"
    assert ts._valid_speaker("경기콘텐츠진흥원 원장", NAMES) == "경기콘텐츠진흥원 원장"


def test_valid_speaker_merged_staff_title_suffixes():
    """_OFFICIAL_SUFFIX가 staff_roster_service.STAFF_TITLE_SUFFIXES를 병합 —
    과거 기획관/지사/교육감/감사관/청장/관장이 빠져 유효 화자가 거부되던 결함."""
    assert ts._valid_speaker("경제기획관", NAMES) == "경제기획관"
    assert ts._valid_speaker("행정1부지사", NAMES) == "행정1부지사"
    assert ts._valid_speaker("제1부교육감", NAMES) == "제1부교육감"
    assert ts._valid_speaker("감사관", NAMES) == "감사관"
    assert ts._valid_speaker("소방재난본부 청장", NAMES) == "소방재난본부 청장"
    assert ts._valid_speaker("박물관장", NAMES) == "박물관장"
    # 기존 접미사(하위호환)도 그대로 통과
    assert ts._valid_speaker("정책보좌관", NAMES) == "정책보좌관"
    assert ts._valid_speaker("데이터센터장", NAMES) == "데이터센터장"
    # ★'위원장' 계열은 여전히 거부 — '원장' 접미사보다 위원장 가드가 우선
    assert ts._valid_speaker("아무개 위원장", NAMES) is None


def test_valid_speaker_rejects_non_roster_member():
    # 명부에 없는 'OO 위원'은 거부 — 없는 위원 생성 금지(안전)
    assert ts._valid_speaker("홍길동 위원", NAMES) is None
    assert ts._valid_speaker("아무개 위원장", NAMES) is None


def test_valid_speaker_rejects_garbage():
    assert ts._valid_speaker("그냥아무말", NAMES) is None
    assert ts._valid_speaker("", NAMES) is None


def test_build_prompt_includes_roster_and_structure():
    p = ts._build_system_prompt("미래과학협력위원회", ROSTER)
    assert "미래과학협력위원회" in p
    assert "이제영" in p and "위원장" in p
    assert "심홍순" in p
    assert "호명" in p or "질의" in p  # 진행 구조 단서


async def test_attribute_speakers_assigns_and_carries(monkeypatch):
    """LLM 결과를 자막에 부여하고, 단서 없는 라인은 직전 화자를 유지한다."""
    subs = [
        {"text": "김철현 위원 질의하세요.", "speaker": None},
        {"text": "안녕하십니까 안양 출신 김철현입니다.", "speaker": None},
        {"text": "예산이 얼마죠?", "speaker": None},  # 단서 없음 → 직전 유지
        {"text": "AI국장 김기병입니다.", "speaker": None},
    ]

    async def fake_llm(system_prompt, user_content):
        return [
            {"i": 0, "s": "이제영 위원장"},
            {"i": 1, "s": "김철현 위원"},
            {"i": 2, "s": "홍길동 위원"},   # 명부 밖 → 거부 → 직전(김철현) 유지
            {"i": 3, "s": "AI국장"},
        ]

    monkeypatch.setattr(ts, "_call_llm", fake_llm)
    labeled = await ts.attribute_speakers(subs, ROSTER, "미래과학협력위원회")

    assert labeled == 4
    assert subs[0]["speaker"] == "이제영 위원장"
    assert subs[1]["speaker"] == "김철현 위원"
    assert subs[2]["speaker"] == "김철현 위원"   # 거부된 명부밖 → 직전 유지
    assert subs[3]["speaker"] == "AI국장"


async def test_attribute_speakers_empty():
    assert await ts.attribute_speakers([], ROSTER, "위원회") == 0


def test_extract_title_bindings_both_orders():
    """자기소개 양방향('직책 이름입니다' / '이름 직책입니다')에서 이름↔직책 결합 추출."""
    subs = [
        {"text": "건설국장 배성호입니다.", "speaker": None},              # 직책 먼저
        {"text": "안녕하십니까, 윤태완 교통국장입니다.", "speaker": None},  # 이름 먼저
        {"text": "예산이 얼마죠?", "speaker": None},                     # 자기소개 아님
    ]
    b = ts.extract_title_bindings(subs)
    assert b["배성호"] == "건설국장"
    assert b["윤태완"] == "교통국장"
    assert len(b) == 2


def test_prompt_includes_staff_bindings():
    """staff 바인딩이 있으면 프롬프트에 '직책=실명' 블록 + 표기/소관/교대 규칙 포함."""
    bindings = {"배성호": "건설국장", "윤태완": "교통국장"}
    p = ts._build_system_prompt("건설교통위원회", ROSTER, staff_bindings=bindings)
    assert "집행부 출석 공무원(직책=실명)" in p
    assert "건설국장=배성호" in p
    assert "교통국장=윤태완" in p
    assert "실명+직책" in p          # 답변 화자 표기 지시
    assert "소관" in p              # 질문 소관 ↔ 직책 소관 일치
    assert "직접 전환 금지" in p     # 위원 간 교대는 위원장 호명 경유


def test_valid_speaker_accepts_staff_name_with_title():
    staff_names = frozenset({"배성호", "권주성"})
    assert ts._valid_speaker("배성호 건설국장", NAMES, staff_names) == "배성호 건설국장"
    # _OFFICIAL_SUFFIX에 없는 직함(기획관)도 staff 이름이 포함되면 허용
    assert ts._valid_speaker("권주성 경제기획관", NAMES, staff_names) == "권주성 경제기획관"
    # 기존 시그니처(2인자) 호출 하위호환 — staff 없이도 직책 접미사로 통과
    assert ts._valid_speaker("배성호 건설국장", NAMES) == "배성호 건설국장"


def test_valid_speaker_rejects_unknown_name():
    staff_names = frozenset({"배성호"})
    # 명부에도 staff에도 없는 이름
    assert ts._valid_speaker("홍길동 위원", NAMES, staff_names) is None
    assert ts._valid_speaker("홍길동", NAMES, staff_names) is None
    # staff 이름이라도 '위원' 사칭은 거부 — 없는 위원 생성 금지
    assert ts._valid_speaker("배성호 위원", NAMES, staff_names) is None


async def test_batch_overlap_context_included(monkeypatch):
    """각 배치 payload 앞에 직전 배치 마지막 확정 (텍스트, 화자) 컨텍스트 포함(재라벨 금지)."""
    monkeypatch.setattr(ts, "_BATCH", 3)
    captured = []

    async def fake_llm(system_prompt, user_content):
        captured.append(user_content)
        payload = json.loads(user_content.splitlines()[-1])  # 배치 payload = 마지막 줄
        return [{"i": p["i"], "s": "이제영 위원장"} for p in payload]

    monkeypatch.setattr(ts, "_call_llm", fake_llm)
    subs = [{"text": f"발언 {n}", "speaker": None} for n in range(5)]
    labeled = await ts.attribute_speakers(subs, ROSTER, "위원회")

    assert labeled == 5
    assert len(captured) == 2
    # 첫 배치엔 직전 컨텍스트 없음
    assert "재라벨 금지" not in captured[0]
    # 두 번째 배치: 직전 배치 마지막 라인들의 텍스트+확정 화자 + 재라벨 금지 명시
    assert "재라벨 금지" in captured[1]
    assert "발언 2" in captured[1]          # 직전 배치 마지막 라인 텍스트
    assert "이제영 위원장" in captured[1]    # 확정 화자


async def test_attribute_backcompat_without_staff(monkeypatch):
    """staff 미전달(기존 시그니처) 시 기존 경로 그대로 — staff 블록 없음, 회귀 없음."""
    prompts = []

    async def fake_llm(system_prompt, user_content):
        prompts.append(system_prompt)
        return [{"i": 0, "s": "이제영 위원장"}]

    monkeypatch.setattr(ts, "_call_llm", fake_llm)
    subs = [{"text": "개의를 선포합니다.", "speaker": None}]
    labeled = await ts.attribute_speakers(subs, ROSTER, "위원회")

    assert labeled == 1
    assert subs[0]["speaker"] == "이제영 위원장"
    assert "집행부 출석 공무원" not in prompts[0]
