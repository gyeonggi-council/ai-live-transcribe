"""Subtitles API 테스트 - TDD"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_supabase
from app.main import app
from app.schemas.subtitle import SubtitleBatchUpdate, SubtitleUpdate
from tests.conftest import (
    TEST_ADMIN_USER,
    MockSupabaseClient,
    MockSupabaseQuery,
    MockSupabaseResponse,
    _make_subtitle_row,
    get_admin_auth_header,
    inject_users_into_mock,
)

# 인가가 필요한 엔드포인트 테스트용 공통 헤더
_AUTH = get_admin_auth_header()


class TestGetSubtitles:
    """GET /api/meetings/{meeting_id}/subtitles 테스트"""

    def test_get_subtitles_returns_200(
        self, client: TestClient, meeting_id: uuid.UUID
    ) -> None:
        """자막 목록 조회 시 200 응답을 반환한다"""
        response = client.get(f"/api/meetings/{meeting_id}/subtitles")
        assert response.status_code == 200

    def test_get_subtitles_returns_list(
        self, client: TestClient, meeting_id: uuid.UUID
    ) -> None:
        """자막 목록 조회 시 리스트를 반환한다"""
        response = client.get(f"/api/meetings/{meeting_id}/subtitles")
        data = response.json()
        assert "items" in data
        assert isinstance(data["items"], list)

    def test_get_subtitles_with_pagination(
        self, client: TestClient, meeting_id: uuid.UUID
    ) -> None:
        """자막 목록 조회 시 페이지네이션 파라미터를 지원한다"""
        response = client.get(
            f"/api/meetings/{meeting_id}/subtitles?limit=10&offset=0"
        )
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "limit" in data
        assert "offset" in data

    def test_get_subtitles_with_data(
        self, client_with_mock_db: TestClient, meeting_id: uuid.UUID
    ) -> None:
        """자막이 있을 경우 올바른 구조의 데이터를 반환한다"""
        response = client_with_mock_db.get(
            f"/api/meetings/{meeting_id}/subtitles"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert len(data["items"]) == 3

        # 항목 구조 검증
        item = data["items"][0]
        assert "id" in item
        assert "meeting_id" in item
        assert "start_time" in item
        assert "end_time" in item
        assert "text" in item
        assert "speaker" in item
        assert "confidence" in item
        assert "created_at" in item

    def test_get_subtitles_empty_list(
        self, client_with_empty_db: TestClient, meeting_id: uuid.UUID
    ) -> None:
        """자막이 없을 경우 빈 리스트를 반환한다"""
        response = client_with_empty_db.get(
            f"/api/meetings/{meeting_id}/subtitles"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_get_subtitles_invalid_meeting_id_returns_422(
        self, client: TestClient
    ) -> None:
        """잘못된 형식의 meeting_id는 200을 반환하며 빈 자막 목록을 응답한다"""
        response = client.get("/api/meetings/invalid-uuid/subtitles")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0


class TestSearchSubtitles:
    """GET /api/meetings/{meeting_id}/subtitles/search 테스트"""

    def test_search_subtitles_returns_200(
        self, client: TestClient, meeting_id: uuid.UUID
    ) -> None:
        """자막 검색 시 200 응답을 반환한다"""
        response = client.get(
            f"/api/meetings/{meeting_id}/subtitles/search?q=test"
        )
        assert response.status_code == 200

    def test_search_subtitles_requires_query_param(
        self, client: TestClient, meeting_id: uuid.UUID
    ) -> None:
        """검색어 파라미터(q)가 없으면 422 에러를 반환한다"""
        response = client.get(f"/api/meetings/{meeting_id}/subtitles/search")
        assert response.status_code == 422

    def test_search_subtitles_returns_list(
        self, client: TestClient, meeting_id: uuid.UUID
    ) -> None:
        """자막 검색 시 리스트를 반환한다"""
        response = client.get(
            f"/api/meetings/{meeting_id}/subtitles/search?q=test"
        )
        data = response.json()
        assert "items" in data
        assert isinstance(data["items"], list)

    def test_search_subtitles_with_data(
        self, client_with_mock_db: TestClient, meeting_id: uuid.UUID
    ) -> None:
        """검색 결과가 있을 경우 올바른 구조의 데이터를 반환한다"""
        response = client_with_mock_db.get(
            f"/api/meetings/{meeting_id}/subtitles/search?q=키워드"
        )
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data

        # 항목이 있으면 구조 검증
        if data["items"]:
            item = data["items"][0]
            assert "id" in item
            assert "meeting_id" in item
            assert "start_time" in item
            assert "end_time" in item
            assert "text" in item

    def test_search_subtitles_empty_query_returns_422(
        self, client: TestClient, meeting_id: uuid.UUID
    ) -> None:
        """빈 검색어는 422 에러를 반환한다"""
        response = client.get(
            f"/api/meetings/{meeting_id}/subtitles/search?q="
        )
        assert response.status_code == 422

    def test_search_subtitles_invalid_meeting_id_returns_422(
        self, client: TestClient
    ) -> None:
        """잘못된 형식의 meeting_id는 200을 반환하며 빈 자막 목록을 응답한다"""
        response = client.get(
            "/api/meetings/invalid-uuid/subtitles/search?q=test"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_search_subtitles_with_pagination(
        self, client: TestClient, meeting_id: uuid.UUID
    ) -> None:
        """자막 검색 시 페이지네이션 파라미터를 지원한다"""
        response = client.get(
            f"/api/meetings/{meeting_id}/subtitles/search?q=test&limit=5&offset=0"
        )
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "limit" in data
        assert data["limit"] == 5
        assert "offset" in data
        assert data["offset"] == 0


# =============================================================================
# @TASK P5-T2.1 - 자막 수정 API 테스트
# @SPEC docs/planning/02-trd.md#자막-수정-API
# =============================================================================


class _UpdateMockSupabaseQuery(MockSupabaseQuery):
    """PATCH 테스트용 Supabase 쿼리 빌더

    update().eq().eq().execute() 체이닝에서 필터링을 실제로 수행합니다.
    """

    def __init__(self, data: list | None = None, count: int | None = None):
        super().__init__(data, count)
        self._filters: dict[str, str] = {}
        self._update_payload: dict | None = None

    def eq(self, column: str, value: str) -> "_UpdateMockSupabaseQuery":
        self._filters[column] = value
        return self

    def select(self, *args, **kwargs) -> "_UpdateMockSupabaseQuery":
        if kwargs.get("count") == "exact":
            self._count = len(self._data)
        return self

    def ilike(self, *args, **kwargs) -> "_UpdateMockSupabaseQuery":
        return self

    def order(self, *args, **kwargs) -> "_UpdateMockSupabaseQuery":
        return self

    def range(self, *args, **kwargs) -> "_UpdateMockSupabaseQuery":
        return self

    def limit(self, *args, **kwargs) -> "_UpdateMockSupabaseQuery":
        return self

    def update(self, payload: dict) -> "_UpdateMockSupabaseQuery":
        self._update_payload = payload
        return self

    def execute(self) -> MockSupabaseResponse:
        # update 호출이 있으면 필터링 후 업데이트 시뮬레이션
        if self._update_payload is not None:
            matched = []
            for row in self._data:
                match = True
                for col, val in self._filters.items():
                    if str(row.get(col, "")) != str(val):
                        match = False
                        break
                if match:
                    updated_row = {**row, **self._update_payload}
                    matched.append(updated_row)
            return MockSupabaseResponse(data=matched)

        # select 쿼리: 필터 적용
        if self._filters:
            matched = []
            for row in self._data:
                match = True
                for col, val in self._filters.items():
                    if str(row.get(col, "")) != str(val):
                        match = False
                        break
                if match:
                    matched.append(row)
            return MockSupabaseResponse(
                data=matched, count=len(matched) if self._count is not None else None
            )

        return MockSupabaseResponse(data=self._data, count=self._count)


class _UpdateMockSupabaseClient:
    """PATCH 테스트에 특화된 Supabase 클라이언트 모킹"""

    def __init__(self, table_data: dict[str, list] | None = None):
        self._table_data = table_data or {}
        # auth_middleware가 users 테이블을 조회할 수 있게 기본 admin 사용자 포함
        if "users" not in self._table_data:
            self._table_data["users"] = [TEST_ADMIN_USER]

    def table(self, name: str) -> _UpdateMockSupabaseQuery:
        data = self._table_data.get(name, [])
        return _UpdateMockSupabaseQuery(data=data)


class TestUpdateSubtitle:
    """PATCH /api/meetings/{meeting_id}/subtitles/{subtitle_id} 테스트"""

    def test_update_subtitle_text_returns_200(self, meeting_id: uuid.UUID) -> None:
        """자막 텍스트 수정 시 200 응답과 수정된 데이터를 반환한다"""
        mid = str(meeting_id)
        subtitle = _make_subtitle_row(mid, "원본 텍스트", 0.0, 5.0)
        sid = subtitle["id"]

        mock_client = _UpdateMockSupabaseClient(
            table_data={"subtitles": [subtitle]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.patch(
            f"/api/meetings/{mid}/subtitles/{sid}",
            json={"text": "수정된 텍스트"},
            headers=_AUTH,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["text"] == "수정된 텍스트"
        assert data["id"] == sid

        app.dependency_overrides.clear()

    def test_update_subtitle_speaker_returns_200(self, meeting_id: uuid.UUID) -> None:
        """화자 수정 시 200 응답과 수정된 데이터를 반환한다"""
        mid = str(meeting_id)
        subtitle = _make_subtitle_row(mid, "자막", 0.0, 5.0, speaker="화자A")
        sid = subtitle["id"]

        mock_client = _UpdateMockSupabaseClient(
            table_data={"subtitles": [subtitle]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.patch(
            f"/api/meetings/{mid}/subtitles/{sid}",
            json={"speaker": "화자B"},
            headers=_AUTH,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["speaker"] == "화자B"

        app.dependency_overrides.clear()

    def test_update_subtitle_both_fields(self, meeting_id: uuid.UUID) -> None:
        """텍스트와 화자를 동시에 수정할 수 있다"""
        mid = str(meeting_id)
        subtitle = _make_subtitle_row(mid, "원본", 0.0, 5.0, speaker="화자A")
        sid = subtitle["id"]

        mock_client = _UpdateMockSupabaseClient(
            table_data={"subtitles": [subtitle]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.patch(
            f"/api/meetings/{mid}/subtitles/{sid}",
            json={"text": "수정됨", "speaker": "화자B"},
            headers=_AUTH,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["text"] == "수정됨"
        assert data["speaker"] == "화자B"

        app.dependency_overrides.clear()

    def test_update_subtitle_not_found_returns_404(
        self, meeting_id: uuid.UUID
    ) -> None:
        """존재하지 않는 subtitle_id로 수정 시 404를 반환한다"""
        mid = str(meeting_id)
        non_existent_sid = str(uuid.uuid4())

        mock_client = _UpdateMockSupabaseClient(
            table_data={"subtitles": []}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.patch(
            f"/api/meetings/{mid}/subtitles/{non_existent_sid}",
            json={"text": "수정"},
            headers=_AUTH,
        )
        assert response.status_code == 404

        app.dependency_overrides.clear()

    def test_update_subtitle_empty_body_returns_400(
        self, meeting_id: uuid.UUID
    ) -> None:
        """빈 body(text, speaker 모두 None)로 수정 시 400을 반환한다"""
        mid = str(meeting_id)
        subtitle = _make_subtitle_row(mid, "원본", 0.0, 5.0)
        sid = subtitle["id"]

        mock_client = _UpdateMockSupabaseClient(
            table_data={"subtitles": [subtitle]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.patch(
            f"/api/meetings/{mid}/subtitles/{sid}",
            json={},
            headers=_AUTH,
        )
        assert response.status_code == 400

        app.dependency_overrides.clear()

    def test_update_subtitle_empty_text_returns_422(
        self, meeting_id: uuid.UUID
    ) -> None:
        """빈 문자열 text로 수정 시 422를 반환한다 (min_length=1 위반)"""
        mid = str(meeting_id)
        subtitle = _make_subtitle_row(mid, "원본", 0.0, 5.0)
        sid = subtitle["id"]

        mock_client = _UpdateMockSupabaseClient(
            table_data={"subtitles": [subtitle]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.patch(
            f"/api/meetings/{mid}/subtitles/{sid}",
            json={"text": ""},
            headers=_AUTH,
        )
        assert response.status_code == 422

        app.dependency_overrides.clear()


class TestUpdateSubtitlesBatch:
    """PATCH /api/meetings/{meeting_id}/subtitles 테스트 (배치 수정)"""

    def test_batch_update_returns_200(self, meeting_id: uuid.UUID) -> None:
        """배치 수정 시 200 응답과 수정 결과를 반환한다"""
        mid = str(meeting_id)
        sub1 = _make_subtitle_row(mid, "첫 번째", 0.0, 5.0)
        sub2 = _make_subtitle_row(mid, "두 번째", 5.0, 10.0)

        mock_client = _UpdateMockSupabaseClient(
            table_data={"subtitles": [sub1, sub2]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.patch(
            f"/api/meetings/{mid}/subtitles",
            json={
                "items": [
                    {"id": sub1["id"], "text": "수정1"},
                    {"id": sub2["id"], "text": "수정2"},
                ]
            },
            headers=_AUTH,
        )
        assert response.status_code == 200
        data = response.json()
        assert "updated" in data
        assert "items" in data
        assert data["updated"] == 2
        assert len(data["items"]) == 2

        app.dependency_overrides.clear()

    def test_batch_update_partial_not_found(self, meeting_id: uuid.UUID) -> None:
        """배치 수정 시 일부 subtitle이 없으면 해당 항목만 건너뛴다"""
        mid = str(meeting_id)
        sub1 = _make_subtitle_row(mid, "첫 번째", 0.0, 5.0)
        non_existent_id = str(uuid.uuid4())

        mock_client = _UpdateMockSupabaseClient(
            table_data={"subtitles": [sub1]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.patch(
            f"/api/meetings/{mid}/subtitles",
            json={
                "items": [
                    {"id": sub1["id"], "text": "수정됨"},
                    {"id": non_existent_id, "text": "없는 자막"},
                ]
            },
            headers=_AUTH,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["updated"] == 1
        assert len(data["items"]) == 1

        app.dependency_overrides.clear()

    def test_batch_update_empty_items_returns_422(
        self, meeting_id: uuid.UUID
    ) -> None:
        """빈 items 배열로 배치 수정 시 422를 반환한다"""
        mid = str(meeting_id)

        mock_client = _UpdateMockSupabaseClient(table_data={"subtitles": []})
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.patch(
            f"/api/meetings/{mid}/subtitles",
            json={"items": []},
            headers=_AUTH,
        )
        assert response.status_code == 422

        app.dependency_overrides.clear()

    def test_batch_update_all_not_found(self, meeting_id: uuid.UUID) -> None:
        """배치 수정 시 모든 subtitle이 없으면 updated=0을 반환한다"""
        mid = str(meeting_id)

        mock_client = _UpdateMockSupabaseClient(table_data={"subtitles": []})
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.patch(
            f"/api/meetings/{mid}/subtitles",
            json={
                "items": [
                    {"id": str(uuid.uuid4()), "text": "없는 자막1"},
                    {"id": str(uuid.uuid4()), "text": "없는 자막2"},
                ]
            },
            headers=_AUTH,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["updated"] == 0
        assert data["items"] == []

        app.dependency_overrides.clear()

    def test_batch_update_speaker_only(self, meeting_id: uuid.UUID) -> None:
        """배치 수정 시 speaker만 수정할 수 있다"""
        mid = str(meeting_id)
        sub1 = _make_subtitle_row(mid, "자막1", 0.0, 5.0, speaker="화자A")

        mock_client = _UpdateMockSupabaseClient(
            table_data={"subtitles": [sub1]}
        )
        app.dependency_overrides[get_supabase] = lambda: mock_client
        client = TestClient(app)

        response = client.patch(
            f"/api/meetings/{mid}/subtitles",
            json={
                "items": [
                    {"id": sub1["id"], "speaker": "화자B"},
                ]
            },
            headers=_AUTH,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["updated"] == 1
        assert data["items"][0]["speaker"] == "화자B"

        app.dependency_overrides.clear()


class TestSubtitleUpdateSchema:
    """SubtitleUpdate / SubtitleBatchUpdate 스키마 테스트"""

    def test_subtitle_update_text_only(self) -> None:
        """text만 포함된 SubtitleUpdate 생성"""
        update = SubtitleUpdate(text="수정 텍스트")
        assert update.text == "수정 텍스트"
        assert update.speaker is None

    def test_subtitle_update_speaker_only(self) -> None:
        """speaker만 포함된 SubtitleUpdate 생성"""
        update = SubtitleUpdate(speaker="화자B")
        assert update.text is None
        assert update.speaker == "화자B"

    def test_subtitle_update_both(self) -> None:
        """text와 speaker 모두 포함된 SubtitleUpdate 생성"""
        update = SubtitleUpdate(text="수정", speaker="화자")
        assert update.text == "수정"
        assert update.speaker == "화자"

    def test_subtitle_update_empty(self) -> None:
        """빈 SubtitleUpdate 생성 (모두 None)"""
        update = SubtitleUpdate()
        assert update.text is None
        assert update.speaker is None

    def test_subtitle_batch_update_valid(self) -> None:
        """유효한 SubtitleBatchUpdate 생성"""
        batch = SubtitleBatchUpdate(
            items=[
                {"id": str(uuid.uuid4()), "text": "수정1"},
                {"id": str(uuid.uuid4()), "speaker": "화자B"},
            ]
        )
        assert len(batch.items) == 2

    def test_subtitle_batch_update_empty_items_raises(self) -> None:
        """빈 items는 ValidationError 발생"""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SubtitleBatchUpdate(items=[])
