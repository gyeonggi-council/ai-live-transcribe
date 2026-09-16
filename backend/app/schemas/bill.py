"""
의안(Bill) 관련 Pydantic 스키마

@TASK P5-T4.1 - bills 테이블 마이그레이션
@SPEC docs/planning/
"""
from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class BillCreate(BaseModel):
    """의안 생성 요청 스키마"""
    bill_number: str = Field(..., max_length=50, description="의안번호 (예: 제2026-123호)")
    title: str = Field(..., max_length=500, description="의안명")
    proposer: Optional[str] = Field(None, max_length=200, description="제안자")
    committee: Optional[str] = Field(None, max_length=200, description="소관 위원회")
    status: str = Field("received", description="상태 (received/reviewing/decided/promulgated)")
    proposed_date: Optional[date] = Field(None, description="제안일")


class BillUpdate(BaseModel):
    """의안 수정 요청 스키마"""
    bill_number: Optional[str] = Field(None, max_length=50, description="의안번호")
    title: Optional[str] = Field(None, max_length=500, description="의안명")
    proposer: Optional[str] = Field(None, max_length=200, description="제안자")
    committee: Optional[str] = Field(None, max_length=200, description="소관 위원회")
    status: Optional[str] = Field(None, description="상태")
    proposed_date: Optional[date] = Field(None, description="제안일")


class BillResponse(BaseModel):
    """의안 응답 스키마"""
    id: UUID = Field(..., description="의안 ID")
    bill_number: str = Field(..., description="의안번호")
    title: str = Field(..., description="의안명")
    proposer: Optional[str] = Field(None, description="제안자")
    committee: Optional[str] = Field(None, description="소관 위원회")
    status: str = Field(..., description="상태")
    proposed_date: Optional[date] = Field(None, description="제안일")
    created_at: datetime = Field(..., description="생성 시각")
    updated_at: datetime = Field(..., description="수정 시각")

    model_config = {"from_attributes": True}


class BillMentionCreate(BaseModel):
    """의안-회의 연결 생성 요청 스키마"""
    bill_id: UUID = Field(..., description="의안 ID")
    meeting_id: UUID = Field(..., description="회의 ID")
    subtitle_id: Optional[UUID] = Field(None, description="자막 ID")
    start_time: Optional[float] = Field(None, description="시작 시간 (초)")
    end_time: Optional[float] = Field(None, description="종료 시간 (초)")
    note: Optional[str] = Field(None, description="메모")


class BillMentionUpdate(BaseModel):
    """의안-회의 연결 수정 요청 스키마"""
    subtitle_id: Optional[UUID] = Field(None, description="자막 ID")
    start_time: Optional[float] = Field(None, description="시작 시간 (초)")
    end_time: Optional[float] = Field(None, description="종료 시간 (초)")
    note: Optional[str] = Field(None, description="메모")


class BillMentionResponse(BaseModel):
    """의안-회의 연결 응답 스키마"""
    id: UUID = Field(..., description="의안-회의 연결 ID")
    bill_id: UUID = Field(..., description="의안 ID")
    meeting_id: UUID = Field(..., description="회의 ID")
    subtitle_id: Optional[UUID] = Field(None, description="자막 ID")
    start_time: Optional[float] = Field(None, description="시작 시간 (초)")
    end_time: Optional[float] = Field(None, description="종료 시간 (초)")
    note: Optional[str] = Field(None, description="메모")
    created_at: datetime = Field(..., description="생성 시각")

    model_config = {"from_attributes": True}


class BillWithMentions(BillResponse):
    """의안 및 연결된 회의 정보를 포함한 응답 스키마"""
    mentions: list[BillMentionResponse] = Field(default_factory=list, description="해당 의안의 회의 언급")
