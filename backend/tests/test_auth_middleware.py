"""Auth Middleware 테스트 (TDD RED -> GREEN)

# @TASK P11A-R2-T1 - 역할 기반 인가 미들웨어 테스트
# @TEST tests/test_auth_middleware.py
"""

import uuid
from typing import Generator

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.database import get_supabase
from app.core.auth_middleware import get_current_user, optional_auth, require_role
from app.services.auth_service import create_access_token, hash_password
from tests.test_auth_api import UserAwareMockClient


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------
def _make_user(role: str = "staff", user_id: str | None = None) -> dict:
    uid = user_id or str(uuid.uuid4())
    return {
        "id": uid,
        "username": f"user_{role}",
        "password_hash": hash_password("pw"),
        "display_name": f"테스트 {role}",
        "role": role,
        "assigned_committee": None,
        "is_active": True,
        "last_login_at": None,
        "created_at": "2026-03-19T00:00:00+00:00",
    }


def _make_token(user: dict) -> str:
    return create_access_token({"sub": user["id"], "role": user["role"]})


# ---------------------------------------------------------------------------
# 테스트용 미니 앱 (미들웨어 독립 테스트)
# ---------------------------------------------------------------------------
def _create_test_app(users: list[dict] | None = None) -> tuple[FastAPI, TestClient]:
    """미들웨어 테스트용 미니 FastAPI 앱을 생성합니다."""
    test_app = FastAPI()
    mock_client = UserAwareMockClient(users=users or [])

    @test_app.get("/admin-only")
    async def admin_only(user=Depends(require_role("admin"))):
        return {"user_id": user["id"], "role": user["role"]}

    @test_app.get("/manager-or-admin")
    async def manager_or_admin(
        user=Depends(require_role("meeting_manager", "admin")),
    ):
        return {"user_id": user["id"], "role": user["role"]}

    @test_app.get("/optional")
    async def optional_endpoint(user=Depends(optional_auth)):
        if user:
            return {"authenticated": True, "user_id": user["id"]}
        return {"authenticated": False}

    @test_app.get("/current-user")
    async def current_user_endpoint(user=Depends(get_current_user)):
        if user:
            return {"user_id": user["id"]}
        return {"user": None}

    test_app.dependency_overrides[get_supabase] = lambda: mock_client
    client = TestClient(test_app)
    return test_app, client


# ---------------------------------------------------------------------------
# require_role 테스트
# ---------------------------------------------------------------------------
class TestRequireRole:
    """require_role 데코레이터 테스트"""

    def test_admin_access_admin_only(self):
        """admin 역할은 admin-only 엔드포인트에 접근할 수 있어야 한다."""
        user = _make_user("admin")
        _, client = _create_test_app([user])
        token = _make_token(user)
        resp = client.get(
            "/admin-only",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"

    def test_staff_cannot_access_admin_only(self):
        """staff 역할은 admin-only 엔드포인트에 접근할 수 없어야 한다."""
        user = _make_user("staff")
        _, client = _create_test_app([user])
        token = _make_token(user)
        resp = client.get(
            "/admin-only",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_no_token_returns_401(self):
        """토큰 없이 require_role 엔드포인트에 접근하면 401."""
        _, client = _create_test_app([])
        resp = client.get("/admin-only")
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self):
        """잘못된 토큰으로 접근하면 401."""
        _, client = _create_test_app([])
        resp = client.get(
            "/admin-only",
            headers={"Authorization": "Bearer invalid.token"},
        )
        assert resp.status_code == 401

    def test_multiple_roles_allowed(self):
        """meeting_manager 역할은 manager-or-admin 엔드포인트에 접근할 수 있어야 한다."""
        user = _make_user("meeting_manager")
        _, client = _create_test_app([user])
        token = _make_token(user)
        resp = client.get(
            "/manager-or-admin",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    def test_stenographer_cannot_access_manager_endpoint(self):
        """stenographer는 manager-or-admin 엔드포인트에 접근할 수 없어야 한다."""
        user = _make_user("stenographer")
        _, client = _create_test_app([user])
        token = _make_token(user)
        resp = client.get(
            "/manager-or-admin",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# optional_auth 테스트
# ---------------------------------------------------------------------------
class TestOptionalAuth:
    """optional_auth 의존성 테스트"""

    def test_with_valid_token(self):
        """유효한 토큰이 있으면 사용자 정보를 반환해야 한다."""
        user = _make_user("staff")
        _, client = _create_test_app([user])
        token = _make_token(user)
        resp = client.get(
            "/optional",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is True

    def test_without_token(self):
        """토큰 없이도 200을 반환해야 한다 (user=None)."""
        _, client = _create_test_app([])
        resp = client.get("/optional")
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False

    def test_with_invalid_token(self):
        """잘못된 토큰이어도 200을 반환해야 한다 (user=None)."""
        _, client = _create_test_app([])
        resp = client.get(
            "/optional",
            headers={"Authorization": "Bearer bad.token"},
        )
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False

    def test_with_quick_admin_pin_token(self):
        """PIN 로그인(quick-admin) 토큰도 인증 사용자로 인식해야 한다.

        회귀 방지: users 테이블에 레코드가 없는 quick-admin 토큰이
        optional_auth에서 None으로 떨어져, optional_auth+401 가드 방식 API
        (kordoc 미리보기 등)가 PIN 사용자를 익명 취급하던 버그.
        """
        _, client = _create_test_app([])  # users 테이블 비어 있음
        token = create_access_token({"sub": "quick-admin", "role": "admin"})
        resp = client.get(
            "/optional",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"authenticated": True, "user_id": "quick-admin"}


# ---------------------------------------------------------------------------
# get_current_user 테스트
# ---------------------------------------------------------------------------
class TestGetCurrentUser:
    """get_current_user 의존성 테스트"""

    def test_returns_user_with_valid_token(self):
        """유효한 토큰이면 사용자 dict를 반환해야 한다."""
        user = _make_user("admin")
        _, client = _create_test_app([user])
        token = _make_token(user)
        resp = client.get(
            "/current-user",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["user_id"] == user["id"]

    def test_returns_none_without_token(self):
        """토큰 없으면 None을 반환해야 한다."""
        _, client = _create_test_app([])
        resp = client.get("/current-user")
        assert resp.status_code == 200
        assert resp.json()["user"] is None
