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


# ─── 사진 프록시 (2026-09-16) ────────────────────────────────────────────────
def test_photo_cache_dir_is_writable_path():
    """캐시 자리는 **쓸 수 있는 곳**이어야 한다.

    컨테이너 루트가 readOnlyRootFilesystem 이라 예전 자리(/app/data/photo_cache)는
    `[Errno 30] Read-only file system` 으로 전 요청이 500 이었다(2026-09-16 운영).
    """
    from app.api import councilors as mod

    assert not mod._PHOTO_CACHE_DIR.startswith("/app/data"), mod._PHOTO_CACHE_DIR
    assert mod._PHOTO_CACHE_DIR.startswith("/tmp") or "PHOTO_CACHE_DIR" in mod.os.environ


def test_bad_uuid_becomes_404_not_500():
    """PostgREST 의 22P02("uuid 가 아니다")는 404 여야 한다.

    빈 id 로 만들어진 주소(`/api/councilors//photo` → id 가 "photo")가 500 으로 보이면
    운영 오류 로그가 진짜 오류와 섞인다(2026-09-16 실측).
    """
    from fastapi import HTTPException

    from app.api.councilors import _not_found_if_bad_id

    class _ApiError(Exception):
        def __init__(self, payload):
            super().__init__(payload)
            self.code = payload.get("code")

    for exc in (
        _ApiError({"message": 'invalid input syntax for type uuid: "photo"', "code": "22P02"}),
        Exception('invalid input syntax for type uuid: "detail"'),
    ):
        with pytest.raises(HTTPException) as caught:
            _not_found_if_bad_id(exc)
        assert caught.value.status_code == 404

    # 다른 오류는 그대로 통과시킨다 — 삼켜서 404 로 위장하면 진짜 고장을 못 본다
    _not_found_if_bad_id(Exception("connection refused"))
