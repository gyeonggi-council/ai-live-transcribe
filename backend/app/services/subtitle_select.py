# -*- coding: utf-8 -*-
"""자막 선택 유틸 — AI 자막(화자구분) 우선.

한 회의에 실시간 자막(kind='live', 화자 없음)과 AI 자막(kind='ai', 화자 있음)이
함께 있을 수 있다. 같은 음성을 두 번 전사한 것이므로 둘을 섞으면 '발언자 미확인' +
중복 발언이 생긴다. 회의록·요약·화자 타임라인·속기·RAG 등 '특정 회의의 자막을 읽어
사람에게 보여주거나 LLM에 넣는' 모든 경로는 이 헬퍼로 AI 자막만 선택해야 한다.

★주의: 이 필터는 각 자막 dict의 'kind' 키를 본다. 쿼리에서 select 컬럼을 한정한다면
반드시 'kind'를 포함해야 한다(없으면 모든 행의 kind가 None이라 필터가 무력화됨).
"""

from __future__ import annotations


def prefer_ai_subtitles(all_subs: list[dict]) -> list[dict]:
    """AI 자막(kind='ai')이 있으면 그것만, 없으면 live 제외분, 그래도 없으면 전체.

    - only-ai      → ai 그대로
    - mixed(ai+live) → ai만 (혼재·중복 제거)
    - only-live    → live (라이브만 있는 회의도 빈 결과가 되지 않게 폴백)
    - null-kind(레거시) → 전체 (kind 컬럼 이전 데이터 보존)
    - empty        → 빈 목록
    """
    ai = [s for s in all_subs if s.get("kind") == "ai"]
    if ai:
        return ai
    non_live = [s for s in all_subs if s.get("kind") != "live"]
    return non_live if non_live else all_subs
