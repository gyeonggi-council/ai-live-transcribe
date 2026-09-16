"""속기록 AI 보조 서비스

# @TASK P11C-T5 - AI 보조 서비스
# @SPEC docs/planning/02-trd.md#속기록

속기록 라인에 대한 AI 기반 화자 구분, 맞춤법 교정, 문단 구분 기능을 제공합니다.
OpenAI GPT-5-mini 모델을 사용합니다.
"""

import json
import logging
import time
from typing import Optional

import httpx

from app.core.config import settings
from app.services.dictionary import DictionaryService, get_default_dictionary

logger = logging.getLogger(__name__)

# ===========================================================================
# OpenAI 호출 헬퍼
# ===========================================================================

SPEAKER_DETECT_PROMPT = """당신은 한국어 의회 회의록의 화자를 식별하는 전문가입니다.

아래 속기록 라인들을 분석하여 각 라인의 화자를 추정하세요.

규칙:
1. "의장", "위원장", "부의장" 등의 직위를 화자로 사용
2. "OOO 의원" 형태의 의원명이 언급되면 해당 의원을 화자로
3. 발언 패턴(질문/답변 교대, 호칭 등)으로 화자 변경 감지
4. 확실하지 않으면 이전 화자를 유지

의원 목록(참고):
{councilor_names}

입력: JSON 배열 [{{"id": "...", "text": "..."}}]
출력: JSON 배열 [{{"line_id": "...", "suggested_speaker": "..."}}]

반드시 유효한 JSON만 출력하세요."""

PROOFREAD_PROMPT = """당신은 한국어 맞춤법/문법 교정 전문가입니다.
경기도의회 속기록을 교정합니다.

규칙:
1. 맞춤법 오류만 교정 (의미 변경 금지)
2. 띄어쓰기 교정
3. 조사 오류 교정
4. 구어체 → 문어체 변환 (회의록이므로)
5. 의회 전문용어는 그대로 유지
6. 교정이 필요 없는 항목은 포함하지 마세요

용어 사전:
{dictionary_entries}

입력: JSON 배열 [{{"id": "...", "text": "..."}}]
출력: JSON 배열 [{{"line_id": "...", "original_text": "...", "corrected_text": "...", "changes": ["변경설명"]}}]

반드시 유효한 JSON만 출력하세요."""

PARAGRAPH_PROMPT = """당신은 한국어 의회 회의록의 문단 구분 전문가입니다.

아래 속기록 라인들을 분석하여 새로운 문단이 시작되는 지점을 찾으세요.

규칙:
1. 화자가 변경되면 새 문단
2. 주제가 변경되면 새 문단 (안건 전환, 질의→답변 등)
3. "다음 안건", "넘어가겠습니다" 등의 전환 키워드 후 새 문단
4. 첫 번째 라인은 문단 시작으로 포함하지 마세요

입력: JSON 배열 [{{"id": "...", "sequence_no": N, "text": "..."}}]
출력: JSON 배열 [{{"line_id": "...", "starts_new_paragraph": true}}]

새 문단으로 시작하는 라인만 출력하세요.
반드시 유효한 JSON만 출력하세요."""


async def _call_openai_json(system_prompt: str, user_content: str) -> list[dict]:
    """OpenAI API를 호출하여 JSON 응답을 파싱합니다."""
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다.")

    t0 = time.monotonic()
    success = False

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.openai_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    "max_completion_tokens": 4096,
                },
            )
            response.raise_for_status()
        success = True
    finally:
        try:
            from app.api.admin import api_tracker
            latency = (time.monotonic() - t0) * 1000
            api_tracker.record("openai", latency, success)
        except Exception:
            pass

    data = response.json()
    content = data["choices"][0]["message"]["content"].strip()

    # JSON 파싱 (코드블록 제거)
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.warning("OpenAI JSON 파싱 실패: %s", content[:200])
        return []


# ===========================================================================
# 화자 자동 구분
# ===========================================================================


async def auto_detect_speakers(
    supabase,
    record_id: str,
    meeting_id: str,
) -> list[dict]:
    """속기 라인의 화자를 자동으로 구분합니다.

    GPT-5-mini로 화자 발언 패턴을 분석하고,
    councilors 테이블의 의원 목록을 참고합니다.

    Args:
        supabase: Supabase 클라이언트
        record_id: 속기록 레코드 ID
        meeting_id: 회의 ID

    Returns:
        [{line_id, suggested_speaker}, ...]
    """
    # 라인 조회
    lines_result = (
        supabase.table("stenography_lines")
        .select("id, sequence_no, text, speaker")
        .eq("record_id", record_id)
        .order("sequence_no")
        .execute()
    )
    lines = lines_result.data or []

    if not lines:
        return []

    # 의원 목록 조회
    councilor_names = ""
    try:
        councilors_result = (
            supabase.table("councilors")
            .select("name, committee")
            .eq("active", True)
            .execute()
        )
        if councilors_result.data:
            councilor_names = ", ".join(
                c["name"] for c in councilors_result.data if c.get("name")
            )
    except Exception:
        logger.debug("의원 목록 조회 실패 (무시)")

    # AI 호출
    prompt = SPEAKER_DETECT_PROMPT.format(councilor_names=councilor_names or "없음")
    input_data = [{"id": l["id"], "text": l["text"]} for l in lines]
    user_content = json.dumps(input_data, ensure_ascii=False)

    result = await _call_openai_json(prompt, user_content)

    # 결과 검증
    valid_line_ids = {l["id"] for l in lines}
    validated = []
    for item in result:
        if isinstance(item, dict) and item.get("line_id") in valid_line_ids:
            validated.append({
                "line_id": item["line_id"],
                "suggested_speaker": item.get("suggested_speaker", ""),
            })

    return validated


# ===========================================================================
# 맞춤법/용어 교정
# ===========================================================================


async def auto_proofread(
    supabase,
    record_id: str,
) -> list[dict]:
    """속기 라인의 맞춤법/용어를 교정합니다.

    기존 grammar_checker.py 패턴 + dictionary 테이블 교정 사전을 활용합니다.

    Args:
        supabase: Supabase 클라이언트
        record_id: 속기록 레코드 ID

    Returns:
        [{line_id, original_text, corrected_text, changes}, ...]
    """
    # 라인 조회
    lines_result = (
        supabase.table("stenography_lines")
        .select("id, text")
        .eq("record_id", record_id)
        .order("sequence_no")
        .execute()
    )
    lines = lines_result.data or []

    if not lines:
        return []

    # 용어 사전 로드
    dictionary = get_default_dictionary()
    try:
        dictionary.load_from_db(supabase)
    except Exception:
        logger.debug("사전 DB 로드 실패 (기본 사전만 사용)")

    # 사전 항목 요약 (프롬프트용)
    dict_entries = dictionary.get_entries()
    dict_summary = "\n".join(
        f"- {e.wrong_text} -> {e.correct_text}" for e in dict_entries[:30]
    )

    # AI 호출
    prompt = PROOFREAD_PROMPT.format(dictionary_entries=dict_summary or "없음")
    input_data = [{"id": l["id"], "text": l["text"]} for l in lines]
    user_content = json.dumps(input_data, ensure_ascii=False)

    result = await _call_openai_json(prompt, user_content)

    # 결과 검증
    valid_line_ids = {l["id"] for l in lines}
    validated = []
    for item in result:
        if not isinstance(item, dict):
            continue
        if item.get("line_id") not in valid_line_ids:
            continue
        if item.get("original_text") == item.get("corrected_text"):
            continue
        validated.append({
            "line_id": item["line_id"],
            "original_text": item.get("original_text", ""),
            "corrected_text": item.get("corrected_text", ""),
            "changes": item.get("changes", []),
        })

    return validated


# ===========================================================================
# 문단 자동 구분
# ===========================================================================


async def auto_paragraphs(
    supabase,
    record_id: str,
) -> list[dict]:
    """속기 라인의 문단을 자동으로 구분합니다.

    GPT-5-mini로 주제 변경점을 감지합니다.

    Args:
        supabase: Supabase 클라이언트
        record_id: 속기록 레코드 ID

    Returns:
        [{line_id, starts_new_paragraph: true}, ...]
    """
    # 라인 조회
    lines_result = (
        supabase.table("stenography_lines")
        .select("id, sequence_no, text")
        .eq("record_id", record_id)
        .order("sequence_no")
        .execute()
    )
    lines = lines_result.data or []

    if not lines:
        return []

    # AI 호출
    input_data = [{"id": l["id"], "sequence_no": l["sequence_no"], "text": l["text"]} for l in lines]
    user_content = json.dumps(input_data, ensure_ascii=False)

    result = await _call_openai_json(PARAGRAPH_PROMPT, user_content)

    # 결과 검증
    valid_line_ids = {l["id"] for l in lines}
    validated = []
    for item in result:
        if isinstance(item, dict) and item.get("line_id") in valid_line_ids:
            validated.append({
                "line_id": item["line_id"],
                "starts_new_paragraph": True,
            })

    return validated
