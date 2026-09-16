"""AI RAG (Retrieval-Augmented Generation) 서비스

# @TASK P11B - AI Assistant RAG service
# @SPEC docs/planning/02-trd.md#AI-어시스턴트

회의 자막 및 의안 데이터를 검색하고, OpenAI GPT를 사용하여
컨텍스트 기반 Q&A 답변을 생성합니다.
"""

import asyncio
import json
import logging
import re
import time

import httpx
from supabase import Client

from app.core.config import settings
from app.services import rag_context
from app.services.openai_opts import reasoning_kw
from app.services.subtitle_fetch import fetch_all_subtitles
from app.services.subtitle_select import prefer_ai_subtitles

logger = logging.getLogger(__name__)


class AiNotConfiguredError(RuntimeError):
    """OPENAI_API_KEY 없음 — 라우터가 503 으로 낸다."""


class AiUpstreamError(RuntimeError):
    """OpenAI 호출 실패·빈 응답·파싱 실패 — 라우터가 502 로 낸다. 예외 원문을 답변으로 내보내지 않는다(2026-09-14)."""


# 검색 결과 최대 개수
MAX_SEARCH_RESULTS = 20
# 컨텍스트 텍스트 최대 길이
MAX_CONTEXT_CHARS = 12000

RAG_SYSTEM_PROMPT = """당신은 경기도의회 회의 자료 기반 Q&A 어시스턴트입니다.
주어진 컨텍스트(회의 정보, 발언자 목록, 요약, 자막)와 이전 대화 맥락을 바탕으로 질문에 답변하세요.

규칙:
- 한국어로, 일반 텍스트로만 답변하세요.
- 마크다운 서식 기호(**, *, #, 백틱, 표 등)를 절대 사용하지 마세요. 강조가 필요해도 별표를 쓰지 마세요.
- 질문에 충분히 자세하고 구체적으로 답하세요. 관련 발언 내용을 인용·종합하고, 누가 어떤 맥락에서 말했는지 포함하세요. 한두 문장으로 끝내지 말고 필요한 만큼 충실히 설명하세요.
- 여러 항목을 나열할 땐 줄바꿈으로 구분하고 앞에 "•"만 붙이세요.
- 이전 대화는 '그것·그 의원' 같은 지시어를 이해하는 데만 쓰세요. 사실은 이번 컨텍스트 발췌로만 판단하고, 이전 답변과 다르면 이번 발췌를 따르고 정정하세요.
- 컨텍스트에 [검색 안내]가 있으면 반드시 따르세요(누가 말했는지, 일치하는 발언이 없다는 사실 등).
- 질문한 내용이 자막에 없으면 첫 문장에서 없다(찾지 못했다)고 분명히 말하세요. 비슷한 다른 논의는 "참고로"로만 덧붙이고, 있었다고 말하지 마세요.
- 컨텍스트에 없는 내용은 지어내지 말고, 정말 관련 정보가 없을 때만 "관련 자료를 찾지 못했습니다"라고 답변하세요.
- 출처나 시간 표기를 답변 본문에 길게 붙이지 마세요(시간은 별도로 표시됩니다)."""


def _strip_markdown(text: str) -> str:
    """LLM 답변에서 흔한 마크다운 기호를 제거해 일반 텍스트로 만든다."""
    text = text.replace("**", "").replace("__", "")
    text = text.replace("`", "")
    lines: list[str] = []
    for line in text.split("\n"):
        s = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)  # 헤더
        s = re.sub(r"^(\s*)[-*]\s+", r"\1• ", s)      # 글머리 기호 → •
        lines.append(s)
    return "\n".join(lines)


async def search_context(
    supabase: Client,
    question: str,
    meeting_context_id: str | None = None,
    history: list[dict] | None = None,
    scope: dict | None = None,
) -> list[dict]:
    """질문과 관련된 자막 및 의안을 검색합니다.

    회의 한정(meeting_context_id)이면 자막 전량을 안전하게 읽고(services/subtitle_fetch) 요약 + 질문 유형별 발췌를
    12,000자 안에 담은 컨텍스트 블록 하나를 만든다(services/rag_context, 2026-09-14). 예전엔 자막 전량을 앞에서 12,000자에
    잘라 2~3시간 회의의 뒷부분을 통째로 잃었다. 회의가 없으면 LookupError.

    회의 미지정이면 예전처럼 질문으로 자막·의안·회의 제목을 찾는다(여러 회의 검색 — 3차 개편 예정).
    """
    if meeting_context_id:
        return await _meeting_context(supabase, question, meeting_context_id, history)
    return await asyncio.to_thread(_global_search, supabase, question, scope)


_ROSTER_TTL = 3600.0
_roster_cache: dict[str, tuple[float, list[str]]] = {}


def _roster_names(supabase: Client, committee: str | None) -> list[str]:
    """위원회 명단 이름(1시간 캐시) — 질문 속 이름 오타를 이 회의 사람으로 맞출 때 쓴다.

    JSON 명단이 없으면 DB 폴백이 PostgREST 를 부른다 — 생중계 자막 입력과 연결 5개를 나눠 쓰니 매 질문마다 부르지 않는다.
    """
    if not committee:
        return []
    now = time.monotonic()
    hit = _roster_cache.get(committee)
    if hit and now - hit[0] < _ROSTER_TTL:
        return hit[1]
    try:
        from app.services.roster_loader import load_committee_with_roles

        names = [m["name"] for m in load_committee_with_roles(supabase, committee) if m.get("name")]
    except Exception as e:  # 명단이 없어도 대화는 된다
        logger.debug("위원회 명단 로드 실패(이름 보정 없이 진행): %s", e)
        names = []
    _roster_cache[committee] = (now, names)
    return names


def _one_row(resp) -> dict | None:
    rows = getattr(resp, "data", None) or []
    return rows[0] if rows else None


async def _meeting_context(
    supabase: Client, question: str, meeting_id: str, history: list[dict] | None
) -> list[dict]:
    try:
        meeting = _one_row(
            supabase.table("meetings")
            .select("id, title, meeting_date, committee, duration_seconds, status")
            .eq("id", meeting_id)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.warning("회의 조회 실패: %s", e)
        meeting = None
    if meeting is None:
        raise LookupError("회의를 찾을 수 없습니다.")

    # 뜻으로 찾기(임베딩 검색)는 자막 조회와 동시에 — 2.5초 안에 못 오면 키워드 검색만으로 답한다
    vec_task = None
    if settings.rag_vector_enabled and settings.openai_api_key:
        from app.services import subtitle_embeddings

        vec_task = asyncio.ensure_future(asyncio.to_thread(
            subtitle_embeddings.search, supabase, meeting_id,
            rag_context.retrieval_query(question, history), settings.rag_vector_k))
    subs = prefer_ai_subtitles(await asyncio.to_thread(fetch_all_subtitles, supabase, meeting_id))
    for sub in subs:
        sub.setdefault("meeting_id", meeting_id)

    summary_row: dict | None = None
    try:
        summary_row = _one_row(
            supabase.table("meeting_summaries").select("*").eq("meeting_id", meeting_id).limit(1).execute()
        )
    except Exception as e:
        logger.debug("요약 조회 실패(없이 진행): %s", e)

    agendas: list[dict] = []
    try:
        aresp = (
            supabase.table("meeting_agendas")
            .select("order_num, title")
            .eq("meeting_id", meeting_id)
            .order("order_num")
            .execute()
        )
        agendas = [a for a in (aresp.data or []) if a.get("title")]
    except Exception as e:
        logger.debug("안건 조회 실패(없이 진행): %s", e)

    roster = await asyncio.to_thread(_roster_names, supabase, meeting.get("committee"))
    semantic, vector_state = None, "off"
    if vec_task is not None:
        try:
            semantic = await asyncio.wait_for(vec_task, timeout=2.5)
            vector_state = "ok" if semantic else "missing"
        except asyncio.TimeoutError:
            vector_state = "timeout"
        except Exception as e:  # 표 없음(036 전)·RPC·OpenAI 실패 — 키워드 검색만으로 계속
            vector_state = "error"
            logger.warning("뜻으로 찾기 실패(키워드 검색만): %s", str(e)[:200])
    bundle = rag_context.build_meeting_context(
        subtitles=subs,
        meeting=meeting,
        summary_row=summary_row,
        agendas=agendas,
        question=question,
        history=history,
        roster=roster,
        semantic_hits=semantic,
        semantic_min=settings.rag_vector_min_sim,
        semantic_band=settings.rag_vector_band,
    )
    bundle.stats["vector"] = vector_state
    raw = {"meeting": meeting, "subs": subs, "agendas": agendas, "summary": summary_row, "roster": roster}
    logger.info(
        "rag context meeting=%s level=%s mode=%s vector=%s semantic_rows=%s hits=%s excerpts=%s chars=%s last_quarter=%s "
        "names=%s unresolved=%s restored=%s intent=%s",
        meeting_id[:8],
        bundle.stats.get("level"),
        bundle.stats.get("mode"),
        bundle.stats.get("vector"),
        bundle.stats.get("semantic_rows"),
        bundle.stats.get("hits"),
        bundle.stats.get("excerpt_count"),
        bundle.stats.get("chars"),
        bundle.stats.get("covered_last_quarter"),
        bundle.stats.get("names"),
        bundle.stats.get("unresolved"),
        bundle.stats.get("restored"),
        bundle.stats.get("intent"),
    )
    return [
        # _raw: 에이전트 도구가 자막을 다시 읽지 않게 싣는 내부 자료 — 응답으로 나가지 않는다
        {"source_type": "context_block", "text": bundle.text, "sources": bundle.sources, "stats": bundle.stats, "_raw": raw},
        {"source_type": "meeting_meta", **meeting},
    ]


# ── 여러 회의 검색(회의 미선택) — 범위 먼저, 토큰 OR 은 그 안에서 (2026-09-14, Codex 검토 반영) ─────────────
_SAFE_TERM = re.compile(r"^[0-9A-Za-z가-힣]{2,20}$")  # PostgREST or=() 문법 문자(, : ( ) . " * % _ 공백)를 원천 배제
GLOBAL_MAX_TERMS = 6
GLOBAL_MAX_MEETINGS = 30       # 범위 안에서 후보로 잡는 회의 수(최근순)
GLOBAL_MAX_CANDIDATES = 200    # 자막 후보 행
GLOBAL_PER_MEETING = 4
GLOBAL_TOP_MEETINGS = 5


def search_terms(question: str) -> list[str]:
    """질문 → 검색어(원형+보수적 파생, 안전 문자만, ≤6). rag_context 의 토큰 규칙을 그대로 쓴다."""
    plan = rag_context.parse_question(question, known_speakers=set(), agendas=[], duration=None)
    out: list[str] = []
    for t in plan.names + plan.terms:
        if _SAFE_TERM.match(t) and t not in out:
            out.append(t)
    return out[:GLOBAL_MAX_TERMS]


def build_ilike_or(terms: list[str], column: str = "text") -> str:
    """supabase-py .or_() 인자 — `text.ilike.*예산*,text.ilike.*삭감*` (clips.py 의 관용구와 같다)."""
    return ",".join(f"{column}.ilike.*{t}*" for t in terms if _SAFE_TERM.match(t))


def distribute_global_hits(rows: list[dict], terms: list[str], per_meeting: int = GLOBAL_PER_MEETING,
                           max_meetings: int = GLOBAL_TOP_MEETINGS) -> list[dict]:
    """회의별로 AI/live 자막을 고르고(prefer_ai 는 회의 단위 — 전체에 걸면 다른 회의의 live 가 사라진다) 점수순 분산."""
    by_mid: dict[str, list[dict]] = {}
    for r in rows:
        by_mid.setdefault(r.get("meeting_id") or "", []).append(r)
    scored: dict[str, list[tuple[float, dict]]] = {}
    norm_terms = [re.sub(r"\s+", "", t) for t in terms]
    for mid, grp in by_mid.items():
        grp = prefer_ai_subtitles(grp) if any("kind" in g for g in grp) else grp
        items: list[tuple[float, dict]] = []
        for g in grp:
            text = re.sub(r"\s+", "", g.get("text") or "")
            hit = [t for t in norm_terms if t in text]
            score = len(hit) + (1.0 if len(hit) >= 2 else 0.0)
            items.append((score, g))
        items.sort(key=lambda x: -x[0])
        scored[mid] = items[:per_meeting]
    ranked = sorted(scored, key=lambda m: -sum(sc for sc, _ in scored[m]))[:max_meetings]
    out: list[dict] = []
    for mid in ranked:
        out.extend(g for _, g in sorted(scored[mid], key=lambda x: (x[1].get("start_time") or 0)))
    return out


def _global_search(supabase: Client, question: str, scope: dict | None = None) -> list[dict]:
    """여러 회의에서 검색: 기간(기본 30일)·위원회로 회의 후보를 먼저 제한하고 그 안에서 검색어 OR."""
    from datetime import date, timedelta

    scope = scope or {}
    days = int(scope.get("days") or 30)
    committee = (scope.get("committee") or "").strip()
    since = (date.today() - timedelta(days=days)).isoformat()
    terms = search_terms(question)
    results: list[dict] = []

    # 1. 범위 안의 회의 후보(최근순)
    meetings: dict[str, dict] = {}
    try:
        q = (
            supabase.table("meetings")
            .select("id, title, meeting_date, committee, status")
            .gte("meeting_date", since)
        )
        if committee and _SAFE_TERM.match(committee):
            q = q.ilike("committee", f"*{committee}*")
        mresp = q.order("meeting_date", desc=True).limit(GLOBAL_MAX_MEETINGS).execute()
        meetings = {m["id"]: m for m in (mresp.data or []) if m.get("id")}
    except Exception as e:
        logger.warning("회의 범위 조회 실패: %s", e)
    ids = list(meetings)

    # 2. 자막 — 검색어 OR(안전 문자만). 검색어가 없으면 예전처럼 질문 전체 ilike
    if ids:
        try:
            sq = (
                supabase.table("subtitles")
                .select("id, meeting_id, text, speaker, start_time, end_time, kind")
                .in_("meeting_id", ids)
            )
            sq = sq.or_(build_ilike_or(terms)) if terms else sq.ilike("text", f"%{question}%")
            sresp = sq.limit(GLOBAL_MAX_CANDIDATES).execute()
            for sub in distribute_global_hits(sresp.data or [], terms or [question]):
                m = meetings.get(sub.get("meeting_id") or "", {})
                results.append({
                    "source_type": "subtitle",
                    "meeting_id": sub.get("meeting_id"),
                    "meeting_title": m.get("title"),
                    "meeting_date": m.get("meeting_date"),
                    "text": sub.get("text"),
                    "speaker": sub.get("speaker"),
                    "start_time": sub.get("start_time"),
                    "end_time": sub.get("end_time"),
                })
        except Exception as e:
            logger.warning("자막 검색 실패: %s", e)

    # 3. 의안 제목(기간 무관)
    try:
        bq = supabase.table("bills").select("id, bill_number, title, proposer, committee, status")
        bq = bq.or_(build_ilike_or(terms, "title")) if terms else bq.ilike("title", f"%{question}%")
        for bill in (bq.limit(10).execute().data or []):
            results.append({
                "source_type": "bill",
                "bill_id": bill["id"],
                "bill_number": bill.get("bill_number"),
                "title": bill["title"],
                "proposer": bill.get("proposer"),
                "committee": bill.get("committee"),
                "status": bill.get("status"),
            })
    except Exception as e:
        logger.warning("의안 검색 실패: %s", e)

    # 4. 회의 제목(범위 안)
    try:
        mq = supabase.table("meetings").select("id, title, meeting_date, status").gte("meeting_date", since)
        if committee and _SAFE_TERM.match(committee):
            mq = mq.ilike("committee", f"*{committee}*")
        mq = mq.or_(build_ilike_or(terms, "title")) if terms else mq.ilike("title", f"%{question}%")
        for mtg in (mq.order("meeting_date", desc=True).limit(5).execute().data or []):
            results.append({
                "source_type": "meeting",
                "meeting_id": mtg["id"],
                "title": mtg["title"],
                "meeting_date": mtg.get("meeting_date"),
            })
    except Exception as e:
        logger.warning("회의 검색 실패: %s", e)

    results.append({"source_type": "scope", "days": days, "committee": committee or None, "meetings": len(ids), "terms": terms})
    return results


def _format_context_for_prompt(context: list[dict]) -> str:
    """검색 결과를 GPT 프롬프트용 텍스트로 변환합니다.

    회의 정보·발언자 목록·요약을 앞쪽에 배치하여, 자막이 길어 뒤가 잘리더라도
    핵심 정보(누가 발언했는지, 회의 요약 등)는 항상 포함되게 한다.
    """
    blocks = [c for c in context if c.get("source_type") == "context_block"]
    if blocks:  # 회의 한정 — rag_context 가 예산 안에서 이미 조립했다
        return blocks[0].get("text") or ""
    if not any(c.get("source_type") in ("subtitle", "bill", "meeting", "meeting_meta", "summary") for c in context):
        return ""  # 검색 범위 안내(scope)만 남은 것은 자료가 아니다 — 빈 컨텍스트 경로(모델 호출 없음)로

    lines: list[str] = []

    subtitles = [c for c in context if c.get("source_type") == "subtitle"]
    bills = [c for c in context if c.get("source_type") == "bill"]
    meetings = [c for c in context if c.get("source_type") == "meeting"]
    metas = [c for c in context if c.get("source_type") == "meeting_meta"]
    summaries = [c for c in context if c.get("source_type") == "summary"]

    # 회의 정보
    for m in metas:
        lines.append("=== 회의 정보 ===")
        lines.append(f"제목: {m.get('title', '')}")
        if m.get("meeting_date"):
            lines.append(f"일시: {m.get('meeting_date')}")
        if m.get("committee"):
            lines.append(f"위원회: {m.get('committee')}")
        lines.append("")

    # 발언자 목록 (자막에서 중복 제거, 등장 순서)
    if subtitles:
        speakers: list[str] = []
        seen: set[str] = set()
        for sub in subtitles:
            sp = sub.get("speaker") or "발언자 미확인"
            if sp not in seen:
                seen.add(sp)
                speakers.append(sp)
        if speakers:
            lines.append("=== 발언자 목록 ===")
            lines.append(", ".join(speakers))
            lines.append("")

    # 회의 요약
    for s in summaries:
        txt = (s.get("text") or "").strip()
        if txt:
            lines.append("=== 회의 요약 ===")
            lines.append(txt)
            lines.append("")

    # 관련 의안 (전역 검색 시)
    if bills:
        lines.append("=== 관련 의안 ===")
        for bill in bills:
            number = bill.get("bill_number", "")
            title = bill.get("title", "")
            status = bill.get("status", "")
            lines.append(f"의안 {number}: {title} (상태: {status})")
        lines.append("")

    # 관련 회의 (전역 검색 시)
    if meetings:
        lines.append("=== 관련 회의 ===")
        for mtg in meetings:
            title = mtg.get("title", "")
            date = mtg.get("meeting_date", "")
            lines.append(f"회의: {title} ({date})")
        lines.append("")

    scopes = [c for c in context if c.get("source_type") == "scope"]
    for sc in scopes:
        lines.append(f"(검색 범위: 최근 {sc.get('days')}일 · 회의 {sc.get('meetings')}건"
                     + (f" · {sc.get('committee')}" if sc.get("committee") else "") + ")")
        lines.append("")

    # 회의 자막 (맨 뒤 — 길면 여기서부터 잘림). 여러 회의면 회의별로 묶어 제목·날짜를 앞세운다
    if subtitles:
        lines.append("=== 회의 자막(발췌) ===")
        last_mid = None
        for sub in subtitles:
            mid = sub.get("meeting_id")
            if mid != last_mid:
                title = sub.get("meeting_title") or f"회의 {str(mid or '')[:8]}"
                date = sub.get("meeting_date") or ""
                lines.append(f"▶ {title} ({date})" if date else f"▶ {title}")
                last_mid = mid
            speaker = sub.get("speaker") or "발언자 미확인"
            start = sub.get("start_time", 0) or 0
            text = sub.get("text", "")
            lines.append(f"[{start:.1f}초] {speaker}: {text}")
        lines.append("")

    result = "\n".join(lines)
    if len(result) > MAX_CONTEXT_CHARS:
        result = result[:MAX_CONTEXT_CHARS] + "\n... (이하 생략)"

    return result


def _extract_sources(context: list[dict]) -> list[dict]:
    """검색 결과에서 소스 참조 정보를 추출합니다."""
    sources: list[dict] = []
    seen_meetings: set[str] = set()

    for item in context:
        if item.get("source_type") == "subtitle":
            mid = item.get("meeting_id", "")
            if mid not in seen_meetings:
                seen_meetings.add(mid)
                sources.append({
                    "meeting_id": mid,
                    "meeting_title": item.get("meeting_title"),
                    "start_time": item.get("start_time"),
                    "text_snippet": (item.get("text") or "")[:100],
                    "source_type": "subtitle",
                })
        elif item.get("source_type") == "bill":
            sources.append({
                "meeting_id": "",
                "meeting_title": item.get("title"),
                "start_time": None,
                "text_snippet": f"의안 {item.get('bill_number', '')}: {item.get('title', '')}",
                "source_type": "bill",
            })

    return sources[:10]  # 최대 10개


def _relevant_sources(question: str, context: list[dict]) -> list[dict]:
    """질문 키워드와 겹치는 자막 상위 3개를 출처(재생용 타임스탬프 포함)로 반환.
    겹치는 자막이 없으면 회의 단위 출처로 폴백한다."""
    for c in context:
        if c.get("source_type") == "context_block":
            # 회의 한정 — 프롬프트에 실제로 들어간 발췌 안에서만 고른 출처(rag_context). 프롬프트 밖 자막을 가리키던 결함 수정.
            return list(c.get("sources") or [])[:5]
    subs = [c for c in context if c.get("source_type") == "subtitle"]
    qwords = search_terms(question) or [w for w in re.split(r"\s+", question) if len(w) >= 2]
    scored: list[tuple[int, dict]] = []
    for s in subs:
        text = s.get("text") or ""
        score = sum(1 for w in qwords if w in text)
        if score > 0:
            scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    top = [s for _, s in scored[:3]]
    if not top:
        return _extract_sources(context)
    return [
        {
            "meeting_id": s.get("meeting_id", ""),
            "meeting_title": s.get("meeting_title"),
            "start_time": s.get("start_time"),
            "text_snippet": (s.get("text") or "")[:80],
            "source_type": "subtitle",
        }
        for s in top
    ]


NO_CONTEXT_ANSWER = "질문과 관련된 회의 자료를 찾지 못했습니다. 다른 키워드로 질문해 주세요."
OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"


def _build_messages(question: str, context_text: str, history: list[dict] | None) -> list[dict]:
    """system → 이전 대화(최근 8개) → 이번 질문+컨텍스트. 자막은 현재 질문에만 1회 포함한다."""
    # 이전 답은 근거 자막 없이 다시 들어가 오답이 굳었다(2026-09-15 "대화할수록 이상하다") — 줄이고 표시하며,
    # "찾지 못했습니다" 류 답은 뺀다. 이전 질문은 지시어 해석에 필요하니 남긴다.
    messages: list[dict] = [{"role": "system", "content": RAG_SYSTEM_PROMPT}]
    for h in (history or [])[-8:]:
        role = h.get("role")
        content = (h.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        if role == "user":
            content = content[:500]
        else:
            if NO_CONTEXT_ANSWER in content or "찾지 못했" in content:
                continue
            content = "[이전 답변 일부 — 근거 자막 없음] " + content[:300]
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": f"질문: {question}\n\n컨텍스트:\n{context_text}"})
    return messages


def _chat_body(messages: list[dict], *, stream: bool) -> dict:
    body: dict = {
        "model": settings.ai_chat_model,
        "messages": messages,
        # 추론 모델은 생각 토큰도 이 상한에 포함된다 — 실제로 쓴 만큼만 과금되니 넉넉히 둔다(2026-09-15)
        "max_completion_tokens": settings.ai_chat_max_tokens,
        **reasoning_kw(settings.ai_chat_reasoning_effort),
    }
    if stream:
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
    return body


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"}


def _log_usage(kind: str, model: str | None, usage: dict | None, finish: str | None, t0: float) -> None:
    u = usage or {}
    reasoning = (u.get("completion_tokens_details") or {}).get("reasoning_tokens")
    logger.info(
        "ai %s model=%s in=%s out=%s reasoning=%s finish=%s %.1fs",
        kind, model, u.get("prompt_tokens"), u.get("completion_tokens"), reasoning, finish, time.monotonic() - t0,
    )


def _finalize(raw: str, finish: str | None, model: str | None) -> str:
    """정리본(마크다운 제거). 비었으면 AiUpstreamError — 길이 상한에서 잘린 빈 답을 정상처럼 내보내지 않는다."""
    answer = _strip_markdown((raw or "").strip())
    if finish == "length":
        # 생각 토큰이 상한을 먹으면 본문이 비거나 중간에 끊긴다(9-14 요약 1,200 토큰 사고와 같은 구조)
        logger.warning("AI 답변이 길이 상한(%s)에서 잘렸다(model=%s, %d자)", settings.ai_chat_max_tokens, model, len(answer))
        if not answer:
            raise AiUpstreamError("AI 답변이 길이 상한에서 잘렸습니다. 질문을 나눠 다시 시도해 주세요.")
    if not answer:
        raise AiUpstreamError("AI 가 빈 답변을 돌려주었습니다. 다시 시도해 주세요.")
    return answer


def _record(t0: float, ok: bool) -> None:
    try:
        from app.api.admin import api_tracker

        api_tracker.record("openai", (time.monotonic() - t0) * 1000, ok)
    except Exception:
        pass


async def generate_answer(
    question: str,
    context: list[dict],
    meeting_context_id: str | None = None,
    history: list[dict] | None = None,
) -> dict:
    """컨텍스트 기반으로 AI 답변을 생성합니다(한 번에 받는 경로 — /api/ai/chat).

    Returns:
        {"answer": str, "sources": list[dict]}
    """
    context_text = _format_context_for_prompt(context)

    if not context_text.strip():  # 비용 0 경로 — 키 검사보다 먼저
        return {"answer": NO_CONTEXT_ANSWER, "sources": []}

    if not settings.openai_api_key:
        raise AiNotConfiguredError("AI 서비스가 설정되지 않았습니다. (OPENAI_API_KEY 필요)")

    messages = _build_messages(question, context_text, history)
    t0 = time.monotonic()
    api_success = False
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(OPENAI_CHAT_URL, headers=_headers(), json=_chat_body(messages, stream=False))
            response.raise_for_status()
        api_success = True
    except Exception as e:
        logger.error("OpenAI API 호출 실패: %s", e)
        raise AiUpstreamError("AI 응답 생성에 실패했습니다. 잠시 뒤 다시 시도해 주세요.") from e
    finally:
        _record(t0, api_success)

    try:
        data = response.json()
        choice = data["choices"][0]
        raw = choice["message"]["content"] or ""
        finish = choice.get("finish_reason")
        _log_usage("chat", data.get("model"), data.get("usage"), finish, t0)
    except Exception as e:  # 형식이 다른 응답
        logger.error("OpenAI 응답 파싱 실패: %s", e)
        raise AiUpstreamError("AI 응답을 읽지 못했습니다. 잠시 뒤 다시 시도해 주세요.") from e
    answer = _finalize(raw, finish, data.get("model"))
    return {"answer": answer, "sources": _relevant_sources(question, context)}


async def stream_answer(
    question: str,
    context: list[dict],
    meeting_context_id: str | None = None,
    history: list[dict] | None = None,
):
    """답을 글자 조각으로 흘려보내는 비동기 생성기(/api/ai/chat/stream, 2026-09-15 담당자 요청 "답변 속도").

    끝까지 다 만든 뒤 한 번에 보내던 방식은 1,000~2,500자 답이면 그동안 아무것도 안 보였다.
    내놓는 것: ("start", None) — OpenAI 가 200 으로 응답을 시작함(이 전의 실패는 AiUpstreamError 로 올라가 호출자가 502 로 낸다)
              ("delta", str)   — 본문 조각(마크다운 제거 전 원문)
              ("done", {"answer": 정리본, "sources": [...]})
    호출자가 소비를 멈추면(브라우저 끊김) async with 가 OpenAI 연결도 닫는다.
    """
    context_text = _format_context_for_prompt(context)
    if not context_text.strip():  # 비용 0 경로
        yield ("start", None)
        yield ("delta", NO_CONTEXT_ANSWER)
        yield ("done", {"answer": NO_CONTEXT_ANSWER, "sources": []})
        return

    if not settings.openai_api_key:
        raise AiNotConfiguredError("AI 서비스가 설정되지 않았습니다. (OPENAI_API_KEY 필요)")

    messages = _build_messages(question, context_text, history)
    t0 = time.monotonic()
    ok = False
    parts: list[str] = []
    finish: str | None = None
    usage: dict | None = None
    model: str | None = None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=90.0)) as client:
            try:
                async with client.stream(
                    "POST", OPENAI_CHAT_URL, headers=_headers(), json=_chat_body(messages, stream=True)
                ) as response:
                    if response.status_code != 200:
                        body = (await response.aread())[:300]
                        logger.error("OpenAI 스트림 시작 실패 %s: %s", response.status_code, body)
                        raise AiUpstreamError("AI 응답 생성에 실패했습니다. 잠시 뒤 다시 시도해 주세요.")
                    yield ("start", None)
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        model = event.get("model") or model
                        if event.get("usage"):
                            usage = event["usage"]
                        for choice in event.get("choices") or []:
                            piece = (choice.get("delta") or {}).get("content")
                            if piece:
                                parts.append(piece)
                                yield ("delta", piece)
                            if choice.get("finish_reason"):
                                finish = choice["finish_reason"]
            except AiUpstreamError:
                raise
            except httpx.HTTPError as e:
                logger.error("OpenAI 스트림 오류: %s", e)
                raise AiUpstreamError("AI 응답이 중간에 끊겼습니다. 다시 시도해 주세요.") from e
        ok = True
    finally:
        _record(t0, ok)
    _log_usage("chat-stream", model, usage, finish, t0)
    if finish is None:
        # 상류가 HTTP 오류 없이 연결만 끊으면 완료 신호가 없다 — 반쪽 답을 완료로 저장하지 않는다(Codex 검토 2026-09-15)
        logger.error("OpenAI 스트림이 완료 신호 없이 끝났다(model=%s, %d자)", model, len("".join(parts)))
        raise AiUpstreamError("AI 응답이 중간에 끊겼습니다. 다시 시도해 주세요.")
    answer = _finalize("".join(parts), finish, model)
    yield ("done", {"answer": answer, "sources": _relevant_sources(question, context)})


async def stream_agent(
    question: str,
    context: list[dict],
    meeting_context_id: str | None,
    history: list[dict] | None,
    supabase: Client,
):
    """에이전트형 흐름(services/ai_agent) — 켜져 있고 회의 한정일 때만. 시작 전에 실패하면 한 번 답 경로(stream_answer)로."""
    from app.services import ai_agent

    block = next((c for c in context if c.get("source_type") == "context_block"), None)
    raw = (block or {}).get("_raw")
    if not (settings.ai_agent_enabled and raw and meeting_context_id and settings.openai_api_key):
        async for item in stream_answer(question, context, meeting_context_id, history):
            yield item
        return
    context_text = _format_context_for_prompt(context)
    if not context_text.strip():
        async for item in stream_answer(question, context, meeting_context_id, history):
            yield item
        return
    messages = _build_messages(question, context_text, history)
    messages[0] = {"role": "system", "content": RAG_SYSTEM_PROMPT + ai_agent.AGENT_RULES}
    mid = meeting_context_id

    async def semantic(q: str):
        from app.services import subtitle_embeddings

        return await asyncio.to_thread(subtitle_embeddings.search, supabase, mid, q, settings.rag_vector_k)

    def requests_loader() -> list[dict]:
        return (supabase.table("material_requests").select("start_time, councilor_name, summary, department, status")
                .eq("meeting_id", mid).order("start_time").execute().data or [])

    toolbox = ai_agent.MeetingToolbox(
        meeting=raw["meeting"], subs=raw["subs"], agendas=raw["agendas"], summary=raw["summary"], roster=raw["roster"],
        semantic=semantic if settings.rag_vector_enabled else None, requests_loader=requests_loader)
    started = False
    try:
        async for item in ai_agent.stream_agent_answer(question, messages, toolbox, (block or {}).get("sources") or []):
            started = True
            yield item
    except AiUpstreamError:
        if started:
            raise
        logger.warning("에이전트 시작 실패 — 한 번 답 경로로")
        async for item in stream_answer(question, context, meeting_context_id, history):
            yield item


async def generate_meeting_summary_enhanced(
    supabase: Client,
    meeting_id: str,
) -> dict:
    """회의 요약을 생성합니다 (기존 summary_service 래핑).

    Args:
        supabase: Supabase 클라이언트
        meeting_id: 회의 ID

    Returns:
        {"summary_text": str, "key_points": list, "agenda_items": list}
    """
    from app.services.summary_service import generate_meeting_summary

    try:
        summary = await generate_meeting_summary(supabase, meeting_id)
        return {
            "summary_text": summary.summary_text,
            "key_points": summary.key_decisions,
            "agenda_items": [
                a.get("title", "") for a in summary.agenda_summaries
            ],
        }
    except ValueError as e:
        return {
            "summary_text": str(e),
            "key_points": [],
            "agenda_items": [],
        }
