"""roster_loader — 위원회 명부 로더.

본회의처럼 committee_rosters.json 에도 councilors.committees 에도 없는 회의는 전체 활성 의원으로
폴백한다(2026-09-08). 없으면 라이브 교정·VOD 화자귀속·음성 융합이 본회의에서 통째로 꺼진다.
"""

from unittest.mock import MagicMock

from app.services import roster_loader


def _svc(by_committee, all_active):
    svc = MagicMock()
    svc.get_by_committee.return_value = by_committee
    svc.get_all_active.return_value = all_active
    return svc


def test_plenary_falls_back_to_all_active_members(monkeypatch):
    svc = _svc([], [{"name": "김태희"}, {"name": "정용한"}, {"name": ""}])
    monkeypatch.setattr("app.services.councilor_sync.CouncilorSyncService", lambda _sb: svc)

    out = roster_loader.load_committee_with_roles(MagicMock(), "본회의")

    assert out == [{"name": "김태희", "role": "의원"}, {"name": "정용한", "role": "의원"}]
    svc.get_all_active.assert_called_once()


def test_committee_roster_from_db_keeps_roles(monkeypatch):
    # committee_rosters.json 에 없는 위원회명이라 DB 폴백(2 경로)으로 간다
    rows = [{"name": "문형근", "committees": [{"name": "가상특별위원회", "role": "위원장"}]}]
    svc = _svc(rows, [{"name": "누구"}])
    monkeypatch.setattr("app.services.councilor_sync.CouncilorSyncService", lambda _sb: svc)

    out = roster_loader.load_committee_with_roles(MagicMock(), "가상특별위원회")

    assert out == [{"name": "문형근", "role": "위원장"}]
    svc.get_all_active.assert_not_called()


def test_json_roster_wins_over_db(monkeypatch):
    svc = _svc([], [{"name": "누구"}])
    monkeypatch.setattr("app.services.councilor_sync.CouncilorSyncService", lambda _sb: svc)

    out = roster_loader.load_committee_with_roles(MagicMock(), "의회운영위원회")

    assert out, "data/committee_rosters.json 의 의회운영위원회 명부가 읽혀야 한다"
    svc.get_all_active.assert_not_called()


def test_no_committee_returns_empty():
    assert roster_loader.load_committee_with_roles(MagicMock(), None) == []
