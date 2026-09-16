"""안건/의사일정 자동초안 서비스 (Phase 13).

AI 자막에서 회의의 "안건"과 "의사일정 내용" 초안을 생성한다. 새 AI 자산을 만들지 않고
기존 두 기능을 조합·재사용한다:
- (안건 없을 때만) 자막에서 안건 목록 추출 → meeting_agendas insert (사람이 입력한 안건은 보존)
- summary_service.generate_meeting_summary()의 agenda_summaries(안건별 요약)로
  각 안건 description(=의사일정 내용)이 비어 있으면 채움 + 의사일정 마크다운 직렬화

멱등: 재호출해도 안건이 이미 있으면 추출 skip, description은 빈 것만 채움(덮어쓰기 안 함).
"""

import json
import logging

import httpx
from supabase import Client

from app.core.config import settings
from app.services.openai_opts import reasoning_kw
from app.services.summary_service import generate_meeting_summary

logger = logging.getLogger(__name__)

_AGENDA_EXTRACT_PROMPT = """다음은 경기도의회 회의 자막입니다. 상정된 안건(의사일정 항목)만 추출하세요.

반드시 아래 JSON 형식으로만 응답하세요:
{
  "agendas": [
    {"order_num": 1, "title": "안건 제목"}
  ]
}

규칙:
- "제N호 의안", "상정", "의사일정 제N항", "안건" 등의 키워드에서 추출
- order_num은 상정 순서(1부터)
- 명시적으로 언급된 안건만. 없으면 빈 배열
- 반드시 유효한 JSON만 출력"""


def _fetch_all_subtitles(supabase: Client, meeting_id: str) -> list[dict]:
    """회의 전체 자막을 시간순으로(페이지네이션, Supabase 1000행 캡 회피)."""
    out: list[dict] = []
    offset = 0
    while True:
        r = (
            supabase.table("subtitles")
            .select("text, speaker, start_time")
            .eq("meeting_id", meeting_id)
            .order("start_time")
            .range(offset, offset + 999)
            .execute()
        ).data or []
        out.extend(r)
        if len(r) < 1000:
            break
        offset += 1000
    return out


async def _extract_agendas(supabase: Client, meeting_id: str) -> list[dict]:
    """자막에서 안건 목록을 추출한다 (안건 미등록 회의용). 실패 시 빈 리스트.

    ★안건은 회의 전반에 걸쳐 '의사일정 제N항 … 상정합니다'로 도입되므로, 앞부분만
    보면(이전 limit=120) 뒤쪽 안건을 통째로 놓친다(실측: 6건 중 2건만 추출).
    따라서 회의 전체에서 (a) 첫부분 의사일정 안내 + (b) '상정/의사일정' 포함 발언만
    모아 LLM에 준다 — 전량을 보내지 않아 비용은 캡하면서 모든 안건을 포착한다.
    """
    rows = _fetch_all_subtitles(supabase, meeting_id)
    if not rows:
        return []

    head = rows[:40]  # 개의 직후 '오늘 회의는 … 건의안 N건, 조례안 M건 … 심사' 안내
    seen_starts = {s.get("start_time") for s in head}
    picked = list(head)
    for s in rows[40:]:
        txt = s.get("text") or ""
        if ("상정" in txt or "의사일정" in txt) and s.get("start_time") not in seen_starts:
            picked.append(s)
            seen_starts.add(s.get("start_time"))
    picked.sort(key=lambda s: s.get("start_time") or 0)
    transcript = "\n".join(f"[{s.get('speaker') or '미지정'}] {s.get('text', '')}" for s in picked)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.agenda_model,
                    "messages": [
                        {"role": "system", "content": _AGENDA_EXTRACT_PROMPT},
                        {"role": "user", "content": transcript},
                    ],
                    # 생각 토큰도 이 상한에 포함된다(2026-09-15 5.6 계열 전환) — 1,500 이면 안건 JSON 이 잘릴 수 있다
                    "max_completion_tokens": 3000,
                    **reasoning_kw(settings.agenda_reasoning_effort),
                },
            )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        parsed = json.loads(content)
        return parsed.get("agendas", []) or []
    except Exception as e:
        logger.warning("안건 추출 실패(건너뜀): %s", e)
        return []


async def ensure_agendas(supabase: Client, meeting_id: str) -> list[dict]:
    """meeting_agendas가 비어 있으면 자막에서 안건을 추출·저장하고 최종 목록을 반환(멱등).

    회의록 내보내기(hwpx 등)에서 '의사일정/심사된 안건'을 원천데이터(자막)에서
    추출·정제해 채우기 위한 경량 진입점. 요약(summary)은 만들지 않아 generate_agenda_draft
    보다 저렴하다(안건 제목만 1회 추출).

    - 이미 등록된 안건이 있으면 추출하지 않고 그대로 반환(사람 입력 보존).
    - 추출 실패 시 빈 목록(회의록은 '안건 미등록'으로 graceful degrade).
    """
    def _load() -> list[dict]:
        return (
            supabase.table("meeting_agendas").select("*")
            .eq("meeting_id", meeting_id).order("order_num").execute()
        ).data or []

    existing = _load()
    if existing:
        return existing
    for a in await _extract_agendas(supabase, meeting_id):
        title = (a.get("title") or "").strip()
        if not title:
            continue
        try:
            supabase.table("meeting_agendas").insert({
                "meeting_id": meeting_id,
                "order_num": a.get("order_num"),
                "title": title,
            }).execute()
        except Exception as e:
            logger.warning("안건 자동저장 실패: %s", e)
    return _load()


def _build_order_of_business(items: list[dict]) -> str:
    """안건 요약 목록을 의사일정 마크다운 초안으로 직렬화."""
    ordered = sorted(items, key=lambda x: x.get("order_num") or 0)
    lines = ["# 의사일정 (AI 초안)"]
    for it in ordered:
        num = it.get("order_num") or ""
        title = it.get("title") or "제목 미상"
        lines.append(f"\n## 의사일정 제{num}항 {title}".rstrip())
        summary = (it.get("summary") or it.get("description") or "").strip()
        if summary:
            lines.append(summary)
    return "\n".join(lines)


async def generate_agenda_draft(supabase: Client, meeting_id: str) -> dict:
    """AI 자막 기반으로 안건 + 의사일정 내용 초안을 생성·저장하고 결과를 반환한다.

    Raises:
        ValueError: 자막이 없을 때.
    """
    sub_count = (
        supabase.table("subtitles").select("id", count="exact")
        .eq("meeting_id", meeting_id).execute()
    ).count or 0
    if sub_count == 0:
        raise ValueError("자막이 없어 안건 초안을 생성할 수 없습니다.")

    # 1. 기존 안건 (사람이 입력한 것 보존)
    def _load_agendas() -> list[dict]:
        return (
            supabase.table("meeting_agendas").select("*")
            .eq("meeting_id", meeting_id).order("order_num").execute()
        ).data or []

    existing = _load_agendas()
    created = 0
    extracted: list[dict] = []
    if not existing:
        extracted = await _extract_agendas(supabase, meeting_id)

    # 2. 요약(agenda_summaries) 생성 — summary_service 재사용(meeting_summaries 저장 포함).
    #    ★안건 insert 보다 먼저★ — 요약이 실패(상한·상류 오류)하면 아무것도 남기지 않아 재시도가 409 에 막히지 않는다
    #    (2026-09-14 Codex 검토: 예전엔 안건만 들어가고 요약이 죽으면 다음 요청이 "이미 생성됨" 409 였다).
    summary = await generate_meeting_summary(supabase, meeting_id, agendas_override=extracted or None)

    if not existing and extracted:
        for a in extracted:
            try:
                supabase.table("meeting_agendas").insert({
                    "meeting_id": meeting_id,
                    "order_num": a.get("order_num"),
                    "title": a.get("title", ""),
                }).execute()
                created += 1
            except Exception as e:
                logger.warning("안건 insert 실패: %s", e)
        existing = _load_agendas()

    # 3. order_num 매칭으로 안건 description(의사일정 내용) 빈 것만 채움
    by_order = {a.get("order_num"): a for a in existing}
    for s in summary.agenda_summaries or []:
        ag = by_order.get(s.get("order_num"))
        text = (s.get("summary") or "").strip()
        if ag and text and not (ag.get("description") or "").strip():
            try:
                supabase.table("meeting_agendas").update(
                    {"description": text}
                ).eq("id", ag["id"]).execute()
                ag["description"] = text
            except Exception as e:
                logger.warning("안건 description 업데이트 실패: %s", e)

    # 4. 의사일정 마크다운 (요약이 안건별로 있으면 그걸, 없으면 등록 안건 제목으로)
    items = summary.agenda_summaries or [
        {"order_num": a.get("order_num"), "title": a.get("title"), "description": a.get("description")}
        for a in existing
    ]
    order_of_business = _build_order_of_business(items)

    return {
        "meeting_id": meeting_id,
        "agendas": _load_agendas(),
        "agenda_summaries": summary.agenda_summaries,
        "summary_text": summary.summary_text,
        "key_decisions": summary.key_decisions,
        "action_items": summary.action_items,
        "order_of_business_markdown": order_of_business,
        "created_agendas": created,
    }
