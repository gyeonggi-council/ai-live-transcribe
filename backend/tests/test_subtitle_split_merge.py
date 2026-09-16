"""자막 분할/병합/시간편집 API 테스트"""

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_supabase
from app.main import app

client = TestClient(app)


def make_subtitle(
    text="테스트 자막 텍스트입니다",
    start_time=10.0,
    end_time=20.0,
    meeting_id=None,
    subtitle_id=None,
    speaker="화자 1",
    confidence=0.9,
):
    sid = subtitle_id or str(uuid.uuid4())
    mid = meeting_id or str(uuid.uuid4())
    return {
        "id": sid,
        "meeting_id": mid,
        "text": text,
        "start_time": start_time,
        "end_time": end_time,
        "speaker": speaker,
        "confidence": confidence,
        "created_at": "2026-01-01T00:00:00Z",
    }


# ============================================================================
# Schema Tests
# ============================================================================


class TestSubtitleSchemas:
    def test_subtitle_update_with_time_fields(self):
        from app.schemas.subtitle import SubtitleUpdate

        update = SubtitleUpdate(text="새 텍스트", start_time=5.0, end_time=15.0)
        data = update.model_dump(exclude_none=True)
        assert data["start_time"] == 5.0
        assert data["end_time"] == 15.0

    def test_subtitle_update_time_fields_optional(self):
        from app.schemas.subtitle import SubtitleUpdate

        update = SubtitleUpdate(text="텍스트만")
        data = update.model_dump(exclude_none=True)
        assert "start_time" not in data
        assert "end_time" not in data

    def test_subtitle_batch_item_with_time(self):
        from app.schemas.subtitle import SubtitleBatchItem

        item = SubtitleBatchItem(id="abc", text="text", start_time=1.0, end_time=5.0)
        assert item.start_time == 1.0
        assert item.end_time == 5.0

    def test_split_request_validation(self):
        from app.schemas.subtitle import SubtitleSplitRequest

        req = SubtitleSplitRequest(position=10)
        assert req.position == 10
        assert req.split_time is None

    def test_split_request_with_time(self):
        from app.schemas.subtitle import SubtitleSplitRequest

        req = SubtitleSplitRequest(position=10, split_time=15.5)
        assert req.split_time == 15.5

    def test_split_request_negative_position_rejected(self):
        from pydantic import ValidationError

        from app.schemas.subtitle import SubtitleSplitRequest

        with pytest.raises(ValidationError):
            SubtitleSplitRequest(position=-1)

    def test_merge_request_min_two_ids(self):
        from pydantic import ValidationError

        from app.schemas.subtitle import SubtitleMergeSelectedRequest

        with pytest.raises(ValidationError):
            SubtitleMergeSelectedRequest(subtitle_ids=["only_one"])

    def test_merge_request_valid(self):
        from app.schemas.subtitle import SubtitleMergeSelectedRequest

        req = SubtitleMergeSelectedRequest(subtitle_ids=["a", "b", "c"])
        assert len(req.subtitle_ids) == 3


# ============================================================================
# Helper: Setup mock supabase
# ============================================================================


def setup_mock():
    mock_sb = MagicMock()
    app.dependency_overrides[get_supabase] = lambda: mock_sb
    return mock_sb


def cleanup_mock():
    app.dependency_overrides.clear()


# ============================================================================
# Split API Tests
# ============================================================================


class TestSplitSubtitle:
    def teardown_method(self):
        cleanup_mock()

    def test_split_at_position(self):
        mock_sb = setup_mock()
        mid = str(uuid.uuid4())
        sid = str(uuid.uuid4())
        original = make_subtitle(
            text="앞부분 텍스트 뒷부분 텍스트",
            start_time=10.0,
            end_time=20.0,
            meeting_id=mid,
            subtitle_id=sid,
        )

        # Chain: table().select().eq().eq().limit().execute()
        select_chain = MagicMock()
        select_chain.execute.return_value = MagicMock(data=[original])

        update_chain = MagicMock()
        update_chain.execute.return_value = MagicMock(data=[{**original, "text": "앞부분 텍스트", "end_time": 15.0}])

        new_sub = {**original, "id": str(uuid.uuid4()), "text": "뒷부분 텍스트", "start_time": 15.0}
        insert_chain = MagicMock()
        insert_chain.execute.return_value = MagicMock(data=[new_sub])

        # Build mock chain
        table_mock = MagicMock()
        mock_sb.table.return_value = table_mock

        # select chain (called multiple times: initial lookup + final lookup)
        table_mock.select.return_value.eq.return_value.eq.return_value.limit.return_value = select_chain
        # For final select (without second eq)
        table_mock.select.return_value.eq.return_value.limit.return_value = select_chain
        # update chain
        table_mock.update.return_value.eq.return_value = update_chain
        # insert chain
        table_mock.insert.return_value = insert_chain

        resp = client.post(
            f"/api/meetings/{mid}/subtitles/{sid}/split",
            json={"position": 8},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "original" in data
        assert "new" in data

    def test_split_position_zero_rejected(self):
        mock_sb = setup_mock()
        mid = str(uuid.uuid4())
        sid = str(uuid.uuid4())
        original = make_subtitle(text="테스트 텍스트", meeting_id=mid, subtitle_id=sid)

        table_mock = MagicMock()
        mock_sb.table.return_value = table_mock
        table_mock.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[original]
        )

        resp = client.post(
            f"/api/meetings/{mid}/subtitles/{sid}/split",
            json={"position": 0},
        )
        assert resp.status_code == 400

    def test_split_position_at_end_rejected(self):
        mock_sb = setup_mock()
        mid = str(uuid.uuid4())
        sid = str(uuid.uuid4())
        text = "테스트 텍스트"
        original = make_subtitle(text=text, meeting_id=mid, subtitle_id=sid)

        table_mock = MagicMock()
        mock_sb.table.return_value = table_mock
        table_mock.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[original]
        )

        resp = client.post(
            f"/api/meetings/{mid}/subtitles/{sid}/split",
            json={"position": len(text)},
        )
        assert resp.status_code == 400

    def test_split_not_found(self):
        mock_sb = setup_mock()
        mid = str(uuid.uuid4())
        sid = str(uuid.uuid4())

        table_mock = MagicMock()
        mock_sb.table.return_value = table_mock
        table_mock.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )

        resp = client.post(
            f"/api/meetings/{mid}/subtitles/{sid}/split",
            json={"position": 5},
        )
        assert resp.status_code == 404

    def test_split_with_custom_time(self):
        mock_sb = setup_mock()
        mid = str(uuid.uuid4())
        sid = str(uuid.uuid4())
        original = make_subtitle(
            text="앞부분 뒷부분",
            start_time=10.0,
            end_time=20.0,
            meeting_id=mid,
            subtitle_id=sid,
        )

        table_mock = MagicMock()
        mock_sb.table.return_value = table_mock

        select_chain = MagicMock()
        select_chain.execute.return_value = MagicMock(data=[original])
        table_mock.select.return_value.eq.return_value.eq.return_value.limit.return_value = select_chain
        table_mock.select.return_value.eq.return_value.limit.return_value = select_chain

        table_mock.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[original])
        new_sub = {**original, "id": str(uuid.uuid4()), "text": "뒷부분", "start_time": 15.0}
        table_mock.insert.return_value.execute.return_value = MagicMock(data=[new_sub])

        resp = client.post(
            f"/api/meetings/{mid}/subtitles/{sid}/split",
            json={"position": 4, "split_time": 15.0},
        )
        assert resp.status_code == 200


# ============================================================================
# Merge Selected API Tests
# ============================================================================


class TestMergeSelectedSubtitles:
    def teardown_method(self):
        cleanup_mock()

    def test_merge_two_subtitles(self):
        mock_sb = setup_mock()
        mid = str(uuid.uuid4())
        sid1, sid2 = str(uuid.uuid4()), str(uuid.uuid4())

        sub1 = make_subtitle(text="첫번째", start_time=10, end_time=15, meeting_id=mid, subtitle_id=sid1)
        sub2 = make_subtitle(text="두번째", start_time=15, end_time=20, meeting_id=mid, subtitle_id=sid2)

        table_mock = MagicMock()
        mock_sb.table.return_value = table_mock

        # Each subtitle lookup returns the appropriate subtitle
        select_chain = MagicMock()
        select_chain.execute.side_effect = [
            MagicMock(data=[sub1]),  # first id lookup
            MagicMock(data=[sub2]),  # second id lookup
            MagicMock(data=[{**sub1, "text": "첫번째 두번째", "end_time": 20}]),  # final merged select
        ]
        table_mock.select.return_value.eq.return_value.eq.return_value.limit.return_value = select_chain
        table_mock.select.return_value.eq.return_value.limit.return_value = select_chain

        # update + delete
        table_mock.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[sub1])
        table_mock.delete.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        resp = client.post(
            f"/api/meetings/{mid}/subtitles/merge-selected",
            json={"subtitle_ids": [sid1, sid2]},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "merged" in data
        assert data["deleted_count"] == 1

    def test_merge_requires_two_ids(self):
        setup_mock()
        mid = str(uuid.uuid4())
        resp = client.post(
            f"/api/meetings/{mid}/subtitles/merge-selected",
            json={"subtitle_ids": ["only_one"]},
        )
        assert resp.status_code == 422

    def test_merge_requires_ids(self):
        setup_mock()
        mid = str(uuid.uuid4())
        resp = client.post(
            f"/api/meetings/{mid}/subtitles/merge-selected",
            json={},
        )
        assert resp.status_code == 422

    def test_merge_not_found(self):
        mock_sb = setup_mock()
        mid = str(uuid.uuid4())
        sid1, sid2 = str(uuid.uuid4()), str(uuid.uuid4())

        table_mock = MagicMock()
        mock_sb.table.return_value = table_mock
        table_mock.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )

        resp = client.post(
            f"/api/meetings/{mid}/subtitles/merge-selected",
            json={"subtitle_ids": [sid1, sid2]},
        )
        assert resp.status_code == 404


# ============================================================================
# Time Edit in PATCH Tests
# ============================================================================


class TestTimeEditPatch:
    def teardown_method(self):
        cleanup_mock()

    def test_patch_with_time_fields(self):
        mock_sb = setup_mock()
        mid = str(uuid.uuid4())
        sid = str(uuid.uuid4())
        original = make_subtitle(meeting_id=mid, subtitle_id=sid)

        table_mock = MagicMock()
        mock_sb.table.return_value = table_mock
        table_mock.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[original]
        )
        updated = {**original, "start_time": 5.5, "end_time": 18.0}
        table_mock.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[updated]
        )

        resp = client.patch(
            f"/api/meetings/{mid}/subtitles/{sid}",
            json={"start_time": 5.5, "end_time": 18.0},
        )
        assert resp.status_code == 200
        assert resp.json()["start_time"] == 5.5
        assert resp.json()["end_time"] == 18.0

    def test_batch_patch_with_time_fields(self):
        mock_sb = setup_mock()
        mid = str(uuid.uuid4())
        sid = str(uuid.uuid4())
        original = make_subtitle(meeting_id=mid, subtitle_id=sid)

        table_mock = MagicMock()
        mock_sb.table.return_value = table_mock
        table_mock.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[original]
        )
        updated = {**original, "start_time": 3.0}
        table_mock.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[updated]
        )

        resp = client.patch(
            f"/api/meetings/{mid}/subtitles",
            json={"items": [{"id": sid, "start_time": 3.0}]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["updated"] == 1

    def test_patch_only_time_no_text(self):
        """시간만 변경하고 텍스트는 변경하지 않는 경우"""
        mock_sb = setup_mock()
        mid = str(uuid.uuid4())
        sid = str(uuid.uuid4())
        original = make_subtitle(meeting_id=mid, subtitle_id=sid)

        table_mock = MagicMock()
        mock_sb.table.return_value = table_mock
        table_mock.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[original]
        )
        table_mock.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{**original, "end_time": 25.0}]
        )

        resp = client.patch(
            f"/api/meetings/{mid}/subtitles/{sid}",
            json={"end_time": 25.0},
        )
        assert resp.status_code == 200
