"""요구자료 API 테스트 (목록/수정/수동추가/스캔 가드)."""

import uuid
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from app.core.auth_middleware import get_current_user
from app.core.database import get_supabase
from app.main import app


class _MockResponse:
    def __init__(self, data: list):
        self.data = data


class _MockQuery:
    def __init__(self, data: list, log: list, table: str):
        self._data = data
        self._log = log
        self._table = table
        self._update_payload = None

    def select(self, *a, **kw):
        return self

    def eq(self, *a, **kw):
        return self

    def order(self, *a, **kw):
        return self

    def range(self, *a, **kw):
        return self

    def limit(self, *a, **kw):
        return self

    def delete(self, *a, **kw):
        self._log.append({"table": self._table, "op": "delete"})
        return self

    def insert(self, payload, **kw):
        self._log.append({"table": self._table, "op": "insert", "payload": payload})
        rows = payload if isinstance(payload, list) else [payload]
        self._data = rows
        return self

    def update(self, payload, **kw):
        self._update_payload = payload
        self._log.append({"table": self._table, "op": "update", "payload": payload})
        return self

    def execute(self):
        if self._update_payload and self._data:
            return _MockResponse([{**self._data[0], **self._update_payload}])
        return _MockResponse(self._data)


class _MockClient:
    def __init__(self, requests_rows: list | None = None):
        self._rows = requests_rows or []
        self.log: list = []

    def table(self, name: str):
        if name == "material_requests":
            return _MockQuery(self._rows, self.log, name)
        return _MockQuery([], self.log, name)


@pytest.fixture
def meeting_id() -> str:
    return str(uuid.uuid4())


# 편집 계열은 직원 역할만(2026-09-12) — 기본 클라이언트는 로그인한 위원회 직원으로 호출한다
_STAFF = {"id": "u-staff", "username": "staff1", "display_name": "직원", "role": "committee_staff"}


def _client(mock: _MockClient, user: dict | None = _STAFF) -> Generator[TestClient, None, None]:
    app.dependency_overrides[get_supabase] = lambda: mock
    app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestEditRequiresStaff:
    """로그인 없이·권한 없이 요구자료를 바꾸거나 AI 스캔을 돌릴 수 없다."""

    @pytest.mark.parametrize("method,path_suffix,body", [
        ("patch", "/material-requests/r1", {"status": "confirmed"}),
        ("post", "/material-requests", {"summary": "수동 추가"}),
        ("post", "/material-requests/scan", None),
    ])
    def test_anonymous_401(self, meeting_id, method, path_suffix, body):
        mock = _MockClient([{"id": "r1", "meeting_id": meeting_id, "status": "detected"}])
        for client in _client(mock, user=None):
            resp = getattr(client, method)(f"/api/meetings/{meeting_id}{path_suffix}", json=body)
            assert resp.status_code == 401
        assert not any(e["op"] in ("insert", "update", "delete") for e in mock.log)

    def test_viewer_role_403(self, meeting_id):
        viewer = {**_STAFF, "role": "viewer"}
        for client in _client(_MockClient([{"id": "r1"}]), user=viewer):
            resp = client.patch(f"/api/meetings/{meeting_id}/material-requests/r1", json={"status": "dismissed"})
            assert resp.status_code == 403

    def test_list_stays_public(self, meeting_id):
        for client in _client(_MockClient([]), user=None):
            assert client.get(f"/api/meetings/{meeting_id}/material-requests").status_code == 200


class TestListMaterialRequests:
    def test_returns_rows(self, meeting_id):
        rows = [{"id": "r1", "meeting_id": meeting_id, "summary": "지방채 발행 검토 자료", "status": "detected"}]
        for client in _client(_MockClient(rows)):
            resp = client.get(f"/api/meetings/{meeting_id}/material-requests")
            assert resp.status_code == 200
            assert resp.json()[0]["summary"] == "지방채 발행 검토 자료"

    def test_empty_on_error_fail_soft(self, meeting_id):
        class _Broken(_MockClient):
            def table(self, name):
                raise RuntimeError("db down")

        for client in _client(_Broken()):
            resp = client.get(f"/api/meetings/{meeting_id}/material-requests")
            assert resp.status_code == 200
            assert resp.json() == []


class TestUpdateMaterialRequest:
    def test_confirm_status(self, meeting_id):
        rows = [{"id": "r1", "meeting_id": meeting_id, "summary": "s", "status": "detected"}]
        for client in _client(_MockClient(rows)):
            resp = client.patch(
                f"/api/meetings/{meeting_id}/material-requests/r1",
                json={"status": "confirmed"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "confirmed"

    def test_invalid_status_422(self, meeting_id):
        for client in _client(_MockClient([{"id": "r1"}])):
            resp = client.patch(
                f"/api/meetings/{meeting_id}/material-requests/r1",
                json={"status": "banana"},
            )
            assert resp.status_code == 422

    def test_not_found_404(self, meeting_id):
        for client in _client(_MockClient([])):
            resp = client.patch(
                f"/api/meetings/{meeting_id}/material-requests/nope",
                json={"status": "dismissed"},
            )
            assert resp.status_code == 404

    def test_no_fields_422(self, meeting_id):
        for client in _client(_MockClient([{"id": "r1"}])):
            resp = client.patch(
                f"/api/meetings/{meeting_id}/material-requests/r1", json={}
            )
            assert resp.status_code == 422


class TestCreateManual:
    def test_manual_add(self, meeting_id):
        mock = _MockClient()
        for client in _client(mock):
            resp = client.post(
                f"/api/meetings/{meeting_id}/material-requests",
                json={"summary": "미수납액 현황", "councilor_name": "오창준"},
            )
            assert resp.status_code == 201
            body = resp.json()
            assert body["summary"] == "미수납액 현황"
            assert body["source"] == "manual"
            assert body["status"] == "confirmed"


class TestScan:
    def test_scan_requires_openai_key(self, meeting_id, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "openai_api_key", "")
        for client in _client(_MockClient()):
            resp = client.post(f"/api/meetings/{meeting_id}/material-requests/scan")
            assert resp.status_code == 503

    def test_scan_calls_service(self, meeting_id, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "openai_api_key", "sk-test")

        async def fake_scan(supabase, mid):
            return [{"id": "r1", "meeting_id": mid, "summary": "지방채 발행 검토 자료"}]

        import app.services.material_request_detector as svc

        monkeypatch.setattr(svc, "scan_meeting_subtitles", fake_scan)
        for client in _client(_MockClient()):
            resp = client.post(f"/api/meetings/{meeting_id}/material-requests/scan")
            assert resp.status_code == 200
            assert resp.json()["count"] == 1
