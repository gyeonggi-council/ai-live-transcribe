# -*- coding: utf-8 -*-
"""예산/큰숫자 오전사 정규화 — 결정론 재표기 + LLM 교정 후보 선별.

STT가 예산 발화("14억 8100만 원")를 무단위 숫자열("14100008000")이나 아라비아
콤마 표기("1,481,000,000원")로 내보내는 오전사를 처리한다.

  - format_korean_amount: 정수 → 조/억/만 단위 한국어 표기 ("14억8100만")
  - normalize_amount_runs: 보수적 결정론 재표기 — 금액 문맥(원/예산 등)이 확실한
    숫자열만 한국어 단위로 재표기. 연도(2026년)/회차(제391회)/의안번호/전화번호는
    절대 건드리지 않음. 자릿수 오연결 의심(내부 0런)은 재표기하지 않고 LLM에 넘김.
  - find_suspect_numerals / llm_fix_numerals: 결정론으로 못 고치는 이상 숫자열
    (자릿수 오연결 등)이 있는 자막만 골라 GPT 배치 1회로 재구성 (fail-soft).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

logger = logging.getLogger(__name__)

_LLM_TIMEOUT = 60.0

# ============================================================================
# 한국어 금액 표기
# ============================================================================

_KR_UNITS = ((10**12, "조"), (10**8, "억"), (10**4, "만"))


def format_korean_amount(n: int) -> str:
    """정수를 조/억/만 단위 한국어 표기로 변환 (0단위 생략, 만 미만은 그대로).

    1_481_000_000 → "14억8100만", 3_000_000_000 → "30억", 5000 → "5000".
    """
    if n < 10000:
        return str(n)
    parts: list[str] = []
    rest = n
    for unit_val, unit_name in _KR_UNITS:
        q, rest = divmod(rest, unit_val)
        if q:
            parts.append(f"{q}{unit_name}")
    if rest:
        parts.append(str(rest))
    return "".join(parts)


# ============================================================================
# 보수적 결정론 재표기 (normalize_amount_runs)
# ============================================================================

# ① 콤마 표기 숫자 ("1,481,000,000") + 바로 뒤 '원'(선택)
_COMMA_AMOUNT_RE = re.compile(r"(?<![\d,.])(\d{1,3}(?:,\d{3})+)(?![\d,])(\s*원)?")
# ② 콤마 없는 8자리 이상 숫자열 + 바로 뒤 '원'(선택)
_PLAIN_AMOUNT_RE = re.compile(r"(?<![\d,.])(\d{8,})(?![\d,.])(\s*원)?")

# 숫자 바로 뒤가 단위 글자(이미 한국어 단위 표기: "5,777억") 또는
# 회차/연도/개수류 접미사("제391회", "350명")면 금액 재표기 금지.
_BLOCK_AFTER_RE = re.compile(r"\s*[조억만천백십회차호년번명건개%]")
# 금액임을 뒷받침하는 근접 문맥 단어 ('원'은 숫자 직후에만 인정 — 의원/위원장 오탐 방지)
_BUDGET_CONTEXT = ("예산", "사업비", "증액", "감액", "편성", "교부")
_CONTEXT_WINDOW = 12


def _blocked_context(text: str, start: int, num_end: int) -> bool:
    """연도/회차/의안번호/단위표기 등 '재표기 금지' 문맥이면 True."""
    if _BLOCK_AFTER_RE.match(text[num_end:]):
        return True
    before = text[:start]
    if re.search(r"제\s*$", before):  # "제391회" 류
        return True
    if "의안번호" in before[-10:] or "의안 번호" in before[-11:]:
        return True
    return False


def _has_budget_context(text: str, start: int, end: int, has_won: bool) -> bool:
    """숫자 직후 '원' 또는 근접 창 내 예산 문맥 단어가 있으면 True."""
    if has_won:
        return True
    before = text[max(0, start - _CONTEXT_WINDOW):start]
    after = text[end:end + _CONTEXT_WINDOW]
    return any(w in before or w in after for w in _BUDGET_CONTEXT)


def _looks_misjoined(digits: str) -> bool:
    """자릿수 오연결 의심(내부 0런 뒤 다시 숫자: "14100008000")이면 True.

    이런 숫자열은 액면 그대로 재표기하면 오히려 틀린 금액이 되므로
    결정론 재표기 대상에서 제외하고 LLM 교정 후보로 남긴다.
    """
    return "0000" in digits.rstrip("0")


def _make_repl(min_value: int):
    def _repl(m: re.Match) -> str:
        digits = m.group(1).replace(",", "")
        if digits[0] == "0":  # 전화번호류 (0으로 시작)
            return m.group(0)
        value = int(digits)
        if value < min_value or _looks_misjoined(digits):
            return m.group(0)
        text = m.string
        if _blocked_context(text, m.start(), m.end(1)):
            return m.group(0)
        if not _has_budget_context(text, m.start(), m.end(), bool(m.group(2))):
            return m.group(0)
        return format_korean_amount(value) + "원"

    return _repl


_comma_repl = _make_repl(min_value=10000)
_plain_repl = _make_repl(min_value=10**7)  # 8자리 이상만 매칭되므로 사실상 항상 통과


def normalize_amount_runs(text: str) -> str:
    """금액 문맥이 확실한 숫자열만 한국어 단위(억/만)로 보수적으로 재표기.

    ① "1,481,000,000원" 같은 콤마 표기 + 원/예산 문맥 → "14억8100만원"
    ② 콤마 없는 8자리 이상 숫자열 + 예산 문맥 근접 → "14억8100만원"
    연도/회차/의안번호/전화번호/이미 단위가 붙은 금액은 절대 건드리지 않는다.
    """
    if not text or not any(c.isdigit() for c in text):
        return text
    out = _COMMA_AMOUNT_RE.sub(_comma_repl, text)
    out = _PLAIN_AMOUNT_RE.sub(_plain_repl, out)
    return out


# ============================================================================
# LLM 교정 후보 선별 (find_suspect_numerals)
# ============================================================================

# 콤마 없는 7자리 이상 숫자열
_SUSPECT_PLAIN_RE = re.compile(r"(?<![\d,.])\d{7,}(?![\d,.])")
# 내부 0런 (0이 4개 이상 이어진 뒤 다시 숫자 — 자릿수 오연결 의심)
_SUSPECT_ZERO_RUN_RE = re.compile(r"\d0{4,}\d")
# 단위문자+숫자 혼입 이상 패턴 ("14억8100000" — 단위 뒤 5자리 이상은 비정상)
_SUSPECT_UNIT_MIX_RE = re.compile(r"[조억만]\d{5,}")


def find_suspect_numerals(text: str) -> list[str]:
    """LLM 교정 후보가 되는 의심 숫자열 토큰을 반환 (없으면 빈 리스트)."""
    if not text:
        return []
    spans: list[tuple[int, int]] = []
    for pat in (_SUSPECT_PLAIN_RE, _SUSPECT_ZERO_RUN_RE, _SUSPECT_UNIT_MIX_RE):
        spans.extend(m.span() for m in pat.finditer(text))
    if not spans:
        return []
    # 다른 스팬에 완전히 포함되는 스팬 제거 + 동일 스팬 중복 제거
    kept: list[tuple[int, int]] = []
    for s, e in sorted(set(spans)):
        if not any(s2 <= s and e <= e2 for s2, e2 in set(spans) - {(s, e)}):
            kept.append((s, e))
    return [text[s:e] for s, e in kept]


# ============================================================================
# 의심 라인 배치 LLM 교정 (llm_fix_numerals)
# ============================================================================

_LLM_SYSTEM_PROMPT = (
    "당신은 경기도의회 회의 자막의 숫자/금액 표기 교정기입니다. "
    "음성 인식(STT) 결과의 숫자 오인식만 교정합니다.\n"
    "규칙:\n"
    "- 무단위 긴 숫자열(예: 14100008000)은 금액 발화가 잘못 이어붙은 오인식일 수 "
    "있습니다. 문맥상 예산/금액이면 '14억8100만원'처럼 조/억/만 단위 한국어 표기로 "
    "재구성하세요.\n"
    "- 확신이 없으면 원문을 그대로 두세요. 의미 변경·내용 추가 금지.\n"
    "- 연도(2026년)/회차(제391회)/의안번호/전화번호는 절대 바꾸지 마세요.\n"
    "- 출력은 JSON 객체만: {\"입력 인덱스\": \"교정문\", ...} (인덱스는 입력 그대로)\n"
)


async def llm_fix_numerals(
    subtitles: list[dict], client, model: str, glossary: str = ""
) -> int:
    """의심 숫자열이 있는 자막만 모아 배치 1회 LLM 교정 (in-place, 수정 건수 반환).

    find_suspect_numerals에 걸린 자막만 프롬프트에 넣어 비용을 최소화한다.
    실패(호출/파싱 오류)는 0 반환 — 자막 파이프라인을 막지 않는다 (fail-soft).
    """
    try:
        flagged = [
            (i, s) for i, s in enumerate(subtitles)
            if find_suspect_numerals(s.get("text") or "")
        ]
        if not flagged:
            return 0
        numbered = "\n".join(f"{i}: {s.get('text')}" for i, s in flagged)
        user_content = (f"{glossary}\n\n" if glossary else "") + numbered
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
            ),
            timeout=_LLM_TIMEOUT,
        )
        content = (resp.choices[0].message.content or "").strip()
        data = json.loads(content)
        if not isinstance(data, dict):
            return 0
        by_index = dict(flagged)
        fixed = 0
        for key, val in data.items():
            try:
                idx = int(key)
            except (TypeError, ValueError):
                continue
            sub = by_index.get(idx)
            if sub is None or not isinstance(val, str):
                continue
            new_text = val.strip()
            if new_text and new_text != (sub.get("text") or "").strip():
                sub["text"] = new_text
                fixed += 1
        return fixed
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning("예산/숫자 LLM 교정 실패(무시): %s", e)
        return 0
