"""Stenography API 테스트 - 속기록 관리

# @TASK P12-T1.1 - 속기록 관리 API 테스트
# @TEST backend/tests/api/test_stenography.py

TDD RED -> GREEN
"""

import io
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_supabase
from app.main import app
from tests.conftest import (
    TEST_ADMIN_USER,
    MockSupabaseQuery,
    MockSupabaseResponse,
    get_admin_auth_header,
)

# 인가가 필요한 엔드포인트 테스트용 공통 헤더
_AUTH = get_admin_auth_header()


# =============================================================================
# Mock Supabase Client
# =============================================================================


class StenographyMockSupabaseQuery(MockSupabaseQuery):
    """속기록 API 테스트용 Supabase 쿼리 빌더"""

    def __init__(self, data: list | None = None, count: int | None = None):
        super().__init__(data, count)
        self._filters: dict[str, str] = {}
        self._insert_data = None
        self._update_data = None
        self._is_delete = False

    def eq(self, column: str, value) -> "StenographyMockSupabaseQuery":
        self._filters[column] = str(value)
        return self

    def select(self, *args, **kwargs) -> "StenographyMockSupabaseQuery":
        if kwargs.get("count") == "exact":
            self._count = len(self._data)
        return self

    def order(self, *args, **kwargs) -> "StenographyMockSupabaseQuery":
        return self

    def limit(self, *args, **kwargs) -> "StenographyMockSupabaseQuery":
        return self

    def insert(self, data: dict) -> "StenographyMockSupabaseQuery":
        self._insert_data = data
        return self

    def update(self, data: dict) -> "StenographyMockSupabaseQuery":
        self._update_data = data
        return self

    def delete(self) -> "StenographyMockSupabaseQuery":
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


class StenographyMockSupabaseClient:
    """속기록 테스트용 Supabase 클라이언트 모킹"""

    def __init__(self, table_data: dict[str, list] | None = None):
        self._table_data = table_data or {}
        # auth_middleware가 users 테이블을 조회할 수 있게 기본 admin 사용자 포함
        if "users" not in self._table_data:
            self._table_data["users"] = [TEST_ADMIN_USER]

    def table(self, name: str) -> StenographyMockSupabaseQuery:
        data = self._table_data.get(name, [])
        return StenographyMockSupabaseQuery(data=data)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def meeting_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def record_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def sample_record(meeting_id: str, record_id: str) -> dict:
    return {
        "id": record_id,
        "meeting_id": meeting_id,
        "content": "첫 번째 줄\n두 번째 줄\n세 번째 줄",
        "stenographer_name": "홍길동",
        "status": "draft",
        "file_path": None,
        "filename": None,
        "file_size": None,
        "created_at": "2026-02-15T10:00:00Z",
        "updated_at": "2026-02-15T10:00:00Z",
    }


@pytest.fixture
def sample_subtitles(meeting_id: str) -> list[dict]:
    return [
        {
            "id": str(uuid.uuid4()),
            "meeting_id": meeting_id,
            "text": "첫 번째 자막",
            "start_time": 0.0,
            "end_time": 5.0,
            "speaker": "화자 1",
        },
        {
            "id": str(uuid.uuid4()),
            "meeting_id": meeting_id,
            "text": "두 번째 자막",
            "start_time": 5.0,
            "end_time": 10.0,
            "speaker": "화자 2",
        },
    ]


# =============================================================================
# GET - 속기록 목록 조회
# =============================================================================


class TestListStenography:
    """GET /api/meetings/{mid}/stenography 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_list_returns_200(self, meeting_id: str):
        """속기록 목록 조회 시 200을 반환한다"""
        mock_client = StenographyMockSupabaseClient(
            table_data={"stenography_records": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(f"/api/meetings/{meeting_id}/stenography")

        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_empty_returns_empty_list(self, meeting_id: str):
        """속기록이 없으면 빈 리스트를 반환한다"""
        mock_client = StenographyMockSupabaseClient(
            table_data={"stenography_records": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(f"/api/meetings/{meeting_id}/stenography")

        assert response.json() == []

    def test_list_with_data(self, meeting_id: str, sample_record: dict):
        """속기록이 있으면 목록을 반환한다"""
        mock_client = StenographyMockSupabaseClient(
            table_data={"stenography_records": [sample_record]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(f"/api/meetings/{meeting_id}/stenography")

        data = response.json()
        assert len(data) == 1
        assert data[0]["stenographer_name"] == "홍길동"


# =============================================================================
# POST - 속기록 등록
# =============================================================================


class TestCreateStenography:
    """POST /api/meetings/{mid}/stenography 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_create_with_text_returns_201(self, meeting_id: str):
        """텍스트로 속기록 등록 시 201을 반환한다"""
        mock_client = StenographyMockSupabaseClient(
            table_data={"stenography_records": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.post(
            f"/api/meetings/{meeting_id}/stenography",
            data={
                "stenographer_name": "홍길동",
                "content": "속기록 내용입니다.",
            },
            headers=_AUTH,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["stenographer_name"] == "홍길동"
        assert data["content"] == "속기록 내용입니다."
        assert data["status"] == "draft"
        assert data["meeting_id"] == meeting_id

    def test_create_with_file_returns_201(self, meeting_id: str):
        """파일로 속기록 등록 시 201을 반환한다"""
        mock_client = StenographyMockSupabaseClient(
            table_data={"stenography_records": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        file_content = b"stenography file content"
        response = client.post(
            f"/api/meetings/{meeting_id}/stenography",
            data={"stenographer_name": "김철수"},
            files={"file": ("steno.txt", io.BytesIO(file_content), "text/plain")},
            headers=_AUTH,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["filename"] == "steno.txt"
        assert data["file_size"] == len(file_content)

    def test_create_without_content_or_file_returns_400(self, meeting_id: str):
        """content도 file도 없으면 400을 반환한다"""
        mock_client = StenographyMockSupabaseClient(
            table_data={"stenography_records": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.post(
            f"/api/meetings/{meeting_id}/stenography",
            data={"stenographer_name": "홍길동"},
            headers=_AUTH,
        )

        assert response.status_code == 400
        assert "content" in response.json()["detail"] or "file" in response.json()["detail"]

    def test_create_without_stenographer_name_returns_422(self, meeting_id: str):
        """작성자명 없이 요청하면 422를 반환한다"""
        mock_client = StenographyMockSupabaseClient(
            table_data={"stenography_records": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.post(
            f"/api/meetings/{meeting_id}/stenography",
            data={"content": "내용"},
            headers=_AUTH,
        )

        assert response.status_code == 422


# =============================================================================
# PATCH - 속기록 수정
# =============================================================================


class TestUpdateStenography:
    """PATCH /api/meetings/{mid}/stenography/{rid} 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_update_content_returns_200(
        self, meeting_id: str, record_id: str, sample_record: dict
    ):
        """속기록 내용 수정 시 200을 반환한다"""
        mock_client = StenographyMockSupabaseClient(
            table_data={"stenography_records": [sample_record]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.patch(
            f"/api/meetings/{meeting_id}/stenography/{record_id}",
            json={"content": "수정된 내용"},
            headers=_AUTH,
        )

        assert response.status_code == 200

    def test_update_status_returns_200(
        self, meeting_id: str, record_id: str, sample_record: dict
    ):
        """속기록 상태 변경 시 200을 반환한다"""
        mock_client = StenographyMockSupabaseClient(
            table_data={"stenography_records": [sample_record]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.patch(
            f"/api/meetings/{meeting_id}/stenography/{record_id}",
            json={"status": "submitted"},
            headers=_AUTH,
        )

        assert response.status_code == 200

    def test_update_invalid_status_returns_400(
        self, meeting_id: str, record_id: str, sample_record: dict
    ):
        """잘못된 상태값이면 400을 반환한다"""
        mock_client = StenographyMockSupabaseClient(
            table_data={"stenography_records": [sample_record]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.patch(
            f"/api/meetings/{meeting_id}/stenography/{record_id}",
            json={"status": "invalid_status"},
            headers=_AUTH,
        )

        assert response.status_code == 400

    def test_update_not_found_returns_404(self, meeting_id: str):
        """존재하지 않는 속기록 수정 시 404를 반환한다"""
        mock_client = StenographyMockSupabaseClient(
            table_data={"stenography_records": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        non_existent_id = str(uuid.uuid4())
        response = client.patch(
            f"/api/meetings/{meeting_id}/stenography/{non_existent_id}",
            json={"content": "수정"},
            headers=_AUTH,
        )

        assert response.status_code == 404

    def test_update_empty_body_returns_400(
        self, meeting_id: str, record_id: str, sample_record: dict
    ):
        """수정할 필드가 없으면 400을 반환한다"""
        mock_client = StenographyMockSupabaseClient(
            table_data={"stenography_records": [sample_record]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.patch(
            f"/api/meetings/{meeting_id}/stenography/{record_id}",
            json={},
            headers=_AUTH,
        )

        assert response.status_code == 400


# =============================================================================
# DELETE - 속기록 삭제
# =============================================================================


class TestDeleteStenography:
    """DELETE /api/meetings/{mid}/stenography/{rid} 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_delete_returns_200(
        self, meeting_id: str, record_id: str, sample_record: dict
    ):
        """속기록 삭제 시 200을 반환한다"""
        mock_client = StenographyMockSupabaseClient(
            table_data={"stenography_records": [sample_record]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.delete(
            f"/api/meetings/{meeting_id}/stenography/{record_id}",
            headers=_AUTH,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] is True
        assert data["record_id"] == record_id

    def test_delete_not_found_returns_404(self, meeting_id: str):
        """존재하지 않는 속기록 삭제 시 404를 반환한다"""
        mock_client = StenographyMockSupabaseClient(
            table_data={"stenography_records": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        non_existent_id = str(uuid.uuid4())
        response = client.delete(
            f"/api/meetings/{meeting_id}/stenography/{non_existent_id}",
            headers=_AUTH,
        )

        assert response.status_code == 404


# =============================================================================
# GET - STT 자막과 비교
# =============================================================================


class TestCompareStenography:
    """GET /api/meetings/{mid}/stenography/{rid}/compare 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_compare_returns_200(
        self,
        meeting_id: str,
        record_id: str,
        sample_record: dict,
        sample_subtitles: list[dict],
    ):
        """비교 결과를 200으로 반환한다"""
        mock_client = StenographyMockSupabaseClient(
            table_data={
                "stenography_records": [sample_record],
                "subtitles": sample_subtitles,
            }
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(
            f"/api/meetings/{meeting_id}/stenography/{record_id}/compare"
        )

        assert response.status_code == 200
        data = response.json()
        assert "stenography_lines" in data
        assert "subtitle_texts" in data
        assert "total_steno_lines" in data
        assert "total_subtitle_count" in data

    def test_compare_splits_content_by_lines(
        self,
        meeting_id: str,
        record_id: str,
        sample_record: dict,
    ):
        """속기록 content가 줄 단위로 분리된다"""
        mock_client = StenographyMockSupabaseClient(
            table_data={
                "stenography_records": [sample_record],
                "subtitles": [],
            }
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(
            f"/api/meetings/{meeting_id}/stenography/{record_id}/compare"
        )

        data = response.json()
        # sample_record content: "첫 번째 줄\n두 번째 줄\n세 번째 줄"
        assert data["total_steno_lines"] == 3
        assert data["stenography_lines"] == ["첫 번째 줄", "두 번째 줄", "세 번째 줄"]

    def test_compare_not_found_returns_404(self, meeting_id: str):
        """존재하지 않는 속기록 비교 시 404를 반환한다"""
        mock_client = StenographyMockSupabaseClient(
            table_data={"stenography_records": [], "subtitles": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        non_existent_id = str(uuid.uuid4())
        response = client.get(
            f"/api/meetings/{meeting_id}/stenography/{non_existent_id}/compare"
        )

        assert response.status_code == 404

    def test_compare_includes_subtitle_texts(
        self,
        meeting_id: str,
        record_id: str,
        sample_record: dict,
        sample_subtitles: list[dict],
    ):
        """비교 결과에 자막 텍스트가 포함된다"""
        mock_client = StenographyMockSupabaseClient(
            table_data={
                "stenography_records": [sample_record],
                "subtitles": sample_subtitles,
            }
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(
            f"/api/meetings/{meeting_id}/stenography/{record_id}/compare"
        )

        data = response.json()
        assert data["total_subtitle_count"] == 2
        assert "첫 번째 자막" in data["subtitle_texts"]
        assert "두 번째 자막" in data["subtitle_texts"]
