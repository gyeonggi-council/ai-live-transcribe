"""Auth API 엔드포인트 테스트 (TDD RED -> GREEN)

# @TASK P11A-R1-T4 - 인증 API 테스트
# @TEST tests/test_auth_api.py
"""

import uuid
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_supabase
from app.main import app
from app.services.auth_service import create_access_token, hash_password
from tests.conftest import MockSupabaseClient, MockSupabaseQuery, MockSupabaseResponse


# ---------------------------------------------------------------------------
# 헬퍼: 사용자 데이터 팩토리
# ---------------------------------------------------------------------------
def _make_user(
    username: str = "testuser",
    display_name: str = "테스트 사용자",
    role: str = "staff",
    password: str = "test-password-123",
    is_active: bool = True,
    user_id: str | None = None,
) -> dict:
    """Supabase 응답 형태의 사용자 dict를 생성합니다."""
    return {
        "id": user_id or str(uuid.uuid4()),
        "username": username,
        "password_hash": hash_password(password),
        "display_name": display_name,
        "role": role,
        "assigned_committee": None,
        "is_active": is_active,
        "last_login_at": None,
        "created_at": "2026-03-19T00:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# 커스텀 Mock: users 테이블에서 username 필터링 지원
# ---------------------------------------------------------------------------
class UserAwareMockQuery(MockSupabaseQuery):
    """users 테이블 쿼리에서 eq 필터를 실제로 적용하는 mock."""

    def __init__(self, data: list | None = None, count: int | None = None):
        super().__init__(data, count)
        self._filters: dict = {}
        self._is_update = False
        self._update_data: dict = {}

    def eq(self, column: str, value) -> "UserAwareMockQuery":
        self._filters[column] = value
        return self

    def select(self, *args, **kwargs) -> "UserAwareMockQuery":
        if kwargs.get("count") == "exact":
            self._count = len(self._data)
        return self

    def update(self, data: dict) -> "UserAwareMockQuery":
        self._is_update = True
        self._update_data = data
        return self

    def single(self) -> "UserAwareMockQuery":
        return self

    def execute(self) -> MockSupabaseResponse:
        filtered = self._data
        for col, val in self._filters.items():
            filtered = [r for r in filtered if r.get(col) == val]
        if self._is_update:
            return MockSupabaseResponse(data=filtered)
        return MockSupabaseResponse(data=filtered, count=len(filtered) if self._count is not None else None)


class UserAwareMockClient:
    """users 테이블을 인식하는 Supabase 클라이언트 mock."""

    def __init__(self, users: list | None = None):
        self._users = users or []

    def table(self, name: str) -> UserAwareMockQuery:
        if name == "users":
            return UserAwareMockQuery(data=self._users)
        return MockSupabaseQuery(data=[])


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------
@pytest.fixture
def test_user_data() -> dict:
    """테스트용 사용자 원본 데이터."""
    return _make_user()


@pytest.fixture
def auth_client(test_user_data: dict) -> Generator[TestClient, None, None]:
    """사용자 데이터가 있는 테스트 클라이언트."""
    mock = UserAwareMockClient(users=[test_user_data])
    app.dependency_overrides[get_supabase] = lambda: mock
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def empty_auth_client() -> Generator[TestClient, None, None]:
    """사용자 없는 테스트 클라이언트."""
    mock = UserAwareMockClient(users=[])
    app.dependency_overrides[get_supabase] = lambda: mock
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 아이디·비밀번호 로그인은 없앴다 (2026-08-28) — 되살아나면 이 테스트가 잡는다
# ---------------------------------------------------------------------------
class TestPasswordLoginRemoved:
    """`POST /api/auth/login` 은 더 이상 존재하지 않아야 한다.

    들어오는 길은 QR(`/api/auth/qr/*`)과 통합 로그인 교환(`/api/auth/sso`) 둘뿐이다.
    라우터를 무심코 되살리면(예: 옛 커밋 revert) 여기서 404 가 아니라 200/401 이 나온다.
    """

    def test_login_endpoint_gone(self, auth_client: TestClient):
        resp = auth_client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": "test-password-123"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/auth/me 테스트
# ---------------------------------------------------------------------------
class TestMe:
    """현재 사용자 조회 API 테스트"""

    def test_me_with_valid_token(self, auth_client: TestClient, test_user_data: dict):
        """유효한 토큰으로 사용자 정보를 조회할 수 있어야 한다."""
        token = create_access_token({"sub": test_user_data["id"], "role": "staff"})
        resp = auth_client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == "testuser"
        assert "password_hash" not in body

    def test_me_without_token(self, auth_client: TestClient):
        """토큰 없이 요청하면 401을 반환해야 한다."""
        resp = auth_client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_me_with_invalid_token(self, auth_client: TestClient):
        """잘못된 토큰으로 요청하면 401을 반환해야 한다."""
        resp = auth_client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert resp.status_code == 401

    def test_me_with_quick_admin_pin_token(self, auth_client: TestClient):
        """PIN 로그인(quick-admin) 토큰으로 /me 가 200을 반환해야 한다.

        회귀 방지: 비UUID id('quick-admin') users 조회가 500을 내고
        프론트 getMe()가 토큰을 폐기해 새로고침 시 PIN 로그인이 풀리던 버그.
        """
        token = create_access_token({"sub": "quick-admin", "role": "admin"})
        resp = auth_client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "quick-admin"
        assert body["role"] == "admin"
