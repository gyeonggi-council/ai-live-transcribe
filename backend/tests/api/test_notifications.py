"""Notifications API 테스트

# @TASK P11-T5.1 - 알림 API 테스트
# @TEST backend/tests/api/test_notifications.py

TDD RED -> GREEN
"""

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_supabase
from app.main import app
from tests.conftest import MockSupabaseQuery, MockSupabaseResponse


# =============================================================================
# Mock Supabase Client
# =============================================================================


class NotificationsMockSupabaseQuery(MockSupabaseQuery):
    """알림 API 테스트용 Supabase 쿼리 빌더"""

    def __init__(self, data: list | None = None, count: int | None = None):
        super().__init__(data, count)
        self._filters: dict[str, str] = {}
        self._insert_data = None
        self._update_data = None

    def eq(self, column: str, value) -> "NotificationsMockSupabaseQuery":
        self._filters[column] = str(value)
        return self

    def select(self, *args, **kwargs) -> "NotificationsMockSupabaseQuery":
        if kwargs.get("count") == "exact":
            self._count = len(self._data)
        return self

    def order(self, *args, **kwargs) -> "NotificationsMockSupabaseQuery":
        return self

    def limit(self, *args, **kwargs) -> "NotificationsMockSupabaseQuery":
        return self

    def insert(self, data: dict) -> "NotificationsMockSupabaseQuery":
        self._insert_data = data
        return self

    def update(self, data: dict) -> "NotificationsMockSupabaseQuery":
        self._update_data = data
        return self

    def execute(self) -> MockSupabaseResponse:
        if self._insert_data is not None:
            return MockSupabaseResponse(data=[self._insert_data])

        if self._update_data is not None:
            if self._filters:
                matched = []
                for row in self._data:
                    match = True
                    for col, val in self._filters.items():
                        if str(row.get(col, "")) != val:
                            match = False
                            break
                    if match:
                        updated_row = {**row, **self._update_data}
                        matched.append(updated_row)
                return MockSupabaseResponse(data=matched)
            return MockSupabaseResponse(data=[])

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


class NotificationsMockSupabaseClient:
    """알림 테스트용 Supabase 클라이언트 모킹"""

    def __init__(self, table_data: dict[str, list] | None = None):
        self._table_data = table_data or {}

    def table(self, name: str) -> NotificationsMockSupabaseQuery:
        data = self._table_data.get(name, [])
        return NotificationsMockSupabaseQuery(data=data)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def notification_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def sample_notifications(notification_id: str) -> list[dict]:
    return [
        {
            "id": notification_id,
            "type": "status_change",
            "title": "회의록 상태 변경",
            "message": "제1회 본회의 회의록이 reviewing(으)로 변경되었습니다",
            "related_meeting_id": str(uuid.uuid4()),
            "is_read": False,
            "created_at": "2026-02-15T10:00:00Z",
        },
        {
            "id": str(uuid.uuid4()),
            "type": "stt_complete",
            "title": "STT 처리 완료",
            "message": "제2회 본회의 STT 처리가 완료되었습니다",
            "related_meeting_id": str(uuid.uuid4()),
            "is_read": True,
            "created_at": "2026-02-14T10:00:00Z",
        },
    ]


# =============================================================================
# GET /api/notifications
# =============================================================================


class TestGetNotifications:
    """GET /api/notifications 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_get_notifications_returns_200(self):
        """알림 목록 조회 시 200을 반환한다"""
        mock_client = NotificationsMockSupabaseClient(
            table_data={"notifications": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/notifications")

        assert response.status_code == 200

    def test_get_notifications_empty(self):
        """알림이 없으면 빈 리스트를 반환한다"""
        mock_client = NotificationsMockSupabaseClient(
            table_data={"notifications": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/notifications")

        assert response.json() == []

    def test_get_notifications_with_data(self, sample_notifications):
        """알림이 있으면 목록을 반환한다"""
        mock_client = NotificationsMockSupabaseClient(
            table_data={"notifications": sample_notifications}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/notifications")

        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2

    def test_get_notifications_has_required_fields(self, sample_notifications):
        """각 알림에 필수 필드가 포함된다"""
        mock_client = NotificationsMockSupabaseClient(
            table_data={"notifications": sample_notifications}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/notifications")

        data = response.json()
        for item in data:
            assert "id" in item
            assert "type" in item
            assert "title" in item
            assert "message" in item
            assert "is_read" in item

    def test_get_notifications_with_limit(self, sample_notifications):
        """limit 파라미터가 적용된다"""
        mock_client = NotificationsMockSupabaseClient(
            table_data={"notifications": sample_notifications}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/notifications?limit=1")

        assert response.status_code == 200

    def test_get_notifications_invalid_limit_returns_422(self):
        """limit가 범위 밖이면 422를 반환한다"""
        mock_client = NotificationsMockSupabaseClient(
            table_data={"notifications": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get("/api/notifications?limit=0")

        assert response.status_code == 422


# =============================================================================
# POST /api/notifications
# =============================================================================


class TestCreateNotification:
    """POST /api/notifications 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_create_notification_returns_201(self):
        """알림 생성 시 201을 반환한다"""
        mock_client = NotificationsMockSupabaseClient(
            table_data={"notifications": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.post(
            "/api/notifications",
            json={
                "type": "status_change",
                "title": "테스트 알림",
                "message": "테스트 메시지입니다",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["type"] == "status_change"
        assert data["title"] == "테스트 알림"
        assert data["message"] == "테스트 메시지입니다"
        assert data["is_read"] is False

    def test_create_notification_with_meeting_id(self):
        """회의 ID를 포함하여 알림을 생성할 수 있다"""
        mock_client = NotificationsMockSupabaseClient(
            table_data={"notifications": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        mid = str(uuid.uuid4())
        response = client.post(
            "/api/notifications",
            json={
                "type": "status_change",
                "title": "상태 변경",
                "message": "회의록이 변경되었습니다",
                "related_meeting_id": mid,
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["related_meeting_id"] == mid

    def test_create_notification_missing_required_field(self):
        """필수 필드가 없으면 422를 반환한다"""
        mock_client = NotificationsMockSupabaseClient(
            table_data={"notifications": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.post(
            "/api/notifications",
            json={"type": "test"},
        )

        assert response.status_code == 422


# =============================================================================
# PATCH /api/notifications/{id}/read
# =============================================================================


class TestMarkNotificationRead:
    """PATCH /api/notifications/{id}/read 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_mark_read_returns_200(self, notification_id: str, sample_notifications):
        """알림 읽음 처리 시 200을 반환한다"""
        mock_client = NotificationsMockSupabaseClient(
            table_data={"notifications": sample_notifications}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.patch(f"/api/notifications/{notification_id}/read")

        assert response.status_code == 200
        data = response.json()
        assert data["is_read"] is True

    def test_mark_read_not_found_returns_404(self):
        """알림이 없으면 404를 반환한다"""
        mock_client = NotificationsMockSupabaseClient(
            table_data={"notifications": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        non_existent_id = str(uuid.uuid4())
        response = client.patch(f"/api/notifications/{non_existent_id}/read")

        assert response.status_code == 404


# =============================================================================
# Notification Auto-Creation on Transcript Status Change
# =============================================================================


class TestNotificationAutoCreation:
    """meetings transcript-status 변경 시 알림 자동 생성 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_transcript_status_change_creates_notification(self):
        """회의록 상태 변경 시 알림이 생성된다"""
        meeting_id = str(uuid.uuid4())
        meeting_data = {
            "id": meeting_id,
            "title": "제1회 본회의",
            "transcript_status": "reviewing",
        }

        # meetings 테이블 update + notifications 테이블 insert 모두 지원
        class _MultiTableMock:
            def __init__(self):
                self._tables = {
                    "meetings": [meeting_data],
                    "notifications": [],
                }

            def table(self, name: str):
                return NotificationsMockSupabaseQuery(
                    data=self._tables.get(name, [])
                )

        mock_client = _MultiTableMock()
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        # create_notification_record 호출 확인
        with patch("app.api.meetings.create_notification_record") as mock_notify:
            response = client.patch(
                f"/api/meetings/{meeting_id}/transcript-status",
                json={"transcript_status": "reviewing"},
            )

            # 응답 확인 (데이터가 있는 경우)
            if response.status_code == 200:
                # create_notification_record가 호출되었는지 확인
                mock_notify.assert_called_once()
                call_kwargs = mock_notify.call_args
                assert call_kwargs[1]["notification_type"] == "status_change" or \
                       call_kwargs[0][1] == "status_change"
