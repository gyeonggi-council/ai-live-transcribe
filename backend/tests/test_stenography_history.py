"""속기록 수정 이력 서비스 테스트

# @TASK P11C-T7.1 - 수정 이력 서비스 테스트
# @TEST backend/tests/test_stenography_history.py
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services.stenography_history import (
    EditHistoryEntry,
    record_edit,
    get_history,
)


@pytest.fixture
def mock_supabase():
    """Supabase REST 클라이언트 mock"""
    client = MagicMock()
    return client


class TestRecordEdit:
    """record_edit 함수 테스트"""

    def test_record_edit_creates_history_entry(self, mock_supabase):
        """수정 이력이 정상적으로 생성되는지 확인"""
        line_id = str(uuid.uuid4())
        editor_name = "홍길동"
        field_changed = "text"
        old_value = "원래 텍스트"
        new_value = "수정된 텍스트"

        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{
                "id": str(uuid.uuid4()),
                "line_id": line_id,
                "editor_name": editor_name,
                "field_changed": field_changed,
                "old_value": old_value,
                "new_value": new_value,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }]
        )

        result = record_edit(
            supabase=mock_supabase,
            line_id=line_id,
            editor_id=None,
            editor_name=editor_name,
            field_changed=field_changed,
            old_value=old_value,
            new_value=new_value,
        )

        mock_supabase.table.assert_called_with("stenography_edit_history")
        assert result is not None
        assert result["line_id"] == line_id

    def test_record_edit_skips_when_values_equal(self, mock_supabase):
        """old_value와 new_value가 동일하면 이력을 생성하지 않음"""
        result = record_edit(
            supabase=mock_supabase,
            line_id=str(uuid.uuid4()),
            editor_id=None,
            editor_name="홍길동",
            field_changed="text",
            old_value="같은 텍스트",
            new_value="같은 텍스트",
        )

        mock_supabase.table.assert_not_called()
        assert result is None

    def test_record_edit_allows_none_old_value(self, mock_supabase):
        """old_value가 None이면 (신규 설정) 이력 생성"""
        line_id = str(uuid.uuid4())

        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{
                "id": str(uuid.uuid4()),
                "line_id": line_id,
                "editor_name": "홍길동",
                "field_changed": "speaker",
                "old_value": None,
                "new_value": "김의원",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }]
        )

        result = record_edit(
            supabase=mock_supabase,
            line_id=line_id,
            editor_id=None,
            editor_name="홍길동",
            field_changed="speaker",
            old_value=None,
            new_value="김의원",
        )

        assert result is not None


class TestGetHistory:
    """get_history 함수 테스트"""

    def test_get_history_returns_entries(self, mock_supabase):
        """수정 이력 조회가 정상적으로 동작하는지 확인"""
        record_id = str(uuid.uuid4())
        line_id_1 = str(uuid.uuid4())
        line_id_2 = str(uuid.uuid4())

        # stenography_lines 조회 mock
        lines_mock = MagicMock()
        lines_mock.data = [
            {"id": line_id_1, "record_id": record_id},
            {"id": line_id_2, "record_id": record_id},
        ]

        # history 조회 mock
        history_mock = MagicMock()
        history_mock.data = [
            {
                "id": str(uuid.uuid4()),
                "line_id": line_id_1,
                "editor_name": "홍길동",
                "field_changed": "text",
                "old_value": "원래",
                "new_value": "수정",
                "created_at": "2026-03-19T12:00:00Z",
            },
        ]

        def table_side_effect(name):
            mock_table = MagicMock()
            if name == "stenography_lines":
                mock_table.select.return_value.eq.return_value.execute.return_value = lines_mock
            elif name == "stenography_edit_history":
                chain = mock_table.select.return_value
                chain.in_.return_value.order.return_value.limit.return_value.offset.return_value.execute.return_value = history_mock
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        items, total = get_history(mock_supabase, record_id, limit=50, offset=0)

        assert len(items) == 1
        assert items[0]["field_changed"] == "text"

    def test_get_history_empty_when_no_lines(self, mock_supabase):
        """라인이 없는 레코드의 이력 조회 시 빈 목록 반환"""
        record_id = str(uuid.uuid4())

        lines_mock = MagicMock()
        lines_mock.data = []

        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = lines_mock

        items, total = get_history(mock_supabase, record_id, limit=50, offset=0)

        assert items == []
        assert total == 0
