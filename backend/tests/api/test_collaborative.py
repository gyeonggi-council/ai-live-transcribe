"""Collaborative Editing API 테스트 - 공동교정/편집

# @TASK P12-T2.1 - 공동교정/편집 API 테스트
# @TEST backend/tests/api/test_collaborative.py

TDD RED -> GREEN
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_supabase
from app.main import app
from tests.conftest import MockSupabaseQuery, MockSupabaseResponse


# =============================================================================
# Mock Supabase Client
# =============================================================================


class CollaborativeMockSupabaseQuery(MockSupabaseQuery):
    """공동교정 API 테스트용 Supabase 쿼리 빌더"""

    def __init__(self, data: list | None = None, count: int | None = None):
        super().__init__(data, count)
        self._filters: dict[str, str] = {}
        self._insert_data = None
        self._update_data = None
        self._is_delete = False

    def eq(self, column: str, value) -> "CollaborativeMockSupabaseQuery":
        self._filters[column] = str(value)
        return self

    def select(self, *args, **kwargs) -> "CollaborativeMockSupabaseQuery":
        if kwargs.get("count") == "exact":
            self._count = len(self._data)
        return self

    def order(self, *args, **kwargs) -> "CollaborativeMockSupabaseQuery":
        return self

    def limit(self, *args, **kwargs) -> "CollaborativeMockSupabaseQuery":
        return self

    def insert(self, data: dict) -> "CollaborativeMockSupabaseQuery":
        self._insert_data = data
        return self

    def update(self, data: dict) -> "CollaborativeMockSupabaseQuery":
        self._update_data = data
        return self

    def delete(self) -> "CollaborativeMockSupabaseQuery":
        self._is_delete = True
        return self

    def execute(self) -> MockSupabaseResponse:
        if self._insert_data is not None:
            return MockSupabaseResponse(data=[self._insert_data])

        if self._update_data is not None:
            if self._filters:
                matched = []
                for row in self._data:
                    match = all(
                        str(row.get(col, "")) == val
                        for col, val in self._filters.items()
                    )
                    if match:
                        matched.append({**row, **self._update_data})
                return MockSupabaseResponse(data=matched)
            return MockSupabaseResponse(data=[])

        if self._is_delete:
            return MockSupabaseResponse(data=[])

        if self._filters:
            matched = []
            for row in self._data:
                match = all(
                    str(row.get(col, "")) == val
                    for col, val in self._filters.items()
                )
                if match:
                    matched.append(row)
            return MockSupabaseResponse(data=matched, count=len(matched))
        return MockSupabaseResponse(data=self._data, count=self._count)


class CollaborativeMockSupabaseClient:
    """공동교정 테스트용 Supabase 클라이언트 모킹"""

    def __init__(self, table_data: dict[str, list] | None = None):
        self._table_data = table_data or {}

    def table(self, name: str) -> CollaborativeMockSupabaseQuery:
        data = self._table_data.get(name, [])
        return CollaborativeMockSupabaseQuery(data=data)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def meeting_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def session_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def subtitle_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def comment_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def sample_session(meeting_id: str, session_id: str) -> dict:
    return {
        "id": session_id,
        "meeting_id": meeting_id,
        "editor_name": "편집자A",
        "started_at": "2026-02-15T10:00:00Z",
        "last_active_at": "2026-02-15T10:05:00Z",
        "status": "active",
    }


@pytest.fixture
def sample_comment(meeting_id: str, subtitle_id: str, comment_id: str) -> dict:
    return {
        "id": comment_id,
        "subtitle_id": subtitle_id,
        "meeting_id": meeting_id,
        "author_name": "검토자A",
        "content": "이 부분 확인 필요합니다.",
        "resolved": False,
        "created_at": "2026-02-15T10:00:00Z",
    }


# =============================================================================
# Edit Sessions - 편집 세션
# =============================================================================


class TestListEditSessions:
    """GET /api/meetings/{mid}/edit-sessions 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_list_sessions_returns_200(self, meeting_id: str):
        """편집 세션 목록 조회 시 200을 반환한다"""
        mock_client = CollaborativeMockSupabaseClient(
            table_data={"edit_sessions": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(f"/api/meetings/{meeting_id}/edit-sessions")

        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_sessions_returns_active_only(
        self, meeting_id: str, sample_session: dict
    ):
        """활성 세션만 반환한다"""
        mock_client = CollaborativeMockSupabaseClient(
            table_data={"edit_sessions": [sample_session]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(f"/api/meetings/{meeting_id}/edit-sessions")

        data = response.json()
        assert len(data) == 1
        assert data[0]["status"] == "active"


class TestCreateEditSession:
    """POST /api/meetings/{mid}/edit-sessions 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_create_session_returns_201(self, meeting_id: str):
        """편집 세션 생성 시 201을 반환한다"""
        mock_client = CollaborativeMockSupabaseClient(
            table_data={"edit_sessions": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.post(
            f"/api/meetings/{meeting_id}/edit-sessions",
            json={"editor_name": "편집자A"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["editor_name"] == "편집자A"
        assert data["status"] == "active"
        assert data["meeting_id"] == meeting_id

    def test_create_session_missing_editor_name_returns_422(self, meeting_id: str):
        """편집자 이름 없이 요청하면 422를 반환한다"""
        mock_client = CollaborativeMockSupabaseClient(
            table_data={"edit_sessions": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.post(
            f"/api/meetings/{meeting_id}/edit-sessions",
            json={},
        )

        assert response.status_code == 422


class TestUpdateEditSession:
    """PATCH /api/meetings/{mid}/edit-sessions/{sid} 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_update_session_returns_200(
        self, meeting_id: str, session_id: str, sample_session: dict
    ):
        """편집 세션 업데이트 시 200을 반환한다"""
        mock_client = CollaborativeMockSupabaseClient(
            table_data={"edit_sessions": [sample_session]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.patch(
            f"/api/meetings/{meeting_id}/edit-sessions/{session_id}",
            json={"status": "completed"},
        )

        assert response.status_code == 200

    def test_update_session_invalid_status_returns_400(
        self, meeting_id: str, session_id: str, sample_session: dict
    ):
        """잘못된 상태값이면 400을 반환한다"""
        mock_client = CollaborativeMockSupabaseClient(
            table_data={"edit_sessions": [sample_session]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.patch(
            f"/api/meetings/{meeting_id}/edit-sessions/{session_id}",
            json={"status": "invalid"},
        )

        assert response.status_code == 400

    def test_update_session_not_found_returns_404(self, meeting_id: str):
        """존재하지 않는 세션 업데이트 시 404를 반환한다"""
        mock_client = CollaborativeMockSupabaseClient(
            table_data={"edit_sessions": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        non_existent_id = str(uuid.uuid4())
        response = client.patch(
            f"/api/meetings/{meeting_id}/edit-sessions/{non_existent_id}",
            json={"status": "completed"},
        )

        assert response.status_code == 404


class TestDeleteEditSession:
    """DELETE /api/meetings/{mid}/edit-sessions/{sid} 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_delete_session_returns_200(
        self, meeting_id: str, session_id: str, sample_session: dict
    ):
        """편집 세션 종료 시 200을 반환한다"""
        mock_client = CollaborativeMockSupabaseClient(
            table_data={"edit_sessions": [sample_session]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.delete(
            f"/api/meetings/{meeting_id}/edit-sessions/{session_id}"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] is True
        assert data["session_id"] == session_id

    def test_delete_session_not_found_returns_404(self, meeting_id: str):
        """존재하지 않는 세션 종료 시 404를 반환한다"""
        mock_client = CollaborativeMockSupabaseClient(
            table_data={"edit_sessions": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        non_existent_id = str(uuid.uuid4())
        response = client.delete(
            f"/api/meetings/{meeting_id}/edit-sessions/{non_existent_id}"
        )

        assert response.status_code == 404


# =============================================================================
# Comments - 코멘트
# =============================================================================


class TestListComments:
    """GET /api/meetings/{mid}/comments 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_list_comments_returns_200(self, meeting_id: str):
        """코멘트 목록 조회 시 200을 반환한다"""
        mock_client = CollaborativeMockSupabaseClient(
            table_data={"subtitle_comments": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(f"/api/meetings/{meeting_id}/comments")

        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_comments_with_data(
        self, meeting_id: str, sample_comment: dict
    ):
        """코멘트가 있으면 목록을 반환한다"""
        mock_client = CollaborativeMockSupabaseClient(
            table_data={"subtitle_comments": [sample_comment]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(f"/api/meetings/{meeting_id}/comments")

        data = response.json()
        assert len(data) == 1
        assert data[0]["author_name"] == "검토자A"

    def test_list_comments_with_subtitle_filter(
        self, meeting_id: str, subtitle_id: str, sample_comment: dict
    ):
        """subtitle_id 필터로 특정 자막의 코멘트만 조회한다"""
        mock_client = CollaborativeMockSupabaseClient(
            table_data={"subtitle_comments": [sample_comment]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(
            f"/api/meetings/{meeting_id}/comments?subtitle_id={subtitle_id}"
        )

        assert response.status_code == 200


class TestCreateComment:
    """POST /api/meetings/{mid}/subtitles/{sid}/comments 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_create_comment_returns_201(self, meeting_id: str, subtitle_id: str):
        """코멘트 생성 시 201을 반환한다"""
        mock_client = CollaborativeMockSupabaseClient(
            table_data={"subtitle_comments": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.post(
            f"/api/meetings/{meeting_id}/subtitles/{subtitle_id}/comments",
            json={
                "author_name": "검토자B",
                "content": "수정이 필요합니다.",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["author_name"] == "검토자B"
        assert data["content"] == "수정이 필요합니다."
        assert data["resolved"] is False
        assert data["subtitle_id"] == subtitle_id
        assert data["meeting_id"] == meeting_id

    def test_create_comment_missing_fields_returns_422(
        self, meeting_id: str, subtitle_id: str
    ):
        """필수 필드 없이 요청하면 422를 반환한다"""
        mock_client = CollaborativeMockSupabaseClient(
            table_data={"subtitle_comments": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.post(
            f"/api/meetings/{meeting_id}/subtitles/{subtitle_id}/comments",
            json={"author_name": "검토자"},
        )

        assert response.status_code == 422


class TestUpdateComment:
    """PATCH /api/meetings/{mid}/comments/{cid} 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_update_comment_resolve_returns_200(
        self, meeting_id: str, comment_id: str, sample_comment: dict
    ):
        """코멘트 해결 처리 시 200을 반환한다"""
        mock_client = CollaborativeMockSupabaseClient(
            table_data={"subtitle_comments": [sample_comment]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.patch(
            f"/api/meetings/{meeting_id}/comments/{comment_id}",
            json={"resolved": True},
        )

        assert response.status_code == 200

    def test_update_comment_not_found_returns_404(self, meeting_id: str):
        """존재하지 않는 코멘트 수정 시 404를 반환한다"""
        mock_client = CollaborativeMockSupabaseClient(
            table_data={"subtitle_comments": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        non_existent_id = str(uuid.uuid4())
        response = client.patch(
            f"/api/meetings/{meeting_id}/comments/{non_existent_id}",
            json={"resolved": True},
        )

        assert response.status_code == 404

    def test_update_comment_empty_body_returns_400(
        self, meeting_id: str, comment_id: str, sample_comment: dict
    ):
        """수정할 필드가 없으면 400을 반환한다"""
        mock_client = CollaborativeMockSupabaseClient(
            table_data={"subtitle_comments": [sample_comment]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.patch(
            f"/api/meetings/{meeting_id}/comments/{comment_id}",
            json={},
        )

        assert response.status_code == 400


class TestDeleteComment:
    """DELETE /api/meetings/{mid}/comments/{cid} 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_delete_comment_returns_200(
        self, meeting_id: str, comment_id: str, sample_comment: dict
    ):
        """코멘트 삭제 시 200을 반환한다"""
        mock_client = CollaborativeMockSupabaseClient(
            table_data={"subtitle_comments": [sample_comment]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.delete(
            f"/api/meetings/{meeting_id}/comments/{comment_id}"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] is True
        assert data["comment_id"] == comment_id

    def test_delete_comment_not_found_returns_404(self, meeting_id: str):
        """존재하지 않는 코멘트 삭제 시 404를 반환한다"""
        mock_client = CollaborativeMockSupabaseClient(
            table_data={"subtitle_comments": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        non_existent_id = str(uuid.uuid4())
        response = client.delete(
            f"/api/meetings/{meeting_id}/comments/{non_existent_id}"
        )

        assert response.status_code == 404
