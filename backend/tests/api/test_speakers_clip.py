"""Speakers Clip API 테스트 - 발언 영상 클립 추출

# @TASK P11-T1.1 - 발언 영상 클립 추출 API 테스트
# @TASK B2-clip - ffmpeg URL-seek 재작성: 인증 필수(401 우선) 반영
# @TEST backend/tests/api/test_speakers_clip.py

TDD RED -> GREEN: ffmpeg mock 사용
"""

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_supabase
from app.main import app
from tests.conftest import (
    TEST_ADMIN_USER,
    MockSupabaseQuery,
    MockSupabaseResponse,
)


# =============================================================================
# Mock Supabase Client
# =============================================================================


class ClipMockSupabaseQuery(MockSupabaseQuery):
    """클립 API 테스트용 Supabase 쿼리 빌더

    eq().limit() 체이닝에서 필터링을 수행합니다.
    """

    def __init__(self, data: list | None = None, count: int | None = None):
        super().__init__(data, count)
        self._filters: dict[str, str] = {}

    def eq(self, column: str, value: str) -> "ClipMockSupabaseQuery":
        self._filters[column] = value
        return self

    def select(self, *args, **kwargs) -> "ClipMockSupabaseQuery":
        if kwargs.get("count") == "exact":
            self._count = len(self._data)
        return self

    def limit(self, *args, **kwargs) -> "ClipMockSupabaseQuery":
        return self

    def order(self, *args, **kwargs) -> "ClipMockSupabaseQuery":
        return self

    def execute(self) -> MockSupabaseResponse:
        if self._filters:
            matched = []
            for row in self._data:
                match = True
                for col, val in self._filters.items():
                    if str(row.get(col, "")) != str(val):
                        match = False
                        break
                if match:
                    matched.append(row)
            return MockSupabaseResponse(data=matched, count=len(matched))
        return MockSupabaseResponse(data=self._data, count=self._count)


class ClipMockSupabaseClient:
    """클립 테스트용 Supabase 클라이언트 모킹"""

    def __init__(self, table_data: dict[str, list] | None = None):
        self._table_data = table_data or {}

    def table(self, name: str) -> ClipMockSupabaseQuery:
        data = self._table_data.get(name, [])
        return ClipMockSupabaseQuery(data=data)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def meeting_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def meeting_with_vod(meeting_id: str) -> dict:
    return {
        "id": meeting_id,
        "title": "테스트 회의",
        "vod_url": "https://example.com/test.mp4",
    }


@pytest.fixture
def meeting_without_vod(meeting_id: str) -> dict:
    return {
        "id": meeting_id,
        "title": "VOD 없는 회의",
        "vod_url": None,
    }


# =============================================================================
# Tests
# =============================================================================


class TestGetSpeakerClip:
    """GET /api/meetings/{meeting_id}/speakers/clip 테스트 (인증 필수)"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _setup_client(self, meetings: list) -> TestClient:
        """meetings + 인증용 users 테이블을 포함한 mock 클라이언트 구성."""
        mock_client = ClipMockSupabaseClient(
            table_data={"meetings": meetings, "users": [TEST_ADMIN_USER]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        return TestClient(app)

    def test_unauthenticated_returns_401(
        self, meeting_id: str, meeting_with_vod: dict
    ):
        """인증 없이 호출하면 401 (다른 가드보다 우선 — ffmpeg 유무 무관)"""
        client = self._setup_client([meeting_with_vod])

        with patch("app.api.speakers._check_ffmpeg_available", return_value=False):
            response = client.get(
                f"/api/meetings/{meeting_id}/speakers/clip"
                f"?start=0&end=10"
            )

        assert response.status_code == 401

    def test_ffmpeg_not_available_returns_501(
        self, meeting_id: str, meeting_with_vod: dict, admin_auth_header: dict
    ):
        """ffmpeg가 없으면 501을 반환한다"""
        client = self._setup_client([meeting_with_vod])

        with patch("app.api.speakers._check_ffmpeg_available", return_value=False):
            response = client.get(
                f"/api/meetings/{meeting_id}/speakers/clip"
                f"?start=0&end=10",
                headers=admin_auth_header,
            )

        assert response.status_code == 501
        assert "ffmpeg" in response.json()["detail"]

    def test_meeting_not_found_returns_404(self, admin_auth_header: dict):
        """회의가 없으면 404를 반환한다"""
        client = self._setup_client([])

        non_existent_id = str(uuid.uuid4())

        with patch("app.api.speakers._check_ffmpeg_available", return_value=True):
            response = client.get(
                f"/api/meetings/{non_existent_id}/speakers/clip"
                f"?start=0&end=10",
                headers=admin_auth_header,
            )

        assert response.status_code == 404

    def test_no_vod_url_returns_400(
        self, meeting_id: str, meeting_without_vod: dict, admin_auth_header: dict
    ):
        """VOD URL이 없으면 400을 반환한다"""
        client = self._setup_client([meeting_without_vod])

        with patch("app.api.speakers._check_ffmpeg_available", return_value=True):
            response = client.get(
                f"/api/meetings/{meeting_id}/speakers/clip"
                f"?start=0&end=10",
                headers=admin_auth_header,
            )

        assert response.status_code == 400
        assert "VOD URL" in response.json()["detail"]

    def test_end_less_than_start_returns_400(
        self, meeting_id: str, meeting_with_vod: dict, admin_auth_header: dict
    ):
        """end가 start보다 작으면 400을 반환한다"""
        client = self._setup_client([meeting_with_vod])

        with patch("app.api.speakers._check_ffmpeg_available", return_value=True):
            response = client.get(
                f"/api/meetings/{meeting_id}/speakers/clip"
                f"?start=10&end=5",
                headers=admin_auth_header,
            )

        assert response.status_code == 400
        assert "end" in response.json()["detail"]

    def test_missing_start_param_returns_422(
        self, meeting_id: str, admin_auth_header: dict
    ):
        """start 파라미터가 없으면 422를 반환한다"""
        client = self._setup_client([])

        response = client.get(
            f"/api/meetings/{meeting_id}/speakers/clip"
            f"?end=10",
            headers=admin_auth_header,
        )

        assert response.status_code == 422

    def test_missing_end_param_returns_422(
        self, meeting_id: str, admin_auth_header: dict
    ):
        """end 파라미터가 없으면 422를 반환한다"""
        client = self._setup_client([])

        response = client.get(
            f"/api/meetings/{meeting_id}/speakers/clip"
            f"?start=0",
            headers=admin_auth_header,
        )

        assert response.status_code == 422

    def test_negative_start_returns_422(
        self, meeting_id: str, admin_auth_header: dict
    ):
        """start가 음수이면 422를 반환한다"""
        client = self._setup_client([])

        response = client.get(
            f"/api/meetings/{meeting_id}/speakers/clip"
            f"?start=-1&end=10",
            headers=admin_auth_header,
        )

        assert response.status_code == 422


class TestGetSpeakersTimeline:
    """GET /api/meetings/{meeting_id}/speakers 기존 엔드포인트 보호 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_speakers_timeline_still_works(self, meeting_id: str):
        """기존 화자 타임라인 API가 정상 동작한다"""
        subtitle = {
            "id": str(uuid.uuid4()),
            "meeting_id": meeting_id,
            "start_time": 0.0,
            "end_time": 5.0,
            "text": "테스트",
            "speaker": "화자A",
            "confidence": 0.95,
        }
        mock_client = ClipMockSupabaseClient(
            table_data={"subtitles": [subtitle]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(f"/api/meetings/{meeting_id}/speakers")

        assert response.status_code == 200
        data = response.json()
        assert "speakers" in data
        assert "total_duration" in data
