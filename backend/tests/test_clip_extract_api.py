"""클립 추출 재작성 테스트 — ffmpeg URL-seek + 인증 필수화 (B2-clip)

# @TASK B2-clip - GET /speakers/clip 재작성 + clip_service 신규
# @TEST backend/tests/test_clip_extract_api.py

검증 포인트:
- 인증 필수 (401 우선), staff 등 5역할 허용
- 가드: end<=start 400 / 길이 상한 413 / 비허용 VOD 소스 422 (admin 예외)
- 파일명 규약: ggc_{kms_midx}_{start}-{end}.mp4 (midx 없으면 meeting_id 앞 8자)
- ffmpeg 인자 순서: -ss 가 -i 보다 앞 (입력 시킹 = 필요 바이트만 전송) — 회귀 방지 핵심
"""

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import get_supabase
from app.main import app
from app.services import clip_service
from app.services.auth_service import create_access_token
from tests.conftest import TEST_ADMIN_USER, MockSupabaseClient


# ---------------------------------------------------------------------------
# 테스트용 staff 계정 (관리자 아님 — 소스 가드 검증용)
# ---------------------------------------------------------------------------
STAFF_USER_ID = "00000000-0000-0000-0000-000000000002"
STAFF_USER = {
    **TEST_ADMIN_USER,
    "id": STAFF_USER_ID,
    "username": "staff1",
    "display_name": "테스트 직원",
    "role": "staff",
}

# 허용 소스 (kms.ggc.go.kr https) / 비허용 소스
ALLOWED_VOD_URL = "https://kms.ggc.go.kr/mp4//mp4media2/test/20260101_test.mp4"
DISALLOWED_VOD_URL = "https://evil.example.com/video.mp4"


def _staff_auth_header() -> dict[str, str]:
    token = create_access_token({"sub": STAFF_USER_ID, "role": "staff"})
    return {"Authorization": f"Bearer {token}"}


def _make_meeting(meeting_id: str, vod_url: str | None, kms_midx: str | None = None) -> dict:
    return {
        "id": meeting_id,
        "title": "테스트 회의",
        "vod_url": vod_url,
        "kms_midx": kms_midx,
    }


@pytest.fixture
def meeting_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def ffmpeg_available(monkeypatch):
    """ffmpeg 바이너리가 있다고 가정 (501 가드 통과)."""
    monkeypatch.setattr("app.api.speakers._check_ffmpeg_available", lambda: True)


@pytest.fixture
def stub_extract(monkeypatch):
    """실제 ffmpeg 실행 없이 stub 파일을 쓰는 extract_clip_mp4 대체."""
    calls: list[dict] = []

    async def _fake_extract(vod_url, start, end, out_path):
        calls.append({
            "vod_url": vod_url,
            "start": start,
            "end": end,
            "out_path": str(out_path),
        })
        Path(out_path).write_bytes(b"FAKE_MP4_DATA")

    monkeypatch.setattr(clip_service, "extract_clip_mp4", _fake_extract)
    return calls


def _make_client(table_data: dict) -> TestClient:
    mock = MockSupabaseClient(table_data=table_data)
    app.dependency_overrides[get_supabase] = lambda: mock
    return TestClient(app)


# =============================================================================
# API 테스트
# =============================================================================


class TestClipExtractApi:
    """GET /api/meetings/{meeting_id}/speakers/clip — 재작성 동작"""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_clip_requires_auth_401(self, meeting_id: str):
        """인증 없이 호출하면 401 (다른 가드보다 우선)."""
        client = _make_client({
            "meetings": [_make_meeting(meeting_id, ALLOWED_VOD_URL)],
        })

        response = client.get(
            f"/api/meetings/{meeting_id}/speakers/clip?start=0&end=10"
        )

        assert response.status_code == 401

    def test_clip_allows_staff_role(
        self, meeting_id: str, ffmpeg_available, stub_extract
    ):
        """staff 역할 로그인 사용자는 클립을 받을 수 있다 (200, video/mp4)."""
        client = _make_client({
            "meetings": [_make_meeting(meeting_id, ALLOWED_VOD_URL, kms_midx="137982")],
            "users": [TEST_ADMIN_USER, STAFF_USER],
        })

        response = client.get(
            f"/api/meetings/{meeting_id}/speakers/clip?start=10&end=40",
            headers=_staff_auth_header(),
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "video/mp4"
        assert response.content == b"FAKE_MP4_DATA"
        # extract 호출 인자 확인
        assert len(stub_extract) == 1
        assert stub_extract[0]["vod_url"] == ALLOWED_VOD_URL
        assert stub_extract[0]["start"] == 10
        assert stub_extract[0]["end"] == 40

    def test_clip_invalid_range_400(
        self, meeting_id: str, ffmpeg_available, admin_auth_header
    ):
        """end <= start 이면 400."""
        client = _make_client({
            "meetings": [_make_meeting(meeting_id, ALLOWED_VOD_URL)],
        })

        response = client.get(
            f"/api/meetings/{meeting_id}/speakers/clip?start=10&end=5",
            headers=admin_auth_header,
        )

        assert response.status_code == 400

    def test_clip_duration_over_cap_413(
        self, meeting_id: str, ffmpeg_available, admin_auth_header
    ):
        """구간 길이가 clip_max_seconds 를 넘으면 413."""
        over = settings.clip_max_seconds + 1
        client = _make_client({
            "meetings": [_make_meeting(meeting_id, ALLOWED_VOD_URL)],
        })

        response = client.get(
            f"/api/meetings/{meeting_id}/speakers/clip?start=0&end={over}",
            headers=admin_auth_header,
        )

        assert response.status_code == 413

    def test_clip_disallowed_vod_source_422(
        self, meeting_id: str, ffmpeg_available, stub_extract, admin_auth_header
    ):
        """비허용 VOD 소스는 admin 이 아니면 422, admin 은 허용."""
        client = _make_client({
            "meetings": [_make_meeting(meeting_id, DISALLOWED_VOD_URL)],
            "users": [TEST_ADMIN_USER, STAFF_USER],
        })

        # staff → 422
        response = client.get(
            f"/api/meetings/{meeting_id}/speakers/clip?start=0&end=10",
            headers=_staff_auth_header(),
        )
        assert response.status_code == 422

        # admin → 소스 가드 우회 허용
        response = client.get(
            f"/api/meetings/{meeting_id}/speakers/clip?start=0&end=10",
            headers=admin_auth_header,
        )
        assert response.status_code == 200

    def test_clip_filename_convention_uses_kms_midx(
        self, meeting_id: str, ffmpeg_available, stub_extract, admin_auth_header
    ):
        """Content-Disposition 파일명이 ggc_{kms_midx}_{start}-{end}.mp4 규약을 따른다."""
        client = _make_client({
            "meetings": [_make_meeting(meeting_id, ALLOWED_VOD_URL, kms_midx="137982")],
        })

        response = client.get(
            f"/api/meetings/{meeting_id}/speakers/clip?start=1350&end=1440",
            headers=admin_auth_header,
        )

        assert response.status_code == 200
        disposition = response.headers["content-disposition"]
        assert "attachment" in disposition
        assert "ggc_137982_22m30s-24m00s.mp4" in disposition

    def test_clip_failure_detail_hides_ffmpeg_stderr(
        self, meeting_id: str, ffmpeg_available, monkeypatch, admin_auth_header
    ):
        """추출 실패 시 응답 detail 에 ffmpeg stderr(내부 정보)가 유출되지 않는다.

        stderr(URL·경로·버전 등)는 logger.error 로만 남기고 detail 은 일반 메시지.
        """
        async def _fail(vod_url, start, end, out_path):
            raise clip_service.ClipExtractError(
                "ffmpeg 실패 (exit 1): [https @ 0x1] HTTP error 403 "
                "Forbidden https://kms.ggc.go.kr/secret/path.mp4"
            )

        monkeypatch.setattr(clip_service, "extract_clip_mp4", _fail)
        client = _make_client({
            "meetings": [_make_meeting(meeting_id, ALLOWED_VOD_URL)],
        })

        response = client.get(
            f"/api/meetings/{meeting_id}/speakers/clip?start=0&end=10",
            headers=admin_auth_header,
        )

        assert response.status_code == 500
        detail = response.json()["detail"]
        assert "ffmpeg" not in detail
        assert "kms.ggc.go.kr" not in detail
        assert "클립 추출에 실패" in detail


# =============================================================================
# clip_service 단위 테스트
# =============================================================================


class TestClipService:
    """clip_service 순수 함수/커맨드 빌더 검증"""

    def test_format_hms_compact_cases(self):
        """h 없으면 분 패딩 없음, h 있으면 분 2자리, 초는 항상 2자리."""
        assert clip_service.format_hms_compact(1350) == "22m30s"
        assert clip_service.format_hms_compact(3723) == "1h02m03s"
        assert clip_service.format_hms_compact(0) == "0m00s"
        assert clip_service.format_hms_compact(45) == "0m45s"
        assert clip_service.format_hms_compact(65) == "1m05s"
        assert clip_service.format_hms_compact(3600) == "1h00m00s"
        assert clip_service.format_hms_compact(7325.7) == "2h02m05s"

    def test_build_clip_filename_without_midx_uses_meeting_id_prefix(self):
        """kms_midx 없으면 meeting_id 앞 8자를 사용한다."""
        mid = "abcdef12-3456-7890-abcd-ef1234567890"
        assert (
            clip_service.build_clip_filename(None, mid, 10, 40)
            == "ggc_abcdef12_0m10s-0m40s.mp4"
        )
        assert (
            clip_service.build_clip_filename("137982", mid, 10, 40)
            == "ggc_137982_0m10s-0m40s.mp4"
        )

    def test_clip_service_command_has_ss_before_input(self):
        """-ss 가 -i 보다 앞 (입력 시킹) — 순서가 바뀌면 전체 다운로드로 회귀한다."""
        cmd = clip_service.build_extract_cmd(
            ALLOWED_VOD_URL, 10.0, 40.0, "out.mp4"
        )

        assert isinstance(cmd, list)  # shell 문자열 금지
        assert cmd[0] == "ffmpeg"
        ss_idx = cmd.index("-ss")
        i_idx = cmd.index("-i")
        assert ss_idx < i_idx, "-ss 는 반드시 -i 보다 앞이어야 한다 (입력 시킹)"
        assert cmd[ss_idx + 1] == "10.0"
        assert cmd[i_idx + 1] == ALLOWED_VOD_URL

        # -t {dur} / -c copy / faststart 는 -i 뒤
        t_idx = cmd.index("-t")
        assert t_idx > i_idx
        assert cmd[t_idx + 1] == "30.0"
        c_idx = cmd.index("-c")
        assert cmd[c_idx + 1] == "copy"
        mov_idx = cmd.index("-movflags")
        assert cmd[mov_idx + 1] == "+faststart"

        # KMS 헤더 주입 (-headers 는 -i 앞, User-Agent/Referer 포함)
        h_idx = cmd.index("-headers")
        assert h_idx < i_idx
        assert "User-Agent" in cmd[h_idx + 1]
        assert "Referer: https://kms.ggc.go.kr" in cmd[h_idx + 1]

    def test_build_extract_cmd_normalizes_hls_url(self):
        """HLS(.m3u8) vod_url 은 직접 MP4 URL 로 정규화된다."""
        hls = "https://kms.ggc.go.kr/vod/_definst_//mp4media2/a/b.mp4/playlist.m3u8"
        cmd = clip_service.build_extract_cmd(hls, 0.0, 10.0, "out.mp4")
        i_idx = cmd.index("-i")
        assert cmd[i_idx + 1] == "https://kms.ggc.go.kr/mp4//mp4media2/a/b.mp4"

    def test_concat_list_path_escaping(self):
        """concat 리스트 파일 경로의 작은따옴표를 이스케이프한다."""
        assert clip_service._escape_concat_path("a'b.mp4") == "a'\\''b.mp4"
        assert clip_service._escape_concat_path("plain.mp4") == "plain.mp4"

    async def test_run_ffmpeg_spawns_at_low_priority(self, monkeypatch):
        """추출 ffmpeg 는 생중계 STT 와 같은 파드에서 돌므로 nice/ionice 뒤에 세운다 (2026-09-08)."""
        import asyncio

        spawned = {}

        class _Done:
            returncode = 0

            async def communicate(self):
                return b"", b""

        async def _fake_exec(*cmd, **kwargs):
            spawned["cmd"] = list(cmd)
            return _Done()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        await clip_service._run_ffmpeg(["ffmpeg", "-y", "x.mp4"], timeout=5)
        assert spawned["cmd"][:7] == ["nice", "-n", "19", "ionice", "-c", "3", "ffmpeg"]

    async def test_extract_cancel_kills_ffmpeg_and_cleans_partial(
        self, monkeypatch, tmp_path
    ):
        """동기 클립 요청 취소(CancelledError) 시 ffmpeg 프로세스를 kill 하고
        부분 산출물을 정리한 뒤 취소를 재전파한다 — ffmpeg 고아 방지."""
        import asyncio

        killed = {"value": False}

        class _FakeProc:
            returncode = None

            async def communicate(self):
                await asyncio.sleep(3600)  # 추출 진행 중(장시간) 모사

            def kill(self):
                killed["value"] = True

        async def _fake_exec(*cmd, **kwargs):
            return _FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

        out_path = tmp_path / "clip.mp4"
        out_path.write_bytes(b"PARTIAL")  # 취소 시점의 부분 산출물 모사

        task = asyncio.create_task(
            clip_service.extract_clip_mp4(ALLOWED_VOD_URL, 0, 10, out_path)
        )
        await asyncio.sleep(0.05)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert killed["value"], "취소 시 ffmpeg 프로세스를 kill 해야 한다"
        assert not out_path.exists(), "취소 시 부분 산출물을 정리해야 한다"
