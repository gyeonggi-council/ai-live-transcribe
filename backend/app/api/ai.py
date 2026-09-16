"""AI 어시스턴트 API 라우터

# @TASK P11B - AI Assistant API
# @SPEC docs/planning/02-trd.md#AI-어시스턴트

엔드포인트:
  POST /api/ai/chat                        - RAG Q&A (optional_auth — 담당자 결정 2026-09-14: 외부 비로그인도 하루 한도 안에서)
  POST /api/ai/chat/stream                 - 같은 Q&A 를 글자 조각으로 흘려보낸다(text/event-stream, 2026-09-15) — 화면이 쓰는 경로
  POST /api/ai/summary                     - 회의 요약 (AI_ROLES 또는 의회망 손님) — 정본은 /api/meetings/{id}/summary 로 옮기는 중
  GET  /api/ai/conversations               - 본인 세션 목록
  GET  /api/ai/conversations/{session_id}  - 본인 세션 대화 이력

이력·세션 규칙(2026-09-14, migration 033):
- 소유자 키(owner_key)는 서버가 검증한 주체에서만 만든다(core.auth_middleware.ai_owner_key). 없으면 저장·이력 없음.
- 세션은 소유자 + 회의(meeting_context_id)에 고정. 남의 세션은 조회·이어쓰기 모두 404, 같은 소유자라도 회의가 다르면 400.
- 클라이언트가 보낸 session_id 가 DB 에 없으면 서버가 새 ID 를 발급한다(임의 값을 세션 식별자로 채택하지 않는다).
- 옛 GET /conversations/shared(로그인 없이 최근 60건 공개)는 없앴다 — 본인 것만 본다.
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from supabase import Client

from app.core.auth_middleware import AI_ROLES, ai_owner_key, optional_auth, require_role_or_council
from app.core.config import settings
from app.core.council_network import client_ip, is_council_ip
from app.core.database import get_supabase
from app.schemas.ai import (
    ChatRequest,
    ChatResponse,
    ConversationItem,
    ConversationSession,
    SourceReference,
    SummaryRequest,
    SummaryResponse,
)
from app.services.ai_rag_service import (
    AiNotConfiguredError,
    AiUpstreamError,
    generate_answer,
    generate_meeting_summary_enhanced,
    search_context,
    stream_agent,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["ai"])

KST = timezone(timedelta(hours=9))

# 비용 보호 — 하루 호출 수 제한(인메모리, 단일 파드 가정, 재시작 시 초기화).
# 키 "ip:<주소>" 는 모든 요청에, "user:<owner>" 는 로그인 사용자에게 추가로 건다. 일자 경계는 KST(예전엔 UTC 라 한국의 "내일"과 달랐다).
_chat_calls: dict[str, tuple[str, int]] = {}
HISTORY_TURNS = 12  # 세션에서 읽는 최근 행 수(질문+답변) — 생성기는 이 중 최근 8개를 쓴다


def _today() -> str:
    return datetime.now(KST).date().isoformat()


def _bump(key: str, limit: int, what: str) -> None:
    today = _today()
    last_date, count = _chat_calls.get(key, (today, 0))
    if last_date != today:
        count = 0
    if count >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"오늘 AI 대화 한도({limit}회, {what})를 초과했습니다. 내일 00시(한국시간)에 다시 열립니다.",
        )
    _chat_calls[key] = (today, count + 1)


def _enforce_chat_rate_limit(request: Request, owner_key: str | None) -> None:
    # IP 는 Traefik 이 넣는 X-Real-IP 기준(core/council_network). 의회망은 NAT 뒤라 건물 전체가 한 칸을 나눠 쓴다.
    ip = client_ip(request) or "unknown"
    limit = settings.ai_chat_daily_limit_council if is_council_ip(ip) else settings.ai_chat_daily_limit
    _bump(f"ip:{ip}", limit, "접속 주소 기준")
    if owner_key and owner_key.startswith("user:"):
        _bump(owner_key, settings.ai_chat_daily_limit_user, "계정 기준")


def _is_uuid(value: str | None) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError):
        return False


def _session_head(supabase: Client, session_id: str) -> dict | None:
    """세션의 첫 행(소유자·회의) — 없으면 None."""
    resp = (
        supabase.table("ai_conversations")
        .select("owner_key, meeting_context_id")
        .eq("session_id", session_id)
        .order("created_at")
        .limit(1)
        .execute()
    )
    rows = resp.data or []
    return rows[0] if rows else None


def _require_owner(request: Request, user: dict | None) -> str:
    owner_key = ai_owner_key(request, user)
    if not owner_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="대화 이력은 로그인하거나 이 브라우저의 손님 표식(X-Guest-Id)이 있어야 볼 수 있습니다.",
        )
    return owner_key


@dataclass
class _ChatPrep:
    owner_key: str | None
    meeting_id: str | None
    session_id: str
    history: list[dict]
    context: list[dict]


async def _prepare_chat(body: ChatRequest, request: Request, user: dict | None, supabase: Client) -> _ChatPrep:
    """한도 → 세션·이력 → 컨텍스트. /chat 과 /chat/stream 이 같이 쓴다 — 오류(400/404/429)는 흐름 시작 전에 일반 HTTP 오류로."""
    owner_key = ai_owner_key(request, user)
    _enforce_chat_rate_limit(request, owner_key)
    meeting_id = body.meeting_context_id or None
    if meeting_id and not _is_uuid(meeting_id):
        raise HTTPException(status_code=400, detail="회의 ID 형식이 올바르지 않습니다.")

    # 0. 세션 — 소유자·회의에 고정. 남의 것은 404, 회의가 다르면 400, 모르는 ID 는 새로 발급.
    session_id: str | None = None
    history: list[dict] = []
    if body.session_id and _is_uuid(body.session_id):
        try:
            head = _session_head(supabase, body.session_id)
        except Exception as e:  # 이력 테이블 조회 실패는 대화를 막지 않는다 — 새 세션으로
            logger.warning("세션 조회 실패(새 세션으로 진행): %s", e)
            head = None
        if head is not None:
            if not owner_key or head.get("owner_key") != owner_key:
                raise HTTPException(status_code=404, detail="대화 세션을 찾을 수 없습니다.")
            if (head.get("meeting_context_id") or None) != meeting_id:
                raise HTTPException(
                    status_code=400,
                    detail="이 대화는 다른 회의에 묶여 있습니다. 회의를 바꾸려면 새 대화를 시작하세요.",
                )
            session_id = body.session_id
            try:
                hresp = (
                    supabase.table("ai_conversations")
                    .select("role, content")
                    .eq("session_id", session_id)
                    .eq("owner_key", owner_key)  # 옛 혼합 세션(033 이전 shared 화면)의 남의 행·익명 행을 맥락에 넣지 않는다
                    .order("created_at", desc=True)
                    .order("role")  # 같은 시각이면 assistant 가 앞 → 뒤집으면 user 가 먼저
                    .limit(HISTORY_TURNS)
                    .execute()
                )
                history = list(reversed(hresp.data or []))  # 최근 N건을 오래된 순으로
            except Exception as e:
                logger.warning("대화 이력 조회 실패(맥락 없이 진행): %s", e)
                history = []
    session_id = session_id or str(uuid.uuid4())

    # 1. 관련 컨텍스트 검색 (회의 한정이면 요약 + 질문 유형별 발췌 — services/rag_context)
    try:
        context = await search_context(
            supabase, body.question, meeting_id, history=history,
            scope=body.scope.model_dump() if body.scope else None,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e) or "회의를 찾을 수 없습니다.")
    return _ChatPrep(owner_key, meeting_id, session_id, history, context)


def _save_history(
    supabase: Client, prep: _ChatPrep, user: dict | None, question: str, answer: str, sources: list[SourceReference]
) -> bool:
    """질문·답변을 한 번에 저장(반쪽 저장 방지). 소유자를 알 때만."""
    if not prep.owner_key:
        return False
    user_id = user.get("id") if user and _is_uuid(user.get("id")) else None  # quick-admin 은 users 행이 없다
    common = {
        "session_id": prep.session_id,
        "user_id": user_id,
        "owner_key": prep.owner_key,
        "meeting_context_id": prep.meeting_id,
    }
    # 한 INSERT 의 두 행은 created_at DEFAULT now() 가 같아 순서가 흔들린다 → 시각을 명시(답변 = 질문 +1ms)
    t_user = datetime.now(timezone.utc)
    t_answer = t_user + timedelta(milliseconds=1)
    try:
        supabase.table("ai_conversations").insert([
            {**common, "role": "user", "content": question, "created_at": t_user.isoformat()},
            {**common, "role": "assistant", "content": answer, "sources": [s.model_dump() for s in sources],
             "created_at": t_answer.isoformat()},
        ]).execute()
        return True
    except Exception as e:
        logger.warning("대화 이력 저장 실패: %s", e)
        return False


@router.post("/chat", response_model=ChatResponse)
async def ai_chat(
    body: ChatRequest,
    request: Request,
    user: dict | None = Depends(optional_auth),
    supabase: Client = Depends(get_supabase),
) -> ChatResponse:
    """AI Q&A 채팅 - 회의 자료 기반 RAG 답변을 한 번에 받는다(모델은 settings.ai_chat_model).

    로그인 불필요(담당자 결정). 비용 보호를 위해 IP당·계정당 하루 호출 수가 제한된다.
    소유자를 알 수 있을 때(로그인 또는 손님 표식) 대화 이력이 저장되고 후속 질문이 이어진다.
    화면은 2026-09-15 부터 /chat/stream 을 쓴다 — 이 경로는 호환·도구용으로 남긴다.
    """
    prep = await _prepare_chat(body, request, user, supabase)
    try:
        result = await generate_answer(body.question, prep.context, prep.meeting_id, prep.history)
    except AiNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except AiUpstreamError as e:
        raise HTTPException(status_code=502, detail=str(e))

    answer = result["answer"]
    sources = [SourceReference(**s) for s in result.get("sources", [])]
    saved = _save_history(supabase, prep, user, body.question, answer, sources)
    return ChatResponse(answer=answer, sources=sources, session_id=prep.session_id, saved=saved)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
async def ai_chat_stream(
    body: ChatRequest,
    request: Request,
    user: dict | None = Depends(optional_auth),
    supabase: Client = Depends(get_supabase),
) -> StreamingResponse:
    """AI 답을 글자 조각으로 흘려보낸다(text/event-stream, 2026-09-15 담당자 요청 "AI 답변 속도").

    이벤트: delta {"t": 조각} … → done {"answer": 정리본, "sources", "session_id", "saved"} / 도중 실패 error {"detail"}.
    한도·세션·회의 오류와 OpenAI 가 응답을 시작하지 못한 실패는 흐름을 열기 전에 일반 HTTP 오류(4xx/502/503)로 낸다.
    다 받은 뒤에만 이력을 저장한다 — 브라우저가 중간에 끊으면 반쪽 답은 남기지 않는다.
    """
    prep = await _prepare_chat(body, request, user, supabase)
    gen = stream_agent(body.question, prep.context, prep.meeting_id, prep.history, supabase)
    try:
        await gen.__anext__()  # ("start", None) — OpenAI 가 200 으로 응답을 시작할 때까지
    except AiNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except AiUpstreamError as e:
        raise HTTPException(status_code=502, detail=str(e))

    async def events():
        try:
            final: dict | None = None
            async for kind, payload in gen:
                if kind == "delta":
                    yield _sse("delta", {"t": payload})
                elif kind == "status":
                    yield _sse("status", {"t": payload})       # 에이전트가 도구로 찾는 중("자막 검색 중…")
                elif kind == "reset":
                    yield _sse("reset", {})                     # 흘려보낸 반쪽 글을 지우라(도구 호출로 바뀜)
                elif kind == "done":
                    final = payload
            if final is None:
                raise AiUpstreamError("AI 응답이 중간에 끊겼습니다. 다시 시도해 주세요.")
            sources = [SourceReference(**s) for s in final.get("sources", [])]
            saved = await asyncio.to_thread(_save_history, supabase, prep, user, body.question, final["answer"], sources)
            yield _sse("done", {
                "answer": final["answer"],
                "sources": [s.model_dump() for s in sources],
                "session_id": prep.session_id,
                "saved": saved,
            })
        except AiUpstreamError as e:
            yield _sse("error", {"detail": str(e)})
        except Exception:
            logger.exception("AI 스트림 처리 오류")
            yield _sse("error", {"detail": "AI 응답 생성 중 오류가 발생했습니다. 다시 시도해 주세요."})
        finally:
            await gen.aclose()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/summary", response_model=SummaryResponse)
async def ai_summary(
    body: SummaryRequest,
    user: dict = Depends(require_role_or_council(*AI_ROLES)),
    supabase: Client = Depends(get_supabase),
) -> SummaryResponse:
    """회의 AI 요약 생성 (로그인 AI_ROLES 또는 의회망 손님)

    호환 어댑터 — 정본은 POST /api/meetings/{id}/summary(전 필드 반환). 프런트가 옮겨 가면 없앤다.
    """
    result = await generate_meeting_summary_enhanced(supabase, body.meeting_id)
    return SummaryResponse(
        summary_text=result["summary_text"],
        key_points=result["key_points"],
        agenda_items=result["agenda_items"],
    )


@router.get("/conversations", response_model=list[ConversationSession])
async def list_conversations(
    request: Request,
    user: dict = Depends(require_role_or_council(*AI_ROLES)),
    supabase: Client = Depends(get_supabase),
) -> list[ConversationSession]:
    """본인의 대화 세션 목록 — 최근 활동순 최대 50개. 첫 질문·메시지 수·회의 제목을 정확히 센다."""
    owner_key = _require_owner(request, user)
    try:
        resp = (
            supabase.table("ai_conversations")
            .select("session_id, role, content, meeting_context_id, created_at")
            .eq("owner_key", owner_key)
            .order("created_at", desc=True)
            .limit(400)
            .execute()
        )
    except Exception as e:
        logger.error("대화 세션 조회 실패: %s", e)
        return []

    sessions: dict[str, dict] = {}
    for row in resp.data or []:  # 최신 → 오래된 순으로 온다
        sid = row["session_id"]
        s = sessions.get(sid)
        if s is None:
            s = sessions[sid] = {
                "session_id": sid,
                "first_question": "",
                "message_count": 0,
                "meeting_context_id": row.get("meeting_context_id"),
                "created_at": row["created_at"],
                "last_active_at": row["created_at"],
            }
        s["message_count"] += 1
        if row["created_at"] < s["created_at"]:
            s["created_at"] = row["created_at"]
        if row["created_at"] > s["last_active_at"]:
            s["last_active_at"] = row["created_at"]
        if row.get("role") == "user":
            s["first_question"] = (row.get("content") or "")[:200]  # 오래된 행이 뒤에 오므로 마지막에 남는 것이 첫 질문

    titles: dict[str, str] = {}
    mids = sorted({s["meeting_context_id"] for s in sessions.values() if s.get("meeting_context_id")})
    if mids:
        try:
            mresp = supabase.table("meetings").select("id, title").in_("id", mids).execute()
            titles = {m["id"]: m.get("title") or "" for m in (mresp.data or [])}
        except Exception as e:
            logger.warning("세션 회의 제목 조회 실패: %s", e)

    out = sorted(sessions.values(), key=lambda s: s["last_active_at"], reverse=True)[:50]
    return [ConversationSession(**s, meeting_title=titles.get(s["meeting_context_id"] or "")) for s in out]


@router.get("/conversations/{session_id}", response_model=list[ConversationItem])
async def get_conversation(
    session_id: str,
    request: Request,
    user: dict = Depends(require_role_or_council(*AI_ROLES)),
    supabase: Client = Depends(get_supabase),
) -> list[ConversationItem]:
    """본인 세션의 대화 이력(출처 포함). 남의 세션은 404."""
    owner_key = _require_owner(request, user)
    try:
        resp = (
            supabase.table("ai_conversations")
            .select("*")
            .eq("session_id", session_id)
            .eq("owner_key", owner_key)
            .order("created_at")
            .order("role", desc=True)  # 같은 시각이면 user 가 먼저
            .execute()
        )
    except Exception as e:
        logger.error("대화 이력 조회 실패: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="대화 이력 조회 실패")

    rows = [r for r in (resp.data or []) if r.get("owner_key") == owner_key]
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="대화 세션을 찾을 수 없습니다.")

    return [
        ConversationItem(
            id=row["id"],
            session_id=row["session_id"],
            role=row["role"],
            content=row["content"],
            sources=row.get("sources"),
            meeting_context_id=row.get("meeting_context_id"),
            created_at=row["created_at"],
        )
        for row in rows
    ]
