"""익명 VOD 등록 + 도메인 화이트리스트 + 중복 방지 테스트.

Phase 11+ 변경:
  - POST /api/meetings/from-url, POST /api/meetings 가 비로그인 허용.
  - 허용 도메인은 kms.ggc.go.kr (https) 한 곳만.
  - 동일한 resolved vod_url 이 이미 있으면 409 Conflict.

@TASK anonymous-vod-registration
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_supabase
from app.main import app
from tests.conftest import MockSupabaseClient


KMS_VIEWER_URL = "https://kms.ggc.go.kr/caster/player/vodViewer.do?midx=137982"
RESOLVED_MP4_URL = "https://kms.ggc.go.kr/mp4/mp4media2/test/20260101_test.mp4"


def _metadata_fixture() -> dict:
    return {
        "title": "제400회 본회의 [2026.01.01]",
        "meeting_date": "2026-01-01",
        "vod_url": RESOLVED_MP4_URL,
        "duration_seconds": 3600,
    }


@pytest.fixture
def empty_meetings_client():
    mock = MockSupabaseClient(table_data={"meetings": []})
    app.dependency_overrides[get_supabase] = lambda: mock
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_with_existing_meeting():
    """이미 등록된 VOD 가 있는 상태 — 중복 체크 대상."""
    existing = {
        "id": "existing-meeting-id",
        "title": "기존 회의",
        "meeting_date": "2026-01-01",
        "vod_url": RESOLVED_MP4_URL,
        "status": "ended",
    }
    mock = MockSupabaseClient(table_data={"meetings": [existing]})
    app.dependency_overrides[get_supabase] = lambda: mock
    yield TestClient(app)
    app.dependency_overrides.clear()


# =============================================================================
# POST /api/meetings/from-url — 익명 허용
# =============================================================================


class TestFromUrlAnonymous:
    """비로그인 사용자도 KMS URL 로 VOD 를 등록할 수 있어야 한다."""

    def test_anonymous_can_create_from_kms_url(self, empty_meetings_client):
        """Authorization 헤더 없이도 201 을 반환한다."""
        created = {
            "id": "new-meeting-id",
            "title": "제400회 본회의",
            "meeting_date": "2026-01-01",
            "vod_url": RESOLVED_MP4_URL,
            "status": "ended",
        }
        with patch("app.api.meetings.resolve_kms_vod_metadata") as mock_resolve, patch(
            "app.api.meetings.create_meeting_service"
        ) as mock_create:
            mock_resolve.return_value = _metadata_fixture()
            mock_create.return_value = created

            response = empty_meetings_client.post(
                "/api/meetings/from-url",
                json={"url": KMS_VIEWER_URL},
            )

        assert response.status_code == 201, response.text
        assert response.json()["id"] == "new-meeting-id"
        mock_resolve.assert_awaited_once_with(KMS_VIEWER_URL)
        mock_create.assert_called_once()

    def test_rejects_non_kms_domain(self, empty_meetings_client):
        """kms.ggc.go.kr 이 아닌 호스트는 422 로 거부된다."""
        response = empty_meetings_client.post(
            "/api/meetings/from-url",
            json={"url": "https://youtube.com/watch?v=abc"},
        )
        assert response.status_code == 422
        assert "kms.ggc.go.kr" in response.json()["detail"]

    def test_rejects_http_scheme(self, empty_meetings_client):
        """http (non-https) 는 거부된다."""
        response = empty_meetings_client.post(
            "/api/meetings/from-url",
            json={"url": "http://kms.ggc.go.kr/caster/player/vodViewer.do?midx=1"},
        )
        assert response.status_code == 422

    def test_rejects_userinfo_bypass(self, empty_meetings_client):
        """userinfo 주입 `https://evil@kms.ggc.go.kr` 는 실제로는 kms 가 맞지만,
        parsed.hostname 이 정확히 kms.ggc.go.kr 이면 허용해야 한다.

        여기서는 다른 호스트로 우회하려는 시도를 차단하는지 확인.
        """
        response = empty_meetings_client.post(
            "/api/meetings/from-url",
            json={"url": "https://kms.ggc.go.kr.evil.com/caster/player/vodViewer.do?midx=1"},
        )
        assert response.status_code == 422

    def test_duplicate_vod_url_returns_409(self, client_with_existing_meeting):
        """동일 resolved vod_url 이 이미 있으면 409 를 반환한다."""
        with patch("app.api.meetings.resolve_kms_vod_metadata") as mock_resolve:
            mock_resolve.return_value = _metadata_fixture()

            response = client_with_existing_meeting.post(
                "/api/meetings/from-url",
                json={"url": KMS_VIEWER_URL},
            )

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["existing_meeting_id"] == "existing-meeting-id"
        assert "이미 등록" in detail["message"]


# =============================================================================
# POST /api/meetings — 익명 + 중복 방지
# =============================================================================


class TestCreateMeetingAnonymous:
    """POST /api/meetings 도 비로그인 허용 + 중복 방지."""

    def test_anonymous_can_create_meeting_with_kms_url(self, empty_meetings_client):
        created = {
            "id": "new-2",
            "title": "테스트 회의",
            "meeting_date": "2026-01-01",
            "vod_url": RESOLVED_MP4_URL,
            "status": "ended",
        }
        with patch("app.api.meetings.resolve_kms_vod_url") as mock_resolve, patch(
            "app.api.meetings.create_meeting_service"
        ) as mock_create:
            mock_resolve.return_value = RESOLVED_MP4_URL
            mock_create.return_value = created

            response = empty_meetings_client.post(
                "/api/meetings",
                json={
                    "title": "테스트 회의",
                    "meeting_date": "2026-01-01",
                    "vod_url": KMS_VIEWER_URL,
                    "status": "ended",
                },
            )

        assert response.status_code == 201, response.text
        assert response.json()["id"] == "new-2"

    def test_rejects_non_kms_vod_url(self, empty_meetings_client):
        response = empty_meetings_client.post(
            "/api/meetings",
            json={
                "title": "테스트 회의",
                "meeting_date": "2026-01-01",
                "vod_url": "https://evil.example.com/video.mp4",
                "status": "ended",
            },
        )
        assert response.status_code == 422

    def test_duplicate_direct_mp4_url_returns_409(self, client_with_existing_meeting):
        """KMS resolve 가 필요 없는 직접 MP4 URL 로 등록 시에도 중복 감지."""
        # 이미 존재하는 vod_url 과 정확히 같은 값으로 등록 시도
        response = client_with_existing_meeting.post(
            "/api/meetings",
            json={
                "title": "중복 시도",
                "meeting_date": "2026-01-02",
                "vod_url": RESOLVED_MP4_URL,
                "status": "ended",
            },
        )
        assert response.status_code == 409
        assert response.json()["detail"]["existing_meeting_id"] == "existing-meeting-id"

    def test_no_vod_url_skips_whitelist_and_dup_check(self, empty_meetings_client):
        """vod_url 이 없는 (실시간/예정) 회의는 화이트리스트/중복 체크를 건너뛴다."""
        created = {
            "id": "new-3",
            "title": "실시간 회의",
            "meeting_date": "2026-01-01",
            "stream_url": "https://stream01.cdn.gov-ntruss.com/live/ch1/index.m3u8",
            "vod_url": None,
            "status": "live",
        }
        with patch("app.api.meetings.create_meeting_service") as mock_create:
            mock_create.return_value = created
            response = empty_meetings_client.post(
                "/api/meetings",
                json={
                    "title": "실시간 회의",
                    "meeting_date": "2026-01-01",
                    "stream_url": "https://stream01.cdn.gov-ntruss.com/live/ch1/index.m3u8",
                    "status": "live",
                },
            )
        assert response.status_code == 201
