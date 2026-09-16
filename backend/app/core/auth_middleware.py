"""인증/인가 미들웨어 - JWT 기반 역할 제어

# @TASK P11A-R2-T1 - 역할 기반 인가 미들웨어
# @SPEC docs/planning/02-trd.md#인증-API

사용법:
    # 특정 역할만 허용
    @router.post("/admin-action")
    async def admin_action(user=Depends(require_role("admin"))):
        ...

    # 여러 역할 허용
    @router.patch("/edit")
    async def edit(user=Depends(require_role("meeting_manager", "admin"))):
        ...

    # 비로그인도 허용 (user=None 가능)
    @router.get("/public")
    async def public(user=Depends(optional_auth)):
        ...
"""

import logging
import re
from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import Client

from app.core.council_network import is_council
from app.core.database import get_supabase
from app.services.auth_service import verify_token

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    supabase: Client = Depends(get_supabase),
) -> dict | None:
    """JWT 토큰에서 현재 사용자를 추출합니다.

    토큰이 없거나 유효하지 않으면 None을 반환합니다.
    인증이 필수인 엔드포인트에서는 require_role()을 사용하세요.

    Returns:
        사용자 dict 또는 None
    """
    if not credentials:
        return None

    payload = verify_token(credentials.credentials)
    if not payload:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    # PIN 로그인(/api/auth/pin-login)으로 발급된 quick-admin 토큰은
    # users 테이블에 대응 레코드가 없으므로 JWT payload에서 역할을 직접 구성.
    if user_id == "quick-admin":
        return {
            "id": "quick-admin",
            "username": "quick-admin",
            "display_name": "빠른 관리자",
            "role": payload.get("role", "admin"),
            "assigned_committee": None,
            "is_active": True,
        }

    # Supabase에서 사용자 조회
    try:
        result = (
            supabase.table("users")
            .select("*")
            .eq("id", user_id)
            .execute()
        )
        if result.data:
            return result.data[0]
    except Exception:
        logger.warning("사용자 조회 실패 (user_id=%s)", user_id)

    return None


def require_role(*roles: str) -> Callable:
    """역할 기반 인가 의존성 팩토리.

    지정된 역할 중 하나라도 가진 사용자만 접근을 허용합니다.

    Args:
        *roles: 허용할 역할 목록 (예: "admin", "meeting_manager")

    Returns:
        FastAPI Depends에서 사용할 의존성 함수

    Raises:
        HTTPException 401: 인증 안 됨
        HTTPException 403: 권한 부족
    """
    async def dependency(
        user: dict | None = Depends(get_current_user),
    ) -> dict:
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="인증이 필요합니다.",
            )
        if user["role"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="권한이 부족합니다.",
            )
        return user

    return dependency


# AI 어시스턴트를 쓰는 로그인 역할 — staff 가 빠져 있으면 QR 로 들어온 의원(portal_role: ROLE_COUNCILOR→staff)이 막힌다(2026-09-14).
# 비로그인 의회망 손님은 require_role_or_council 이 따로 들인다. 프런트 정본은 lib/auth.ts 의 AI_ROLES — 함께 고친다.
AI_ROLES = ("staff", "committee_staff", "meeting_manager", "stenographer", "admin")

COUNCIL_GUEST_ROLE = "council_guest"
_GUEST_ID_RE = re.compile(r"^[0-9a-fA-F-]{8,40}$")


def council_guest(request: Request) -> dict:
    """의회망 비로그인 방문자 — 브라우저마다 X-Guest-Id(무작위 UUID)로 추출 기록을 가른다.

    NAT 뒤라 IP 로는 사람을 못 가른다(한 IP 를 건물 전체가 쓴다). 헤더가 없거나 형식이 틀리면 공용 칸.
    owner_username 은 VARCHAR(50) — 'guest:' + 40자 이내.
    """
    gid = (request.headers.get("x-guest-id") or "").strip()
    if not _GUEST_ID_RE.match(gid):
        gid = "shared"
    return {
        "id": None,
        "username": f"guest:{gid.lower()}",
        "display_name": "의회망 이용자",
        "role": COUNCIL_GUEST_ROLE,
        "assigned_committee": None,
        "is_active": True,
    }


def require_role_or_council(*roles: str) -> Callable:
    """require_role 과 같되, 로그인하지 않은 **의회망** 방문자는 손님으로 들인다 (2026-09-11 담당자 요청).

    로그인한 사람은 역할 판정을 그대로 받는다 — 역할이 모자란 로그인 사용자를 손님으로 올려 주지 않는다.
    """
    async def dependency(
        request: Request,
        user: dict | None = Depends(get_current_user),
    ) -> dict:
        if user is None:
            if is_council(request):
                return council_guest(request)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="인증이 필요합니다.",
            )
        if user["role"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="권한이 부족합니다.",
            )
        return user

    return dependency


async def optional_auth(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    supabase: Client = Depends(get_supabase),
) -> dict | None:
    """비로그인도 허용하는 인증 의존성.

    유효한 토큰이 있으면 사용자 정보를, 없으면 None을 반환합니다.
    401/403을 절대 발생시키지 않습니다.
    """
    if not credentials:
        return None

    payload = verify_token(credentials.credentials)
    if not payload:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    # PIN 로그인 quick-admin 토큰은 users 테이블에 레코드가 없음 —
    # get_current_user와 동일하게 payload에서 직접 구성 (누락 시 PIN 사용자가
    # optional_auth+401 가드 방식 API(kordoc 미리보기 등)에서 익명 취급되는 버그).
    if user_id == "quick-admin":
        return {
            "id": "quick-admin",
            "username": "quick-admin",
            "display_name": "빠른 관리자",
            "role": payload.get("role", "admin"),
            "assigned_committee": None,
            "is_active": True,
        }

    try:
        result = (
            supabase.table("users")
            .select("*")
            .eq("id", user_id)
            .execute()
        )
        if result.data:
            return result.data[0]
    except Exception:
        logger.warning("optional_auth 사용자 조회 실패")

    return None


def ai_owner_key(request: Request, user: dict | None) -> str | None:
    """AI 대화 이력의 소유자 키 — 서버가 검증한 주체에서만 만든다(2026-09-14, migration 033).

    로그인 → user:<users.id>(PIN 관리자 quick-admin 은 users 행이 없어 admin:pin) ·
    비로그인 → 유효한 X-Guest-Id 가 있을 때만 guest:<id>. 표식이 없거나 형식이 틀리면 None —
    council_guest() 의 'shared' 폴백을 여기서는 쓰지 않는다(공용 이력이 되살아난다). None 이면 저장도 이력도 없다.
    """
    if user and user.get("role") != COUNCIL_GUEST_ROLE:
        uid = user.get("id")
        if uid == "quick-admin":
            return "admin:pin"
        return f"user:{uid}" if uid else None
    gid = (request.headers.get("x-guest-id") or "").strip()
    if not _GUEST_ID_RE.match(gid) or gid.lower() == "shared":
        return None
    return f"guest:{gid.lower()}"
