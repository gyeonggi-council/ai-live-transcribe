"""Meeting Pydantic 스키마"""

from datetime import date, datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class MeetingStatus(str, Enum):
    """회의 상태 enum"""

    SCHEDULED = "scheduled"
    LIVE = "live"
    PROCESSING = "processing"
    ENDED = "ended"


class TranscriptStatus(str, Enum):
    """회의록 상태 enum"""

    DRAFT = "draft"
    REVIEWING = "reviewing"
    FINAL = "final"


class SubtitleStage(str, Enum):
    """자막 워크플로우 단계 enum (migration 017).

    none → draft(라이브) → ai(OpenAI 배치 재생성) → reviewing(속기사) → final
    """

    NONE = "none"
    DRAFT = "draft"
    AI = "ai"
    REVIEWING = "reviewing"
    FINAL = "final"


class MeetingBase(BaseModel):
    """회의 기본 스키마"""

    title: str = Field(..., max_length=255, description="회의 제목")
    meeting_date: date = Field(..., description="회의 날짜")
    stream_url: Optional[str] = Field(None, description="실시간 스트림 URL")
    vod_url: Optional[str] = Field(None, description="VOD URL")
    status: MeetingStatus = Field(
        default=MeetingStatus.SCHEDULED, description="회의 상태"
    )
    duration_seconds: Optional[int] = Field(None, description="총 재생 시간 (초)")


class MeetingCreate(MeetingBase):
    """회의 생성 요청 스키마"""

    pass


class MeetingFromUrl(BaseModel):
    """URL만으로 VOD 등록 요청 스키마"""

    url: str = Field(..., description="KMS VOD URL 또는 MP4 URL")


class MeetingUpdate(BaseModel):
    """회의 수정 요청 스키마"""

    title: Optional[str] = Field(None, max_length=255, description="회의 제목")
    meeting_date: Optional[date] = Field(None, description="회의 날짜")
    stream_url: Optional[str] = Field(None, description="실시간 스트림 URL")
    vod_url: Optional[str] = Field(None, description="VOD URL")
    status: Optional[MeetingStatus] = Field(None, description="회의 상태")
    duration_seconds: Optional[int] = Field(None, description="총 재생 시간 (초)")
    meeting_type: Optional[str] = Field(None, max_length=50, description="회의 유형 (본회의, 상임위 등)")
    committee: Optional[str] = Field(None, max_length=200, description="소속 위원회")
    transcript_status: Optional[TranscriptStatus] = Field(None, description="회의록 상태 (draft/reviewing/final)")
    subtitle_stage: Optional[SubtitleStage] = Field(None, description="자막 워크플로우 단계 (none/draft/ai/reviewing/final)")


class MeetingResponse(MeetingBase):
    """회의 응답 스키마"""

    id: UUID = Field(..., description="고유 식별자")
    created_at: datetime = Field(..., description="생성 시각")
    updated_at: datetime = Field(..., description="수정 시각")

    model_config = {"from_attributes": True}


class MeetingListResponse(BaseModel):
    """회의 목록 응답 스키마"""

    items: list[MeetingResponse]
    total: int
    limit: int
    offset: int


# =============================================================================
# Participant (참석자) 스키마
# =============================================================================


class ParticipantCreate(BaseModel):
    """참석자 추가 요청"""

    councilor_id: str = Field(..., max_length=100, description="의원 ID")
    name: Optional[str] = Field(None, max_length=200, description="의원 이름")
    role: Optional[str] = Field(None, max_length=100, description="역할 (위원장, 위원 등)")


class ParticipantResponse(BaseModel):
    """참석자 응답"""

    id: str
    meeting_id: str
    councilor_id: str
    name: Optional[str] = None
    role: Optional[str] = None
    created_at: Optional[str] = None


# =============================================================================
# Agenda (안건) 스키마
# =============================================================================


class AgendaCreate(BaseModel):
    """안건 추가 요청"""

    order_num: int = Field(..., ge=1, description="안건 순서")
    title: str = Field(..., max_length=500, description="안건 제목")
    description: Optional[str] = Field(None, description="안건 설명")


class AgendaUpdate(BaseModel):
    """안건 수정 요청"""

    order_num: Optional[int] = Field(None, ge=1, description="안건 순서")
    title: Optional[str] = Field(None, max_length=500, description="안건 제목")
    description: Optional[str] = Field(None, description="안건 설명")


class AgendaResponse(BaseModel):
    """안건 응답"""

    id: str
    meeting_id: str
    order_num: int
    title: str
    description: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# =============================================================================
# Transcript Status (회의록 상태) 스키마
# =============================================================================


class TranscriptStatusUpdate(BaseModel):
    """회의록 상태 변경 요청"""

    transcript_status: TranscriptStatus = Field(..., description="변경할 상태")


class PublicationCreate(BaseModel):
    """확정/공개 이력 등록 요청"""

    status: TranscriptStatus = Field(..., description="상태")
    published_by: Optional[str] = Field(None, max_length=200, description="확정자")
    notes: Optional[str] = Field(None, description="비고")


class PublicationResponse(BaseModel):
    """확정/공개 이력 응답"""

    id: str
    meeting_id: str
    status: str
    published_by: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[str] = None
