"""OpenAI 요청 본문 공통 조각(2026-09-15)."""


def reasoning_kw(effort: str | None) -> dict:
    """추론 수준 인자 — 빈 값이면 보내지 않는다(추론 수준을 모르는 옛 모델로 되돌릴 때 호환)."""
    value = (effort or "").strip()
    return {"reasoning_effort": value} if value else {}
