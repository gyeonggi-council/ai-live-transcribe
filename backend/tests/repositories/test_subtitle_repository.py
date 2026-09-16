"""SubtitleRepository 계약 테스트

MockSupabaseClient를 직접 주입해 반환 형태(list / dict|None / count)와
예외 전파 계약을 검증한다. 체인 메서드는 conftest mock 지원 집합만 사용해야 한다.
"""

import pytest

from app.repositories.subtitle_repository import SubtitleRepository
from tests.conftest import MockSupabaseClient, _make_subtitle_row

MEETING_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def rows() -> list[dict]:
    return [
        _make_subtitle_row(MEETING_ID, "첫 번째", 0.0, 5.0),
        _make_subtitle_row(MEETING_ID, "두 번째", 5.0, 10.0),
    ]


@pytest.fixture
def repo(rows: list[dict]) -> SubtitleRepository:
    return SubtitleRepository(MockSupabaseClient(table_data={"subtitles": rows}))


class TestReads:
    def test_count_by_meeting(self, repo: SubtitleRepository):
        assert repo.count_by_meeting(MEETING_ID) == 2

    def test_count_by_meeting_empty(self):
        repo = SubtitleRepository(MockSupabaseClient(table_data={"subtitles": []}))
        assert repo.count_by_meeting(MEETING_ID) == 0

    def test_list_by_meeting_returns_list(self, repo: SubtitleRepository, rows):
        assert repo.list_by_meeting(MEETING_ID, limit=100, offset=0) == rows

    def test_list_all_ordered(self, repo: SubtitleRepository, rows):
        assert repo.list_all_ordered(MEETING_ID) == rows

    def test_list_id_text_with_ids(self, repo: SubtitleRepository, rows):
        assert repo.list_id_text(MEETING_ID, [rows[0]["id"]]) == rows

    def test_search_and_count(self, repo: SubtitleRepository, rows):
        assert repo.search(MEETING_ID, "첫", limit=10, offset=0) == rows
        assert repo.count_search(MEETING_ID, "첫") == 2

    def test_get_returns_first_or_none(self, repo: SubtitleRepository, rows):
        assert repo.get(rows[0]["id"], MEETING_ID) == rows[0]
        empty = SubtitleRepository(MockSupabaseClient(table_data={"subtitles": []}))
        assert empty.get("no-such-id", MEETING_ID) is None

    def test_get_by_id_and_get_text(self, repo: SubtitleRepository, rows):
        assert repo.get_by_id(rows[0]["id"]) == rows[0]
        assert repo.get_text(rows[0]["id"], MEETING_ID) == rows[0]


class TestWrites:
    def test_update_returns_raw_list(self, repo: SubtitleRepository, rows):
        # 빈 리스트 → 404 판정을 호출자가 유지할 수 있도록 raw list 반환
        assert repo.update(rows[0]["id"], {"text": "수정"}, MEETING_ID) == rows

    def test_update_without_meeting_filter(self, repo: SubtitleRepository, rows):
        assert repo.update(rows[0]["id"], {"text": "수정"}) == rows

    def test_insert_returns_raw_list(self, repo: SubtitleRepository, rows):
        assert repo.insert({"meeting_id": MEETING_ID, "text": "새 자막"}) == rows

    def test_delete_no_return(self, repo: SubtitleRepository, rows):
        assert repo.delete(rows[0]["id"]) is None
        assert repo.delete_by_meeting(MEETING_ID) is None


class TestExceptionPropagation:
    def test_repository_propagates_client_errors(self):
        class BrokenClient:
            def table(self, name: str):
                raise RuntimeError("connection refused")

        repo = SubtitleRepository(BrokenClient())
        with pytest.raises(RuntimeError):
            repo.count_by_meeting(MEETING_ID)
