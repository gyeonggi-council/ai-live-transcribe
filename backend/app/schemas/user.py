"""사용자 인증 관련 Pydantic 스키마

# @TASK P11A-R1-T2 - 사용자 인증 스키마
# @SPEC docs/planning/02-trd.md#인증-API
"""

from typing import Optional

from pydantic import BaseModel, Field


class UserLogin(BaseModel):
    """로그인 요청"""

    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1)


class UserCreate(BaseModel):
    """사용자 생성 요청"""

    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6)
    display_name: str = Field(..., min_length=1, max_length=100)
    role: str = Field(
        default="staff",
        pattern=r"^(anonymous|staff|committee_staff|meeting_manager|stenographer|admin)$",
    )
    assigned_committee: Optional[str] = None


class UserUpdate(BaseModel):
    """사용자 수정 요청"""

    display_name: Optional[str] = Field(None, min_length=1, max_length=100)
    role: Optional[str] = Field(
        None,
        pattern=r"^(anonymous|staff|committee_staff|meeting_manager|stenographer|admin)$",
    )
    assigned_committee: Optional[str] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    """사용자 응답"""

    id: str
    username: str
    display_name: str
    role: str
    assigned_committee: Optional[str] = None
    is_active: bool


class TokenResponse(BaseModel):
    """JWT 토큰 응답"""

    access_token: str
    token_type: str = "bearer"
    user: UserResponse
