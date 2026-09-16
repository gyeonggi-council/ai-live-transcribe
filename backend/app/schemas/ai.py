"""AI 어시스턴트 관련 Pydantic 스키마

# @TASK P11B - AI Assistant schemas
# @SPEC docs/planning/02-trd.md#AI-어시스턴트
"""

from typing import Optional

from pydantic import BaseModel, Field


class SearchScope(BaseModel):
    """여러 회의 검색(회의 미선택) 범위 — 무제한 전역을 기본으로 두지 않는다(2026-09-14)"""

    days: int = Field(30, ge=1, le=365)
    committee: Optional[str] = Field(None, max_length=60)


class ChatRequest(BaseModel):
    """AI 채팅 요청"""

    question: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = None
    meeting_context_id: Optional[str] = None
    scope: Optional[SearchScope] = None


class SourceReference(BaseModel):
    """답변 참조 소스"""

    meeting_id: str
    meeting_title: Optional[str] = None
    start_time: Optional[float] = None
    text_snippet: Optional[str] = None
    source_type: str = "subtitle"  # subtitle | bill


class ChatResponse(BaseModel):
    """AI 채팅 응답"""

    answer: str
    sources: list[SourceReference] = Field(default_factory=list)
    session_id: str
    # False = 소유자를 알 수 없어(손님 표식 없음) 이력에 저장하지 않았다 → 후속 질문 맥락이 이어지지 않는다
    saved: bool = True


class SummaryRequest(BaseModel):
    """회의 요약 요청"""

    meeting_id: str


class SummaryResponse(BaseModel):
    """회의 요약 응답"""

    summary_text: str
    key_points: list[str] = Field(default_factory=list)
    agenda_items: list[str] = Field(default_factory=list)


class ConversationItem(BaseModel):
    """대화 이력 항목"""

    id: str
    session_id: str
    role: str
    content: str
    sources: Optional[list[dict]] = None
    meeting_context_id: Optional[str] = None
    created_at: str


class ConversationSession(BaseModel):
    """대화 세션 요약"""

    session_id: str
    first_question: str
    message_count: int
    meeting_context_id: Optional[str] = None
    meeting_title: Optional[str] = None
    created_at: str
    last_active_at: str
