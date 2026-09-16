"""STT 도메인 프롬프트 빌더 — 고유명사(의원명·의회 용어) 오인식 저감

OpenAI 전사 API(prompt 파라미터)와 Realtime transcription 세션에 주입할
짧은 도메인 컨텍스트를 만든다. 위원회를 알면 소속 의원 명부를 포함해
'원장'↔'위원장', 의원 이름 오인식을 줄인다.

프롬프트가 길면 역효과·비용 증가 → settings.stt_domain_prompt_max_chars 로 상한.
"""

import logging
import time
from typing import Optional

from app.core.channels import get_committee_for_channel
from app.core.config import settings
from app.services.dictionary import get_default_dictionary

logger = logging.getLogger(__name__)

_BASE = (
    "경기도의회 회의 발언입니다. 의원 이름과 의회 용어(위원장, 조례안, 부의, 의결, 질의)를 정확히 표기하세요. "
    "'위원'과 '의원'을 문맥에 맞게 구분하고, 회수·대수·차수는 아라비아 숫자로 표기합니다(예: 제392회, 제12대, 제1차)."
)

# 위원회별 캐시 (명부 DB 조회 절약)
_cache: dict[str, tuple[float, str]] = {}
_CACHE_TTL_SECONDS = 600.0

# API가 prompt 파라미터를 거부한 경우 세션 동안 재시도하지 않기 위한 플래그
_prompt_rejected = False


def prompt_supported() -> bool:
    return settings.stt_domain_prompt_enabled and not _prompt_rejected


def mark_prompt_rejected(error: Exception) -> bool:
    """API 오류가 prompt 파라미터 거부인지 판정하고, 맞으면 비활성화한다."""
    global _prompt_rejected
    msg = str(error).lower()
    if "prompt" in msg and ("unsupported" in msg or "unknown" in msg or "unexpected" in msg or "invalid" in msg):
        _prompt_rejected = True
        logger.warning("STT prompt 파라미터가 거부되어 비활성화합니다: %s", error)
        return True
    return False


def build_stt_prompt(
    committee: Optional[str] = None,
    extra_names: Optional[list[str]] = None,
) -> str:
    """도메인 프롬프트를 생성한다. 비활성화 시 빈 문자열.

    extra_names: 명부 외 추가 화자/기관명 힌트 (예: 집행부 참석자). 캐시 미적용.
    """
    if not prompt_supported():
        return ""

    key = committee or ""
    now = time.monotonic()
    cached = _cache.get(key)
    if cached and now - cached[0] < _CACHE_TTL_SECONDS and not extra_names:
        return cached[1]

    parts = [_BASE]

    if committee:
        try:
            from app.services.voiceprint_service import voiceprint_service

            roster = voiceprint_service.get_committee_roster(committee)
            names = [r["name"] for r in roster if r.get("name")]
            if names:
                parts.append(f"{committee} 소속 의원: {', '.join(names[:20])}.")
        except Exception as e:
            logger.debug("stt_prompt roster 조회 실패 (committee=%s): %s", committee, e)

    if extra_names:
        parts.append(f"참석 발언자: {', '.join(extra_names[:20])}.")

    # 용어사전의 교정 결과(correct_text)를 도메인 용어 힌트로 추가
    try:
        terms: list[str] = []
        seen: set[str] = set()
        for entry in get_default_dictionary().get_entries():
            t = entry.correct_text.strip()
            if t and t not in seen and len(t) >= 2:
                seen.add(t)
                terms.append(t)
        if terms:
            parts.append("자주 나오는 용어: " + ", ".join(terms[:25]) + ".")
    except Exception as e:
        logger.debug("stt_prompt 용어사전 로드 실패: %s", e)

    prompt = " ".join(parts)
    max_chars = settings.stt_domain_prompt_max_chars
    if len(prompt) > max_chars:
        prompt = prompt[:max_chars].rsplit(",", 1)[0]

    if not extra_names:
        _cache[key] = (now, prompt)
    return prompt


def build_stt_prompt_for_channel(channel_id: str) -> str:
    """라이브 채널용 — 채널→위원회 정적 매핑으로 명부 포함 프롬프트 생성."""
    committee = None
    try:
        committee = get_committee_for_channel(channel_id)
    except Exception:
        pass
    return build_stt_prompt(committee)
