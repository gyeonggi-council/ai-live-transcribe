"""pytest 공통 설정 및 픽스처

Supabase REST 클라이언트를 모킹합니다.
"""

import uuid
from datetime import datetime, timezone
from typing import Generator
import pytest
from fastapi.testclient import TestClient

from app.core.database import get_supabase
from app.main import app
from app.services.auth_service import create_access_token


# ---------------------------------------------------------------------------
# 테스트용 관리자 계정 (인가가 필요한 엔드포인트 테스트용)
# ---------------------------------------------------------------------------
TEST_ADMIN_USER_ID = "00000000-0000-0000-0000-000000000001"
TEST_ADMIN_USER = {
    "id": TEST_ADMIN_USER_ID,
    "username": "admin",
    "password_hash": "$2b$12$dummy",  # 실제 검증 안 함
    "display_name": "테스트 관리자",
    "role": "admin",
    "assigned_committee": None,
    "is_active": True,
    "last_login_at": None,
    "created_at": "2026-01-01T00:00:00+00:00",
}


def _make_subtitle_row(
    meeting_id: str,
    text: str = "테스트 자막",
    start_time: float = 0.0,
    end_time: float = 5.0,
    speaker: str | None = "발언자",
    confidence: float | None = 0.95,
    subtitle_id: str | None = None,
) -> dict:
    """Supabase 응답 형태의 자막 dict를 생성합니다."""
    return {
        "id": subtitle_id or str(uuid.uuid4()),
        "meeting_id": str(meeting_id),
        "start_time": start_time,
        "end_time": end_time,
        "text": text,
        "speaker": speaker,
        "confidence": confidence,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


class MockSupabaseResponse:
    """Supabase execute() 반환 객체"""

    def __init__(self, data: list | None = None, count: int | None = None):
        self.data = data or []
        self.count = count


class MockSupabaseQuery:
    """Supabase 체이닝 쿼리 빌더 모킹

    .table("x").select("*").eq("k","v").execute() 패턴을 지원합니다.
    """

    def __init__(self, data: list | None = None, count: int | None = None):
        self._data = data or []
        self._count = count

    # 체이닝 메서드: 모두 self 반환
    def select(self, *args, **kwargs) -> "MockSupabaseQuery":
        if kwargs.get("count") == "exact":
            self._count = len(self._data)
        return self

    def eq(self, *args, **kwargs) -> "MockSupabaseQuery":
        return self

    def or_(self, *args, **kwargs) -> "MockSupabaseQuery":
        # PostgREST or=(…) 필터 — 실제로 걸지 않는다(ilike 와 같다). 없으면 서비스의 broad except 에 가려 0건이 된다(2026-09-14)
        return self

    def ilike(self, *args, **kwargs) -> "MockSupabaseQuery":
        return self

    def order(self, *args, **kwargs) -> "MockSupabaseQuery":
        return self

    def range(self, *args, **kwargs) -> "MockSupabaseQuery":
        return self

    def limit(self, *args, **kwargs) -> "MockSupabaseQuery":
        return self

    def update(self, *args, **kwargs) -> "MockSupabaseQuery":
        return self

    def insert(self, *args, **kwargs) -> "MockSupabaseQuery":
        return self

    def delete(self, *args, **kwargs) -> "MockSupabaseQuery":
        return self

    def upsert(self, *args, **kwargs) -> "MockSupabaseQuery":
        return self

    def neq(self, *args, **kwargs) -> "MockSupabaseQuery":
        return self

    def lt(self, *args, **kwargs) -> "MockSupabaseQuery":
        return self

    def in_(self, *args, **kwargs) -> "MockSupabaseQuery":
        return self

    def gte(self, *args, **kwargs) -> "MockSupabaseQuery":
        return self

    def lte(self, *args, **kwargs) -> "MockSupabaseQuery":
        return self

    def is_(self, *args, **kwargs) -> "MockSupabaseQuery":
        return self

    def execute(self) -> MockSupabaseResponse:
        return MockSupabaseResponse(data=self._data, count=self._count)


class AuthAwareMockQuery(MockSupabaseQuery):
    """users 테이블에서 eq 필터를 적용하는 MockSupabaseQuery 확장."""

    def __init__(self, data: list | None = None, count: int | None = None):
        super().__init__(data, count)
        self._filters: dict = {}

    def eq(self, column: str, value) -> "AuthAwareMockQuery":
        self._filters[column] = value
        return self

    def single(self) -> "AuthAwareMockQuery":
        return self

    def execute(self) -> MockSupabaseResponse:
        filtered = self._data
        for col, val in self._filters.items():
            filtered = [r for r in filtered if r.get(col) == val]
        return MockSupabaseResponse(data=filtered, count=self._count)


class MockSupabaseClient:
    """Supabase Client 모킹

    table() 호출 시 MockSupabaseQuery를 반환합니다.
    users 테이블은 항상 TEST_ADMIN_USER를 포함합니다 (인가 미들웨어 지원).
    """

    def __init__(self, table_data: dict[str, list] | None = None):
        self._table_data = table_data or {}
        # users 테이블에 테스트 관리자 계정을 항상 포함
        if "users" not in self._table_data:
            self._table_data["users"] = [TEST_ADMIN_USER]

    def table(self, name: str) -> MockSupabaseQuery:
        data = self._table_data.get(name, [])
        # users 테이블은 eq 필터링이 필요하므로 AuthAwareMockQuery 사용
        if name == "users":
            return AuthAwareMockQuery(data=data)
        return MockSupabaseQuery(data=data)


@pytest.fixture
def admin_auth_header() -> dict[str, str]:
    """인가가 필요한 엔드포인트 테스트용 Authorization 헤더."""
    token = create_access_token({"sub": TEST_ADMIN_USER_ID, "role": "admin"})
    return {"Authorization": f"Bearer {token}"}


def get_admin_auth_header() -> dict[str, str]:
    """인가 헤더를 함수로 직접 가져올 때 사용 (fixture 불가 상황)."""
    token = create_access_token({"sub": TEST_ADMIN_USER_ID, "role": "admin"})
    return {"Authorization": f"Bearer {token}"}


def inject_users_into_mock(mock_client, users: list | None = None):
    """기존 mock 클라이언트에 users 테이블 데이터를 주입합니다.

    auth_middleware가 users 테이블을 조회할 수 있게 해줍니다.
    """
    if hasattr(mock_client, "_table_data"):
        mock_client._table_data["users"] = users or [TEST_ADMIN_USER]
    return mock_client


@pytest.fixture
def meeting_id() -> uuid.UUID:
    """테스트용 회의 ID"""
    return uuid.uuid4()


@pytest.fixture
def mock_subtitles(meeting_id: uuid.UUID) -> list[dict]:
    """테스트용 자막 목록 (dict 형태)"""
    mid = str(meeting_id)
    return [
        _make_subtitle_row(mid, "첫 번째 자막입니다", 0.0, 5.0),
        _make_subtitle_row(mid, "두 번째 자막입니다", 5.0, 10.0),
        _make_subtitle_row(mid, "테스트 키워드 포함", 10.0, 15.0),
    ]


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """기본 테스트 클라이언트 (빈 DB)"""
    mock_supabase = MockSupabaseClient()
    app.dependency_overrides[get_supabase] = lambda: mock_supabase
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_with_mock_db(
    mock_subtitles: list[dict],
) -> Generator[TestClient, None, None]:
    """자막 데이터가 있는 Supabase 모킹 클라이언트"""
    mock_supabase = MockSupabaseClient(
        table_data={"subtitles": mock_subtitles}
    )
    app.dependency_overrides[get_supabase] = lambda: mock_supabase
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_with_empty_db() -> Generator[TestClient, None, None]:
    """빈 DB를 사용하는 테스트 클라이언트"""
    mock_supabase = MockSupabaseClient(table_data={"subtitles": []})
    app.dependency_overrides[get_supabase] = lambda: mock_supabase
    yield TestClient(app)
    app.dependency_overrides.clear()
