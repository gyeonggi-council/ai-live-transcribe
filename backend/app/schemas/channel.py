"""채널 관리 스키마 (2026-09-16)"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

# meetings.channel_id 가 VARCHAR(20) 이다. 넘치면 회의 생성이 실패하고,
# 그 예외 경로가 자막을 존재하지 않는 회의에 붙인다.
ID_PATTERN = r"^[A-Za-z0-9_-]{1,20}$"
PROVIDERS = ("ggc", "probe", "manual", "schedule", "none")


class ChannelBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    code: Optional[str] = Field(default=None, max_length=40)
    stream_url: str = Field(default="", max_length=2000)
    committee: Optional[str] = Field(default=None, max_length=100)
    page_url: Optional[str] = Field(default=None, max_length=2000)
    status_provider: str = "probe"
    provider_config: dict[str, Any] = Field(default_factory=dict)
    sort_order: int = 1000
    is_active: bool = True
    is_test: bool = False

    @field_validator("status_provider")
    @classmethod
    def _known_provider(cls, v: str) -> str:
        if v not in PROVIDERS:
            raise ValueError(f"status_provider 는 {PROVIDERS} 중 하나여야 합니다")
        return v


class ChannelCreate(ChannelBase):
    id: str = Field(pattern=ID_PATTERN)


class ChannelUpdate(BaseModel):
    """부분 수정. `id` 는 바꿀 수 없다 — 지난 회의·WS 룸 키·오버라이드가 전부 어긋난다."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    code: Optional[str] = Field(default=None, max_length=40)
    stream_url: Optional[str] = Field(default=None, max_length=2000)
    committee: Optional[str] = Field(default=None, max_length=100)
    page_url: Optional[str] = Field(default=None, max_length=2000)
    status_provider: Optional[str] = None
    provider_config: Optional[dict[str, Any]] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    is_test: Optional[bool] = None

    @field_validator("status_provider")
    @classmethod
    def _known_provider(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in PROVIDERS:
            raise ValueError(f"status_provider 는 {PROVIDERS} 중 하나여야 합니다")
        return v


class ChannelBulkCreate(BaseModel):
    items: list[ChannelCreate]


class DiscoverRequest(BaseModel):
    page_url: str = Field(min_length=8, max_length=2000)


class ManualStatusRequest(BaseModel):
    livestatus: int = Field(ge=0, le=4)
    # 자동 만료. 끄는 것을 잊으면 STT 가 밤새 돌아 비용이 샌다.
    minutes: int = Field(default=240, ge=1, le=1440)
