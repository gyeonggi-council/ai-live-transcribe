"""병합 클립 백그라운드 잡 테스트 — 여러 발언 구간 → 하나의 mp4 (B3-clip-jobs)

# @TASK B3-clip-jobs - POST /speakers/clip-jobs + 상태 조회 + 다운로드
# @TEST backend/tests/test_clip_merge_job.py

검증 포인트:
- 잡 생성 202 {job_id}, 인증 필수(401 우선)
- 검증: 빈 segments / end<=start / 개수 상한 / 총 길이 상한 → 400
- 잡 생명주기: 추출 stub 즉시 완료 → done / progress 1.0 / 병합 파일명 규약
- done 전 download 404, 없는 잡 404

KMS 스로틀로 추출이 실시간 배속(추출 시간 ≈ 구간 길이)이라 동기 응답이
불가능하므로 202 + 인메모리 잡으로 처리한다. 테스트에서는 TestClient 의
요청별 이벤트루프 종료로 백그라운드 태스크가 취소될 수 있어, 생명주기
테스트는 ``_run_clip_job`` 을 직접 완주시켜 결정적으로 검증한다.
"""

import asyncio
import uuid

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import speakers as speakers_module
from app.core.config import settings
from app.core.database import get_supabase
from app.main import app
from app.services import clip_service
from tests.conftest import MockSupabaseClient

# 허용 소스 (kms.ggc.go.kr https)
ALLOWED_VOD_URL = "https://kms.ggc.go.kr/mp4//mp4media2/test/20260101_test.mp4"


def _make_meeting(meeting_id: str, vod_url: str | None, kms_midx: str | None = None) -> dict:
    return {
        "id": meeting_id,
        "title": "테스트 회의",
        "vod_url": vod_url,
        "kms_midx": kms_midx,
    }


def _make_client(table_data: dict) -> TestClient:
    mock = MockSupabaseClient(table_data=table_data)
    app.dependency_overrides[get_supabase] = lambda: mock
    return TestClient(app)


def _job_url(meeting_id: str) -> str:
    return f"/api/meetings/{meeting_id}/speakers/clip-jobs"


@pytest.fixture
def meeting_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture(autouse=True)
def _clean_state():
    """테스트 간 인메모리 잡 저장소/의존성 오버라이드 격리."""
    speakers_module._clip_jobs.clear()
    yield
    import shutil

    for job in speakers_module._clip_jobs.values():
        shutil.rmtree(job.get("tmp_dir", ""), ignore_errors=True)
    speakers_module._clip_jobs.clear()
    app.dependency_overrides.clear()


@pytest.fixture
def ffmpeg_available(monkeypatch):
    """ffmpeg 바이너리가 있다고 가정 (501 가드 통과)."""
    monkeypatch.setattr("app.api.speakers._check_ffmpeg_available", lambda: True)


@pytest.fixture
def stub_ffmpeg_pipeline(monkeypatch):
    """실제 ffmpeg 실행 없이 추출/병합을 즉시 완료하는 stub."""
    calls: dict[str, list] = {"extract": [], "concat": []}

    async def _fake_extract(vod_url, start, end, out_path):
        calls["extract"].append({"vod_url": vod_url, "start": start, "end": end})
        Path(out_path).write_bytes(b"FAKE_PART")

    async def _fake_concat(parts, out_path):
        calls["concat"].append({"parts": [str(p) for p in parts]})
        Path(out_path).write_bytes(b"FAKE_MERGED_MP4")

    monkeypatch.setattr(clip_service, "extract_clip_mp4", _fake_extract)
    monkeypatch.setattr(clip_service, "concat_clips_mp4", _fake_concat)
    return calls


@pytest.fixture
def stub_extract_hang(monkeypatch):
    """완료되지 않는 추출 stub — done 이전 상태 검증용."""

    async def _hang(vod_url, start, end, out_path):
        await asyncio.sleep(3600)

    monkeypatch.setattr(clip_service, "extract_clip_mp4", _hang)


# =============================================================================
# 잡 생성
# =============================================================================


class TestClipMergeJobCreate:
    """POST /api/meetings/{meeting_id}/speakers/clip-jobs"""

    def test_create_job_returns_job_id_202(
        self, meeting_id: str, ffmpeg_available, stub_ffmpeg_pipeline, admin_auth_header
    ):
        """유효한 요청이면 202 + job_id 를 반환하고 잡이 등록된다."""
        client = _make_client({
            "meetings": [_make_meeting(meeting_id, ALLOWED_VOD_URL, kms_midx="137982")],
        })

        response = client.post(
            _job_url(meeting_id),
            json={
                "segments": [{"start": 0, "end": 10}, {"start": 60, "end": 90}],
                "merge": True,
            },
            headers=admin_auth_header,
        )

        assert response.status_code == 202
        job_id = response.json()["job_id"]
        assert job_id
        assert job_id in speakers_module._clip_jobs

    def test_job_requires_auth_401(self, meeting_id: str, ffmpeg_available):
        """인증 없이 호출하면 401 (다른 가드보다 우선)."""
        client = _make_client({
            "meetings": [_make_meeting(meeting_id, ALLOWED_VOD_URL)],
        })

        response = client.post(
            _job_url(meeting_id),
            json={"segments": [{"start": 0, "end": 10}], "merge": True},
        )

        assert response.status_code == 401

    def test_job_rejects_empty_segments_400(
        self, meeting_id: str, ffmpeg_available, admin_auth_header
    ):
        """빈 segments(또는 누락, end<=start 구간)는 400."""
        client = _make_client({
            "meetings": [_make_meeting(meeting_id, ALLOWED_VOD_URL)],
        })

        # 빈 리스트
        response = client.post(
            _job_url(meeting_id),
            json={"segments": [], "merge": True},
            headers=admin_auth_header,
        )
        assert response.status_code == 400

        # segments 키 누락
        response = client.post(
            _job_url(meeting_id),
            json={"merge": True},
            headers=admin_auth_header,
        )
        assert response.status_code == 400

        # end <= start 구간
        response = client.post(
            _job_url(meeting_id),
            json={"segments": [{"start": 10, "end": 10}], "merge": True},
            headers=admin_auth_header,
        )
        assert response.status_code == 400

    def test_job_rejects_non_finite_segments_400(
        self, meeting_id: str, ffmpeg_available, admin_auth_header
    ):
        """NaN start/end 는 모든 부등호 비교가 False라 검증을 통과하던 회귀 — 400.

        서버측 json.loads 는 NaN/Infinity 리터럴을 허용하므로 nan 이 핸들러까지
        도달한다 (httpx 클라이언트는 allow_nan=False 라 raw body 로 보낸다).
        """
        client = _make_client({
            "meetings": [_make_meeting(meeting_id, ALLOWED_VOD_URL)],
        })

        for bad_body in (
            '{"segments": [{"start": NaN, "end": 10}], "merge": true}',
            '{"segments": [{"start": 0, "end": NaN}], "merge": true}',
            '{"segments": [{"start": Infinity, "end": Infinity}], "merge": true}',
        ):
            response = client.post(
                _job_url(meeting_id),
                content=bad_body,
                headers={**admin_auth_header, "Content-Type": "application/json"},
            )
            assert response.status_code == 400, bad_body

    def test_job_rejects_too_many_segments_400(
        self, meeting_id: str, ffmpeg_available, admin_auth_header
    ):
        """구간 개수 상한(clip_job_max_segments) 초과 및 총 길이 상한 초과는 400."""
        client = _make_client({
            "meetings": [_make_meeting(meeting_id, ALLOWED_VOD_URL)],
        })

        # 개수 상한 초과
        over_count = settings.clip_job_max_segments + 1
        segments = [
            {"start": i * 10, "end": i * 10 + 5} for i in range(over_count)
        ]
        response = client.post(
            _job_url(meeting_id),
            json={"segments": segments, "merge": True},
            headers=admin_auth_header,
        )
        assert response.status_code == 400

        # 총 길이 상한(clip_max_seconds * 2) 초과
        cap = settings.clip_max_seconds
        response = client.post(
            _job_url(meeting_id),
            json={
                "segments": [
                    {"start": 0, "end": cap},
                    {"start": cap + 100, "end": cap + 100 + cap + 1},
                ],
                "merge": True,
            },
            headers=admin_auth_header,
        )
        assert response.status_code == 400


# =============================================================================
# 잡 상태 / 다운로드
# =============================================================================


class TestClipMergeJobLifecycle:
    """GET clip-jobs/{job_id} + GET clip-jobs/{job_id}/download"""

    def test_job_status_lifecycle(
        self, meeting_id: str, ffmpeg_available, stub_ffmpeg_pipeline, admin_auth_header
    ):
        """추출 stub 즉시 완료 → done / progress 1.0 / 병합 파일명 / 다운로드 성공."""
        client = _make_client({
            "meetings": [_make_meeting(meeting_id, ALLOWED_VOD_URL, kms_midx="137982")],
        })

        response = client.post(
            _job_url(meeting_id),
            json={
                "segments": [{"start": 0, "end": 10}, {"start": 60, "end": 90}],
                "merge": True,
            },
            headers=admin_auth_header,
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]

        # 백그라운드 태스크는 TestClient 포털 종료로 취소될 수 있으므로 직접
        # 완주시킨다 (이미 완료됐어도 stub 재실행은 무해 → 결정적 상태 보장).
        asyncio.run(speakers_module._run_clip_job(job_id))

        status_resp = client.get(
            f"{_job_url(meeting_id)}/{job_id}", headers=admin_auth_header
        )
        assert status_resp.status_code == 200
        body = status_resp.json()
        assert body["status"] == "done"
        assert body["progress"] == 1.0
        assert body["current_segment"] is None
        assert body["error"] is None
        assert body["filename"] == "ggc_137982_merged_2clips.mp4"

        # 세그먼트별 추출 + 병합이 호출되었다 (백그라운드 중복 실행 허용 → 이상)
        assert len(stub_ffmpeg_pipeline["extract"]) >= 2
        assert len(stub_ffmpeg_pipeline["concat"]) >= 1

        # 완료 후 다운로드 성공 (mp4 + 병합 파일명)
        dl_resp = client.get(
            f"{_job_url(meeting_id)}/{job_id}/download", headers=admin_auth_header
        )
        assert dl_resp.status_code == 200
        assert dl_resp.headers["content-type"] == "video/mp4"
        assert dl_resp.content == b"FAKE_MERGED_MP4"
        assert "ggc_137982_merged_2clips.mp4" in dl_resp.headers["content-disposition"]

    def test_job_download_404_before_done(
        self, meeting_id: str, ffmpeg_available, stub_extract_hang, admin_auth_header
    ):
        """잡이 done 이 되기 전에는 download 가 404."""
        client = _make_client({
            "meetings": [_make_meeting(meeting_id, ALLOWED_VOD_URL)],
        })

        response = client.post(
            _job_url(meeting_id),
            json={"segments": [{"start": 0, "end": 10}], "merge": True},
            headers=admin_auth_header,
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]

        status_resp = client.get(
            f"{_job_url(meeting_id)}/{job_id}", headers=admin_auth_header
        )
        assert status_resp.status_code == 200
        assert status_resp.json()["status"] in ("queued", "running")

        dl_resp = client.get(
            f"{_job_url(meeting_id)}/{job_id}/download", headers=admin_auth_header
        )
        assert dl_resp.status_code == 404

    def test_unknown_job_404(self, meeting_id: str, admin_auth_header):
        """없는 잡은 상태/다운로드 모두 404 + 서버 재시작 만료 안내 detail.

        인메모리 잡은 프로세스 재시작 시 소멸하므로, 사용자에게 원인(만료)과
        행동(다시 시도)을 알려야 한다.
        """
        client = _make_client({})
        unknown = str(uuid.uuid4())

        status_resp = client.get(
            f"{_job_url(meeting_id)}/{unknown}", headers=admin_auth_header
        )
        assert status_resp.status_code == 404
        assert "서버 재시작으로 작업이 만료되었습니다" in status_resp.json()["detail"]

        dl_resp = client.get(
            f"{_job_url(meeting_id)}/{unknown}/download", headers=admin_auth_header
        )
        assert dl_resp.status_code == 404
        assert "서버 재시작으로 작업이 만료되었습니다" in dl_resp.json()["detail"]


# =============================================================================
# 동시 상한 + 고아 임시디렉토리 정리
# =============================================================================


class TestClipMergeJobLimits:
    """running 잡 동시 상한(429) + 재시작 고아 clipjob_* 임시디렉토리 lazy 정리"""

    @staticmethod
    def _seed_active_job(meeting_id: str) -> str:
        """미완료(finished_at=None) 잡을 저장소에 직접 시딩합니다.

        TestClient 는 요청별 이벤트루프 종료로 백그라운드 태스크를 취소하므로
        (finally 가 finished_at 기록) 실제 요청으로는 '실행 중' 상태를 유지할 수
        없다 — 저장소 시딩으로 결정적으로 검증한다.
        """
        job_id = str(uuid.uuid4())
        speakers_module._clip_jobs[job_id] = {
            "job_id": job_id,
            "meeting_id": meeting_id,
            "vod_url": ALLOWED_VOD_URL,
            "segments": [{"start": 0, "end": 10}],
            "filename": "ggc_test_merged_1clips.mp4",
            "tmp_dir": f"__nonexistent_clipjob_{job_id[:8]}__",
            "status": "running",
            "progress": 0.5,
            "current_segment": 1,
            "error": None,
            "output_path": None,
            "finished_at": None,
        }
        return job_id

    def test_concurrent_jobs_capped_429(
        self, meeting_id: str, ffmpeg_available, stub_ffmpeg_pipeline, admin_auth_header
    ):
        """미완료(finished_at 없음) 잡이 상한(2개)이면 새 잡 생성은 429.

        잡당 임시파일 ~0.8GB + KMS 스로틀 순차 추출 — 상한 없이는 디스크/회선이
        고갈된다. 완료(finished_at 기록) 잡은 상한에 포함되지 않는다.
        """
        client = _make_client({
            "meetings": [_make_meeting(meeting_id, ALLOWED_VOD_URL)],
        })
        body = {"segments": [{"start": 0, "end": 10}], "merge": True}

        # 미완료 잡 1개 → 아직 상한 미만 → 202
        self._seed_active_job(meeting_id)
        ok = client.post(_job_url(meeting_id), json=body, headers=admin_auth_header)
        assert ok.status_code == 202
        # 방금 만든 잡을 완료 처리(백그라운드 태스크 취소 여부와 무관하게 결정적)
        speakers_module._clip_jobs[ok.json()["job_id"]]["finished_at"] = 0.0

        # 미완료 잡 2개(상한) → 429
        self._seed_active_job(meeting_id)
        blocked = client.post(_job_url(meeting_id), json=body, headers=admin_auth_header)
        assert blocked.status_code == 429
        assert "다시 시도" in blocked.json()["detail"]

    def test_orphan_tmpdir_cleanup_on_create(
        self, meeting_id: str, ffmpeg_available, stub_ffmpeg_pipeline, admin_auth_header,
        tmp_path, monkeypatch,
    ):
        """잡 생성 시 24시간 지난 고아 clipjob_* 임시디렉토리를 lazy 정리한다.

        서버 재시작으로 _clip_jobs 가 비면 tmp 디렉토리(잡당 ~0.8GB)가 영영 남던
        결함 — 신선한 디렉토리는 보존한다.
        """
        import os
        import tempfile as tempfile_module
        import time as time_module

        # 테스트 전용 tempdir 로 격리 (실제 %TEMP% 를 건드리지 않음)
        monkeypatch.setattr(tempfile_module, "gettempdir", lambda: str(tmp_path))

        def _mkdtemp(prefix=""):
            d = tmp_path / f"{prefix}{uuid.uuid4().hex[:8]}"
            d.mkdir()
            return str(d)

        monkeypatch.setattr(tempfile_module, "mkdtemp", _mkdtemp)

        stale = tmp_path / "clipjob_stale_orphan"
        stale.mkdir()
        (stale / "part_000.mp4").write_bytes(b"OLD")
        old = time_module.time() - 25 * 3600
        os.utime(stale, (old, old))

        fresh = tmp_path / "clipjob_fresh_orphan"
        fresh.mkdir()

        client = _make_client({
            "meetings": [_make_meeting(meeting_id, ALLOWED_VOD_URL)],
        })
        response = client.post(
            _job_url(meeting_id),
            json={"segments": [{"start": 0, "end": 10}], "merge": True},
            headers=admin_auth_header,
        )
        assert response.status_code == 202

        assert not stale.exists()  # 24h 초과 고아 → 삭제
        assert fresh.exists()      # 신선한 디렉토리 → 보존
