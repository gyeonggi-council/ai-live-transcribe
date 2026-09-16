"""용어표기점검 서비스

의회 전문용어 사전을 기반으로 자막 텍스트의 용어 표기 일관성을 점검합니다.
기존 DictionaryService를 확장하여 '감지'(변경 없이 리포팅)도 지원합니다.
"""

import re
from dataclasses import dataclass

from app.services.dictionary import DictionaryEntry, get_default_dictionary


@dataclass
class TermIssue:
    """용어 표기 불일치 항목"""

    subtitle_id: str
    original_text: str
    wrong_term: str
    correct_term: str
    category: str | None
    position: int  # 텍스트 내 위치


def check_terminology(
    subtitles: list[dict],
    extra_entries: list[DictionaryEntry] | None = None,
) -> list[TermIssue]:
    """자막 목록에서 용어 표기 불일치를 감지합니다.

    Args:
        subtitles: [{"id": ..., "text": ...}, ...]
        extra_entries: 추가 사전 항목 (사용자 정의)

    Returns:
        감지된 불일치 목록
    """
    dictionary = get_default_dictionary()
    if extra_entries:
        for entry in extra_entries:
            dictionary.add_entry(entry)

    issues: list[TermIssue] = []
    entries = dictionary.get_entries()

    for subtitle in subtitles:
        text = subtitle.get("text", "")
        subtitle_id = subtitle.get("id", "")

        for entry in entries:
            # 잘못된 표기가 텍스트에 있는지 검사
            start = 0
            while True:
                pos = text.find(entry.wrong_text, start)
                if pos == -1:
                    break
                issues.append(TermIssue(
                    subtitle_id=subtitle_id,
                    original_text=text,
                    wrong_term=entry.wrong_text,
                    correct_term=entry.correct_text,
                    category=entry.category,
                    position=pos,
                ))
                start = pos + len(entry.wrong_text)

    return issues


def apply_terminology_fix(
    subtitles: list[dict],
    extra_entries: list[DictionaryEntry] | None = None,
) -> list[dict]:
    """자막 목록의 용어를 일괄 교정합니다.

    Returns:
        [{"id": ..., "original_text": ..., "corrected_text": ..., "fixes": [...]}, ...]
    """
    dictionary = get_default_dictionary()
    if extra_entries:
        for entry in extra_entries:
            dictionary.add_entry(entry)

    results = []
    for subtitle in subtitles:
        text = subtitle.get("text", "")
        corrected = dictionary.correct(text)

        if corrected != text:
            results.append({
                "id": subtitle["id"],
                "original_text": text,
                "corrected_text": corrected,
            })

    return results


# 추가 표기 규칙 (정규식 기반)
_SPACING_RULES = [
    # "~을/를 ~하다" 패턴에서 불필요한 띄어쓰기
    (re.compile(r"(\w+)\s+(하겠습니다|합니다|드립니다|됩니다)"), r"\1\2"),
    # 조사 앞 불필요한 띄어쓰기: "위원 님" → "위원님"
    (re.compile(r"(\w+)\s+(님|씨|께서|에게|에서|으로|이며|이고)(?=\s|$)"), r"\1\2"),
]


def check_spacing_rules(text: str) -> list[dict]:
    """정규식 기반 띄어쓰기 규칙 검사."""
    issues = []
    for pattern, replacement in _SPACING_RULES:
        for match in pattern.finditer(text):
            fixed = pattern.sub(replacement, match.group(0))
            if fixed != match.group(0):
                issues.append({
                    "original": match.group(0),
                    "suggested": fixed,
                    "position": match.start(),
                    "rule": "spacing",
                })
    return issues
