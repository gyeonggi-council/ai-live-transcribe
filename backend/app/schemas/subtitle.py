"""Subtitle Pydantic 스키마"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SubtitleBase(BaseModel):
    """자막 기본 스키마"""

    start_time: float = Field(..., ge=0, description="시작 시간 (초)")
    end_time: float = Field(..., ge=0, description="종료 시간 (초)")
    text: str = Field(..., min_length=1, description="자막 텍스트")
    speaker: Optional[str] = Field(None, max_length=100, description="화자")
    confidence: Optional[float] = Field(None, ge=0, le=1, description="인식 신뢰도 (0~1)")


class SubtitleCreate(SubtitleBase):
    """자막 생성 스키마"""

    meeting_id: uuid.UUID = Field(..., description="회의 ID")


class SubtitleResponse(SubtitleBase):
    """자막 응답 스키마"""

    id: uuid.UUID = Field(..., description="자막 ID")
    meeting_id: uuid.UUID = Field(..., description="회의 ID")
    created_at: datetime = Field(..., description="생성 시각")

    model_config = ConfigDict(from_attributes=True)


class SubtitleListResponse(BaseModel):
    """자막 목록 응답 스키마"""

    items: list[SubtitleResponse] = Field(default_factory=list, description="자막 목록")
    total: int = Field(..., ge=0, description="전체 자막 수")
    limit: int = Field(..., ge=1, description="페이지 크기")
    offset: int = Field(..., ge=0, description="오프셋")


class SubtitleSearchQuery(BaseModel):
    """자막 검색 쿼리 스키마"""

    q: str = Field(..., min_length=1, description="검색어")

    @field_validator("q")
    @classmethod
    def validate_query(cls, v: str) -> str:
        """검색어 검증"""
        stripped = v.strip()
        if not stripped:
            raise ValueError("검색어는 비어있을 수 없습니다")
        return stripped


# @TASK P5-T2.1 - 자막 수정 스키마
# @SPEC docs/planning/02-trd.md#자막-수정-API


class SubtitleUpdate(BaseModel):
    """자막 단건 수정 스키마"""

    text: Optional[str] = Field(None, min_length=1, description="자막 텍스트")
    speaker: Optional[str] = Field(None, max_length=100, description="화자")
    start_time: Optional[float] = Field(None, ge=0, description="시작 시간 (초)")
    end_time: Optional[float] = Field(None, ge=0, description="종료 시간 (초)")


class SubtitleBatchItem(BaseModel):
    """자막 배치 수정 개별 항목 스키마"""

    id: str = Field(..., description="자막 ID")
    text: Optional[str] = Field(None, min_length=1, description="자막 텍스트")
    speaker: Optional[str] = Field(None, max_length=100, description="화자")
    start_time: Optional[float] = Field(None, ge=0, description="시작 시간 (초)")
    end_time: Optional[float] = Field(None, ge=0, description="종료 시간 (초)")


class SubtitleBatchUpdate(BaseModel):
    """자막 배치 수정 스키마"""

    items: list[SubtitleBatchItem] = Field(
        ..., min_length=1, description="수정할 자막 항목 목록"
    )


class SubtitleSplitRequest(BaseModel):
    """자막 분할 요청 스키마"""

    position: int = Field(..., ge=0, description="텍스트 분할 위치 (문자 인덱스)")
    split_time: Optional[float] = Field(None, ge=0, description="분할 시점 (초)")


class SubtitleMergeSelectedRequest(BaseModel):
    """자막 선택 병합 요청 스키마"""

    subtitle_ids: list[str] = Field(..., min_length=2, description="병합할 자막 ID 목록")
