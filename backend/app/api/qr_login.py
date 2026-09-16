"""QR 로그인 — 경기도의회 모바일 로그인 서비스 연동 (소비 서비스 측).

명세: {settings.ggc_login_base_url}/integrate.md (v1.0.0)
- 세션 생성·폴링은 이 백엔드가 서버-투-서버로 호출한다(브라우저 직접 호출은 CORS 차단).
- QR 세션은 5분 유효·1회용. 폴링이 authenticated 를 받는 순간 상류 세션은 소비된다.
- 상류 access_token 은 브라우저로 내보내지 않는다 — usercode 를 users.username 과
  매칭해 이 서비스의 JWT 만 발급하고, 상류 토큰은 즉시 폐기(logout)한다.
- 계정 매칭 규약: 경기도의정포털 usercode == 자막 서비스 username.
- **미등록이면 계정을 자동 생성해 바로 로그인시킨다** (2026-08-22 사용자 결정).
  예전에는 unregistered 로 돌려보내 관리자가 손으로 계정을 만들어야 했다.
  unregistered 는 이제 '관리자가 비활성화한 계정'에만 쓰인다.
- 상류 프로필(부서·직급·권한·포털 로그인 이력)은 매 로그인 갱신한다. 상류가 정본이다.
  ★단 이 서비스의 role 은 덮어쓰지 않는다 — 손으로 올려둔 권한이 되돌아가면 안 된다.
- ★DID/전자지갑 식별자(wallet_id·holder_did·wallet_created_at)는 저장하지 않는다.
  users 테이블에 그 컬럼이 아예 없다(migration 028 주석 참조).
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone

import asyncio

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from supabase import Client

from app import sso_client
from app.api.auth import _user_to_response
from app.core.config import settings
from app.core.database import get_supabase
from app.services.auth_service import create_access_token
from app.services.portal_role import map_portal_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth/qr", tags=["auth"])

_UPSTREAM_TIMEOUT = 10.0


def _base_url() -> str:
    url = (settings.ggc_login_base_url or "").strip().rstrip("/")
    if not url:
        raise HTTPException(status_code=503, detail="QR 로그인이 구성되지 않았습니다")
    return url


# ── 레이트리밋 (인메모리 고정 윈도우, IP 기준) ──────────────────────────
# 의회망은 NAT 뒤라 한 IP 를 여러 사람이 공유한다 — 폴링(3초 × 5분 = 100회/QR)을
# 감안해 넉넉히 잡되 무한 난사는 막는다. 파드 1개 전제의 인메모리 카운터다.
_buckets: dict[str, tuple[int, float]] = {}


def _client_ip(request: Request) -> str:
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else "unknown"


def _rate_allow(key: str, limit: int, window_sec: float) -> bool:
    now = time.monotonic()
    if len(_buckets) > 10_000:
        for k in [k for k, (_, reset) in _buckets.items() if reset <= now]:
            _buckets.pop(k, None)
    count, reset = _buckets.get(key, (0, 0.0))
    if reset <= now:
        _buckets[key] = (1, now + window_sec)
        return True
    _buckets[key] = (count + 1, reset)
    return count + 1 <= limit


async def _revoke(token: str) -> None:
    """상류 토큰 즉시 폐기 — 우리는 상류 보호 API 를 쓰지 않으므로 남겨둘 이유가 없다.
    폐기 실패는 로그인 성공에 영향을 주지 않는다(best-effort)."""
    if not token:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{settings.ggc_login_base_url.rstrip('/')}/api/app/v1/logout",
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError:
        pass


_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _portal_profile(data: dict) -> dict:
    """상류 응답에서 **저장할 필드만** 골라낸다.

    ★이 함수에 없는 필드는 DB 로 가지 않는다. wallet_id·holder_did·wallet_created_at
      (DID/전자지갑)과 access_token·refresh_token 이 그렇다 — 의도적으로 뺐다.
      users 테이블에 해당 컬럼 자체가 없다(migration 028).
    """

    def _text(key: str, limit: int) -> str | None:
        v = str(data.get(key) or "").strip()
        return v[:limit] if v else None

    def _date(key: str) -> str | None:
        # 상류는 'YYYY-MM-DD' 문자열을 준다. 형태가 다르면 저장하지 않는다.
        v = str(data.get(key) or "").strip()[:10]
        return v if _DATE_RE.fullmatch(v) else None

    return {
        "display_name": _text("user_name", 100),
        "portal_role": _text("role", 50),
        "dept_name": _text("deptnm", 100),
        "group_name": _text("group_name", 100),
        "job_position": _text("jobpositionname", 50),
        "portal_last_login": _date("last_login"),
        "portal_app_last_login": _date("app_last_login"),
    }


def _create_user(supabase: Client, usercode: str, profile: dict) -> dict | None:
    """QR 인증된 미등록 사용자의 계정을 만든다 (권한은 포털 매핑값)."""
    role = map_portal_role(profile.get("portal_role"))
    now = datetime.now(timezone.utc).isoformat()
    row = {k: v for k, v in profile.items() if v is not None}
    row.update(
        {
            "username": usercode,
            # display_name 은 NOT NULL — 이름이 비면 usercode 로 채운다
            "display_name": profile.get("display_name") or usercode,
            "role": role,
            "is_active": True,
            "last_login_at": now,
            "profile_synced_at": now,
        }
    )
    try:
        result = supabase.table("users").insert(row).execute()
    except Exception as e:
        # 같은 순간 두 번 스캔하면 username unique 제약에 걸린다 — 진 쪽은 다시 읽는다.
        logger.warning("QR 자동 등록 insert 실패(%s) — 기존 계정 재조회", e)
        again = supabase.table("users").select("*").eq("username", usercode).execute()
        return again.data[0] if again.data else None

    logger.info("QR 자동 등록: usercode=%r role=%s", usercode, role)
    return result.data[0] if result.data else None


def _sync_profile(supabase: Client, user: dict, profile: dict) -> None:
    """상류 프로필을 갱신한다 (best-effort).

    ★이 서비스의 role 은 절대 건드리지 않는다 — 관리자가 손으로 올려둔 권한이
      다음 로그인에 staff 로 되돌아가면 안 된다. 포털 권한은 portal_role 에만 담는다.
    실패해도 로그인은 계속한다. 인증에 성공한 사용자를 막는 것이 더 나쁜 실패다.
    """
    now = datetime.now(timezone.utc).isoformat()
    updates = {k: v for k, v in profile.items() if v is not None}
    updates["last_login_at"] = now
    updates["profile_synced_at"] = now

    new_portal_role = profile.get("portal_role")
    old_portal_role = user.get("portal_role")
    if new_portal_role and old_portal_role and new_portal_role != old_portal_role:
        logger.info(
            "포털 권한 변경: %r → %r (이 서비스 권한 %r 은 유지)",
            old_portal_role,
            new_portal_role,
            user.get("role"),
        )

    try:
        supabase.table("users").update(updates).eq("id", user["id"]).execute()
        user.update(updates)
    except Exception as e:
        logger.warning("프로필 갱신 실패(무시하고 로그인 진행): %s", e)


async def _upstream_create_session() -> dict:
    """상류 QR 세션 생성. 테스트가 이 함수를 monkeypatch 한다."""
    async with httpx.AsyncClient(timeout=_UPSTREAM_TIMEOUT) as client:
        r = await client.post(f"{_base_url()}/api/v1/auth/qr/session")
        r.raise_for_status()
        return r.json()


async def _upstream_poll_session(session_id: str) -> dict:
    """상류 QR 세션 상태 조회. 테스트가 이 함수를 monkeypatch 한다."""
    async with httpx.AsyncClient(timeout=_UPSTREAM_TIMEOUT) as client:
        r = await client.get(f"{_base_url()}/api/v1/auth/qr/{session_id}")
        return r.json()


@router.post("/session")
async def create_qr_session(request: Request):
    """상류에 QR 세션 생성. 프론트는 응답의 sessionId·apiUrl 로 QR 을 렌더한다."""
    _base_url()  # 미구성이면 503
    if not _rate_allow(f"sess:{_client_ip(request)}", limit=30, window_sec=300):
        raise HTTPException(status_code=429, detail="QR 발급 시도가 너무 많습니다")
    try:
        data = await _upstream_create_session()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=502, detail="로그인 서버에 연결할 수 없습니다")
    if not data.get("sessionId"):
        raise HTTPException(status_code=502, detail="로그인 서버 응답이 올바르지 않습니다")
    return {
        "sessionId": data["sessionId"],
        "apiUrl": data.get("apiUrl", ""),
        "ttl": data.get("ttl") or 300,
    }


@router.get("/{session_id}")
async def poll_qr_session(
    session_id: str,
    request: Request,
    response: Response,
    supabase: Client = Depends(get_supabase),
):
    """상류 세션 상태 중계. authenticated 면 자막 서비스 JWT 를 발급한다.

    반환 status: pending | expired | unregistered | authenticated
    (unregistered: 인증은 됐지만 usercode 와 일치하는 계정이 없음 — 상류 세션은
    이미 1회용으로 소비됐으므로 프론트는 새 QR 을 발급해야 한다)
    """
    _base_url()  # 미구성이면 503
    if not _rate_allow(f"poll:{_client_ip(request)}", limit=600, window_sec=300):
        raise HTTPException(status_code=429, detail="요청이 너무 많습니다")
    try:
        data = await _upstream_poll_session(session_id)
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=502, detail="로그인 서버에 연결할 수 없습니다")

    status = data.get("status")
    if status == "pending":
        return {"status": "pending"}
    if status != "authenticated":
        return {"status": "expired"}

    # 실앱 스캔 진단용 — 상류가 준 식별 필드만 남긴다(토큰·자격증명은 절대 남기지 않는다).
    # 앱이 인증했는데 로그인이 안 되는 경우, 여기서 usercode 표기를 확인하면
    # "계정 미등록" 인지 "필드 계약 불일치" 인지 한 번에 갈린다.
    logger.info(
        "QR 인증 도달: usercode=%r user_name=%r 상류필드=%s",
        data.get("usercode"),
        data.get("user_name"),
        sorted(k for k in data if k not in ("access_token", "refresh_token")),
    )

    usercode = str(data.get("usercode") or "").strip()
    await _revoke(str(data.get("access_token") or ""))

    if not usercode:
        # 상류가 인증은 했는데 식별자를 안 줬다 — 계약 위반이라 계정을 만들 수 없다.
        logger.error("QR 인증 응답에 usercode 가 없다 — 로그인 불가")
        return {
            "status": "unregistered",
            "usercode": "",
            "user_name": data.get("user_name"),
            "detail": "로그인 서버가 사용자 코드를 주지 않았습니다. 관리자에게 문의하세요.",
        }

    result = supabase.table("users").select("*").eq("username", usercode).execute()
    user = result.data[0] if result.data else None

    if user and not user.get("is_active", True):
        # 자동 생성이 도입된 뒤로 unregistered 는 '관리자가 막은 계정' 전용이다.
        return {
            "status": "unregistered",
            "usercode": usercode,
            "user_name": data.get("user_name"),
            "detail": "관리자가 비활성화한 계정입니다. 담당자에게 문의하세요.",
        }

    profile = _portal_profile(data)

    if user is None:
        user = _create_user(supabase, usercode, profile)
        if user is None:
            return {
                "status": "error",
                "detail": "계정을 만들지 못했습니다. 잠시 후 다시 시도해 주세요.",
            }
    else:
        _sync_profile(supabase, user, profile)

    # 로컬 QR 로그인 성공 → SSO 세션을 함께 발급해 같은 응답에 쿠키로 심는다
    # (ggc_sso/docs/integrate.md §4-④). 실패·비활성이면 조용히 건너뛴다 — 로컬 로그인은 성공.
    # mint 는 동기(urllib) 호출이라 이벤트 루프를 막지 않게 스레드로 보낸다.
    minted = await asyncio.to_thread(
        sso_client.mint, usercode, user.get("display_name"), "transcribe"
    )
    if minted:
        sso_client.set_cookie_from_mint(response, minted)

    token = create_access_token({"sub": user["id"], "role": user["role"]})
    return {
        "status": "authenticated",
        "access_token": token,
        "token_type": "bearer",
        "user": _user_to_response(user),
    }
