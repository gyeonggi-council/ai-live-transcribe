"""회의 영상 썸네일 API·서비스 테스트

배경: KMS MP4 는 moov 가 파일 끝에 있고 1시간짜리가 ~937MB 라, 브라우저가
`<video preload="metadata">` 로 썸네일을 만들면 회의당 수 MB 를 받는다.
서버가 ffmpeg 로 뽑아 캐시하는 경로가 이 테스트의 대상이다.
"""

import asyncio
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import thumbnail_service


@pytest.fixture
def meeting_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """캐시 디렉터리를 테스트마다 격리하고 실패 기억을 비운다."""
    monkeypatch.setattr(thumbnail_service, "THUMBNAIL_DIR", tmp_path / "thumbnails")
    thumbnail_service._failed_until.clear()
    thumbnail_service._locks.clear()
    yield


# =============================================================================
# 서비스
# =============================================================================

def test_returns_cached_file_without_running_ffmpeg(meeting_id):
    """캐시가 있으면 ffmpeg 를 다시 돌리지 않는다."""
    cached = thumbnail_service.thumbnail_path(meeting_id)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(b"\xff\xd8\xff\xdb-fake-jpeg")

    with patch.object(thumbnail_service, "_extract") as extract:
        result = asyncio.run(
            thumbnail_service.ensure_thumbnail(meeting_id, "https://kms.ggc.go.kr/a.mp4")
        )

    assert result == cached
    extract.assert_not_called()


def test_returns_none_without_vod_url(meeting_id):
    """VOD 가 등록되지 않은 회의는 뽑을 대상이 없다."""
    assert asyncio.run(thumbnail_service.ensure_thumbnail(meeting_id, None)) is None


def test_failure_is_remembered_so_ffmpeg_is_not_hammered(meeting_id):
    """실패한 회의를 매 요청마다 재시도하면 ffmpeg 폭주가 된다."""
    calls = []

    async def failing_extract(mid: str, url: str) -> Path | None:
        calls.append(mid)
        thumbnail_service._failed_until[mid] = thumbnail_service.time.monotonic() + 600
        return None

    with patch.object(thumbnail_service, "_extract", failing_extract):
        first = asyncio.run(
            thumbnail_service.ensure_thumbnail(meeting_id, "https://kms.ggc.go.kr/a.mp4")
        )
        second = asyncio.run(
            thumbnail_service.ensure_thumbnail(meeting_id, "https://kms.ggc.go.kr/a.mp4")
        )

    assert first is None and second is None
    assert calls == [meeting_id], "두 번째 요청은 ffmpeg 를 다시 돌리면 안 된다"


def test_ffmpeg_command_carries_kms_browser_headers():
    """KMS 는 브라우저 헤더가 없으면 HTML 오류 페이지를 준다."""
    cmd = thumbnail_service._build_command("https://kms.ggc.go.kr/a.mp4", Path("/tmp/x.jpg"))

    assert cmd[0] == "ffmpeg"
    assert "-user_agent" in cmd
    joined = " ".join(cmd)
    assert "Referer" in joined
    # -ss 는 -i 앞에 와야 입력 단계 탐색(빠름)이 된다
    assert cmd.index("-ss") < cmd.index("-i")


# =============================================================================
# 엔드포인트
# =============================================================================

def test_rejects_non_uuid_meeting_id(client: TestClient):
    """캐시 파일명이 되므로 UUID 가 아닌 값은 받지 않는다(경로 조작 방지)."""
    response = client.get("/api/meetings/..%2F..%2Fetc/thumbnail")
    assert response.status_code == 404


def test_returns_404_when_meeting_has_no_thumbnail(meeting_id, client: TestClient):
    with patch("app.api.meetings.get_meeting_by_id_service") as get_meeting, patch(
        "app.services.thumbnail_service.ensure_thumbnail"
    ) as ensure:
        get_meeting.return_value = {"id": meeting_id, "vod_url": None}

        async def none_result(*_args, **_kwargs):
            return None

        ensure.side_effect = none_result
        response = client.get(f"/api/meetings/{meeting_id}/thumbnail")

    assert response.status_code == 404


def test_serves_cached_jpeg_with_long_cache_header(meeting_id, tmp_path, client: TestClient):
    jpeg = tmp_path / f"{meeting_id}.jpg"
    jpeg.write_bytes(b"\xff\xd8\xff\xdb-fake-jpeg")

    with patch("app.api.meetings.get_meeting_by_id_service") as get_meeting, patch(
        "app.services.thumbnail_service.ensure_thumbnail"
    ) as ensure:
        get_meeting.return_value = {"id": meeting_id, "vod_url": "https://kms.ggc.go.kr/a.mp4"}

        async def cached_result(*_args, **_kwargs):
            return jpeg

        ensure.side_effect = cached_result
        response = client.get(f"/api/meetings/{meeting_id}/thumbnail")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert "max-age=86400" in response.headers.get("cache-control", "")
