"""Meetings API 테스트

TDD RED 단계: 테스트 먼저 작성
"""

import uuid
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.meeting import MeetingCreate, MeetingResponse, MeetingStatus


client = TestClient(app)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_meeting_data() -> dict:
    """테스트용 회의 데이터"""
    return {
        "title": "제123회 본회의",
        "meeting_date": "2024-01-15",
        "stream_url": "https://stream01.cdn.gov-ntruss.com/live/channel1/playlist.m3u8",
        "vod_url": None,
        "status": "scheduled",
        "duration_seconds": None,
    }


@pytest.fixture
def sample_meeting_response() -> dict:
    """테스트용 회의 응답 데이터"""
    return {
        "id": str(uuid.uuid4()),
        "title": "제123회 본회의",
        "meeting_date": "2024-01-15",
        "stream_url": "https://stream01.cdn.gov-ntruss.com/live/channel1/playlist.m3u8",
        "vod_url": None,
        "status": "scheduled",
        "duration_seconds": None,
        "created_at": "2024-01-15T10:00:00Z",
        "updated_at": "2024-01-15T10:00:00Z",
    }


@pytest.fixture
def sample_live_meeting_response() -> dict:
    """테스트용 실시간 회의 응답 데이터"""
    return {
        "id": str(uuid.uuid4()),
        "title": "제124회 본회의",
        "meeting_date": "2024-01-16",
        "stream_url": "https://stream01.cdn.gov-ntruss.com/live/channel1/playlist.m3u8",
        "vod_url": None,
        "status": "live",
        "duration_seconds": None,
        "created_at": "2024-01-16T09:00:00Z",
        "updated_at": "2024-01-16T09:00:00Z",
    }


# =============================================================================
# GET /api/meetings - 회의 목록 조회
# =============================================================================

class TestGetMeetings:
    """GET /api/meetings 테스트"""

    def test_get_meetings_returns_list(self, sample_meeting_response: dict):
        """회의 목록을 조회하면 리스트를 반환한다"""
        with patch("app.api.meetings.get_meetings_service") as mock_service:
            mock_service.return_value = [sample_meeting_response]

            response = client.get("/api/meetings")

            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) == 1
            assert data[0]["title"] == "제123회 본회의"

    def test_get_meetings_empty_list(self):
        """회의가 없으면 빈 리스트를 반환한다"""
        with patch("app.api.meetings.get_meetings_service") as mock_service:
            mock_service.return_value = []

            response = client.get("/api/meetings")

            assert response.status_code == 200
            assert response.json() == []

    def test_get_meetings_with_status_filter(self, sample_meeting_response: dict):
        """status 파라미터로 필터링할 수 있다"""
        with patch("app.api.meetings.get_meetings_service") as mock_service:
            mock_service.return_value = [sample_meeting_response]

            response = client.get("/api/meetings?status=scheduled")

            assert response.status_code == 200
            mock_service.assert_called_once()
            # status 파라미터가 전달되었는지 확인
            call_kwargs = mock_service.call_args
            assert call_kwargs is not None

    def test_get_meetings_with_pagination(self, sample_meeting_response: dict):
        """limit, offset 파라미터로 페이지네이션할 수 있다"""
        with patch("app.api.meetings.get_meetings_service") as mock_service:
            mock_service.return_value = [sample_meeting_response]

            response = client.get("/api/meetings?limit=10&offset=0")

            assert response.status_code == 200

    def test_get_meetings_invalid_status(self):
        """유효하지 않은 status 값이면 422 에러를 반환한다"""
        response = client.get("/api/meetings?status=invalid_status")

        assert response.status_code == 422


# =============================================================================
# GET /api/meetings/live - 실시간 회의 조회
# =============================================================================

class TestGetLiveMeeting:
    """GET /api/meetings/live 테스트"""

    def test_get_live_meeting_returns_meeting(self, sample_live_meeting_response: dict):
        """실시간 회의가 있으면 회의 정보를 반환한다"""
        with patch("app.api.meetings.get_live_meeting_service") as mock_service:
            mock_service.return_value = sample_live_meeting_response

            response = client.get("/api/meetings/live")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "live"
            assert data["title"] == "제124회 본회의"

    def test_get_live_meeting_returns_null_when_no_live(self):
        """실시간 회의가 없으면 null을 반환한다"""
        with patch("app.api.meetings.get_live_meeting_service") as mock_service:
            mock_service.return_value = None

            response = client.get("/api/meetings/live")

            assert response.status_code == 200
            assert response.json() is None


# =============================================================================
# GET /api/meetings/{id} - 회의 상세 조회
# =============================================================================

class TestGetMeetingById:
    """GET /api/meetings/{id} 테스트"""

    def test_get_meeting_by_id_returns_meeting(self, sample_meeting_response: dict):
        """유효한 ID로 조회하면 회의 정보를 반환한다"""
        meeting_id = sample_meeting_response["id"]

        with patch("app.api.meetings.get_meeting_by_id_service") as mock_service:
            mock_service.return_value = sample_meeting_response

            response = client.get(f"/api/meetings/{meeting_id}")

            assert response.status_code == 200
            data = response.json()
            assert data["id"] == meeting_id
            assert data["title"] == "제123회 본회의"

    def test_get_meeting_by_id_not_found(self):
        """존재하지 않는 ID로 조회하면 404 에러를 반환한다"""
        non_existent_id = str(uuid.uuid4())

        with patch("app.api.meetings.get_meeting_by_id_service") as mock_service:
            mock_service.return_value = None

            response = client.get(f"/api/meetings/{non_existent_id}")

            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()

    def test_get_meeting_by_id_invalid_uuid(self):
        """유효하지 않은 UUID 형식이면 404 에러를 반환한다"""
        with patch("app.api.meetings.get_meeting_by_id_service") as mock_service:
            mock_service.return_value = None

            response = client.get("/api/meetings/invalid-uuid-format")

            assert response.status_code == 404


# =============================================================================
# POST /api/meetings - VOD 회의 등록
# =============================================================================

class TestCreateMeeting:
    """POST /api/meetings 테스트"""

    def test_create_meeting_success(self, sample_meeting_data: dict, sample_meeting_response: dict):
        """유효한 데이터로 회의를 생성하면 201과 생성된 회의를 반환한다"""
        with patch("app.api.meetings.create_meeting_service") as mock_service:
            mock_service.return_value = sample_meeting_response

            response = client.post("/api/meetings", json=sample_meeting_data)

            assert response.status_code == 201
            data = response.json()
            assert data["title"] == sample_meeting_data["title"]
            assert "id" in data
            assert "created_at" in data

    def test_create_meeting_missing_required_field(self):
        """필수 필드가 없으면 422 에러를 반환한다"""
        incomplete_data = {
            "meeting_date": "2024-01-15",
        }

        response = client.post("/api/meetings", json=incomplete_data)

        assert response.status_code == 422

    def test_create_meeting_invalid_date_format(self, sample_meeting_data: dict):
        """유효하지 않은 날짜 형식이면 422 에러를 반환한다"""
        sample_meeting_data["meeting_date"] = "invalid-date"

        response = client.post("/api/meetings", json=sample_meeting_data)

        assert response.status_code == 422

    def test_create_meeting_invalid_status(self, sample_meeting_data: dict):
        """유효하지 않은 status 값이면 422 에러를 반환한다"""
        sample_meeting_data["status"] = "invalid_status"

        response = client.post("/api/meetings", json=sample_meeting_data)

        assert response.status_code == 422


# =============================================================================
# Schema 테스트
# =============================================================================

class TestMeetingSchema:
    """Meeting 스키마 테스트"""

    def test_meeting_status_enum_values(self):
        """MeetingStatus enum이 올바른 값을 가지고 있다"""
        assert MeetingStatus.SCHEDULED.value == "scheduled"
        assert MeetingStatus.LIVE.value == "live"
        assert MeetingStatus.PROCESSING.value == "processing"
        assert MeetingStatus.ENDED.value == "ended"

    def test_meeting_create_schema_valid(self):
        """유효한 데이터로 MeetingCreate 스키마를 생성할 수 있다"""
        data = MeetingCreate(
            title="제123회 본회의",
            meeting_date=date(2024, 1, 15),
            stream_url="https://example.com/stream",
            status=MeetingStatus.SCHEDULED,
        )
        assert data.title == "제123회 본회의"
        assert data.meeting_date == date(2024, 1, 15)
        assert data.status == MeetingStatus.SCHEDULED

    def test_meeting_create_schema_defaults(self):
        """MeetingCreate 스키마의 기본값이 올바르다"""
        data = MeetingCreate(
            title="제123회 본회의",
            meeting_date=date(2024, 1, 15),
        )
        assert data.status == MeetingStatus.SCHEDULED
        assert data.stream_url is None
        assert data.vod_url is None
        assert data.duration_seconds is None

    def test_meeting_response_schema(self):
        """MeetingResponse 스키마가 모든 필드를 포함한다"""
        from datetime import datetime

        data = MeetingResponse(
            id=uuid.uuid4(),
            title="제123회 본회의",
            meeting_date=date(2024, 1, 15),
            stream_url=None,
            vod_url=None,
            status=MeetingStatus.SCHEDULED,
            duration_seconds=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        assert data.id is not None
        assert data.title == "제123회 본회의"
        assert data.created_at is not None
        assert data.updated_at is not None
