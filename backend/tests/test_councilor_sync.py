"""의원 동기화 서비스 테스트"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.councilor_sync import CouncilorSyncService


@pytest.fixture
def mock_supabase():
    """Mock Supabase 클라이언트"""
    client = MagicMock()
    return client


@pytest.fixture
def service(mock_supabase):
    return CouncilorSyncService(mock_supabase)


class TestGetAllActive:
    def test_returns_active_councilors(self, service, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
            data=[
                {"id": "1", "name": "김의원", "party": "더불어민주당", "is_active": True},
                {"id": "2", "name": "이의원", "party": "국민의힘", "is_active": True},
            ]
        )

        result = service.get_all_active()
        assert len(result) == 2
        assert result[0]["name"] == "김의원"

    def test_returns_empty_when_no_data(self, service, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
            data=[]
        )

        result = service.get_all_active()
        assert result == []


class TestSearch:
    def test_search_by_name(self, service, mock_supabase):
        mock_supabase.table.return_value.select.return_value.or_.return_value.order.return_value.execute.return_value = MagicMock(
            data=[{"id": "1", "name": "김의원", "party": "더불어민주당"}]
        )

        result = service.search("김의원")
        assert len(result) == 1

    def test_search_empty_result(self, service, mock_supabase):
        mock_supabase.table.return_value.select.return_value.or_.return_value.order.return_value.execute.return_value = MagicMock(
            data=[]
        )

        result = service.search("존재안함")
        assert result == []


class TestGetNamesForCorrection:
    def test_returns_name_list(self, service, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[
                {"name": "김의원"},
                {"name": "이의원"},
                {"name": "박의원"},
            ]
        )

        names = service.get_names_for_correction()
        assert names == ["김의원", "이의원", "박의원"]

    def test_returns_empty_when_no_data(self, service, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[]
        )

        names = service.get_names_for_correction()
        assert names == []


class TestGetByCommittee:
    """위원회별 명부 조회 — 과거 .contains(list[dict]) 크래시 → silent no-op 회귀 방지."""

    def _set_rows(self, mock_supabase, rows):
        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
            data=rows
        )

    def test_filters_by_committee_dict_format(self, service, mock_supabase):
        self._set_rows(mock_supabase, [
            {"id": "1", "name": "김위원", "committees": [{"name": "도시환경위원회"}]},
            {"id": "2", "name": "이위원", "committees": [{"name": "보건복지위원회"}]},
            {"id": "3", "name": "박위원", "committees": [{"name": "도시환경위원회"}, {"name": "예산결산특별위원회"}]},
        ])
        result = service.get_by_committee("도시환경위원회")
        assert [c["name"] for c in result] == ["김위원", "박위원"]

    def test_regression_list_of_dict_does_not_crash(self, service, mock_supabase):
        # 과거 버그: postgrest .contains에 list[dict] 전달 시 ','.join 예외 → 빈 명부 폴백.
        # Python 필터는 list[dict]를 예외 없이 정상 처리해야 한다(명부가 비지 않음).
        self._set_rows(mock_supabase, [
            {"id": "1", "name": "김위원", "committees": [{"name": "교육기획위원회", "role": "위원장"}]},
        ])
        result = service.get_by_committee("교육기획위원회")
        assert len(result) == 1 and result[0]["name"] == "김위원"

    def test_string_committee_format_fallback(self, service, mock_supabase):
        # committees가 list[str] 형식이어도 매칭되어야 한다.
        self._set_rows(mock_supabase, [
            {"id": "1", "name": "김위원", "committees": ["안전행정위원회"]},
        ])
        assert [c["name"] for c in service.get_by_committee("안전행정위원회")] == ["김위원"]

    def test_committees_none_or_missing_excluded(self, service, mock_supabase):
        self._set_rows(mock_supabase, [
            {"id": "1", "name": "김위원", "committees": None},
            {"id": "2", "name": "이위원"},  # 키 자체 누락
        ])
        assert service.get_by_committee("도시환경위원회") == []

    def test_whitespace_normalized_match(self, service, mock_supabase):
        # meeting.committee와 councilor 표기의 공백 흔들림이 있어도 매칭(silent no-op 완화).
        self._set_rows(mock_supabase, [
            {"id": "1", "name": "김위원", "committees": [{"name": "도시환경 위원회"}]},
        ])
        assert [c["name"] for c in service.get_by_committee("도시환경위원회")] == ["김위원"]

    def test_empty_committee_arg_returns_empty(self, service, mock_supabase):
        assert service.get_by_committee("") == []
        assert service.get_by_committee(None) == []


class TestMapMemberToRow:
    def test_basic_mapping(self, service):
        member = {
            "MI_CODE": "M001",
            "MI_NAME": "김의원",
            "MI_PARTY": "더불어민주당",
            "MI_DISTRICT": "수원시갑",
            "MI_COMMITTEE": "보건복지위원회, 교육위원회",
            "MI_OFFICE": "031-123-4567",
            "MI_TERM": 11,
            "MI_PHOTO": "/img/member/M001.jpg",
        }

        row = service._map_member_to_row(member, "2026-03-16T00:00:00Z")

        assert row["mi_code"] == "M001"
        assert row["name"] == "김의원"
        assert row["party"] == "더불어민주당"
        assert row["district"] == "수원시갑"
        assert row["is_active"] is True
        assert row["term"] == 11
        assert row["office_number"] == "031-123-4567"
        assert "https://www.ggc.go.kr/img/member/M001.jpg" == row["profile_image_url"]
        assert len(row["committees"]) == 2
        assert row["committees"][0]["name"] == "보건복지위원회"

    def test_empty_fields(self, service):
        member = {"MI_CODE": "M002", "MI_NAME": "이의원"}

        row = service._map_member_to_row(member, "2026-03-16T00:00:00Z")

        assert row["mi_code"] == "M002"
        assert row["name"] == "이의원"
        assert row["party"] is None
        assert row["district"] is None
        assert row["committees"] == []


class TestSyncFromApi:
    @pytest.mark.asyncio
    async def test_sync_adds_new_members(self, service, mock_supabase):
        # Mock API response
        with patch.object(service, "_fetch_members", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = [
                {"MI_CODE": "M001", "MI_NAME": "김의원", "MI_PARTY": "민주당"},
            ]

            # Mock DB lookup - no existing record
            mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
                data=[]
            )
            # Mock insert
            mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])

            # Mock deactivation query
            mock_supabase.table.return_value.select.return_value.eq.return_value.not_.return_value.execute.return_value = MagicMock(
                data=[]
            )

            result = await service.sync_from_api()

            assert result["added"] == 1
            assert result["updated"] == 0

    @pytest.mark.asyncio
    async def test_sync_handles_api_failure(self, service):
        with patch.object(service, "_fetch_members", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = Exception("API 연결 실패")

            with pytest.raises(Exception, match="API 연결 실패"):
                await service.sync_from_api()
