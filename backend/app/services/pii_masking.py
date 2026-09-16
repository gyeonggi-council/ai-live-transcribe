"""PII(개인정보) 감지 및 마스킹 서비스

전화번호, 주민등록번호, 이메일 주소를 정규식으로 감지하고 마스킹합니다.
"""

import re
from dataclasses import dataclass


@dataclass
class PiiMatch:
    """감지된 PII 항목"""

    type: str  # "phone", "rrn", "email"
    original: str
    masked: str
    start: int
    end: int


# 전화번호: 010-1234-5678, 02-123-4567, 031-1234-5678
_PHONE_PATTERN = re.compile(
    r"(0\d{1,2})[- ]?(\d{3,4})[- ]?(\d{4})"
)

# 주민등록번호: 900101-1234567
_RRN_PATTERN = re.compile(
    r"(\d{6})[- ]?(\d{7})"
)

# 이메일: user@example.com
_EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
)


def _mask_phone(match: re.Match) -> str:
    return f"***-****-{match.group(3)}"


def _mask_rrn(match: re.Match) -> str:
    return f"{match.group(1)}-*******"


def _mask_email(match: re.Match) -> str:
    email = match.group(0)
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = "*" * len(local)
    else:
        masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked_local}@{domain}"


def detect_pii(text: str) -> list[PiiMatch]:
    """텍스트에서 PII를 감지합니다."""
    matches: list[PiiMatch] = []

    for m in _RRN_PATTERN.finditer(text):
        matches.append(PiiMatch(
            type="rrn",
            original=m.group(0),
            masked=_mask_rrn(m),
            start=m.start(),
            end=m.end(),
        ))

    for m in _PHONE_PATTERN.finditer(text):
        # 주민번호와 겹치는 범위 제외
        if any(p.start <= m.start() < p.end for p in matches):
            continue
        matches.append(PiiMatch(
            type="phone",
            original=m.group(0),
            masked=_mask_phone(m),
            start=m.start(),
            end=m.end(),
        ))

    for m in _EMAIL_PATTERN.finditer(text):
        matches.append(PiiMatch(
            type="email",
            original=m.group(0),
            masked=_mask_email(m),
            start=m.start(),
            end=m.end(),
        ))

    return sorted(matches, key=lambda x: x.start)


def mask_pii(text: str) -> tuple[str, list[PiiMatch]]:
    """텍스트의 PII를 마스킹하고 결과를 반환합니다.

    Returns:
        (마스킹된 텍스트, 감지된 PII 목록)
    """
    pii_list = detect_pii(text)
    if not pii_list:
        return text, []

    # 뒤에서부터 치환 (인덱스가 틀어지지 않도록)
    result = text
    for pii in reversed(pii_list):
        result = result[:pii.start] + pii.masked + result[pii.end:]

    return result, pii_list


def mask_pii_batch(texts: list[dict]) -> list[dict]:
    """여러 자막의 text 필드를 일괄 마스킹합니다.

    Args:
        texts: [{"id": ..., "text": ...}, ...]

    Returns:
        [{"id": ..., "original_text": ..., "masked_text": ..., "pii_found": [...]}, ...]
    """
    results = []
    for item in texts:
        masked_text, pii_list = mask_pii(item.get("text", ""))
        results.append({
            "id": item["id"],
            "original_text": item.get("text", ""),
            "masked_text": masked_text,
            "pii_found": [
                {"type": p.type, "original": p.original, "masked": p.masked}
                for p in pii_list
            ],
        })
    return results
