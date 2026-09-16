"""Meetings transcript_status PATCH API 테스트

# @TASK P10-T1.1 - 회의록 상태 변경 API
# @SPEC docs/planning/02-trd.md#회의록-상태

TDD RED 단계: 테스트 먼저 작성
"""

import uuid
from datetime import datetime, timezone
from typing import Generator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_supabase
from app.main import app
from app.schemas.meeting import MeetingUpdate, TranscriptStatus


# =============================================================================
# Fixtures
# =============================================================================


def _make_meeting(meeting_id: str, transcript_status: str = "draft") -> dict:
    """Supabase 응답 형태의 meeting dict를 생성합니다."""
    return {
        "id": meeting_id,
        "title": "제200회 본회의",
        "meeting_date": "2026-02-15",
        "stream_url": None,
        "vod_url": "https://kms.ggc.go.kr/mp4/test.mp4",
        "status": "ended",
        "duration_seconds": 3600,
        "transcript_status": transcript_status,
        "created_at": "2026-02-15T09:00:00Z",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


class _MockResponse:
    """Supabase execute() 반환 객체."""

    def __init__(self, data: list):
        self.data = data


class _MockQuery:
    """Supabase 체이닝 쿼리 빌더 모킹."""

    def __init__(self, data: list):
        self._data = data
        self._update_payload: dict | None = None

    def select(self, *a, **kw):
        return self

    def eq(self, *a, **kw):
        return self

    def limit(self, *a, **kw):
        return self

    def order(self, *a, **kw):
        return self

    def range(self, *a, **kw):
        return self

    def in_(self, *a, **kw):
        return self

    def update(self, payload, **kw):
        self._update_payload = payload
        return self

    def insert(self, *a, **kw):
        return self

    def execute(self):
        # update 호출 시 payload 기반으로 응답 데이터를 갱신하여 반환
        if self._update_payload and self._data:
            merged = {**self._data[0], **self._update_payload}
            return _MockResponse(data=[merged])
        return _MockResponse(data=self._data)


class _MockClient:
    """Supabase Client 모킹."""

    def __init__(self, meetings: list | None = None):
        self._meetings = meetings or []

    def table(self, name: str):
        if name == "meetings":
            return _MockQuery(data=self._meetings)
        return _MockQuery(data=[])


@pytest.fixture
def meeting_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def meeting_row(meeting_id: str) -> dict:
    return _make_meeting(meeting_id, transcript_status="draft")


@pytest.fixture
def client_with_meeting(meeting_row: dict) -> Generator[TestClient, None, None]:
    """meetings 테이블에 1건이 있는 테스트 클라이언트."""
    mock = _MockClient(meetings=[meeting_row])
    app.dependency_overrides[get_supabase] = lambda: mock
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_empty() -> Generator[TestClient, None, None]:
    """meetings 테이블이 비어있는 테스트 클라이언트."""
    mock = _MockClient(meetings=[])
    app.dependency_overrides[get_supabase] = lambda: mock
    yield TestClient(app)
    app.dependency_overrides.clear()


# =============================================================================
# PATCH /api/meetings/{meeting_id} - transcript_status 변경 테스트
# =============================================================================


class TestPatchMeetingTranscriptStatus:
    """PATCH /api/meetings/{meeting_id} 에서 transcript_status 변경 테스트."""

    def test_update_transcript_status_to_reviewing(
        self, client_with_meeting: TestClient, meeting_id: str
    ):
        """transcript_status를 reviewing으로 변경하면 200과 갱신된 데이터를 반환한다."""
        response = client_with_meeting.patch(
            f"/api/meetings/{meeting_id}",
            json={"transcript_status": "reviewing"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["transcript_status"] == "reviewing"

    def test_update_transcript_status_to_final(
        self, client_with_meeting: TestClient, meeting_id: str
    ):
        """transcript_status를 final로 변경하면 200과 갱신된 데이터를 반환한다."""
        response = client_with_meeting.patch(
            f"/api/meetings/{meeting_id}",
            json={"transcript_status": "final"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["transcript_status"] == "final"

    def test_update_transcript_status_to_draft(
        self, client_with_meeting: TestClient, meeting_id: str
    ):
        """transcript_status를 draft로 변경하면 200과 갱신된 데이터를 반환한다."""
        response = client_with_meeting.patch(
            f"/api/meetings/{meeting_id}",
            json={"transcript_status": "draft"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["transcript_status"] == "draft"

    def test_update_transcript_status_invalid_value(
        self, client_with_meeting: TestClient, meeting_id: str
    ):
        """유효하지 않은 transcript_status 값이면 422를 반환한다."""
        response = client_with_meeting.patch(
            f"/api/meetings/{meeting_id}",
            json={"transcript_status": "invalid_value"},
        )

        assert response.status_code == 422

    def test_update_transcript_status_not_found(
        self, client_empty: TestClient
    ):
        """존재하지 않는 meeting이면 404를 반환한다."""
        fake_id = str(uuid.uuid4())
        response = client_empty.patch(
            f"/api/meetings/{fake_id}",
            json={"transcript_status": "reviewing"},
        )

        assert response.status_code == 404

    def test_update_transcript_status_includes_updated_at(
        self, client_with_meeting: TestClient, meeting_id: str
    ):
        """transcript_status 변경 시 updated_at이 포함된다."""
        response = client_with_meeting.patch(
            f"/api/meetings/{meeting_id}",
            json={"transcript_status": "final"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "updated_at" in data

    def test_update_transcript_status_with_other_fields(
        self, client_with_meeting: TestClient, meeting_id: str
    ):
        """transcript_status와 다른 필드를 함께 변경할 수 있다."""
        response = client_with_meeting.patch(
            f"/api/meetings/{meeting_id}",
            json={
                "transcript_status": "reviewing",
                "title": "제201회 본회의 (수정)",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["transcript_status"] == "reviewing"
        assert data["title"] == "제201회 본회의 (수정)"


# =============================================================================
# Schema 테스트: MeetingUpdate에 transcript_status 필드가 있는지
# =============================================================================


class TestMeetingUpdateSchemaTranscriptStatus:
    """MeetingUpdate 스키마에 transcript_status 필드 테스트."""

    def test_meeting_update_accepts_transcript_status(self):
        """MeetingUpdate에 transcript_status 필드를 설정할 수 있다."""
        update = MeetingUpdate(transcript_status=TranscriptStatus.REVIEWING)
        assert update.transcript_status == TranscriptStatus.REVIEWING

    def test_meeting_update_transcript_status_optional(self):
        """MeetingUpdate에서 transcript_status는 선택 필드이다."""
        update = MeetingUpdate(title="Test")
        assert update.transcript_status is None

    def test_meeting_update_transcript_status_enum_values(self):
        """TranscriptStatus enum이 올바른 값을 가지고 있다."""
        assert TranscriptStatus.DRAFT.value == "draft"
        assert TranscriptStatus.REVIEWING.value == "reviewing"
        assert TranscriptStatus.FINAL.value == "final"

    def test_meeting_update_transcript_status_dump(self):
        """model_dump에서 transcript_status가 올바르게 직렬화된다."""
        update = MeetingUpdate(transcript_status=TranscriptStatus.FINAL)
        dumped = update.model_dump(exclude_none=True)
        assert "transcript_status" in dumped
        assert dumped["transcript_status"] == TranscriptStatus.FINAL

    def test_meeting_update_only_transcript_status(self):
        """transcript_status만 변경 요청할 수 있다."""
        update = MeetingUpdate(transcript_status=TranscriptStatus.DRAFT)
        dumped = update.model_dump(exclude_none=True)
        assert len(dumped) == 1
        assert "transcript_status" in dumped
