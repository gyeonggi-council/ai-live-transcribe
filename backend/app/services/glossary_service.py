"""회의별 글로서리(용어/의원명/의안명) 빌더.

STT 재전사 프롬프트 바이어스 및 LLM 교정 단계의 참조 컨텍스트로 사용한다.
"""

from __future__ import annotations

from typing import Any


def build_glossary_terms(
    *,
    dictionary_terms: list[str] | None = None,
    councilor_names: list[str] | None = None,
    bill_titles: list[str] | None = None,
    subtitle_terms: list[str] | None = None,
    staff_terms: list[str] | None = None,
) -> list[str]:
    """여러 소스의 용어를 합쳐 순서 보존 + 중복 제거한 리스트를 반환한다.

    순서 = 문자 캡 절단 시 보존 우선순위: 의원명 → 집행부 staff → 용어사전 →
    의안명 → 자막 화자. staff(공무원 이름+직함)를 의원명 바로 뒤에 두어
    이름 정확도 소스가 캡 안에 함께 살아남게 한다.
    """
    ordered: list[str] = []
    seen: set[str] = set()
    for source in (
        councilor_names or [],
        staff_terms or [],
        dictionary_terms or [],
        bill_titles or [],
        subtitle_terms or [],
    ):
        for term in source:
            t = (term or "").strip()
            if t and t not in seen:
                seen.add(t)
                ordered.append(t)
    return ordered


def format_glossary_prompt(
    terms: list[str], max_terms: int = 200, max_chars: int | None = None
) -> str:
    """글로서리 용어를 STT/LLM 프롬프트 문자열로 포맷한다. 비면 빈 문자열.

    max_chars: 용어 부분의 글자수 상한. 매 호출 재전송되는 경로(라이브 전사 prompt,
    라이브 교정)에서 토큰 비용 폭주를 막는다. build_glossary_terms가 의원명을
    가장 앞에 배치하므로 절단 시 의원명이 자동으로 보존된다.
    """
    if not terms:
        return ""
    capped = terms[:max_terms]
    if max_chars is not None:
        picked: list[str] = []
        total = 0
        for t in capped:
            cost = len(t) + 2  # ", " 구분자 포함
            if picked and total + cost > max_chars:
                break
            picked.append(t)
            total += cost
        capped = picked
    joined = ", ".join(capped)
    return (
        "다음은 이 회의에 등장하는 고유명사/전문용어입니다. "
        "표기를 이 목록과 일치시키세요: " + joined
    )


def _committee_councilor_names(supabase: Any, committee: str | None) -> list[str]:
    """위원회 소속 의원명. 위원회 미상이거나 명부 0명(본회의 등)이면 전체 활성 의원명.

    이름 정확도가 최우선이므로 어떤 경우에도 의원명이 비지 않게 한다 —
    '본회의'처럼 상임위 명부에 매칭되지 않는 회의는 전원(142명)을 쓴다.
    """
    from app.services.councilor_sync import CouncilorSyncService

    svc = CouncilorSyncService(supabase)
    rows = svc.get_by_committee(committee) if committee else []
    if not rows:
        rows = svc.get_all_active()
    return [r.get("name", "").strip() for r in rows if r.get("name")]


def load_meeting_glossary(supabase: Any, meeting_id: str) -> list[str]:
    """회의 컨텍스트(용어사전+의원명+의안명+자막 화자)에서 글로서리를 빌드한다."""
    try:
        dict_rows = supabase.table("dictionary").select("correct_text").limit(500).execute().data or []
    except Exception:
        dict_rows = []
    dictionary_terms = [r.get("correct_text", "").strip() for r in dict_rows if r.get("correct_text")]

    committee = None
    try:
        m = supabase.table("meetings").select("committee").eq("id", meeting_id).limit(1).execute().data
        if m:
            committee = m[0].get("committee")
    except Exception:
        committee = None

    councilor_names = _committee_councilor_names(supabase, committee)

    # 집행부 공무원 명부(속기록 출석명단) — 의원명 바로 뒤 순서로 주입.
    # 테이블 미존재/파싱 실패 등은 무시(fail-soft) — 글로서리 자체는 항상 반환.
    staff_terms: list[str] = []
    if committee:
        try:
            from app.services.staff_roster_service import (
                load_staff_roster,
                staff_glossary_terms,
            )

            staff_terms = staff_glossary_terms(load_staff_roster(supabase, committee))
        except Exception:
            staff_terms = []

    bill_titles: list[str] = []
    if committee:
        try:
            bills = supabase.table("bills").select("title").eq("committee", committee).execute().data or []
            bill_titles = [b.get("title", "").strip() for b in bills if b.get("title")]
        except Exception:
            bill_titles = []

    subtitle_terms: list[str] = []
    try:
        subs = (
            supabase.table("subtitles")
            .select("speaker")
            .eq("meeting_id", meeting_id)
            .order("start_time")
            .execute()
            .data
            or []
        )
        subtitle_terms = sorted({s.get("speaker", "").strip() for s in subs if s.get("speaker")})
    except Exception:
        subtitle_terms = []

    return build_glossary_terms(
        dictionary_terms=dictionary_terms,
        councilor_names=councilor_names,
        bill_titles=bill_titles,
        subtitle_terms=subtitle_terms,
        staff_terms=staff_terms,
    )
