"""의원 API 엔드포인트 테스트"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_supabase
from app.main import app


@pytest.fixture
def mock_supabase():
    client = MagicMock()
    return client


@pytest.fixture
def client(mock_supabase):
    app.dependency_overrides[get_supabase] = lambda: mock_supabase
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestListCouncilors:
    def test_returns_all_active(self, client, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
            data=[
                {"id": "1", "name": "김의원", "party": "민주당", "is_active": True},
            ]
        )

        response = client.get("/api/councilors")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "김의원"

    def test_search_filter(self, client, mock_supabase):
        mock_supabase.table.return_value.select.return_value.or_.return_value.order.return_value.execute.return_value = MagicMock(
            data=[{"id": "1", "name": "김의원"}]
        )

        response = client.get("/api/councilors?q=김")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1


class TestGetCouncilor:
    def test_found(self, client, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": "1", "name": "김의원", "party": "민주당"}]
        )

        response = client.get("/api/councilors/1")
        assert response.status_code == 200
        assert response.json()["name"] == "김의원"

    def test_not_found(self, client, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[]
        )

        response = client.get("/api/councilors/nonexistent")
        assert response.status_code == 404


class TestSyncCouncilors:
    def test_sync_success(self, client, mock_supabase):
        with patch(
            "app.api.councilors.CouncilorSyncService.sync_from_api",
            new_callable=AsyncMock,
            return_value={"added": 5, "updated": 3, "deactivated": 1},
        ):
            response = client.post("/api/councilors/sync")
            assert response.status_code == 200
            data = response.json()
            assert data["added"] == 5
            assert data["updated"] == 3
            assert data["deactivated"] == 1
            assert "message" in data

    def test_sync_failure(self, client, mock_supabase):
        with patch(
            "app.api.councilors.CouncilorSyncService.sync_from_api",
            new_callable=AsyncMock,
            side_effect=Exception("API 연결 실패"),
        ):
            response = client.post("/api/councilors/sync")
            assert response.status_code == 502


class TestSyncStatus:
    def test_returns_status(self, client, mock_supabase):
        # get_last_sync_time
        mock_supabase.table.return_value.select.return_value.not_.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"synced_at": "2026-03-16T00:00:00Z"}]
        )
        # get_all_active
        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
            data=[{"id": "1"}, {"id": "2"}]
        )

        response = client.get("/api/councilors/sync-status")
        assert response.status_code == 200
        data = response.json()
        assert "last_synced_at" in data
        assert "active_count" in data
