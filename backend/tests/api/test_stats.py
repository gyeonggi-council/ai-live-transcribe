"""Statistics & Report API 테스트

# @TASK P11-T2.1 - 통계 API 테스트
# @TASK P11-T4.1 - 리포트 생성 API 테스트
# @TEST backend/tests/api/test_stats.py

TDD RED -> GREEN
"""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_supabase
from app.main import app
from tests.conftest import MockSupabaseQuery, MockSupabaseResponse


# =============================================================================
# Mock Supabase Client (테이블별 다른 데이터 지원)
# =============================================================================


class StatsMockSupabaseQuery(MockSupabaseQuery):
    """stats 테스트용 체이닝 쿼리 빌더"""

    def __init__(self, data: list | None = None, count: int | None = None):
        super().__init__(data, count)
        self._filters: dict[str, str] = {}

    def eq(self, column: str, value) -> "StatsMockSupabaseQuery":
        self._filters[column] = str(value)
        return self

    def gte(self, *args, **kwargs) -> "StatsMockSupabaseQuery":
        return self

    def lte(self, *args, **kwargs) -> "StatsMockSupabaseQuery":
        return self

    def select(self, *args, **kwargs) -> "StatsMockSupabaseQuery":
        if kwargs.get("count") == "exact":
            self._count = len(self._data)
        return self

    def order(self, *args, **kwargs) -> "StatsMockSupabaseQuery":
        return self

    def limit(self, *args, **kwargs) -> "StatsMockSupabaseQuery":
        return self

    def range(self, *args, **kwargs) -> "StatsMockSupabaseQuery":
        return self

    def execute(self) -> MockSupabaseResponse:
        if self._filters:
            matched = []
            for row in self._data:
                match = True
                for col, val in self._filters.items():
                    if str(row.get(col, "")) != val:
                        match = False
                        break
                if match:
                    matched.append(row)
            return MockSupabaseResponse(data=matched, count=len(matched))
        return MockSupabaseResponse(data=self._data, count=self._count)


class StatsMockSupabaseClient:
    """stats 테스트용 Supabase 클라이언트 모킹"""

    def __init__(self, table_data: dict[str, list] | None = None):
        self._table_data = table_data or {}

    def table(self, name: str) -> StatsMockSupabaseQuery:
        data = self._table_data.get(name, [])
        return StatsMockSupabaseQuery(data=data)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def meeting_id_1() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def meeting_id_2() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def sample_meetings(meeting_id_1: str, meeting_id_2: str) -> list[dict]:
    return [
        {
            "id": meeting_id_1,
            "title": "제1회 본회의",
            "meeting_date": "2026-01-15",
            "status": "ended",
            "duration_seconds": 3600,
        },
        {
            "id": meeting_id_2,
            "title": "제2회 본회의",
            "meeting_date": "2026-02-10",
            "status": "ended",
            "duration_seconds": 1800,
        },
    ]


@pytest.fixture
def sample_subtitles(meeting_id_1: str, meeting_id_2: str) -> list[dict]:
    return [
        {
            "id": str(uuid.uuid4()),
            "meeting_id": meeting_id_1,
            "speaker": "김위원",
            "start_time": 0.0,
            "end_time": 10.0,
            "confidence": 0.95,
        },
        {
            "id": str(uuid.uuid4()),
            "meeting_id": meeting_id_1,
            "speaker": "김위원",
            "start_time": 10.0,
            "end_time": 20.0,
            "confidence": 0.90,
        },
        {
            "id": str(uuid.uuid4()),
            "meeting_id": meeting_id_1,
            "speaker": "박위원",
            "start_time": 20.0,
            "end_time": 35.0,
            "confidence": 0.85,
        },
        {
            "id": str(uuid.uuid4()),
            "meeting_id": meeting_id_2,
            "speaker": "김위원",
            "start_time": 0.0,
            "end_time": 15.0,
            "confidence": 0.92,
        },
    ]


# =============================================================================
# GET /api/stats/overview
# =============================================================================


class TestStatsOverview:
    """GET /api/stats/overview 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_overview_returns_200(self):
        """통계 개요가 200을 반환한다"""
        mock_client = StatsMockSupabaseClient(
            table_data={"meetings": [], "subtitles": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/stats/overview")

        assert response.status_code == 200

    def test_overview_empty_db(self):
        """빈 DB에서 0 값을 반환한다"""
        mock_client = StatsMockSupabaseClient(
            table_data={"meetings": [], "subtitles": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/stats/overview")

        data = response.json()
        assert data["total_meetings"] == 0
        assert data["total_subtitles"] == 0
        assert data["total_duration_seconds"] == 0
        assert data["avg_confidence"] == 0.0

    def test_overview_with_data(self, sample_meetings, sample_subtitles):
        """데이터가 있으면 올바른 통계를 반환한다"""
        mock_client = StatsMockSupabaseClient(
            table_data={
                "meetings": sample_meetings,
                "subtitles": sample_subtitles,
            }
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/stats/overview")

        data = response.json()
        assert data["total_meetings"] == 2
        assert data["total_subtitles"] == 4
        assert data["total_duration_seconds"] == 5400  # 3600 + 1800
        assert data["avg_confidence"] > 0

    def test_overview_has_required_fields(self, sample_meetings, sample_subtitles):
        """응답에 필수 필드가 포함된다"""
        mock_client = StatsMockSupabaseClient(
            table_data={
                "meetings": sample_meetings,
                "subtitles": sample_subtitles,
            }
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/stats/overview")

        data = response.json()
        assert "total_meetings" in data
        assert "total_subtitles" in data
        assert "total_duration_seconds" in data
        assert "avg_confidence" in data


# =============================================================================
# GET /api/stats/speakers
# =============================================================================


class TestStatsSpeakers:
    """GET /api/stats/speakers 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_speakers_returns_200(self):
        """화자별 통계가 200을 반환한다"""
        mock_client = StatsMockSupabaseClient(
            table_data={"subtitles": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/stats/speakers")

        assert response.status_code == 200

    def test_speakers_empty_db(self):
        """빈 DB에서 빈 리스트를 반환한다"""
        mock_client = StatsMockSupabaseClient(
            table_data={"subtitles": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/stats/speakers")

        assert response.json() == []

    def test_speakers_with_data(self, sample_subtitles):
        """데이터가 있으면 화자별 통계를 반환한다"""
        mock_client = StatsMockSupabaseClient(
            table_data={"subtitles": sample_subtitles}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/stats/speakers")

        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2  # 김위원, 박위원
        # 김위원이 3개 세그먼트로 1위
        assert data[0]["speaker"] == "김위원"
        assert data[0]["total_segments"] == 3

    def test_speakers_has_required_fields(self, sample_subtitles):
        """각 화자 통계에 필수 필드가 포함된다"""
        mock_client = StatsMockSupabaseClient(
            table_data={"subtitles": sample_subtitles}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/stats/speakers")

        data = response.json()
        for item in data:
            assert "speaker" in item
            assert "total_segments" in item
            assert "total_duration" in item
            assert "meeting_count" in item

    def test_speakers_meeting_count(
        self, sample_subtitles, meeting_id_1, meeting_id_2
    ):
        """화자의 meeting_count가 정확하다"""
        mock_client = StatsMockSupabaseClient(
            table_data={"subtitles": sample_subtitles}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/stats/speakers")

        data = response.json()
        kim = next(s for s in data if s["speaker"] == "김위원")
        assert kim["meeting_count"] == 2  # 두 회의에 참여
        park = next(s for s in data if s["speaker"] == "박위원")
        assert park["meeting_count"] == 1


# =============================================================================
# GET /api/stats/meetings
# =============================================================================


class TestStatsMeetings:
    """GET /api/stats/meetings 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_meetings_returns_200(self):
        """월별 회의 통계가 200을 반환한다"""
        mock_client = StatsMockSupabaseClient(
            table_data={"meetings": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/stats/meetings")

        assert response.status_code == 200

    def test_meetings_empty_db(self):
        """빈 DB에서 빈 리스트를 반환한다"""
        mock_client = StatsMockSupabaseClient(
            table_data={"meetings": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/stats/meetings")

        assert response.json() == []

    def test_meetings_with_data(self, sample_meetings):
        """데이터가 있으면 월별 통계를 반환한다"""
        mock_client = StatsMockSupabaseClient(
            table_data={"meetings": sample_meetings}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/stats/meetings")

        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2  # 2026-01, 2026-02

    def test_meetings_has_required_fields(self, sample_meetings):
        """각 월별 통계에 필수 필드가 포함된다"""
        mock_client = StatsMockSupabaseClient(
            table_data={"meetings": sample_meetings}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/stats/meetings")

        data = response.json()
        for item in data:
            assert "month" in item
            assert "count" in item
            assert "total_duration" in item

    def test_meetings_sorted_by_month(self, sample_meetings):
        """월별 통계가 월 순서로 정렬된다"""
        mock_client = StatsMockSupabaseClient(
            table_data={"meetings": sample_meetings}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/stats/meetings")

        data = response.json()
        months = [item["month"] for item in data]
        assert months == sorted(months)


# =============================================================================
# GET /api/stats/report
# =============================================================================


class TestStatsReport:
    """GET /api/stats/report 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_report_markdown_returns_200(self, sample_meetings, sample_subtitles):
        """Markdown 리포트가 200을 반환한다"""
        mock_client = StatsMockSupabaseClient(
            table_data={
                "meetings": sample_meetings,
                "subtitles": sample_subtitles,
            }
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(
            "/api/stats/report?date_from=2026-01-01&date_to=2026-12-31&format=markdown"
        )

        assert response.status_code == 200
        assert "text/markdown" in response.headers.get("content-type", "")

    def test_report_json_returns_200(self, sample_meetings, sample_subtitles):
        """JSON 리포트가 200을 반환한다"""
        mock_client = StatsMockSupabaseClient(
            table_data={
                "meetings": sample_meetings,
                "subtitles": sample_subtitles,
            }
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(
            "/api/stats/report?date_from=2026-01-01&date_to=2026-12-31&format=json"
        )

        assert response.status_code == 200
        data = response.json()
        assert "period" in data
        assert "meetings_count" in data

    def test_report_json_has_required_fields(self, sample_meetings, sample_subtitles):
        """JSON 리포트에 필수 필드가 포함된다"""
        mock_client = StatsMockSupabaseClient(
            table_data={
                "meetings": sample_meetings,
                "subtitles": sample_subtitles,
            }
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(
            "/api/stats/report?date_from=2026-01-01&date_to=2026-12-31&format=json"
        )

        data = response.json()
        assert "period" in data
        assert "meetings_count" in data
        assert "meetings" in data
        assert "total_duration_seconds" in data
        assert "total_subtitles" in data
        assert "avg_confidence" in data
        assert "speaker_stats" in data

    def test_report_markdown_contains_sections(self, sample_meetings, sample_subtitles):
        """Markdown 리포트에 필수 섹션이 포함된다"""
        mock_client = StatsMockSupabaseClient(
            table_data={
                "meetings": sample_meetings,
                "subtitles": sample_subtitles,
            }
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(
            "/api/stats/report?date_from=2026-01-01&date_to=2026-12-31&format=markdown"
        )

        content = response.text
        assert "# 회의 리포트" in content
        assert "## 개요" in content
        assert "## 회의 목록" in content

    def test_report_missing_date_from_returns_422(self):
        """date_from 없으면 422를 반환한다"""
        mock_client = StatsMockSupabaseClient()
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/stats/report?date_to=2026-12-31")

        assert response.status_code == 422

    def test_report_missing_date_to_returns_422(self):
        """date_to 없으면 422를 반환한다"""
        mock_client = StatsMockSupabaseClient()
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/stats/report?date_from=2026-01-01")

        assert response.status_code == 422

    def test_report_empty_period(self):
        """기간 내 회의가 없으면 빈 리포트를 반환한다"""
        mock_client = StatsMockSupabaseClient(
            table_data={"meetings": [], "subtitles": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(
            "/api/stats/report?date_from=2030-01-01&date_to=2030-12-31&format=json"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["meetings_count"] == 0
        assert data["total_subtitles"] == 0
