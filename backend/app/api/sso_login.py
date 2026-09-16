"""SSO 교환 라우트 — 플랫폼 통합 로그인(ggc-sso) 쿠키를 이 서비스 JWT 로 바꾼다.

계약: ggc_sso/docs/integrate.md §4-③ (소비 서비스 배선 패턴)
- 브라우저가 `__Host-ggc_sso` 쿠키를 갖고 `GET /api/auth/sso` 를 부르면
  클러스터 내부 Service(ggc-sso-internal:8081)에 introspection 해 usercode 를 얻고,
  **QR 폴링 성공 분기(qr_login.poll_qr_session)와 같은 계정 매칭·자동 생성**을 거쳐
  QR authenticated 응답과 같은 JSON({status, access_token, token_type, user})을 돌려준다.
- 이 라우트는 **공개**다. 이 서비스는 라우트별 Depends(B형) 방식이라
  인증 Depends 를 걸지 않으면 그대로 공개 경로가 된다(별도 등록 없음).
- `GGC_SSO_INTERNAL_URL` 이 비면 introspect 가 항상 None → 401 (SSO 꺼짐,
  `GGC_LOGIN_BASE_URL` 관례와 같다).
- unregistered(403)는 QR 폴링과 같은 의미다 — 관리자가 비활성화한 계정
  (미등록 신규 사용자는 QR 성공 분기와 동일하게 **자동 생성**한다. 2026-08-22 사용자 결정).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from supabase import Client

from app import sso_client
from app.api.auth import _user_to_response
from app.api.qr_login import _client_ip, _create_user, _rate_allow
from app.core.database import get_supabase
from app.services.auth_service import create_access_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

#: 미인증 시 안내할 중앙 로그인 URL. next 는 이 서비스 로그인 화면 —
#: 돌아오면 로그인 페이지가 마운트 시 자동 교환(fetch /api/auth/sso)을 다시 시도한다.
_LOGIN_NEXT = "/transcribe/login"


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "detail": "SSO 세션이 없습니다",
            "login": sso_client.login_url(_LOGIN_NEXT),
        },
    )


@router.get("/sso")
async def sso_exchange(
    request: Request,
    supabase: Client = Depends(get_supabase),
):
    """SSO 쿠키 → 이 서비스 JWT 교환.

    응답:
      200 {status:"authenticated", access_token, token_type, user}  — QR 폴링과 같은 형태
      401 {detail, login}   — SSO 세션 없음/무효 (login = /sso/login?next=…)
      403 {detail:"unregistered", usercode}  — 관리자가 비활성화한 계정
    """
    if not _rate_allow(f"sso:{_client_ip(request)}", limit=60, window_sec=300):
        return JSONResponse(status_code=429, content={"detail": "요청이 너무 많습니다"})

    sid = request.cookies.get(sso_client.SSO_COOKIE)
    # introspect 는 동기(urllib) 호출 — 이벤트 루프를 막지 않게 스레드로 보낸다.
    sess = await asyncio.to_thread(sso_client.introspect, sid) if sid else None
    if not sess:
        return _unauthorized()

    # 격리 키는 언제나 usercode — user_name 으로 계정을 찾지 않는다(동명이인, integrate.md §5).
    usercode = str(sess.get("usercode") or "").strip()
    if not usercode:
        return _unauthorized()

    result = supabase.table("users").select("*").eq("username", usercode).execute()
    user = result.data[0] if result.data else None

    if user and not user.get("is_active", True):
        return JSONResponse(
            status_code=403, content={"detail": "unregistered", "usercode": usercode}
        )

    if user is None:
        # QR 성공 분기와 같은 자동 생성. SSO introspection 은 포털 프로필(부서·직급 등)을
        # 주지 않으므로 이름만 채운다 — 다음 QR 로그인 때 상류 정본으로 갱신된다.
        display_name = str(sess.get("user_name") or "").strip()[:100] or None
        user = _create_user(supabase, usercode, {"display_name": display_name})
        if user is None:
            return JSONResponse(
                status_code=403, content={"detail": "unregistered", "usercode": usercode}
            )
    else:
        # SSO 세션은 프로필 정본이 아니다 — last_login_at 만 갱신(best-effort).
        try:
            supabase.table("users").update(
                {"last_login_at": datetime.now(timezone.utc).isoformat()}
            ).eq("id", user["id"]).execute()
        except Exception:
            logger.warning("SSO 로그인 last_login_at 갱신 실패 (무시)")

    token = create_access_token({"sub": user["id"], "role": user["role"]})
    return {
        "status": "authenticated",
        "access_token": token,
        "token_type": "bearer",
        "user": _user_to_response(user),
    }
