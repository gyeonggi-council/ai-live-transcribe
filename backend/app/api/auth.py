"""Auth API 라우터 - 관리자 PIN 로그인/로그아웃/현재 사용자 조회

# @TASK P11A-R1-T4 - 인증 API
# @SPEC docs/planning/02-trd.md#인증-API
"""

import hmac
import logging
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from supabase import Client

from app.core.config import settings
from app.core.council_network import client_ip, is_council_ip, is_login_required_ip
from app.core.database import get_supabase
from app.schemas.user import TokenResponse, UserResponse
from app.services.auth_service import (
    create_access_token,
    verify_token,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

security = HTTPBearer(auto_error=False)


def _user_to_response(user: dict) -> UserResponse:
    """DB 사용자 dict를 응답 모델로 변환합니다."""
    return UserResponse(
        id=user["id"],
        username=user["username"],
        display_name=user["display_name"],
        role=user["role"],
        assigned_committee=user.get("assigned_committee"),
        is_active=user["is_active"],
    )


# 아이디·비밀번호 로그인(`POST /api/auth/login`)은 2026-08-28 에 없앴다.
# 이 서비스로 들어오는 길은 두 가지뿐이다 — 모바일 의정지원서비스 앱 QR(`/api/auth/qr/*`)과
# 플랫폼 통합 로그인 교환(`/api/auth/sso`). 화면(`/login`)·클라이언트(`lib/auth.login`)·
# 계정 5개가 평문으로 적혀 있던 `/admin/dev-login` 페이지를 같은 날 함께 걷어냈다.
# users.password_hash 컬럼은 028 마이그레이션에서 이미 NULL 허용이라 스키마는 건드리지 않았다.
#
# 아래 PIN 로그인은 **로그인이 아니라 관리 기능 앞의 별도 관문**이다(AdminPinModal).
# 같이 지우면 관리자 도구가 열리지 않으므로 남긴다.

class PinLoginRequest(BaseModel):
    """빠른 관리자 PIN 로그인 요청"""
    pin: str = Field(..., min_length=4, max_length=12, description="4-12자리 관리자 PIN")


# PIN 무차별 대입 차단 (2026-09-12) — 4자리 PIN 이 admin 과 같은 힘이라 1만 번이면 뚫린다.
# 같은 IP 가 _PIN_WINDOW 초 안에 _PIN_MAX_FAILS 번 틀리면 그 창이 지날 때까지 429. 파드 메모리라 재시작하면 초기화된다.
_PIN_MAX_FAILS = 5
_PIN_WINDOW = 600.0
_pin_fails: dict[str, deque] = defaultdict(deque)


@router.post("/pin-login", response_model=TokenResponse)
async def pin_login(body: PinLoginRequest, request: Request) -> TokenResponse:
    """빠른 관리자 PIN 로그인.

    정식 사용자 계정 없이 `settings.admin_quick_pin`과 일치하는 PIN 입력 시
    admin 권한의 임시 JWT를 발급한다. AI 교정 등 admin 전용 기능을
    운영자가 즉시 사용할 수 있도록 하기 위함.

    보안 주의: PIN이 admin 마스터 권한과 동등한 효력을 가지므로 신중 관리 필요.
    """
    if not settings.admin_quick_pin:
        # 비어 있으면 PIN 로그인 자체를 끈다(기본값에 PIN 을 두지 않는다)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="PIN 로그인이 꺼져 있습니다.")
    ip = client_ip(request) or "unknown"
    now = time.monotonic()
    fails = _pin_fails[ip]
    while fails and now - fails[0] > _PIN_WINDOW:
        fails.popleft()
    if len(fails) >= _PIN_MAX_FAILS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="PIN 을 여러 번 틀려 잠시 막았습니다. 10분 뒤 다시 시도하세요.",
        )
    if not hmac.compare_digest(body.pin.encode(), settings.admin_quick_pin.encode()):
        fails.append(now)
        logger.warning("PIN 로그인 실패 ip=%s (%d/%d)", ip, len(fails), _PIN_MAX_FAILS)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="PIN이 일치하지 않습니다.",
        )
    fails.clear()

    token = create_access_token({"sub": "quick-admin", "role": "admin"})
    return TokenResponse(
        access_token=token,
        user=UserResponse(
            id="quick-admin",
            username="quick-admin",
            display_name="빠른 관리자",
            role="admin",
            assigned_committee=None,
            is_active=True,
        ),
    )


@router.get("/network")
async def get_network(request: Request) -> dict:
    """이 브라우저가 의회망에서 왔는가 — 로그인 없이 발언영상·AI 를 열지 화면이 정한다 (2026-09-11).

    공개. 판정은 여기서만 한다(프런트는 IP 를 모른다). ip 는 요청한 사람 자신의 주소라 돌려줘도 된다 —
    "의회망인데 안 열린다" 문의 때 담당자가 이 값과 ACG·대역을 대조한다.
    """
    ip = client_ip(request)
    return {
        "council_network": is_council_ip(ip),
        "ip": ip,
        # 이 대역(의회사무처 직원 PC)에서 로그인 없이 들어오면 화면이 앱 로그인 안내를 띄운다(2026-09-16).
        # 예전에는 Traefik 이 아예 막았다 — 막는 대신 안내로 바꾼 것이다.
        "login_required": is_login_required_ip(ip),
        "app_install_guide_url": settings.app_install_guide_url,
    }


@router.get("/me", response_model=UserResponse)
async def get_me(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    supabase: Client = Depends(get_supabase),
) -> UserResponse:
    """현재 인증된 사용자 정보를 반환합니다."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증이 필요합니다.",
        )

    payload = verify_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 토큰입니다.",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="토큰에 사용자 정보가 없습니다.",
        )

    # PIN 로그인 quick-admin 토큰은 users 테이블에 레코드가 없음 —
    # 비UUID id 조회가 500을 내며 프론트가 토큰을 폐기(새로고침 시 로그인 풀림)하던 버그.
    if user_id == "quick-admin":
        return _user_to_response({
            "id": "quick-admin",
            "username": "quick-admin",
            "display_name": "빠른 관리자",
            "role": payload.get("role", "admin"),
            "assigned_committee": None,
            "is_active": True,
        })

    # Supabase에서 사용자 조회
    result = (
        supabase.table("users")
        .select("*")
        .eq("id", user_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="사용자를 찾을 수 없습니다.",
        )

    return _user_to_response(result.data[0])
