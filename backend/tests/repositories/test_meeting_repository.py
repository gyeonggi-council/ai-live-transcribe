"""MeetingRepository / NotificationRepository / DictionaryRepository 계약 테스트"""

import pytest

from app.repositories.dictionary_repository import DictionaryRepository
from app.repositories.meeting_repository import MeetingRepository
from app.repositories.notification_repository import NotificationRepository
from tests.conftest import MockSupabaseClient

MEETING_ID = "22222222-2222-2222-2222-222222222222"

MEETING_ROW = {
    "id": MEETING_ID,
    "title": "테스트 회의",
    "meeting_date": "2026-08-01",
    "status": "ended",
    "vod_url": "https://kms.ggc.go.kr/mp4/test.mp4",
}


@pytest.fixture
def repo() -> MeetingRepository:
    return MeetingRepository(
        MockSupabaseClient(
            table_data={
                "meetings": [MEETING_ROW],
                "meeting_agendas": [{"id": "a1", "meeting_id": MEETING_ID, "order_num": 1}],
                "meeting_participants": [{"id": "p1", "meeting_id": MEETING_ID, "name": "홍길동"}],
                "transcript_publications": [{"id": "t1", "meeting_id": MEETING_ID}],
            }
        )
    )


class TestMeetings:
    def test_list(self, repo: MeetingRepository):
        assert repo.list(None, limit=10, offset=0) == [MEETING_ROW]

    def test_list_with_status_filter(self, repo: MeetingRepository):
        assert repo.list(["ended"], limit=10, offset=0) == [MEETING_ROW]

    def test_find_helpers_return_first_or_none(self, repo: MeetingRepository):
        assert repo.find_live_by_channel("ch1") == MEETING_ROW
        assert repo.find_recent_finished_by_channel("ch1") == MEETING_ROW
        assert repo.find_any_live() == MEETING_ROW
        assert repo.get_by_id(MEETING_ID) == MEETING_ROW
        assert repo.find_by_vod_url(MEETING_ROW["vod_url"]) == MEETING_ROW

    def test_find_none_when_empty(self):
        empty = MeetingRepository(MockSupabaseClient(table_data={"meetings": []}))
        assert empty.get_by_id(MEETING_ID) is None
        assert empty.find_any_live() is None

    def test_insert_returns_first_row(self, repo: MeetingRepository):
        assert repo.insert({"title": "새 회의"}) == MEETING_ROW

    def test_update_returns_raw_list(self, repo: MeetingRepository):
        assert repo.update(MEETING_ID, {"status": "ended"}) == [MEETING_ROW]


class TestChildTables:
    def test_agendas(self, repo: MeetingRepository):
        assert repo.list_agendas(MEETING_ID)[0]["id"] == "a1"
        assert repo.insert_agenda({"meeting_id": MEETING_ID})[0]["id"] == "a1"
        assert repo.update_agenda("a1", MEETING_ID, {"title": "x"})[0]["id"] == "a1"
        assert repo.delete_agenda("a1", MEETING_ID)[0]["id"] == "a1"

    def test_participants(self, repo: MeetingRepository):
        assert repo.list_participants(MEETING_ID)[0]["id"] == "p1"
        assert repo.insert_participant({"meeting_id": MEETING_ID})[0]["id"] == "p1"
        assert repo.delete_participant("p1", MEETING_ID)[0]["id"] == "p1"

    def test_publications(self, repo: MeetingRepository):
        assert repo.list_publications(MEETING_ID)[0]["id"] == "t1"
        assert repo.insert_publication({"meeting_id": MEETING_ID})[0]["id"] == "t1"

    def test_participant_insert_propagates_unique_violation(self):
        class UniqueViolationClient:
            def table(self, name: str):
                raise Exception("duplicate key value violates unique constraint")

        repo = MeetingRepository(UniqueViolationClient())
        with pytest.raises(Exception):
            repo.insert_participant({"meeting_id": MEETING_ID})


class TestNotificationRepository:
    def test_insert_list_mark_read(self):
        row = {"id": "n1", "type": "status_change", "is_read": False}
        repo = NotificationRepository(MockSupabaseClient(table_data={"notifications": [row]}))
        assert repo.insert({"type": "status_change"}) == [row]
        assert repo.list(limit=50) == [row]
        assert repo.list(limit=50, is_read=False) == [row]
        assert repo.mark_read("n1") == [row]

    def test_list_empty_returns_list(self):
        repo = NotificationRepository(MockSupabaseClient(table_data={"notifications": []}))
        assert repo.list(limit=50) == []


class TestDictionaryRepository:
    def test_upsert_user_correction(self):
        repo = DictionaryRepository(MockSupabaseClient(table_data={"dictionary": []}))
        # upsert는 반환값 없음 — 예외 없이 실행되는지만 검증
        assert repo.upsert_user_correction("몇일", "며칠") is None
