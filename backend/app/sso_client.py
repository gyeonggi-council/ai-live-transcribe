"""ggc-sso 소비 서비스용 클라이언트 (FastAPI/Flask 등 파이썬 서비스가 **복사해** 쓴다).

정본: ggc_sso/clients/sso_client.py — 바꿀 일이 있으면 여기를 고치고 각 서비스에 다시 복사한다.
계약: ggc_sso/docs/integrate.md

환경변수(매니페스트 env 로 넣는다):
  GGC_SSO_INTERNAL_URL  http://ggc-sso-internal.ggc-poc.svc.cluster.local:8081   (비면 SSO 꺼짐)
  GGC_SSO_COOKIE        __Host-ggc_sso                                            (기본값 그대로)
  GGC_SSO_PUBLIC_PATH   /sso                                                      (로그인·로그아웃 화면 경로)

이 모듈은 **비밀을 갖지 않는다.** 신뢰 경계는 클러스터 내부 Service 다(integrate.md §1).
의존성 추가 없음 — httpx 가 없으면 urllib 로 떨어진다.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

SSO_INTERNAL_URL = os.environ.get("GGC_SSO_INTERNAL_URL", "").rstrip("/")
SSO_COOKIE = os.environ.get("GGC_SSO_COOKIE", "__Host-ggc_sso")
SSO_PUBLIC_PATH = os.environ.get("GGC_SSO_PUBLIC_PATH", "/sso").rstrip("/")
_TIMEOUT = 4


def enabled() -> bool:
    """GGC_SSO_INTERNAL_URL 이 비면 SSO 를 전부 건너뛴다 — GGC_LOGIN_BASE_URL 관례와 같다."""
    return bool(SSO_INTERNAL_URL)


def _call(method: str, path: str, body: dict | None = None, bearer: str | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{SSO_INTERNAL_URL}{path}", data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if bearer:
        req.add_header("Authorization", f"Bearer {bearer}")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:  # noqa: S310 — 클러스터 내부 고정 URL
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except Exception:  # noqa: BLE001
            return e.code, {}
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, {}     # SSO 서비스 불가 — 호출자는 "세션 없음"으로 다룬다(로컬 로그인은 계속 된다)


def introspect(sid: str | None) -> dict | None:
    """유효한 SSO 세션이면 {usercode, user_name, source, issued_at, expires_at}, 아니면 None."""
    if not enabled() or not sid or len(sid) > 128:
        return None
    code, body = _call("GET", "/internal/session", bearer=sid)
    return body if code == 200 and body.get("usercode") else None


def mint(usercode: str, user_name: str | None, source: str) -> dict | None:
    """로컬 QR 로그인 성공 직후 SSO 세션을 함께 만든다.
    반환 {sid, expires_at, cookie:{name,max_age,path,secure,httponly,samesite}} — 실패·비활성이면 None."""
    if not enabled() or not usercode:
        return None
    code, body = _call("POST", "/internal/session",
                       {"usercode": usercode, "user_name": user_name, "source": source})
    return body if code == 201 and body.get("sid") else None


def revoke(sid: str | None) -> bool:
    if not enabled() or not sid:
        return False
    code, body = _call("POST", "/internal/revoke", {"sid": sid})
    return code == 200 and bool(body.get("revoked"))


def set_cookie_from_mint(response, minted: dict) -> None:
    """mint() 응답의 cookie 속성을 **그대로** 써서 SSO 쿠키를 심는다(Starlette/FastAPI Response).
    속성이 하나라도 다르면 브라우저가 다른 쿠키로 취급해 로그아웃이 안 지워진다."""
    c = minted["cookie"]
    response.set_cookie(c["name"], minted["sid"], max_age=c["max_age"], path=c["path"],
                        secure=c["secure"], httponly=c["httponly"], samesite=c["samesite"])


def safe_next(value: str | None, default: str) -> str:
    """같은 오리진 절대 경로만. //evil · https:// · 개행 · 로그인 화면 자기 자신은 기본값으로."""
    if not value or not isinstance(value, str) or len(value) > 2048:
        return default
    if not value.startswith("/") or value.startswith("//") or value.startswith("/\\"):
        return default
    if any(ch in value for ch in ("\r", "\n", "\x00")):
        return default
    bare = value.split("?", 1)[0].rstrip("/")
    if bare in (SSO_PUBLIC_PATH, f"{SSO_PUBLIC_PATH}/login", f"{SSO_PUBLIC_PATH}/logout"):
        return default
    return value


def login_url(next_path: str) -> str:
    """중앙 로그인 화면 URL. next 는 보통 이 서비스의 교환 엔드포인트(…/api/auth/sso?next=원래경로)."""
    from urllib.parse import quote
    return f"{SSO_PUBLIC_PATH}/login?next={quote(next_path, safe='')}"


def logout_url(next_path: str) -> str:
    from urllib.parse import quote
    return f"{SSO_PUBLIC_PATH}/logout?next={quote(next_path, safe='')}"
