"""Stenography lines API tests."""

import uuid

import pytest
from starlette.testclient import TestClient

from app.core.database import get_supabase
from app.main import app
from tests.conftest import MockSupabaseQuery, MockSupabaseResponse


class LinesMockSupabaseQuery(MockSupabaseQuery):
    """Supabase query mock for stenography line endpoints."""

    def __init__(self, client: "LinesMockSupabaseClient", table_name: str):
        super().__init__(data=[])
        self._client = client
        self._table_name = table_name
        self._filters: list[tuple[str, str]] = []
        self._insert_data: dict | list[dict] | None = None
        self._update_data: dict | None = None
        self._is_delete = False
        self._order_column: str | None = None
        self._limit_value: int | None = None

    def select(self, *args, **kwargs) -> "LinesMockSupabaseQuery":
        return self

    def eq(self, column: str, value) -> "LinesMockSupabaseQuery":
        self._filters.append((column, str(value)))
        return self

    def order(self, column: str, *args, **kwargs) -> "LinesMockSupabaseQuery":
        self._order_column = column
        return self

    def limit(self, count: int) -> "LinesMockSupabaseQuery":
        self._limit_value = count
        return self

    def insert(self, data: dict | list[dict]) -> "LinesMockSupabaseQuery":
        self._insert_data = data
        return self

    def update(self, data: dict) -> "LinesMockSupabaseQuery":
        self._update_data = data
        return self

    def delete(self) -> "LinesMockSupabaseQuery":
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

        if self._insert_data is not None:
            payload = (
                self._insert_data
                if isinstance(self._insert_data, list)
                else [self._insert_data]
            )
            inserted_rows: list[dict] = []
            for item in payload:
                row = dict(item)
                if self._table_name == "stenography_lines" and not row.get("id"):
                    row["id"] = str(uuid.uuid4())
                inserted_rows.append(row)

            if self._table_name == "stenography_lines" and inserted_rows:
                sequence_values = [row.get("sequence_no") for row in inserted_rows]
                if all(
                    isinstance(seq, int) for seq in sequence_values
                ) and sequence_values == list(range(1, len(inserted_rows) + 1)):
                    for index, row in enumerate(inserted_rows, start=1):
                        row["sequence_no"] = index * 10

            rows.extend(inserted_rows)
            self._client._table_data[self._table_name] = rows
            return MockSupabaseResponse(data=inserted_rows)

        selected = [row for row in rows if self._matches(row)]
        if self._order_column:
            selected = sorted(
                selected,
                key=lambda row: (
                    row.get(self._order_column) is None,
                    row.get(self._order_column),
                ),
            )
        if self._limit_value is not None:
            selected = selected[: self._limit_value]
        return MockSupabaseResponse(data=selected, count=len(selected))


class LinesMockSupabaseClient:
    """Supabase client mock with multi-table support."""

    def __init__(self, table_data: dict[str, list] | None = None):
        self._table_data = table_data or {}

    def table(self, name: str) -> LinesMockSupabaseQuery:
        return LinesMockSupabaseQuery(client=self, table_name=name)


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
        "content": "첫째 줄\n둘째 줄\n셋째 줄",
        "stenographer_name": "테스트",
        "status": "draft",
        "file_path": None,
        "filename": None,
        "file_size": None,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }


@pytest.fixture
def sample_lines(record_id: str) -> list[dict]:
    return [
        {
            "id": str(uuid.uuid4()),
            "record_id": record_id,
            "sequence_no": 10,
            "text": "첫째 줄",
            "speaker": "화자 1",
            "start_ms": 1000,
            "end_ms": 3000,
            "starts_new_paragraph": False,
        },
        {
            "id": str(uuid.uuid4()),
            "record_id": record_id,
            "sequence_no": 20,
            "text": "둘째 줄",
            "speaker": "화자 2",
            "start_ms": 3000,
            "end_ms": 5000,
            "starts_new_paragraph": False,
        },
    ]


@pytest.fixture
def sample_subtitles(meeting_id: str) -> list[dict]:
    return [
        {
            "id": str(uuid.uuid4()),
            "meeting_id": meeting_id,
            "text": "자막1",
            "speaker": "화자A",
            "start_time": 1.0,
            "end_time": 3.0,
        },
        {
            "id": str(uuid.uuid4()),
            "meeting_id": meeting_id,
            "text": "자막2",
            "speaker": "화자B",
            "start_time": 3.0,
            "end_time": 5.0,
        },
        {
            "id": str(uuid.uuid4()),
            "meeting_id": meeting_id,
            "text": "자막3",
            "speaker": "화자B",
            "start_time": 5.0,
            "end_time": 7.0,
        },
    ]


class TestListStenographyLines:
    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_list_lines_200_empty(
        self, meeting_id: str, record_id: str, sample_record: dict
    ):
        mock_client = LinesMockSupabaseClient(
            table_data={"stenography_records": [sample_record], "stenography_lines": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(f"/api/meetings/{meeting_id}/stenography/{record_id}/lines")

        assert response.status_code == 200
        assert response.json() == []

    def test_list_lines_200_with_data(
        self,
        meeting_id: str,
        record_id: str,
        sample_record: dict,
        sample_lines: list[dict],
    ):
        unsorted_lines = [sample_lines[1], sample_lines[0]]
        mock_client = LinesMockSupabaseClient(
            table_data={"stenography_records": [sample_record], "stenography_lines": unsorted_lines}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(f"/api/meetings/{meeting_id}/stenography/{record_id}/lines")

        assert response.status_code == 200
        data = response.json()
        assert [item["sequence_no"] for item in data] == [10, 20]
        assert [item["text"] for item in data] == ["첫째 줄", "둘째 줄"]

    def test_list_lines_404(self, meeting_id: str, record_id: str):
        mock_client = LinesMockSupabaseClient(
            table_data={"stenography_records": [], "stenography_lines": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.get(f"/api/meetings/{meeting_id}/stenography/{record_id}/lines")

        assert response.status_code == 404


class TestUpdateStenographyLinesBatch:
    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_batch_update_text(
        self,
        meeting_id: str,
        record_id: str,
        sample_record: dict,
        sample_lines: list[dict],
    ):
        mock_client = LinesMockSupabaseClient(
            table_data={"stenography_records": [sample_record], "stenography_lines": sample_lines.copy()}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        payload = {
            "items": [
                {"id": sample_lines[0]["id"], "text": "첫째 줄 수정"},
                {"id": sample_lines[1]["id"], "text": "둘째 줄 수정"},
            ]
        }
        response = client.patch(
            f"/api/meetings/{meeting_id}/stenography/{record_id}/lines",
            json=payload,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["updated"] == 2
        assert {item["text"] for item in data["items"]} == {"첫째 줄 수정", "둘째 줄 수정"}

    def test_batch_update_speaker(
        self,
        meeting_id: str,
        record_id: str,
        sample_record: dict,
        sample_lines: list[dict],
    ):
        mock_client = LinesMockSupabaseClient(
            table_data={"stenography_records": [sample_record], "stenography_lines": sample_lines.copy()}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        payload = {"items": [{"id": sample_lines[0]["id"], "speaker": "의장"}]}
        response = client.patch(
            f"/api/meetings/{meeting_id}/stenography/{record_id}/lines",
            json=payload,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["updated"] == 1
        assert data["items"][0]["speaker"] == "의장"

    def test_batch_update_404_record(
        self, meeting_id: str, record_id: str, sample_lines: list[dict]
    ):
        mock_client = LinesMockSupabaseClient(
            table_data={"stenography_records": [], "stenography_lines": sample_lines.copy()}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.patch(
            f"/api/meetings/{meeting_id}/stenography/{record_id}/lines",
            json={"items": [{"id": sample_lines[0]["id"], "text": "변경"}]},
        )

        assert response.status_code == 404

    def test_batch_update_empty_items(
        self,
        meeting_id: str,
        record_id: str,
        sample_record: dict,
        sample_lines: list[dict],
    ):
        mock_client = LinesMockSupabaseClient(
            table_data={"stenography_records": [sample_record], "stenography_lines": sample_lines.copy()}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.patch(
            f"/api/meetings/{meeting_id}/stenography/{record_id}/lines",
            json={"items": []},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["updated"] == 0
        assert data["items"] == []


class TestImportFromText:
    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_import_from_text_success(
        self, meeting_id: str, record_id: str, sample_record: dict
    ):
        mock_client = LinesMockSupabaseClient(
            table_data={"stenography_records": [sample_record], "stenography_lines": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.post(
            f"/api/meetings/{meeting_id}/stenography/{record_id}/lines/import-from-text",
            json={"text": "line1\nline2\n\nline3"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 3
        assert [line["sequence_no"] for line in data["lines"]] == [10, 20, 30]

    def test_import_from_text_404(self, meeting_id: str, record_id: str):
        mock_client = LinesMockSupabaseClient(
            table_data={"stenography_records": [], "stenography_lines": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.post(
            f"/api/meetings/{meeting_id}/stenography/{record_id}/lines/import-from-text",
            json={"text": "line1\nline2"},
        )

        assert response.status_code == 404

    def test_import_from_text_empty(self, meeting_id: str, record_id: str):
        record = {
            "id": record_id,
            "meeting_id": meeting_id,
            "content": "",
            "stenographer_name": "테스트",
            "status": "draft",
            "file_path": None,
            "filename": None,
            "file_size": None,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }
        mock_client = LinesMockSupabaseClient(
            table_data={"stenography_records": [record], "stenography_lines": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.post(
            f"/api/meetings/{meeting_id}/stenography/{record_id}/lines/import-from-text",
            json={"text": ""},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 0
        assert data["lines"] == []


class TestImportFromSubtitles:
    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_from_subtitles_success(
        self,
        meeting_id: str,
        record_id: str,
        sample_record: dict,
        sample_subtitles: list[dict],
    ):
        mock_client = LinesMockSupabaseClient(
            table_data={
                "stenography_records": [sample_record],
                "stenography_lines": [],
                "subtitles": sample_subtitles,
            }
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.post(
            f"/api/meetings/{meeting_id}/stenography/{record_id}/lines/from-subtitles"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 3
        assert len(data["lines"]) == 3
        assert data["lines"][0]["start_ms"] == 1000
        assert data["lines"][0]["end_ms"] == 3000

    def test_from_subtitles_404(
        self, meeting_id: str, record_id: str, sample_subtitles: list[dict]
    ):
        mock_client = LinesMockSupabaseClient(
            table_data={
                "stenography_records": [],
                "stenography_lines": [],
                "subtitles": sample_subtitles,
            }
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.post(
            f"/api/meetings/{meeting_id}/stenography/{record_id}/lines/from-subtitles"
        )

        assert response.status_code == 404

    def test_from_subtitles_no_subtitles(
        self, meeting_id: str, record_id: str, sample_record: dict
    ):
        mock_client = LinesMockSupabaseClient(
            table_data={
                "stenography_records": [sample_record],
                "stenography_lines": [],
                "subtitles": [],
            }
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.post(
            f"/api/meetings/{meeting_id}/stenography/{record_id}/lines/from-subtitles"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 0
        assert data["lines"] == []


class TestAddStenographyLine:
    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_add_line_success(
        self,
        meeting_id: str,
        record_id: str,
        sample_record: dict,
        sample_lines: list[dict],
    ):
        mock_client = LinesMockSupabaseClient(
            table_data={
                "stenography_records": [sample_record],
                "stenography_lines": sample_lines.copy(),
            }
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.post(
            f"/api/meetings/{meeting_id}/stenography/{record_id}/lines/add",
            json={
                "text": "새 라인",
                "speaker": "화자 3",
                "start_ms": 5000,
                "end_ms": 7000,
                "starts_new_paragraph": False,
                "after_sequence_no": 20,
            },
        )

        assert response.status_code in (200, 201)
        data = response.json()
        assert data["text"] == "새 라인"
        assert data["speaker"] == "화자 3"
        assert data["sequence_no"] == 25
        assert data.get("id") is not None

    def test_add_line_404(self, meeting_id: str, record_id: str):
        mock_client = LinesMockSupabaseClient(
            table_data={"stenography_records": [], "stenography_lines": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.post(
            f"/api/meetings/{meeting_id}/stenography/{record_id}/lines/add",
            json={"text": "새 라인", "after_sequence_no": 10},
        )

        assert response.status_code == 404
