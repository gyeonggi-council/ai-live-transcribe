"""AI 회의록 최종본 생성/상태 API 테스트."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_supabase
from app.main import app
from tests.conftest import (
    AuthAwareMockQuery,
    TEST_ADMIN_USER,
    MockSupabaseResponse,
    get_admin_auth_header,
)

_AUTH = get_admin_auth_header()


# ---------------------------------------------------------------------------
# Mock Supabase client (supports auth middleware users lookup)
# ---------------------------------------------------------------------------


class _FtMockQuery(AuthAwareMockQuery):
    """final-transcript 테스트용 쿼리 — users 테이블 eq 필터링 지원."""

    def limit(self, *args, **kwargs) -> "_FtMockQuery":
        return self

    def order(self, *args, **kwargs) -> "_FtMockQuery":
        return self


class _FtMockSupabase:
    def __init__(self, table_data: dict | None = None):
        self._table_data = table_data or {}
        if "users" not in self._table_data:
            self._table_data["users"] = [TEST_ADMIN_USER]

    def table(self, name: str) -> _FtMockQuery:
        data = self._table_data.get(name, [])
        return _FtMockQuery(data=data)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFinalTranscriptStatus:
    """GET /api/meetings/{id}/final-transcript/status"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_status_idle_when_no_task(self):
        """태스크가 없으면 status=idle을 반환한다."""
        import app.api.final_transcript as ft

        meeting_id = str(uuid.uuid4())

        # patch get_final_task to return None (no task for this meeting)
        original = ft.get_final_task
        ft.get_final_task = lambda mid: None
        try:
            app.dependency_overrides[get_supabase] = lambda: _FtMockSupabase()
            client = TestClient(app)

            resp = client.get(f"/api/meetings/{meeting_id}/final-transcript/status")

            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "idle"
            assert body["progress"] == 0.0
            assert body["record_id"] is None
        finally:
            ft.get_final_task = original

    def test_status_returns_task_fields_when_task_exists(self):
        """태스크가 존재하면 해당 필드를 반환한다."""
        import app.api.final_transcript as ft
        from app.services.final_transcript_service import FinalTaskStatus

        meeting_id = str(uuid.uuid4())
        fake_task = FinalTaskStatus(
            meeting_id=meeting_id,
            status="running",
            progress=0.5,
            message="AI 교정 중",
            record_id=None,
        )

        original = ft.get_final_task
        ft.get_final_task = lambda mid: fake_task
        try:
            app.dependency_overrides[get_supabase] = lambda: _FtMockSupabase()
            client = TestClient(app)

            resp = client.get(f"/api/meetings/{meeting_id}/final-transcript/status")

            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "running"
            assert body["progress"] == 0.5
            assert body["message"] == "AI 교정 중"
        finally:
            ft.get_final_task = original


class TestStartFinalTranscript:
    """POST /api/meetings/{id}/final-transcript"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_start_is_disabled_returns_403(self, monkeypatch):
        """★기능 비활성(사용자 결정 2026-06-11): AI 최종본 생성은 VOD 전체 재전사로
        AI 자막과 중복 지출이라 항상 403을 반환한다 (파이프라인 코드는 보존)."""
        import app.api.final_transcript as ft

        meeting_id = str(uuid.uuid4())

        monkeypatch.setattr(ft, "is_generating", lambda mid: False)
        monkeypatch.setattr(ft, "generate_final_transcript", AsyncMock())

        app.dependency_overrides[get_supabase] = lambda: _FtMockSupabase()
        client = TestClient(app)

        resp = client.post(
            f"/api/meetings/{meeting_id}/final-transcript",
            json={"precise_mode": False},
            headers=_AUTH,
        )

        assert resp.status_code == 403
        assert "비활성" in resp.json()["detail"]

    def test_start_returns_401_without_auth(self, monkeypatch):
        """인증 헤더 없이 요청하면 401을 반환한다."""
        import app.api.final_transcript as ft

        meeting_id = str(uuid.uuid4())

        monkeypatch.setattr(ft, "is_generating", lambda mid: False)
        monkeypatch.setattr(ft, "generate_final_transcript", AsyncMock())

        app.dependency_overrides[get_supabase] = lambda: _FtMockSupabase()
        client = TestClient(app)

        resp = client.post(
            f"/api/meetings/{meeting_id}/final-transcript",
            json={},
            # no headers
        )

        assert resp.status_code == 401
