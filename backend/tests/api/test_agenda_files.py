"""Agenda Files API 테스트 - 부록파일 업로드/다운로드

# @TASK P11-T3.1 - 부록파일 업로드/다운로드 API 테스트
# @TEST backend/tests/api/test_agenda_files.py

TDD RED -> GREEN
"""

import io
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_supabase
from app.main import app
from tests.conftest import MockSupabaseQuery, MockSupabaseResponse


# =============================================================================
# Mock Supabase Client
# =============================================================================


class FilesMockSupabaseQuery(MockSupabaseQuery):
    """파일 API 테스트용 Supabase 쿼리 빌더"""

    def __init__(self, data: list | None = None, count: int | None = None):
        super().__init__(data, count)
        self._filters: dict[str, str] = {}
        self._insert_data = None

    def eq(self, column: str, value: str) -> "FilesMockSupabaseQuery":
        self._filters[column] = str(value)
        return self

    def select(self, *args, **kwargs) -> "FilesMockSupabaseQuery":
        if kwargs.get("count") == "exact":
            self._count = len(self._data)
        return self

    def order(self, *args, **kwargs) -> "FilesMockSupabaseQuery":
        return self

    def limit(self, *args, **kwargs) -> "FilesMockSupabaseQuery":
        return self

    def insert(self, data: dict) -> "FilesMockSupabaseQuery":
        self._insert_data = data
        return self

    def delete(self) -> "FilesMockSupabaseQuery":
        return self

    def execute(self) -> MockSupabaseResponse:
        if self._insert_data is not None:
            return MockSupabaseResponse(data=[self._insert_data])

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


class FilesMockSupabaseClient:
    """파일 테스트용 Supabase 클라이언트 모킹"""

    def __init__(self, table_data: dict[str, list] | None = None):
        self._table_data = table_data or {}

    def table(self, name: str) -> FilesMockSupabaseQuery:
        data = self._table_data.get(name, [])
        return FilesMockSupabaseQuery(data=data)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def meeting_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def agenda_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def file_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def sample_file_meta(meeting_id: str, agenda_id: str, file_id: str, tmp_path: Path) -> dict:
    """테스트용 파일 메타데이터 (실제 파일 생성 포함)"""
    test_file = tmp_path / f"{file_id}.pdf"
    test_file.write_text("dummy content")
    return {
        "id": file_id,
        "agenda_id": agenda_id,
        "meeting_id": meeting_id,
        "filename": "test_document.pdf",
        "file_path": str(test_file),
        "file_size": 13,
        "mime_type": "application/pdf",
        "created_at": "2026-01-15T10:00:00Z",
    }


# =============================================================================
# POST - 파일 업로드 테스트
# =============================================================================


class TestUploadAgendaFile:
    """POST /api/meetings/{mid}/agendas/{aid}/files 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_upload_file_returns_201(self, meeting_id: str, agenda_id: str):
        """파일 업로드 시 201을 반환한다"""
        mock_client = FilesMockSupabaseClient(table_data={"agenda_files": []})
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        file_content = b"test file content"
        response = client.post(
            f"/api/meetings/{meeting_id}/agendas/{agenda_id}/files",
            files={"file": ("test.txt", io.BytesIO(file_content), "text/plain")},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["filename"] == "test.txt"
        assert data["meeting_id"] == meeting_id
        assert data["agenda_id"] == agenda_id
        assert data["mime_type"] == "text/plain"

    def test_upload_file_stores_metadata(self, meeting_id: str, agenda_id: str):
        """업로드 시 파일 메타데이터가 저장된다"""
        mock_client = FilesMockSupabaseClient(table_data={"agenda_files": []})
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        file_content = b"hello world"
        response = client.post(
            f"/api/meetings/{meeting_id}/agendas/{agenda_id}/files",
            files={"file": ("document.pdf", io.BytesIO(file_content), "application/pdf")},
        )

        data = response.json()
        assert "id" in data
        assert data["file_size"] == len(file_content)

    def test_upload_file_without_file_returns_422(self, meeting_id: str, agenda_id: str):
        """파일 없이 요청하면 422를 반환한다"""
        mock_client = FilesMockSupabaseClient(table_data={"agenda_files": []})
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.post(
            f"/api/meetings/{meeting_id}/agendas/{agenda_id}/files",
        )

        assert response.status_code == 422


# =============================================================================
# GET - 파일 목록 조회 테스트
# =============================================================================


class TestListAgendaFiles:
    """GET /api/meetings/{mid}/agendas/{aid}/files 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_list_files_returns_200(self, meeting_id: str, agenda_id: str):
        """파일 목록 조회 시 200을 반환한다"""
        mock_client = FilesMockSupabaseClient(table_data={"agenda_files": []})
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(
            f"/api/meetings/{meeting_id}/agendas/{agenda_id}/files"
        )

        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_files_empty(self, meeting_id: str, agenda_id: str):
        """파일이 없으면 빈 리스트를 반환한다"""
        mock_client = FilesMockSupabaseClient(table_data={"agenda_files": []})
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(
            f"/api/meetings/{meeting_id}/agendas/{agenda_id}/files"
        )

        assert response.json() == []

    def test_list_files_with_data(
        self, meeting_id: str, agenda_id: str, sample_file_meta: dict
    ):
        """파일이 있으면 목록을 반환한다"""
        mock_client = FilesMockSupabaseClient(
            table_data={"agenda_files": [sample_file_meta]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(
            f"/api/meetings/{meeting_id}/agendas/{agenda_id}/files"
        )

        data = response.json()
        assert len(data) == 1
        assert data[0]["filename"] == "test_document.pdf"


# =============================================================================
# GET - 파일 다운로드 테스트
# =============================================================================


class TestDownloadAgendaFile:
    """GET /api/meetings/{mid}/agendas/{aid}/files/{fid}/download 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_download_file_returns_200(
        self, meeting_id: str, agenda_id: str, file_id: str, sample_file_meta: dict
    ):
        """파일 다운로드 시 200을 반환한다"""
        mock_client = FilesMockSupabaseClient(
            table_data={"agenda_files": [sample_file_meta]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(
            f"/api/meetings/{meeting_id}/agendas/{agenda_id}/files/{file_id}/download"
        )

        assert response.status_code == 200

    def test_download_file_not_found_returns_404(
        self, meeting_id: str, agenda_id: str
    ):
        """파일이 없으면 404를 반환한다"""
        mock_client = FilesMockSupabaseClient(table_data={"agenda_files": []})
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        non_existent_id = str(uuid.uuid4())
        response = client.get(
            f"/api/meetings/{meeting_id}/agendas/{agenda_id}/files/{non_existent_id}/download"
        )

        assert response.status_code == 404

    def test_download_file_disk_missing_returns_404(
        self, meeting_id: str, agenda_id: str, file_id: str
    ):
        """디스크에 파일이 없으면 404를 반환한다"""
        file_meta = {
            "id": file_id,
            "agenda_id": agenda_id,
            "meeting_id": meeting_id,
            "filename": "missing.pdf",
            "file_path": "/nonexistent/path/missing.pdf",
            "file_size": 100,
            "mime_type": "application/pdf",
        }
        mock_client = FilesMockSupabaseClient(
            table_data={"agenda_files": [file_meta]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(
            f"/api/meetings/{meeting_id}/agendas/{agenda_id}/files/{file_id}/download"
        )

        assert response.status_code == 404
        assert "디스크" in response.json()["detail"]


# =============================================================================
# DELETE - 파일 삭제 테스트
# =============================================================================


class TestDeleteAgendaFile:
    """DELETE /api/meetings/{mid}/agendas/{aid}/files/{fid} 테스트"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_delete_file_returns_200(
        self, meeting_id: str, agenda_id: str, file_id: str, sample_file_meta: dict
    ):
        """파일 삭제 시 200을 반환한다"""
        mock_client = FilesMockSupabaseClient(
            table_data={"agenda_files": [sample_file_meta]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.delete(
            f"/api/meetings/{meeting_id}/agendas/{agenda_id}/files/{file_id}"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] is True
        assert data["file_id"] == file_id

    def test_delete_file_not_found_returns_404(
        self, meeting_id: str, agenda_id: str
    ):
        """파일이 없으면 404를 반환한다"""
        mock_client = FilesMockSupabaseClient(table_data={"agenda_files": []})
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        non_existent_id = str(uuid.uuid4())
        response = client.delete(
            f"/api/meetings/{meeting_id}/agendas/{agenda_id}/files/{non_existent_id}"
        )

        assert response.status_code == 404
