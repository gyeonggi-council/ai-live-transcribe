"""안건 초안 생성 1회 가드 테스트 (migration 026 시도 마커)

배경: 추출 0개로 끝난 생성 시도는 meeting_agendas에 흔적이 없어
"안건 존재 여부" 가드가 뚫렸다. meetings.agenda_draft_at 마커가
결과와 무관하게 시도 자체를 차단해야 한다.
"""

import uuid
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_supabase
from app.main import app


class _MockResponse:
    def __init__(self, data: list):
        self.data = data


class _MockQuery:
    def __init__(self, data: list, update_log: list | None = None, table: str = ""):
        self._data = data
        self._update_log = update_log
        self._table = table
        self._update_payload: dict | None = None

    def select(self, *a, **kw):
        return self

    def eq(self, *a, **kw):
        return self

    def limit(self, *a, **kw):
        return self

    def order(self, *a, **kw):
        return self

    def update(self, payload, **kw):
        self._update_payload = payload
        if self._update_log is not None:
            self._update_log.append({"table": self._table, "payload": payload})
        return self

    def insert(self, *a, **kw):
        return self

    def execute(self):
        if self._update_payload and self._data:
            return _MockResponse(data=[{**self._data[0], **self._update_payload}])
        return _MockResponse(data=self._data)


class _MockClient:
    def __init__(self, meetings: list, agendas: list):
        self._meetings = meetings
        self._agendas = agendas
        self.update_log: list[dict] = []

    def table(self, name: str):
        if name == "meetings":
            return _MockQuery(self._meetings, self.update_log, "meetings")
        if name == "meeting_agendas":
            return _MockQuery(self._agendas, self.update_log, "meeting_agendas")
        return _MockQuery([], self.update_log, name)


@pytest.fixture
def meeting_id() -> str:
    return str(uuid.uuid4())


def _client(mock: _MockClient) -> Generator[TestClient, None, None]:
    app.dependency_overrides[get_supabase] = lambda: mock
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def _openai_key(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", "sk-test")


class TestAgendaDraftOnceGuard:
    def test_marker_set_blocks_even_with_zero_agendas(self, meeting_id, _openai_key):
        """시도 마커가 있으면 안건 0개여도 409 — 0개 추출 재실행 구멍 회귀 방지."""
        mock = _MockClient(
            meetings=[{"agenda_draft_at": "2026-07-05T01:00:00+00:00"}],
            agendas=[],  # 추출 0개로 끝났던 회의
        )
        for client in _client(mock):
            resp = client.post(f"/api/meetings/{meeting_id}/agenda-draft")
            assert resp.status_code == 409
            assert "1회" in resp.json()["detail"]

    def test_existing_agendas_block_without_marker(self, meeting_id, _openai_key):
        """마커 도입 전 생성된 회의(마커 NULL, 안건 존재)도 호환 가드로 409."""
        mock = _MockClient(
            meetings=[{"agenda_draft_at": None}],
            agendas=[{"id": "a1"}],
        )
        for client in _client(mock):
            resp = client.post(f"/api/meetings/{meeting_id}/agenda-draft")
            assert resp.status_code == 409

    def test_first_run_records_marker(self, meeting_id, _openai_key, monkeypatch):
        """최초 실행은 통과하고, 성공 후 agenda_draft_at 마커를 기록한다."""

        async def _fake_generate(supabase, mid):
            return {"meeting_id": mid, "agendas": [], "created_agendas": 0}

        import app.services.agenda_draft_service as svc

        monkeypatch.setattr(svc, "generate_agenda_draft", _fake_generate)

        mock = _MockClient(meetings=[{"agenda_draft_at": None}], agendas=[])
        for client in _client(mock):
            resp = client.post(f"/api/meetings/{meeting_id}/agenda-draft")
            assert resp.status_code == 200
            marker_updates = [
                u
                for u in mock.update_log
                if u["table"] == "meetings" and "agenda_draft_at" in u["payload"]
            ]
            assert marker_updates, "성공 후 meetings.agenda_draft_at 마커가 기록되어야 함"
