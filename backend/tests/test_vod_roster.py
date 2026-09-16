"""VOD 명부 로드(_load_committee_roster) 회귀 테스트.

과거 버그: councilors의 위원회가 스칼라 'committee'가 아니라 JSONB 배열 'committees'인데
.eq("committee", ...)로 없는 컬럼을 조회 → 빈 명부 → VOD 이름교정 silent no-op.
수정: 라이브와 동일한 단일 진실 소스 get_by_committee 재사용.
"""

from unittest.mock import MagicMock

import pytest

from app.services.vod_stt_service import VodSttService


@pytest.fixture
def svc():
    return VodSttService()


def _mock_supabase(committee, councilor_rows):
    """meetings.committee 조회 + councilors(get_by_committee) 조회를 동시에 모킹."""
    sb = MagicMock()
    # meetings: select.eq.limit.execute
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=([{"committee": committee}] if committee is not None else [])
    )
    # councilors(get_by_committee): select.eq.order.execute
    sb.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
        data=councilor_rows
    )
    return sb


def test_returns_names_when_committee_resolves(svc):
    sb = _mock_supabase(
        "도시환경위원회",
        [
            {"id": "1", "name": "김종배", "committees": [{"name": "도시환경위원회"}]},
            {"id": "2", "name": "이위원", "committees": [{"name": "보건복지위원회"}]},
            {"id": "3", "name": "김시영", "committees": [{"name": "도시환경위원회"}]},
        ],
    )
    names = svc._load_committee_roster(sb, "meeting-1")
    assert names == ["김종배", "김시영"]


def test_empty_when_meeting_has_no_committee(svc):
    sb = _mock_supabase(None, [])
    assert svc._load_committee_roster(sb, "meeting-1") == []


def test_empty_when_committee_blank(svc):
    sb = _mock_supabase("", [{"id": "1", "name": "김종배", "committees": [{"name": "도시환경위원회"}]}])
    assert svc._load_committee_roster(sb, "meeting-1") == []
