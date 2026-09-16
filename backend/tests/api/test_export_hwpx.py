"""hwpx 내보내기 엔드포인트 테스트

GET /api/meetings/{meeting_id}/export?format=hwpx
- ai_final 속기 레코드 + 라인이 있을 때 + 인증 → hwpx 다운로드 (라인 텍스트 포함)
- ai_final 레코드가 없을 때 → subtitles 폴백으로 hwpx 생성
- ai_final 레코드가 있어도 비인증 요청 → subtitles 폴백 (접근 통제)
"""
import io
import uuid
import zipfile
from typing import Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.auth_middleware import optional_auth
from app.core.database import get_supabase
from app.main import app
from tests.conftest import MockSupabaseClient

# ---------------------------------------------------------------------------
# 공통 픽스처 데이터
# ---------------------------------------------------------------------------

MEETING_ID = str(uuid.uuid4())
RECORD_ID = str(uuid.uuid4())

SAMPLE_MEETING = {
    "id": MEETING_ID,
    "title": "보건복지위원회 제3회 정례회의",
    "meeting_date": "2026-06-08",
    "status": "ended",
    "duration_seconds": 3600,
    "vod_url": None,
    "stream_url": None,
}

SAMPLE_STENO_RECORD = {
    "id": RECORD_ID,
    "meeting_id": MEETING_ID,
    "kind": "ai_final",
    "status": "approved",
    "stenographer_name": "홍길동",
}

SAMPLE_STENO_LINES = [
    {
        "id": str(uuid.uuid4()),
        "record_id": RECORD_ID,
        "sequence_no": 1,
        "text": "회의를 시작하겠습니다.",
        "speaker": "위원장",
        "start_ms": 0,
        "end_ms": 4000,
        "starts_new_paragraph": False,
    },
    {
        "id": str(uuid.uuid4()),
        "record_id": RECORD_ID,
        "sequence_no": 2,
        "text": "안건 제1호를 상정합니다.",
        "speaker": "위원장",
        "start_ms": 4000,
        "end_ms": 8000,
        "starts_new_paragraph": False,
    },
    {
        "id": str(uuid.uuid4()),
        "record_id": RECORD_ID,
        "sequence_no": 3,
        "text": "질의 사항이 있습니까?",
        "speaker": "김영수 위원",
        "start_ms": 8000,
        "end_ms": 12000,
        "starts_new_paragraph": True,
    },
]

SAMPLE_SUBTITLES = [
    {
        "id": str(uuid.uuid4()),
        "meeting_id": MEETING_ID,
        "start_time": 0.0,
        "end_time": 5.0,
        "text": "STT 자막 첫 번째",
        "speaker": "화자1",
        "confidence": 0.9,
    },
    {
        "id": str(uuid.uuid4()),
        "meeting_id": MEETING_ID,
        "start_time": 5.0,
        "end_time": 10.0,
        "text": "STT 자막 두 번째",
        "speaker": "화자1",
        "confidence": 0.85,
    },
]


# ---------------------------------------------------------------------------
# 헬퍼: MockSupabaseClient 를 hwpx 용 테이블 데이터로 조립
# ---------------------------------------------------------------------------

def _make_mock_client_with_final(
    steno_records: list[dict],
    steno_lines: list[dict],
    subtitles: list[dict] | None = None,
) -> MockSupabaseClient:
    """ai_final 레코드 + 라인이 있는 mock Supabase 클라이언트를 반환."""
    return MockSupabaseClient(
        table_data={
            "meetings": [SAMPLE_MEETING],
            "subtitles": subtitles or [],
            "meeting_summaries": [],
            "stenography_records": steno_records,
            "stenography_lines": steno_lines,
        }
    )


def _make_mock_client_no_final(subtitles: list[dict]) -> MockSupabaseClient:
    """ai_final 레코드가 없는 mock Supabase 클라이언트를 반환."""
    return MockSupabaseClient(
        table_data={
            "meetings": [SAMPLE_MEETING],
            "subtitles": subtitles,
            "meeting_summaries": [],
            "stenography_records": [],
            "stenography_lines": [],
        }
    )


# ---------------------------------------------------------------------------
# 테스트 클라이언트 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture
def client_with_final() -> Generator[TestClient, None, None]:
    """ai_final 속기 레코드 + 라인이 있는 Supabase mock 클라이언트 (인증된 admin 사용자)."""
    mock_supabase = _make_mock_client_with_final(
        steno_records=[SAMPLE_STENO_RECORD],
        steno_lines=SAMPLE_STENO_LINES,
        subtitles=SAMPLE_SUBTITLES,
    )
    app.dependency_overrides[get_supabase] = lambda: mock_supabase
    # optional_auth가 인증된 admin 사용자를 반환하도록 override
    app.dependency_overrides[optional_auth] = lambda: {"id": "u1", "username": "admin", "role": "admin"}
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_no_final() -> Generator[TestClient, None, None]:
    """ai_final 레코드가 없는 Supabase mock 클라이언트 (subtitles 폴백)."""
    mock_supabase = _make_mock_client_no_final(subtitles=SAMPLE_SUBTITLES)
    app.dependency_overrides[get_supabase] = lambda: mock_supabase
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 테스트
# ---------------------------------------------------------------------------

class TestExportHwpxWithFinal:
    """ai_final 속기 레코드가 있을 때 hwpx 다운로드 테스트."""

    def test_returns_200(self, client_with_final: TestClient):
        """hwpx 포맷 요청 시 200 응답을 반환한다."""
        with patch("app.api.exports.get_meeting_by_id_service", return_value=SAMPLE_MEETING):
            response = client_with_final.get(
                f"/api/meetings/{MEETING_ID}/export?format=hwpx"
            )
        assert response.status_code == 200

    def test_content_type_is_hwp_zip(self, client_with_final: TestClient):
        """Content-Type 이 application/hwp+zip 이어야 한다."""
        with patch("app.api.exports.get_meeting_by_id_service", return_value=SAMPLE_MEETING):
            response = client_with_final.get(
                f"/api/meetings/{MEETING_ID}/export?format=hwpx"
            )
        assert "application/hwp+zip" in response.headers["content-type"]

    def test_content_disposition_hwpx_filename(self, client_with_final: TestClient):
        """Content-Disposition 헤더에 .hwpx 파일명이 있어야 한다."""
        with patch("app.api.exports.get_meeting_by_id_service", return_value=SAMPLE_MEETING):
            response = client_with_final.get(
                f"/api/meetings/{MEETING_ID}/export?format=hwpx"
            )
        disposition = response.headers.get("content-disposition", "")
        assert "attachment" in disposition
        assert ".hwpx" in disposition

    def test_response_is_valid_zip(self, client_with_final: TestClient):
        """응답 바디가 유효한 ZIP 파일이어야 한다."""
        with patch("app.api.exports.get_meeting_by_id_service", return_value=SAMPLE_MEETING):
            response = client_with_final.get(
                f"/api/meetings/{MEETING_ID}/export?format=hwpx"
            )
        zf = zipfile.ZipFile(io.BytesIO(response.content))
        assert "Contents/section0.xml" in zf.namelist()
        assert "mimetype" in zf.namelist()

    def test_section_xml_contains_line_text(self, client_with_final: TestClient):
        """section0.xml 에 ai_final 라인 텍스트가 포함되어야 한다."""
        with patch("app.api.exports.get_meeting_by_id_service", return_value=SAMPLE_MEETING):
            response = client_with_final.get(
                f"/api/meetings/{MEETING_ID}/export?format=hwpx"
            )
        zf = zipfile.ZipFile(io.BytesIO(response.content))
        section = zf.read("Contents/section0.xml").decode("utf-8")
        # ai_final 라인의 텍스트가 들어가야 함
        assert "회의를 시작하겠습니다." in section
        assert "안건 제1호를 상정합니다." in section
        assert "질의 사항이 있습니까?" in section

    def test_section_xml_contains_speaker(self, client_with_final: TestClient):
        """section0.xml 에 화자 이름이 포함되어야 한다."""
        with patch("app.api.exports.get_meeting_by_id_service", return_value=SAMPLE_MEETING):
            response = client_with_final.get(
                f"/api/meetings/{MEETING_ID}/export?format=hwpx"
            )
        zf = zipfile.ZipFile(io.BytesIO(response.content))
        section = zf.read("Contents/section0.xml").decode("utf-8")
        assert "위원장" in section

    def test_does_not_contain_stt_subtitle_text(self, client_with_final: TestClient):
        """ai_final 이 있을 때 STT 자막 텍스트는 포함되지 않아야 한다."""
        with patch("app.api.exports.get_meeting_by_id_service", return_value=SAMPLE_MEETING):
            response = client_with_final.get(
                f"/api/meetings/{MEETING_ID}/export?format=hwpx"
            )
        zf = zipfile.ZipFile(io.BytesIO(response.content))
        section = zf.read("Contents/section0.xml").decode("utf-8")
        assert "STT 자막 첫 번째" not in section


class TestExportHwpxFallback:
    """ai_final 레코드가 없을 때 subtitles 폴백 테스트."""

    def test_returns_200_fallback(self, client_no_final: TestClient):
        """ai_final 없어도 200 응답을 반환한다."""
        with patch("app.api.exports.get_meeting_by_id_service", return_value=SAMPLE_MEETING):
            response = client_no_final.get(
                f"/api/meetings/{MEETING_ID}/export?format=hwpx"
            )
        assert response.status_code == 200

    def test_fallback_contains_subtitle_text(self, client_no_final: TestClient):
        """ai_final 없을 때 subtitles 텍스트가 section0.xml 에 포함되어야 한다."""
        with patch("app.api.exports.get_meeting_by_id_service", return_value=SAMPLE_MEETING):
            response = client_no_final.get(
                f"/api/meetings/{MEETING_ID}/export?format=hwpx"
            )
        zf = zipfile.ZipFile(io.BytesIO(response.content))
        section = zf.read("Contents/section0.xml").decode("utf-8")
        assert "STT 자막 첫 번째" in section


class TestExportHwpxEdgeCases:
    """엣지 케이스 테스트."""

    def test_404_when_meeting_not_found(self):
        """존재하지 않는 회의 ID로 요청하면 404 응답을 반환한다."""
        mock_supabase = MockSupabaseClient()
        app.dependency_overrides[get_supabase] = lambda: mock_supabase
        try:
            client = TestClient(app)
            with patch("app.api.exports.get_meeting_by_id_service", return_value=None):
                response = client.get(
                    f"/api/meetings/{MEETING_ID}/export?format=hwpx"
                )
            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_hwpx_with_empty_lines_and_subtitles(self):
        """라인도 자막도 없을 때 빈 문서 hwpx를 반환한다."""
        mock_supabase = _make_mock_client_with_final(
            steno_records=[SAMPLE_STENO_RECORD],
            steno_lines=[],  # 빈 라인
            subtitles=[],
        )
        app.dependency_overrides[get_supabase] = lambda: mock_supabase
        app.dependency_overrides[optional_auth] = lambda: {"id": "u1", "username": "admin", "role": "admin"}
        try:
            client = TestClient(app)
            with patch("app.api.exports.get_meeting_by_id_service", return_value=SAMPLE_MEETING):
                response = client.get(
                    f"/api/meetings/{MEETING_ID}/export?format=hwpx"
                )
            assert response.status_code == 200
            zf = zipfile.ZipFile(io.BytesIO(response.content))
            assert "Contents/section0.xml" in zf.namelist()
        finally:
            app.dependency_overrides.clear()


class TestExportHwpxAnonymousFallback:
    """비인증(익명) 요청 시 ai_final이 있어도 subtitles 폴백이 적용되는지 검증."""

    def test_anonymous_gets_subtitle_fallback_when_ai_final_exists(self):
        """비인증 요청은 ai_final 레코드가 있어도 STT 자막을 반환해야 한다.

        ai_final 전용 텍스트("회의를 시작하겠습니다.")가 노출되지 않고
        STT 자막 텍스트("STT 자막 첫 번째")가 포함되어야 한다.
        """
        mock_supabase = _make_mock_client_with_final(
            steno_records=[SAMPLE_STENO_RECORD],
            steno_lines=SAMPLE_STENO_LINES,
            subtitles=SAMPLE_SUBTITLES,
        )
        app.dependency_overrides[get_supabase] = lambda: mock_supabase
        # optional_auth 를 override하지 않으면 실제 JWT 검증이 일어나므로
        # 명시적으로 None(비인증)을 반환하도록 override한다.
        app.dependency_overrides[optional_auth] = lambda: None
        try:
            client = TestClient(app)
            with patch("app.api.exports.get_meeting_by_id_service", return_value=SAMPLE_MEETING):
                response = client.get(
                    f"/api/meetings/{MEETING_ID}/export?format=hwpx"
                )
            assert response.status_code == 200
            zf = zipfile.ZipFile(io.BytesIO(response.content))
            section = zf.read("Contents/section0.xml").decode("utf-8")
            # ai_final 전용 텍스트는 포함되면 안 됨
            assert "회의를 시작하겠습니다." not in section
            assert "안건 제1호를 상정합니다." not in section
            # STT 자막 텍스트는 포함되어야 함
            assert "STT 자막 첫 번째" in section
        finally:
            app.dependency_overrides.clear()


class TestExportHwpxMissingStenoTable:
    """stenography_records 테이블이 없는 환경(마이그레이션 미적용)에서 fail-soft 검증.

    회귀 방지: 인증 사용자의 ai_final 존재 프로브가 APIError를 그대로 전파해
    hwpx/minutes-markdown 경로 전체가 500이 되던 버그 — 자막 폴백으로 동작해야 한다.
    """

    def test_authorized_falls_back_when_steno_table_missing(self):
        mock_supabase = _make_mock_client_no_final(subtitles=SAMPLE_SUBTITLES)

        class _RaisingOnStenoTable:
            """stenography_records 접근 시에만 예외를 던지는 래퍼."""

            def __init__(self, inner):
                self._inner = inner

            def table(self, name: str):
                if name == "stenography_records":
                    raise RuntimeError("PGRST205: Could not find the table")
                return self._inner.table(name)

            def __getattr__(self, item):
                return getattr(self._inner, item)

        app.dependency_overrides[get_supabase] = lambda: _RaisingOnStenoTable(mock_supabase)
        app.dependency_overrides[optional_auth] = lambda: {"id": "u1", "username": "admin", "role": "admin"}
        try:
            client = TestClient(app)
            with patch("app.api.exports.get_meeting_by_id_service", return_value=SAMPLE_MEETING):
                response = client.get(f"/api/meetings/{MEETING_ID}/export?format=hwpx")
            assert response.status_code == 200
            zf = zipfile.ZipFile(io.BytesIO(response.content))
            section = zf.read("Contents/section0.xml").decode("utf-8")
            assert "STT 자막 첫 번째" in section
        finally:
            app.dependency_overrides.clear()
