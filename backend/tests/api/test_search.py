"""Global Search API tests - TDD

# @TASK P5-T3.1 - 통합 검색 API
# @SPEC docs/planning/02-trd.md#통합-검색-API
"""

import uuid
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_supabase
from app.main import app
from tests.conftest import (
    MockSupabaseResponse,
    _make_subtitle_row,
)


# =============================================================================
# Fixtures & Helpers
# =============================================================================


def _make_meeting_row(
    meeting_id: str,
    title: str = "제123회 본회의",
    meeting_date: str = "2026-01-15",
    status: str = "ended",
) -> dict:
    """Supabase 응답 형태의 meeting dict를 생성합니다."""
    return {
        "id": meeting_id,
        "title": title,
        "meeting_date": meeting_date,
        "stream_url": None,
        "vod_url": "https://example.com/vod.mp4",
        "status": status,
        "duration_seconds": 3600,
        "created_at": "2026-01-15T10:00:00Z",
        "updated_at": "2026-01-15T10:00:00Z",
    }


class _SearchMockSupabaseQuery:
    """Search 테스트용 Supabase 쿼리 빌더

    다양한 필터 체이닝을 추적하여 올바른 결과를 반환합니다.
    """

    def __init__(self, data: list | None = None, count: int | None = None):
        self._data = data or []
        self._count = count
        self._ilike_field: str | None = None
        self._ilike_pattern: str | None = None
        self._eq_filters: dict[str, str] = {}
        self._in_filters: dict[str, list] = {}
        self._gte_filters: dict[str, str] = {}
        self._lte_filters: dict[str, str] = {}
        self._range_start: int | None = None
        self._range_end: int | None = None
        self._count_requested: bool = False

    def select(self, *args, **kwargs) -> "_SearchMockSupabaseQuery":
        if kwargs.get("count") == "exact":
            self._count_requested = True
        return self

    def eq(self, column: str, value: str) -> "_SearchMockSupabaseQuery":
        self._eq_filters[column] = value
        return self

    def ilike(self, column: str, pattern: str) -> "_SearchMockSupabaseQuery":
        self._ilike_field = column
        self._ilike_pattern = pattern
        return self

    def in_(self, column: str, values: list) -> "_SearchMockSupabaseQuery":
        self._in_filters[column] = values
        return self

    def gte(self, column: str, value: str) -> "_SearchMockSupabaseQuery":
        self._gte_filters[column] = value
        return self

    def lte(self, column: str, value: str) -> "_SearchMockSupabaseQuery":
        self._lte_filters[column] = value
        return self

    def order(self, *args, **kwargs) -> "_SearchMockSupabaseQuery":
        return self

    def range(self, start: int, end: int) -> "_SearchMockSupabaseQuery":
        self._range_start = start
        self._range_end = end
        return self

    def limit(self, *args, **kwargs) -> "_SearchMockSupabaseQuery":
        return self

    def execute(self) -> MockSupabaseResponse:
        filtered = list(self._data)

        # Apply ilike filter
        if self._ilike_field and self._ilike_pattern:
            pattern = self._ilike_pattern.strip("%").lower()
            filtered = [
                row for row in filtered
                if pattern in str(row.get(self._ilike_field, "")).lower()
            ]

        # Apply eq filters
        for col, val in self._eq_filters.items():
            filtered = [
                row for row in filtered
                if str(row.get(col, "")) == str(val)
            ]

        # Apply in_ filters
        for col, values in self._in_filters.items():
            filtered = [
                row for row in filtered
                if row.get(col) in values
            ]

        # Apply gte filters
        for col, val in self._gte_filters.items():
            filtered = [
                row for row in filtered
                if str(row.get(col, "")) >= val
            ]

        # Apply lte filters
        for col, val in self._lte_filters.items():
            filtered = [
                row for row in filtered
                if str(row.get(col, "")) <= val
            ]

        total = len(filtered)

        # Apply range (pagination)
        if self._range_start is not None and self._range_end is not None:
            filtered = filtered[self._range_start:self._range_end + 1]

        count = total if self._count_requested else None
        return MockSupabaseResponse(data=filtered, count=count)


class _SearchMockSupabaseClient:
    """Search 테스트에 특화된 Supabase 클라이언트 모킹"""

    def __init__(self, table_data: dict[str, list] | None = None):
        self._table_data = table_data or {}

    def table(self, name: str) -> _SearchMockSupabaseQuery:
        data = self._table_data.get(name, [])
        return _SearchMockSupabaseQuery(data=data)


@pytest.fixture
def search_meeting_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def search_meeting_id_2() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def search_subtitles(search_meeting_id: str, search_meeting_id_2: str) -> list[dict]:
    """검색 테스트용 자막 목록"""
    return [
        _make_subtitle_row(search_meeting_id, "예산 심의에 대한 발언입니다", 0.0, 5.0, speaker="화자1"),
        _make_subtitle_row(search_meeting_id, "교육 관련 예산 논의", 5.0, 10.0, speaker="화자2"),
        _make_subtitle_row(search_meeting_id, "복지 정책 논의합니다", 10.0, 15.0, speaker="화자1"),
        _make_subtitle_row(search_meeting_id_2, "내년도 예산안 심의", 0.0, 5.0, speaker="화자3"),
        _make_subtitle_row(search_meeting_id_2, "교통 인프라 투자 계획", 5.0, 10.0, speaker="화자3"),
    ]


@pytest.fixture
def search_meetings(search_meeting_id: str, search_meeting_id_2: str) -> list[dict]:
    """검색 테스트용 회의 목록"""
    return [
        _make_meeting_row(search_meeting_id, "제123회 본회의", "2026-01-15"),
        _make_meeting_row(search_meeting_id_2, "제124회 예산결산위원회", "2026-02-10"),
    ]


@pytest.fixture
def search_client(
    search_subtitles: list[dict],
    search_meetings: list[dict],
) -> Generator[TestClient, None, None]:
    """검색 테스트용 클라이언트"""
    mock_supabase = _SearchMockSupabaseClient(
        table_data={
            "subtitles": search_subtitles,
            "meetings": search_meetings,
        }
    )
    app.dependency_overrides[get_supabase] = lambda: mock_supabase
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def empty_search_client() -> Generator[TestClient, None, None]:
    """빈 DB 검색 테스트용 클라이언트"""
    mock_supabase = _SearchMockSupabaseClient(
        table_data={"subtitles": [], "meetings": []}
    )
    app.dependency_overrides[get_supabase] = lambda: mock_supabase
    yield TestClient(app)
    app.dependency_overrides.clear()


# =============================================================================
# Tests
# =============================================================================


class TestGlobalSearchBasic:
    """GET /api/search 기본 기능 테스트"""

    def test_search_returns_200(self, search_client: TestClient) -> None:
        """검색어로 검색 시 200 응답을 반환한다"""
        response = search_client.get("/api/search?q=예산")
        assert response.status_code == 200

    def test_search_returns_correct_structure(self, search_client: TestClient) -> None:
        """검색 결과가 올바른 구조를 가진다"""
        response = search_client.get("/api/search?q=예산")
        data = response.json()

        assert "items" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data
        assert "query" in data
        assert isinstance(data["items"], list)

    def test_search_returns_matching_items(self, search_client: TestClient) -> None:
        """검색어에 매칭되는 자막을 반환한다"""
        response = search_client.get("/api/search?q=예산")
        data = response.json()

        # "예산"을 포함하는 자막은 3개
        assert data["total"] == 3
        assert len(data["items"]) == 3
        for item in data["items"]:
            assert "예산" in item["text"]

    def test_search_includes_meeting_info(self, search_client: TestClient) -> None:
        """검색 결과에 meeting 정보가 포함된다"""
        response = search_client.get("/api/search?q=예산")
        data = response.json()

        assert len(data["items"]) > 0
        item = data["items"][0]
        assert "subtitle_id" in item
        assert "meeting_id" in item
        assert "meeting_title" in item
        assert "meeting_date" in item
        assert "text" in item
        assert "start_time" in item
        assert "end_time" in item
        assert "speaker" in item
        assert "confidence" in item

    def test_search_meeting_title_populated(self, search_client: TestClient) -> None:
        """meeting_title이 실제 회의 제목으로 채워진다"""
        response = search_client.get("/api/search?q=예산")
        data = response.json()

        for item in data["items"]:
            # meeting_title이 빈 문자열이 아니어야 한다
            assert item["meeting_title"] != ""

    def test_search_query_echoed(self, search_client: TestClient) -> None:
        """응답에 검색어가 포함된다"""
        response = search_client.get("/api/search?q=예산")
        data = response.json()
        assert data["query"] == "예산"

    def test_search_no_results(self, search_client: TestClient) -> None:
        """매칭되는 결과가 없으면 빈 리스트를 반환한다"""
        response = search_client.get("/api/search?q=없는키워드xyz")
        data = response.json()

        assert data["total"] == 0
        assert data["items"] == []
        assert data["query"] == "없는키워드xyz"

    def test_search_empty_db(self, empty_search_client: TestClient) -> None:
        """DB가 비어있을 때 빈 결과를 반환한다"""
        response = empty_search_client.get("/api/search?q=테스트")
        data = response.json()

        assert data["total"] == 0
        assert data["items"] == []


class TestGlobalSearchValidation:
    """GET /api/search 입력 검증 테스트"""

    def test_search_missing_query_returns_422(self, search_client: TestClient) -> None:
        """검색어 파라미터가 없으면 422를 반환한다"""
        response = search_client.get("/api/search")
        assert response.status_code == 422

    def test_search_empty_query_returns_422(self, search_client: TestClient) -> None:
        """빈 검색어는 422를 반환한다"""
        response = search_client.get("/api/search?q=")
        assert response.status_code == 422

    def test_search_invalid_limit_returns_422(self, search_client: TestClient) -> None:
        """limit이 범위를 벗어나면 422를 반환한다"""
        response = search_client.get("/api/search?q=예산&limit=0")
        assert response.status_code == 422

        response = search_client.get("/api/search?q=예산&limit=101")
        assert response.status_code == 422

    def test_search_invalid_offset_returns_422(self, search_client: TestClient) -> None:
        """offset이 음수이면 422를 반환한다"""
        response = search_client.get("/api/search?q=예산&offset=-1")
        assert response.status_code == 422


class TestGlobalSearchPagination:
    """GET /api/search 페이지네이션 테스트"""

    def test_search_default_pagination(self, search_client: TestClient) -> None:
        """기본 페이지네이션 값이 적용된다"""
        response = search_client.get("/api/search?q=예산")
        data = response.json()
        assert data["limit"] == 20
        assert data["offset"] == 0

    def test_search_custom_pagination(self, search_client: TestClient) -> None:
        """커스텀 페이지네이션 값이 적용된다"""
        response = search_client.get("/api/search?q=예산&limit=2&offset=1")
        data = response.json()
        assert data["limit"] == 2
        assert data["offset"] == 1

    def test_search_pagination_limits_results(self, search_client: TestClient) -> None:
        """limit에 따라 반환 결과 수가 제한된다"""
        response = search_client.get("/api/search?q=예산&limit=1")
        data = response.json()
        assert len(data["items"]) <= 1
        # total은 전체 매칭 수 (3)
        assert data["total"] == 3


class TestGlobalSearchSpeakerFilter:
    """GET /api/search 화자 필터 테스트"""

    def test_search_with_speaker_filter(self, search_client: TestClient) -> None:
        """speaker 필터가 적용된다"""
        response = search_client.get("/api/search?q=예산&speaker=화자1")
        data = response.json()

        # "예산"을 포함하고 화자1인 자막은 1개 ("예산 심의에 대한 발언입니다")
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["speaker"] == "화자1"

    def test_search_speaker_filter_no_match(self, search_client: TestClient) -> None:
        """speaker 필터 매칭이 없으면 빈 결과를 반환한다"""
        response = search_client.get("/api/search?q=예산&speaker=없는화자")
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []


class TestGlobalSearchDateFilter:
    """GET /api/search 날짜 필터 테스트"""

    def test_search_with_date_from(self, search_client: TestClient) -> None:
        """date_from 필터가 적용된다"""
        response = search_client.get("/api/search?q=예산&date_from=2026-02-01")
        data = response.json()

        # 2026-02-01 이후 회의 = 제124회(2026-02-10)만 해당
        # 해당 회의의 "예산" 포함 자막 = 1개 ("내년도 예산안 심의")
        assert data["total"] == 1
        for item in data["items"]:
            assert item["meeting_date"] >= "2026-02-01"

    def test_search_with_date_to(self, search_client: TestClient) -> None:
        """date_to 필터가 적용된다"""
        response = search_client.get("/api/search?q=예산&date_to=2026-01-31")
        data = response.json()

        # 2026-01-31 이전 회의 = 제123회(2026-01-15)만 해당
        # 해당 회의의 "예산" 포함 자막 = 2개
        assert data["total"] == 2
        for item in data["items"]:
            assert item["meeting_date"] <= "2026-01-31"

    def test_search_with_date_range(self, search_client: TestClient) -> None:
        """date_from + date_to 범위 필터가 적용된다"""
        response = search_client.get(
            "/api/search?q=예산&date_from=2026-01-01&date_to=2026-01-31"
        )
        data = response.json()

        # 2026-01 범위 = 제123회만 해당, 예산 자막 2개
        assert data["total"] == 2
        for item in data["items"]:
            assert "2026-01-01" <= item["meeting_date"] <= "2026-01-31"

    def test_search_date_filter_no_match(self, search_client: TestClient) -> None:
        """날짜 범위에 매칭되는 회의가 없으면 빈 결과를 반환한다"""
        response = search_client.get(
            "/api/search?q=예산&date_from=2099-01-01&date_to=2099-12-31"
        )
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []


class TestGlobalSearchCombinedFilters:
    """GET /api/search 복합 필터 테스트"""

    def test_search_date_and_speaker_combined(self, search_client: TestClient) -> None:
        """날짜 + 화자 필터를 동시에 적용할 수 있다"""
        response = search_client.get(
            "/api/search?q=예산&date_from=2026-01-01&date_to=2026-01-31&speaker=화자2"
        )
        data = response.json()

        # 2026-01 범위 + 화자2 + "예산" = "교육 관련 예산 논의" 1개
        assert data["total"] == 1
        assert data["items"][0]["speaker"] == "화자2"
        assert "예산" in data["items"][0]["text"]
