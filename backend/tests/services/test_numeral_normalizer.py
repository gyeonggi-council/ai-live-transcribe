# -*- coding: utf-8 -*-
"""예산/큰숫자 오전사 정규화(numeral_normalizer) 단위 테스트."""

import json
import types

from app.services.numeral_normalizer import (
    find_suspect_numerals,
    format_korean_amount,
    llm_fix_numerals,
    normalize_amount_runs,
)


# ============================================================================
# format_korean_amount
# ============================================================================


def test_format_korean_amount_basic():
    assert format_korean_amount(1_481_000_000) == "14억8100만"
    assert format_korean_amount(30_000_000) == "3000만"
    assert format_korean_amount(5000) == "5000"  # 만 미만은 그대로 숫자
    assert format_korean_amount(0) == "0"


def test_format_korean_amount_over_jo():
    assert format_korean_amount(1_234_567_890_123) == "1조2345억6789만123"
    assert format_korean_amount(40_000_000_000_000) == "40조"


def test_format_korean_amount_exact_units():
    assert format_korean_amount(100_000_000) == "1억"
    assert format_korean_amount(10_000) == "1만"
    assert format_korean_amount(3_000_000_000) == "30억"  # 0단위(만) 생략


# ============================================================================
# normalize_amount_runs — 보수적 결정론 재표기
# ============================================================================


def test_normalize_reformats_comma_amount_with_won():
    # ① 콤마 표기 + 원 문맥
    assert (
        normalize_amount_runs("예산 1,481,000,000원을 편성하였습니다.")
        == "예산 14억8100만원을 편성하였습니다."
    )
    # ② 콤마 없는 8자리 이상 + 원/예산 문맥
    assert (
        normalize_amount_runs("사업비 1481000000원 증액")
        == "사업비 14억8100만원 증액"
    )


def test_normalize_leaves_year_and_session_and_bill_number():
    # 연도/회차/의안번호는 절대 불변
    text = "2026년 제391회 임시회, 의안번호 12345678 검토"
    assert normalize_amount_runs(text) == text
    # 전화번호류(0으로 시작하는 숫자열)도 불변 — 예산 문맥이 근접해도
    assert (
        normalize_amount_runs("문의 03112345678 예산담당")
        == "문의 03112345678 예산담당"
    )


def test_normalize_ignores_plain_medium_numbers():
    # 이미 한국어 단위가 붙은 금액/중간 크기 숫자/문맥 없는 숫자는 불변
    assert normalize_amount_runs("총 8,793억 원을 감액") == "총 8,793억 원을 감액"
    assert normalize_amount_runs("1,424만 도민") == "1,424만 도민"
    assert normalize_amount_runs("350명이 참석") == "350명이 참석"
    # 금액 문맥 없는 긴 숫자열은 결정론으로 안 건드림
    assert normalize_amount_runs("계좌번호 12345678 입니다") == "계좌번호 12345678 입니다"
    # 자릿수 오연결 의심 숫자열(내부 0런)은 재표기 금지 — LLM 교정 후보로 남김
    assert normalize_amount_runs("예산 14100008000원") == "예산 14100008000원"


# ============================================================================
# find_suspect_numerals — LLM 교정 후보 선별
# ============================================================================


def test_find_suspect_flags_runon_digits():
    # 무단위 긴 숫자열 (실측: "14100008000", 정답 "14억8100만원")
    assert "14100008000" in find_suspect_numerals("예산 14100008000 규모입니다")
    # 콤마 없는 7자리 이상
    assert find_suspect_numerals("총 1481000000원이 소요됩니다")
    # 내부 0런 (\d0{4,}\d)
    assert find_suspect_numerals("금액이 1000001입니다")
    # 단위문자+숫자 혼입 이상 패턴
    assert find_suspect_numerals("14억8100000원")


def test_find_suspect_ignores_normal():
    assert find_suspect_numerals("2026년 제391회 정례회") == []
    assert find_suspect_numerals("총 1,481,000,000원") == []  # 콤마 표기는 정상
    assert find_suspect_numerals("14억 8100만원") == []
    assert find_suspect_numerals("재석 15명 찬성 15명") == []
    assert find_suspect_numerals("") == []


# ============================================================================
# llm_fix_numerals — 의심 라인만 배치 LLM 교정 (mock)
# ============================================================================


class _FakeCompletions:
    def __init__(self, content: str):
        self._content = content
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        msg = types.SimpleNamespace(content=self._content)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])


def _fake_client(content: str):
    completions = _FakeCompletions(content)
    return types.SimpleNamespace(chat=types.SimpleNamespace(completions=completions))


async def test_llm_fix_only_touches_flagged_lines():
    subs = [
        {"text": "안건을 상정합니다."},  # 정상 — LLM에 안 보냄
        {"text": "예산 14100008000 규모입니다."},  # 의심 — 교정 대상
        {"text": "2026년 제391회 정례회입니다."},  # 정상
    ]
    client = _fake_client(
        json.dumps({"1": "예산 14억8100만원 규모입니다."}, ensure_ascii=False)
    )
    fixed = await llm_fix_numerals(subs, client, "gpt-test")

    assert fixed == 1
    assert subs[1]["text"] == "예산 14억8100만원 규모입니다."
    # 의심 라인이 아닌 자막은 절대 불변
    assert subs[0]["text"] == "안건을 상정합니다."
    assert subs[2]["text"] == "2026년 제391회 정례회입니다."

    # LLM 프롬프트에는 의심 라인만 포함됐는지
    calls = client.chat.completions.calls
    assert len(calls) == 1  # 배치 1회 호출
    user_msg = calls[0]["messages"][1]["content"]
    assert "14100008000" in user_msg
    assert "안건을 상정합니다" not in user_msg

    # 의심 라인이 없으면 LLM 호출 자체를 안 함
    clean_client = _fake_client("{}")
    assert await llm_fix_numerals([{"text": "정상 문장입니다."}], clean_client, "gpt-test") == 0
    assert clean_client.chat.completions.calls == []
