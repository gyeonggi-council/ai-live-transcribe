"""kordoc 엔진 내보내기 API 테스트

- GET /api/meetings/{id}/export?format=hwpx&engine=kordoc — 공문서 서식 hwpx
- GET /api/meetings/{id}/minutes-markdown — 마크다운 중간층(미리보기/편집)
- POST /api/meetings/{id}/export/hwpx-from-markdown — 편집 마크다운 → hwpx

kordoc(subprocess)은 monkeypatch/patch로 대체한다.
"""

import uuid
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.auth_middleware import optional_auth
from app.core.database import get_supabase
from app.main import app
from tests.conftest import MockSupabaseClient

MEETING_ID = str(uuid.uuid4())

SAMPLE_MEETING = {
    "id": MEETING_ID,
    "title": "제391회 제3차 경제노동위원회 [2026-06-16]",
    "meeting_date": "2026-06-16",
    "status": "ended",
    "duration_seconds": 3600,
    "vod_url": None,
    "stream_url": None,
}

SAMPLE_SUBTITLES = [
    {
        "id": str(uuid.uuid4()),
        "meeting_id": MEETING_ID,
        "start_time": 0.0,
        "end_time": 5.0,
        "text": "STT 자막 첫 번째",
        "speaker": "허원 위원장",
        "confidence": 0.9,
    },
    {
        "id": str(uuid.uuid4()),
        "meeting_id": MEETING_ID,
        "start_time": 5.0,
        "end_time": 10.0,
        "text": "STT 자막 두 번째",
        "speaker": "허원 위원장",
        "confidence": 0.85,
    },
]

ADMIN_USER = {"id": "u1", "username": "admin", "role": "admin"}


def _mock_db(subtitles: list[dict]) -> MockSupabaseClient:
    return MockSupabaseClient(
        table_data={
            "meetings": [SAMPLE_MEETING],
            "subtitles": subtitles,
            "meeting_summaries": [],
            "stenography_records": [],
            "stenography_lines": [],
            "meeting_agendas": [],
        }
    )


@pytest.fixture
def client_auth() -> Generator[TestClient, None, None]:
    """자막 데이터 + 인증된 admin 사용자."""
    app.dependency_overrides[get_supabase] = lambda: _mock_db(SAMPLE_SUBTITLES)
    app.dependency_overrides[optional_auth] = lambda: ADMIN_USER
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_auth_no_subtitles() -> Generator[TestClient, None, None]:
    """자막 없는 회의 + 인증된 admin 사용자."""
    app.dependency_overrides[get_supabase] = lambda: _mock_db([])
    app.dependency_overrides[optional_auth] = lambda: ADMIN_USER
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_anon() -> Generator[TestClient, None, None]:
    """비인증(익명) 클라이언트 — optional_auth를 override하지 않아 None이 된다."""
    app.dependency_overrides[get_supabase] = lambda: _mock_db(SAMPLE_SUBTITLES)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _patch_meeting():
    return patch("app.api.exports.get_meeting_by_id_service", return_value=SAMPLE_MEETING)


def _patch_agendas():
    """ensure_agendas(LLM 호출 가능)를 빈 목록으로 대체 — 테스트에서 외부 호출 차단."""
    return patch(
        "app.services.agenda_draft_service.ensure_agendas",
        new_callable=AsyncMock,
        return_value=[],
    )


# ---------------------------------------------------------------------------
# GET export?format=hwpx — engine 파라미터
# ---------------------------------------------------------------------------

class TestExportEngineParam:
    def test_default_engine_is_native_and_kordoc_not_called(self, client_auth: TestClient):
        """engine 미지정 시 기존 native 경로(export_hwpx)를 그대로 사용하고
        kordoc은 호출되지 않는다 (기존 동작 불변)."""
        kordoc_mock = AsyncMock(return_value=b"KORDOC")
        with _patch_meeting(), _patch_agendas(), \
                patch("app.api.exports.export_hwpx", return_value=b"NATIVEBYTES") as native, \
                patch("app.services.kordoc_service.markdown_to_hwpx", kordoc_mock):
            response = client_auth.get(f"/api/meetings/{MEETING_ID}/export?format=hwpx")
        assert response.status_code == 200
        assert response.content == b"NATIVEBYTES"
        native.assert_called_once()
        kordoc_mock.assert_not_called()

    def test_engine_kordoc_success(self, client_auth: TestClient):
        """engine=kordoc이면 build_official_markdown → kordoc으로 hwpx를 생성한다."""
        kordoc_mock = AsyncMock(return_value=b"PK-KORDOC-HWPX")
        with _patch_meeting(), _patch_agendas(), \
                patch("app.api.exports.export_hwpx", MagicMock()) as native, \
                patch("app.services.kordoc_service.is_available", return_value=True), \
                patch("app.services.kordoc_service.markdown_to_hwpx", kordoc_mock):
            response = client_auth.get(
                f"/api/meetings/{MEETING_ID}/export?format=hwpx&engine=kordoc"
            )
        assert response.status_code == 200
        assert response.content == b"PK-KORDOC-HWPX"
        assert "application/hwp+zip" in response.headers["content-type"]
        assert ".hwpx" in response.headers.get("content-disposition", "")
        native.assert_not_called()
        # kordoc에 전달된 마크다운은 공식 회의록 구조를 담아야 한다
        kordoc_mock.assert_awaited_once()
        markdown_arg = kordoc_mock.await_args.args[0]
        assert "경제노동위원회 회의록" in markdown_arg
        assert "STT 자막 첫 번째" in markdown_arg

    def test_engine_kordoc_unavailable_returns_503(self, client_auth: TestClient):
        """npx(kordoc) 사용 불가 시 503 + 명확한 detail."""
        with _patch_meeting(), _patch_agendas(), \
                patch("app.services.kordoc_service.is_available", return_value=False):
            response = client_auth.get(
                f"/api/meetings/{MEETING_ID}/export?format=hwpx&engine=kordoc"
            )
        assert response.status_code == 503
        assert "kordoc" in response.json()["detail"]

    def test_engine_kordoc_runtime_failure_returns_503(self, client_auth: TestClient):
        """kordoc 실행 실패(RuntimeError) 시 503 + 일반 detail.

        subprocess stderr(경로·버전 등 내부 정보)는 응답으로 유출하지 않고
        logger.error 로만 남긴다.
        """
        with _patch_meeting(), _patch_agendas(), \
                patch("app.services.kordoc_service.is_available", return_value=True), \
                patch("app.services.kordoc_service.markdown_to_hwpx",
                      AsyncMock(side_effect=RuntimeError(
                          "npm boom: ffmpeg /usr/lib/node_modules stderr dump"
                      ))):
            response = client_auth.get(
                f"/api/meetings/{MEETING_ID}/export?format=hwpx&engine=kordoc"
            )
        assert response.status_code == 503
        detail = response.json()["detail"]
        assert "npm boom" not in detail        # stderr 유출 금지
        assert "ffmpeg" not in detail
        assert "hwpx 생성에 실패" in detail    # 사용자용 일반 메시지

    def test_engine_kordoc_requires_auth_401(self, client_anon: TestClient):
        """비로그인 + engine=kordoc → 401 (node 서브프로세스 자원 보호).
        kordoc 변환은 호출조차 되지 않아야 한다."""
        kordoc_mock = AsyncMock(return_value=b"PK-KORDOC-HWPX")
        with _patch_meeting(), \
                patch("app.services.kordoc_service.is_available", return_value=True), \
                patch("app.services.kordoc_service.markdown_to_hwpx", kordoc_mock):
            response = client_anon.get(
                f"/api/meetings/{MEETING_ID}/export?format=hwpx&engine=kordoc"
            )
        assert response.status_code == 401
        assert "로그인" in response.json()["detail"]
        kordoc_mock.assert_not_called()

    def test_engine_native_allows_anonymous(self, client_anon: TestClient):
        """비로그인 + engine 미지정(native 기본)은 기존대로 hwpx를 반환한다."""
        with _patch_meeting(), \
                patch("app.api.exports.export_hwpx", return_value=b"NATIVEBYTES") as native:
            response = client_anon.get(
                f"/api/meetings/{MEETING_ID}/export?format=hwpx"
            )
        assert response.status_code == 200
        assert response.content == b"NATIVEBYTES"
        native.assert_called_once()

    def test_non_hwpx_format_ignores_engine(self, client_auth: TestClient):
        """hwpx 외 형식은 engine 파라미터와 무관하게 기존 동작을 유지한다."""
        with _patch_meeting():
            response = client_auth.get(
                f"/api/meetings/{MEETING_ID}/export?format=markdown&engine=kordoc"
            )
        assert response.status_code == 200
        assert "text/markdown" in response.headers["content-type"]


# ---------------------------------------------------------------------------
# GET minutes-markdown
# ---------------------------------------------------------------------------

class TestMinutesMarkdown:
    def test_requires_auth_401(self, client_anon: TestClient):
        with _patch_meeting():
            response = client_anon.get(f"/api/meetings/{MEETING_ID}/minutes-markdown")
        assert response.status_code == 401

    def test_success_structure(self, client_auth: TestClient):
        """{"markdown": str, "kordoc_available": bool} 구조를 반환한다."""
        with _patch_meeting(), _patch_agendas(), \
                patch("app.services.kordoc_service.is_available", return_value=True):
            response = client_auth.get(f"/api/meetings/{MEETING_ID}/minutes-markdown")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body["markdown"], str)
        assert body["kordoc_available"] is True
        assert "경제노동위원회 회의록" in body["markdown"]
        assert "STT 자막 첫 번째" in body["markdown"]

    def test_kordoc_available_false_passthrough(self, client_auth: TestClient):
        with _patch_meeting(), _patch_agendas(), \
                patch("app.services.kordoc_service.is_available", return_value=False):
            response = client_auth.get(f"/api/meetings/{MEETING_ID}/minutes-markdown")
        assert response.status_code == 200
        assert response.json()["kordoc_available"] is False

    def test_409_when_no_subtitles(self, client_auth_no_subtitles: TestClient):
        with _patch_meeting(), _patch_agendas():
            response = client_auth_no_subtitles.get(
                f"/api/meetings/{MEETING_ID}/minutes-markdown"
            )
        assert response.status_code == 409

    def test_404_when_meeting_missing(self, client_auth: TestClient):
        with patch("app.api.exports.get_meeting_by_id_service", return_value=None):
            response = client_auth.get(f"/api/meetings/{MEETING_ID}/minutes-markdown")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST export/hwpx-from-markdown
# ---------------------------------------------------------------------------

class TestHwpxFromMarkdown:
    URL = f"/api/meetings/{MEETING_ID}/export/hwpx-from-markdown"

    def test_requires_auth_401(self, client_anon: TestClient):
        with _patch_meeting():
            response = client_anon.post(self.URL, json={"markdown": "# 제목"})
        assert response.status_code == 401

    def test_success_returns_hwpx_with_edited_suffix(self, client_auth: TestClient):
        kordoc_mock = AsyncMock(return_value=b"PK-EDITED-HWPX")
        with _patch_meeting(), \
                patch("app.services.kordoc_service.is_available", return_value=True), \
                patch("app.services.kordoc_service.markdown_to_hwpx", kordoc_mock):
            response = client_auth.post(
                self.URL, json={"markdown": "# 제391회 경기도의회\n\n수정된 본문"}
            )
        assert response.status_code == 200
        assert response.content == b"PK-EDITED-HWPX"
        assert "application/hwp+zip" in response.headers["content-type"]
        disposition = response.headers.get("content-disposition", "")
        assert "_edited.hwpx" in disposition
        kordoc_mock.assert_awaited_once()
        assert kordoc_mock.await_args.args[0] == "# 제391회 경기도의회\n\n수정된 본문"

    def test_413_when_markdown_exceeds_2mb(self, client_auth: TestClient):
        big = "a" * (2 * 1024 * 1024 + 1)
        with _patch_meeting(), \
                patch("app.services.kordoc_service.is_available", return_value=True):
            response = client_auth.post(self.URL, json={"markdown": big})
        assert response.status_code == 413

    def test_503_when_kordoc_unavailable(self, client_auth: TestClient):
        with _patch_meeting(), \
                patch("app.services.kordoc_service.is_available", return_value=False):
            response = client_auth.post(self.URL, json={"markdown": "# 제목"})
        assert response.status_code == 503
        assert "kordoc" in response.json()["detail"]

    def test_404_when_meeting_missing(self, client_auth: TestClient):
        with patch("app.api.exports.get_meeting_by_id_service", return_value=None), \
                patch("app.services.kordoc_service.is_available", return_value=True):
            response = client_auth.post(self.URL, json={"markdown": "# 제목"})
        assert response.status_code == 404
