"""낙관적 동시성 제어 테스트 - PATCH /api/meetings/{id}/stenography/{rid}/lines

version 필드를 통한 409 충돌 감지 및 정상 업데이트(버전 증가) 검증.
"""

import uuid

import pytest
from starlette.testclient import TestClient

from app.core.database import get_supabase
from app.main import app
from tests.conftest import (
    MockSupabaseResponse,
    TEST_ADMIN_USER,
    get_admin_auth_header,
)


# ---------------------------------------------------------------------------
# Supabase 모킹 (test_stenography_lines.py 패턴 재사용)
# ---------------------------------------------------------------------------


class ConcurrencyMockQuery:
    """낙관적 동시성 테스트용 Supabase 쿼리 모킹."""

    def __init__(self, client: "ConcurrencyMockClient", table_name: str):
        self._client = client
        self._table_name = table_name
        self._filters: list[tuple[str, str]] = []
        self._update_data: dict | None = None
        self._is_delete = False
        self._order_column: str | None = None
        self._limit_value: int | None = None

    def select(self, *args, **kwargs) -> "ConcurrencyMockQuery":
        return self

    def eq(self, column: str, value) -> "ConcurrencyMockQuery":
        self._filters.append((column, str(value)))
        return self

    def order(self, column: str, *args, **kwargs) -> "ConcurrencyMockQuery":
        self._order_column = column
        return self

    def limit(self, count: int) -> "ConcurrencyMockQuery":
        self._limit_value = count
        return self

    def insert(self, data) -> "ConcurrencyMockQuery":
        return self

    def update(self, data: dict) -> "ConcurrencyMockQuery":
        self._update_data = data
        return self

    def delete(self) -> "ConcurrencyMockQuery":
        self._is_delete = True
        return self

    def _matches(self, row: dict) -> bool:
        return all(str(row.get(column, "")) == value for column, value in self._filters)

    def _get_rows(self) -> list[dict]:
        return self._client._table_data.setdefault(self._table_name, [])

    def execute(self) -> MockSupabaseResponse:
        rows = self._get_rows()

        if self._is_delete:
            self._client._table_data[self._table_name] = [
                row for row in rows if not self._matches(row)
            ]
            return MockSupabaseResponse(data=[])

        if self._update_data is not None:
            updated_rows: list[dict] = []
            next_rows: list[dict] = []
            for row in rows:
                if self._matches(row):
                    merged = {**row, **self._update_data}
                    updated_rows.append(merged)
                    next_rows.append(merged)
                else:
                    next_rows.append(row)
            self._client._table_data[self._table_name] = next_rows
            return MockSupabaseResponse(data=updated_rows)

        selected = [row for row in rows if self._matches(row)]
        if self._order_column:
            selected = sorted(
                selected,
                key=lambda r: (r.get(self._order_column) is None, r.get(self._order_column)),
            )
        if self._limit_value is not None:
            selected = selected[: self._limit_value]
        return MockSupabaseResponse(data=selected, count=len(selected))


class ConcurrencyMockClient:
    """낙관적 동시성 테스트용 Supabase 클라이언트 모킹."""

    def __init__(self, table_data: dict[str, list] | None = None):
        self._table_data = table_data or {}
        # auth_middleware가 users 테이블을 조회하므로 반드시 포함
        if "users" not in self._table_data:
            self._table_data["users"] = [TEST_ADMIN_USER]

    def table(self, name: str) -> ConcurrencyMockQuery:
        return ConcurrencyMockQuery(client=self, table_name=name)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def meeting_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def record_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def line_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def sample_record(meeting_id: str, record_id: str) -> dict:
    return {
        "id": record_id,
        "meeting_id": meeting_id,
        "content": "첫째 줄",
        "stenographer_name": "테스트",
        "status": "draft",
        "file_path": None,
        "filename": None,
        "file_size": None,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }


def make_line(record_id: str, line_id: str, version: int = 1) -> dict:
    return {
        "id": line_id,
        "record_id": record_id,
        "sequence_no": 10,
        "text": "원본 텍스트",
        "speaker": "화자 1",
        "start_ms": 1000,
        "end_ms": 3000,
        "starts_new_paragraph": False,
        "version": version,
        "updated_by": None,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOptimisticConcurrency:
    def teardown_method(self):
        app.dependency_overrides.clear()

    # ------------------------------------------------------------------
    # Test 1: Stale version → 409
    # ------------------------------------------------------------------
    def test_stale_version_returns_409(
        self, meeting_id: str, record_id: str, line_id: str, sample_record: dict
    ):
        """클라이언트가 낡은 version을 보내면 409가 반환되어야 한다."""
        # DB에는 version=2인 행이 존재
        current_line = make_line(record_id, line_id, version=2)
        mock_client = ConcurrencyMockClient(
            table_data={
                "stenography_records": [sample_record],
                "stenography_lines": [current_line],
                "stenography_edit_history": [],
            }
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client

        client = TestClient(app)
        headers = get_admin_auth_header()

        # 클라이언트는 version=1(낡은 버전)을 보낸다
        payload = {
            "items": [
                {"id": line_id, "text": "수정된 텍스트", "version": 1}
            ]
        }
        response = client.patch(
            f"/api/meetings/{meeting_id}/stenography/{record_id}/lines",
            json=payload,
            headers=headers,
        )

        assert response.status_code == 409
        data = response.json()
        # FastAPI는 HTTPException detail을 {"detail": ...} 로 감싼다
        detail = data.get("detail") or data
        assert "conflicts" in detail or "conflicts" in str(detail)

    # ------------------------------------------------------------------
    # Test 2: Matching version → 200, version incremented
    # ------------------------------------------------------------------
    def test_matching_version_returns_200_and_increments(
        self, meeting_id: str, record_id: str, line_id: str, sample_record: dict
    ):
        """올바른 version을 보내면 200이 반환되고 version이 증가해야 한다."""
        current_line = make_line(record_id, line_id, version=3)
        mock_client = ConcurrencyMockClient(
            table_data={
                "stenography_records": [sample_record],
                "stenography_lines": [current_line],
                "stenography_edit_history": [],
            }
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client

        client = TestClient(app)
        headers = get_admin_auth_header()

        payload = {
            "items": [
                {"id": line_id, "text": "수정된 텍스트", "version": 3}
            ]
        }
        response = client.patch(
            f"/api/meetings/{meeting_id}/stenography/{record_id}/lines",
            json=payload,
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["updated"] == 1
        assert len(data["items"]) == 1
        updated = data["items"][0]
        # version은 3+1=4 여야 한다
        assert updated["version"] == 4

    # ------------------------------------------------------------------
    # Test 3: version 없이 보내면 (None) 기존 동작 유지 → 200
    # ------------------------------------------------------------------
    def test_no_version_skips_check_returns_200(
        self, meeting_id: str, record_id: str, line_id: str, sample_record: dict
    ):
        """version 필드 없이 보내면 버전 체크 없이 200이 반환되어야 한다 (하위 호환)."""
        current_line = make_line(record_id, line_id, version=5)
        mock_client = ConcurrencyMockClient(
            table_data={
                "stenography_records": [sample_record],
                "stenography_lines": [current_line],
                "stenography_edit_history": [],
            }
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client

        client = TestClient(app)
        headers = get_admin_auth_header()

        payload = {
            "items": [
                {"id": line_id, "text": "버전 없이 수정"}
                # version 필드 미전송
            ]
        }
        response = client.patch(
            f"/api/meetings/{meeting_id}/stenography/{record_id}/lines",
            json=payload,
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["updated"] == 1

    # ------------------------------------------------------------------
    # Test 4: 409 응답에 충돌 라인 정보가 포함되어야 한다
    # ------------------------------------------------------------------
    def test_409_detail_contains_conflict_id(
        self, meeting_id: str, record_id: str, line_id: str, sample_record: dict
    ):
        """409 응답 detail에 충돌 라인의 id가 포함되어야 한다."""
        current_line = make_line(record_id, line_id, version=10)
        mock_client = ConcurrencyMockClient(
            table_data={
                "stenography_records": [sample_record],
                "stenography_lines": [current_line],
                "stenography_edit_history": [],
            }
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client

        client = TestClient(app)
        headers = get_admin_auth_header()

        payload = {
            "items": [
                {"id": line_id, "text": "충돌 테스트", "version": 7}
            ]
        }
        response = client.patch(
            f"/api/meetings/{meeting_id}/stenography/{record_id}/lines",
            json=payload,
            headers=headers,
        )

        assert response.status_code == 409
        body = response.json()
        detail = body.get("detail", body)
        # conflicts 배열에 해당 id가 있어야 한다
        conflicts_str = str(detail)
        assert line_id in conflicts_str

    # ------------------------------------------------------------------
    # Test 5: 혼합 배치(ok + stale) → 409 반환, ok 라인도 쓰이지 않음
    # ------------------------------------------------------------------
    def test_mixed_batch_conflict_prevents_any_write(
        self, meeting_id: str, record_id: str, sample_record: dict
    ):
        """배치에 정상 라인과 충돌 라인이 섞여 있을 때
        409가 반환되고 정상 라인도 DB에 기록되지 않아야 한다 (원자적 처리)."""
        ok_line_id = str(uuid.uuid4())
        stale_line_id = str(uuid.uuid4())

        ok_line = make_line(record_id, ok_line_id, version=1)    # 올바른 version
        stale_line = make_line(record_id, stale_line_id, version=2)  # DB=2, 클라이언트=1 → 충돌

        mock_client = ConcurrencyMockClient(
            table_data={
                "stenography_records": [sample_record],
                "stenography_lines": [ok_line, stale_line],
                "stenography_edit_history": [],
            }
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client

        client = TestClient(app)
        headers = get_admin_auth_header()

        payload = {
            "items": [
                {"id": ok_line_id, "text": "ok 라인 수정", "version": 1},    # version 일치
                {"id": stale_line_id, "text": "충돌 라인 수정", "version": 1},  # version 불일치 (DB=2)
            ]
        }
        response = client.patch(
            f"/api/meetings/{meeting_id}/stenography/{record_id}/lines",
            json=payload,
            headers=headers,
        )

        # 전체 배치가 409
        assert response.status_code == 409

        # ok 라인도 DB에 기록되지 않아야 한다 (원자적 — 부분 쓰기 없음)
        lines = mock_client._table_data["stenography_lines"]
        ok_row = next((r for r in lines if r["id"] == ok_line_id), None)
        assert ok_row is not None, "ok_line 행 자체는 존재해야 한다"
        assert ok_row["text"] == "원본 텍스트", (
            f"ok_line이 수정되면 안 됩니다. 실제값: {ok_row['text']!r}"
        )
        assert ok_row["version"] == 1, (
            f"ok_line version이 증가하면 안 됩니다. 실제값: {ok_row['version']}"
        )
