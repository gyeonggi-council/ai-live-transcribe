"""영상추출기(exe) 배포/자동업데이트 채널 테스트 (TDD RED -> GREEN)

# @TASK C1-distribution - version.json + 설치파일 호스팅 (brew 식 배포 채널)

exe 클라이언트가 GET /api/tools/extractor/version.json 을 폴링하여
새 버전이면 url 에서 설치파일을 내려받아 자동업데이트한다.
"""

import hashlib
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_supabase
from app.main import app
from app.services import tool_release_service as trs
from app.services.auth_service import create_access_token
from tests.conftest import TEST_ADMIN_USER, MockSupabaseClient

# ---------------------------------------------------------------------------
# 테스트 데이터
# ---------------------------------------------------------------------------
STAFF_USER_ID = "00000000-0000-0000-0000-000000000002"
STAFF_USER = {
    "id": STAFF_USER_ID,
    "username": "staff",
    "password_hash": "$2b$12$dummy",  # 실제 검증 안 함
    "display_name": "테스트 직원",
    "role": "staff",
    "assigned_committee": None,
    "is_active": True,
    "last_login_at": None,
    "created_at": "2026-01-01T00:00:00+00:00",
}

# 가짜 설치파일 (실제 exe 아님 — 스트리밍/해시 검증용)
EXE_BYTES = b"MZ" + bytes(range(256)) * 4


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------
@pytest.fixture
def release_dir(tmp_path, monkeypatch):
    """RELEASE_DIR를 tmp_path로 격리 (실제 backend/data 오염 방지)."""
    monkeypatch.setattr(trs, "RELEASE_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def client(release_dir) -> Generator[TestClient, None, None]:
    """admin + staff 사용자가 있는 테스트 클라이언트 (release_dir 격리 포함)."""
    mock_supabase = MockSupabaseClient(
        table_data={"users": [TEST_ADMIN_USER, STAFF_USER]}
    )
    app.dependency_overrides[get_supabase] = lambda: mock_supabase
    yield TestClient(app)
    app.dependency_overrides.clear()


def _admin_header() -> dict[str, str]:
    token = create_access_token({"sub": TEST_ADMIN_USER["id"], "role": "admin"})
    return {"Authorization": f"Bearer {token}"}


def _staff_header() -> dict[str, str]:
    token = create_access_token({"sub": STAFF_USER_ID, "role": "staff"})
    return {"Authorization": f"Bearer {token}"}


def _upload(
    client: TestClient,
    version: str = "1.0.0",
    notes: str = "첫 배포",
    filename: str | None = "ggc-extractor-setup.exe",
    content: bytes = EXE_BYTES,
    external_url: str | None = None,
    headers: dict | None = None,
):
    """업로드 요청 헬퍼. headers 미지정 시 admin 토큰 사용."""
    data = {"version": version, "notes": notes}
    files = None
    if external_url is not None:
        data["external_url"] = external_url
    elif filename is not None:
        files = {"file": (filename, content, "application/octet-stream")}
    return client.post(
        "/api/tools/extractor/upload",
        data=data,
        files=files,
        headers=_admin_header() if headers is None else headers,
    )


# ---------------------------------------------------------------------------
# version.json
# ---------------------------------------------------------------------------
def test_version_json_404_when_empty(client):
    """배포된 버전이 없으면 version.json은 404."""
    resp = client.get("/api/tools/extractor/version.json")
    assert resp.status_code == 404


def test_version_json_public_after_upload(client):
    """업로드 후 version.json은 비로그인으로도 조회 가능해야 한다."""
    assert _upload(client, version="1.2.3", notes="버그 수정").status_code == 201

    resp = client.get("/api/tools/extractor/version.json")  # 인증 헤더 없음
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == "1.2.3"
    assert body["notes"] == "버그 수정"
    assert body["name"]
    assert body["published_at"]
    assert body["url"].startswith("http")
    assert body["url"].endswith("/api/tools/extractor/download")
    assert body["sha256"] == hashlib.sha256(EXE_BYTES).hexdigest()
    assert body["size"] == len(EXE_BYTES)
    assert body["min_supported_version"] is None


# ---------------------------------------------------------------------------
# upload (admin 전용)
# ---------------------------------------------------------------------------
def test_upload_requires_admin(client):
    """비로그인은 401, staff는 403."""
    resp = _upload(client, headers={})
    assert resp.status_code == 401

    resp = _upload(client, headers=_staff_header())
    assert resp.status_code == 403


def test_upload_stores_file_sha256_and_manifest(client, release_dir):
    """업로드 시 설치파일 저장 + sha256/size 계산 + 매니페스트 기록."""
    resp = _upload(client, version="1.0.0")
    assert resp.status_code == 201
    body = resp.json()
    assert body["version"] == "1.0.0"
    assert body["sha256"] == hashlib.sha256(EXE_BYTES).hexdigest()
    assert body["size"] == len(EXE_BYTES)

    stored = release_dir / "ggc-extractor-setup-1.0.0.exe"
    assert stored.exists()
    assert stored.read_bytes() == EXE_BYTES

    manifest = trs.load_manifest()
    assert manifest is not None
    assert manifest["version"] == "1.0.0"
    assert manifest["sha256"] == body["sha256"]


def test_upload_rejects_bad_version_400(client):
    """버전 형식(^\\d+\\.\\d+(\\.\\d+)?$)이 아니면 400."""
    for bad in ("v1.0", "1", "1.0.0.0", "abc", "1.0-beta"):
        resp = _upload(client, version=bad)
        assert resp.status_code == 400, f"version={bad}"


def test_upload_rejects_version_with_trailing_newline_400(client):
    """'1.0\\n'처럼 개행이 붙은 버전은 400.

    re.match + '$' 는 문자열 끝 개행 앞에서도 매칭돼 통과했고, 개행이 저장
    파일명에 들어가 Windows에서 OSError(500)를 내던 회귀 케이스 (fullmatch 필요).
    """
    resp = _upload(client, version="1.0\n")
    assert resp.status_code == 400


def test_upload_rejects_non_exe_400(client):
    """.exe 가 아닌 파일은 400."""
    resp = _upload(client, filename="setup.zip")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------
def test_download_serves_installer_with_filename(client):
    """다운로드는 application/octet-stream + 버전 포함 파일명으로 응답."""
    assert _upload(client, version="2.1.0").status_code == 201

    resp = client.get("/api/tools/extractor/download")
    assert resp.status_code == 200
    assert resp.content == EXE_BYTES
    assert resp.headers["content-type"].startswith("application/octet-stream")
    assert "ggc-extractor-setup-2.1.0.exe" in resp.headers.get(
        "content-disposition", ""
    )


def test_upload_with_external_url_redirects_download(client):
    """external_url 배포 시 다운로드는 307 리다이렉트."""
    url = "https://releases.example.com/ggc-extractor-setup-3.0.0.exe"
    resp = _upload(client, version="3.0.0", external_url=url)
    assert resp.status_code == 201

    resp = client.get("/api/tools/extractor/download", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == url


# ---------------------------------------------------------------------------
# 매니페스트 영속성 (서비스 단위)
# ---------------------------------------------------------------------------
def test_manifest_survives_reload(release_dir):
    """save_manifest 후 load_manifest 결과가 일치해야 한다 (원자적 쓰기)."""
    manifest = {
        "name": "경기도의회 영상추출기",
        "version": "1.0.1",
        "notes": "안정성 개선",
        "published_at": "2026-07-04T00:00:00+00:00",
        "sha256": "abc123",
        "size": 1234,
        "file": "ggc-extractor-setup-1.0.1.exe",
        "external_url": None,
        "min_supported_version": None,
    }
    trs.save_manifest(manifest)
    assert trs.load_manifest() == manifest
