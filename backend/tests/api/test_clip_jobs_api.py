# -*- coding: utf-8 -*-
"""발언영상 클립 워크벤치 API — 인가·검증·소유권·다운로드·목록

DB 는 가짜 리포지토리(dependency override), 잡 실행은 submit 을 기록만 하는 stub.
"""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import clips as clips_module
from app.api.deps import get_clip_job_repository
from app.core.config import settings
from app.core.database import get_supabase
from app.main import app
from app.services import clip_store
from app.services.auth_service import create_access_token
from app.services.clip_job_service import clip_job_service
from tests.conftest import TEST_ADMIN_USER, TEST_ADMIN_USER_ID, MockSupabaseClient

STAFF_ID = "00000000-0000-0000-0000-00000000000a"
OTHER_ID = "00000000-0000-0000-0000-00000000000b"
STAFF_USER = {**TEST_ADMIN_USER, "id": STAFF_ID, "username": "staff1", "role": "staff"}
OTHER_USER = {**TEST_ADMIN_USER, "id": OTHER_ID, "username": "staff2", "role": "staff"}
MEETING_ID = str(uuid.uuid4())
MEETING = {"id": MEETING_ID, "title": "테스트 회의", "meeting_date": "2026-09-01",
           "vod_url": "https://kms.ggc.go.kr/mp4//mp4media2/test/20260901_test.mp4",
           "kms_midx": "138295", "duration_seconds": 3600, "committee": None, "channel_id": None,
           "clip_time_offset": None}


class FakeRepo:
    def __init__(self):
        self.jobs: dict[str, dict] = {}
        self.meetings = {MEETING_ID: dict(MEETING)}
        self.offsets = {}
        self.client = MockSupabaseClient()

    def insert(self, row):
        self.jobs[row["id"]] = dict(row)
        return dict(row)

    def get(self, job_id):
        return dict(self.jobs[job_id]) if job_id in self.jobs else None

    def update(self, job_id, patch):
        self.jobs[job_id].update(patch)
        return dict(self.jobs[job_id])

    def list_for_owner(self, owner_user_id, owner_username, *, since_iso, limit, offset, meeting_id=None):
        rows = [j for j in self.jobs.values()
                if (j.get("owner_user_id") == owner_user_id if owner_user_id
                    else j.get("owner_username") == owner_username)]
        return rows[offset:offset + limit]

    def list_all(self, *, since_iso, limit, offset, meeting_id=None):
        return list(self.jobs.values())[offset:offset + limit]

    def list_active(self, origin=None):
        return [j for j in self.jobs.values() if j["status"] in ("queued", "running")
                and (origin is None or j.get("origin", "manual") == origin)]

    def list_evictable(self):
        return [j for j in self.jobs.values() if j["status"] == "done" and not j.get("evicted_at")]

    def count_active(self):
        a = self.list_active()
        return (sum(1 for j in a if j["status"] == "running"), sum(1 for j in a if j["status"] == "queued"))

    def mark_evicted(self, job_id, reason):
        self.jobs[job_id].update({"status": "expired", "evicted_reason": reason, "evicted_at": "now",
                                  "files": [], "bytes_total": 0})

    def get_meeting(self, meeting_id):
        return self.meetings.get(meeting_id)

    def get_meeting_by_midx(self, midx):
        return next((m for m in self.meetings.values() if m.get("kms_midx") == midx), None)

    def get_meetings_brief(self, ids):
        return {i: self.meetings[i] for i in ids if i in self.meetings}

    def set_meeting_offset(self, meeting_id, offset):
        self.offsets[meeting_id] = offset

    def list_auto(self, *, meeting_id=None, since_iso=None, limit=500):
        return [dict(j) for j in self.jobs.values() if j.get("origin") == "auto"
                and (meeting_id is None or j["meeting_id"] == meeting_id)][:limit]


def _token(user):
    return {"Authorization": f"Bearer {create_access_token({'sub': user['id'], 'role': user['role']})}"}


@pytest.fixture
def repo():
    return FakeRepo()


@pytest.fixture
def client(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "clip_store_dir", str(tmp_path / "clips"))
    clip_store.ensure_dirs()
    submitted = []
    monkeypatch.setattr(clip_job_service, "submit", lambda job_id: submitted.append(job_id))
    mock = MockSupabaseClient(table_data={"users": [TEST_ADMIN_USER, STAFF_USER, OTHER_USER]})
    app.dependency_overrides[get_supabase] = lambda: mock
    app.dependency_overrides[get_clip_job_repository] = lambda: repo
    c = TestClient(app)
    c.submitted = submitted
    yield c
    app.dependency_overrides.clear()


def _body(**over):
    b = {"segments": [{"start": 100, "end": 130}], "merge": True, "pad_before": 3, "pad_after": 3,
         "label": "김지호 위원", "speaker_name": "김지호", "source_kind": "official",
         "with_srt": True, "time_offset": 0}
    b.update(over)
    return b


JOBS_URL = f"/api/meetings/{MEETING_ID}/clip-jobs"


class TestAuth:
    def test_unauthenticated_401(self, client):
        assert client.post(JOBS_URL, json=_body()).status_code == 401
        assert client.get(f"/api/meetings/{MEETING_ID}/clip-index").status_code == 401
        assert client.get("/api/clip-jobs").status_code == 401

    def test_scope_all_requires_admin(self, client):
        assert client.get("/api/clip-jobs?scope=all", headers=_token(STAFF_USER)).status_code == 403
        assert client.get("/api/clip-jobs?scope=all", headers=_token(TEST_ADMIN_USER)).status_code == 200

    def test_sweep_requires_admin(self, client):
        assert client.post("/api/clip-jobs/sweep", headers=_token(STAFF_USER)).status_code == 403
        r = client.post("/api/clip-jobs/sweep?dry_run=true", headers=_token(TEST_ADMIN_USER))
        assert r.status_code == 200 and r.json()["dry_run"] is True


class TestCreate:
    def test_202_with_queue_position_and_padded_segments(self, client, repo):
        r = client.post(JOBS_URL, json=_body(), headers=_token(STAFF_USER))
        assert r.status_code == 202, r.text
        data = r.json()
        assert data["status"] == "queued" and data["queue_position"] == 0
        job = repo.jobs[data["job_id"]]
        assert job["segments"] == [{"start": 97.0, "end": 133.0}]     # 여유 3초 적용
        assert job["owner_user_id"] == STAFF_ID and job["owner_username"] == "staff1"
        assert job["vod_url"] == MEETING["vod_url"] and job["source_kind"] == "official"
        assert client.submitted == [data["job_id"]]

    def test_same_request_twice_returns_existing_job(self, client, repo):
        """연타·두 탭·캐시 지연 — 같은 사람의 같은 구간이 진행 중이면 새 잡을 만들지 않는다(2026-09-08 잡 6개 사고)."""
        first = client.post(JOBS_URL, json=_body(), headers=_token(STAFF_USER)).json()
        second = client.post(JOBS_URL, json=_body(), headers=_token(STAFF_USER))
        assert second.status_code == 202
        assert second.json()["job_id"] == first["job_id"] and second.json()["duplicate"] is True
        assert len(repo.jobs) == 1 and client.submitted == [first["job_id"]]
        # 다른 구간·다른 사람은 새 잡
        assert client.post(JOBS_URL, json=_body(merge=False), headers=_token(STAFF_USER)).json()["job_id"] != first["job_id"]
        assert client.post(JOBS_URL, json=_body(), headers=_token(OTHER_USER)).json()["job_id"] != first["job_id"]
        assert len(repo.jobs) == 3

    def test_segment_number_is_kept_through_padding(self, client, repo):
        """no(목록 순번 = 파일 이름 끝 번호, 2026-09-10)가 여유·병합을 거쳐 DB 구간에 남는다."""
        body = _body(merge=False, segments=[{"start": 100, "end": 130, "no": 2},
                                            {"start": 500, "end": 530, "no": 5}])
        r = client.post(JOBS_URL, json=body, headers=_token(STAFF_USER))
        assert r.status_code == 202, r.text
        assert repo.jobs[r.json()["job_id"]]["segments"] == [
            {"start": 97.0, "end": 133.0, "no": 2}, {"start": 497.0, "end": 533.0, "no": 5}]

    def test_overlapping_segments_keep_first_number(self, client, repo):
        body = _body(merge=False, segments=[{"start": 100, "end": 130, "no": 3},
                                            {"start": 132, "end": 150, "no": 4}])
        job = repo.jobs[client.post(JOBS_URL, json=body, headers=_token(STAFF_USER)).json()["job_id"]]
        assert job["segments"] == [{"start": 97.0, "end": 153.0, "no": 3}]

    @pytest.mark.parametrize("no", [0, -1, "3", True, 10000, 1.5])
    def test_bad_segment_number_400(self, client, no):
        r = client.post(JOBS_URL, json=_body(segments=[{"start": 100, "end": 130, "no": no}]),
                        headers=_token(STAFF_USER))
        assert r.status_code == 400 and "구간 번호" in r.json()["detail"]

    def test_duplicate_segment_number_400(self, client):
        """같은 번호 둘 = 한 잡 안에서 같은 파일 이름 → 앞 파일이 덮인다. 거부한다."""
        body = _body(segments=[{"start": 100, "end": 130, "no": 1}, {"start": 500, "end": 530, "no": 1}])
        r = client.post(JOBS_URL, json=body, headers=_token(STAFF_USER))
        assert r.status_code == 400 and "구간 번호" in r.json()["detail"]

    @pytest.mark.parametrize("body,detail", [
        (_body(segments=[]), "1개 이상"),
        (_body(segments=[{"start": 10, "end": 5}]), "커야"),
        (_body(segments=[{"start": 0, "end": 5000}]), "상한"),
        (_body(pad_before=999), "0~120"),
        (_body(source_kind="magic"), "source_kind"),
        (_body(time_offset=99999), "3600"),
    ])
    def test_validation_400(self, client, body, detail):
        r = client.post(JOBS_URL, json=body, headers=_token(STAFF_USER))
        assert r.status_code == 400, r.text
        assert detail in r.json()["detail"]

    def test_nan_segment_400(self, client):
        raw = '{"segments":[{"start":NaN,"end":5}],"label":"x"}'
        r = client.post(JOBS_URL, content=raw, headers={**_token(STAFF_USER), "Content-Type": "application/json"})
        assert r.status_code == 400 and "유한" in r.json()["detail"]

    def test_too_many_segments_400(self, client):
        body = _body(segments=[{"start": i * 10, "end": i * 10 + 1} for i in range(settings.clip_job_max_segments + 1)])
        assert client.post(JOBS_URL, json=body, headers=_token(STAFF_USER)).status_code == 400

    def test_unknown_meeting_404(self, client):
        r = client.post(f"/api/meetings/{uuid.uuid4()}/clip-jobs", json=_body(), headers=_token(STAFF_USER))
        assert r.status_code == 404

    def test_missing_vod_400(self, client, repo):
        repo.meetings[MEETING_ID]["vod_url"] = None
        assert client.post(JOBS_URL, json=_body(), headers=_token(STAFF_USER)).status_code == 400

    def test_foreign_vod_source_422_for_staff(self, client, repo):
        repo.meetings[MEETING_ID]["vod_url"] = "https://evil.example.com/x.mp4"
        assert client.post(JOBS_URL, json=_body(), headers=_token(STAFF_USER)).status_code == 422

    def test_queue_cap_429(self, client, repo, monkeypatch):
        monkeypatch.setattr(settings, "clip_job_max_active", 1)
        monkeypatch.setattr(settings, "clip_job_max_queued", 1)
        # 같은 구간은 중복으로 합쳐지므로 서로 다른 구간으로 채운다
        seg = lambda s: _body(segments=[{"start": s, "end": s + 30}])  # noqa: E731
        assert client.post(JOBS_URL, json=seg(100), headers=_token(STAFF_USER)).status_code == 202
        r2 = client.post(JOBS_URL, json=seg(200), headers=_token(STAFF_USER))
        assert r2.status_code == 202 and r2.json()["queue_position"] == 1
        assert client.post(JOBS_URL, json=seg(300), headers=_token(STAFF_USER)).status_code == 429

    def test_storage_full_507(self, client, monkeypatch):
        monkeypatch.setattr(clip_store, "usage_bytes", lambda: settings.clip_store_max_bytes)
        monkeypatch.setattr(clips_module, "sweep_store", lambda repo, **kw: {"evicted": []})
        r = client.post(JOBS_URL, json=_body(), headers=_token(STAFF_USER))
        assert r.status_code == 507 and "저장 공간" in r.json()["detail"]


def _seed_done(repo, owner=STAFF_USER, files=None, status="done"):
    job_id = str(uuid.uuid4())
    repo.jobs[job_id] = {
        "id": job_id, "meeting_id": MEETING_ID, "owner_user_id": owner["id"],
        "owner_username": owner["username"], "label": "x", "source_kind": "official",
        "segments": [{"start": 1, "end": 2}], "merge": True, "with_srt": True, "status": status,
        "progress": 1.0, "files": files or [], "bytes_total": 0,
        "created_at": datetime.now(timezone.utc).isoformat(), "expires_at": None,
    }
    return job_id


class TestStatusAndDownload:
    def test_owner_sees_status_other_staff_404_admin_ok(self, client, repo):
        job_id = _seed_done(repo)
        url = f"{JOBS_URL}/{job_id}"
        assert client.get(url, headers=_token(STAFF_USER)).status_code == 200
        assert client.get(url, headers=_token(OTHER_USER)).status_code == 404
        assert client.get(url, headers=_token(TEST_ADMIN_USER)).status_code == 200

    def test_status_shape_and_download_urls(self, client, repo):
        job_id = _seed_done(repo, files=[{"name": "a.mp4", "kind": "mp4", "bytes": 3}])
        data = client.get(f"{JOBS_URL}/{job_id}", headers=_token(STAFF_USER)).json()
        assert data["segment_count"] == 1 and data["download_urls"]["a.mp4"].endswith("download?file=a.mp4")

    def test_download_before_done_404_and_expired_410(self, client, repo):
        q = _seed_done(repo, status="queued")
        assert client.get(f"{JOBS_URL}/{q}/download?file=a.mp4", headers=_token(STAFF_USER)).status_code == 404
        e = _seed_done(repo, status="expired")
        assert client.get(f"{JOBS_URL}/{e}/download?file=a.mp4", headers=_token(STAFF_USER)).status_code == 410

    def test_download_serves_file_and_rejects_traversal(self, client, repo):
        job_id = _seed_done(repo, files=[{"name": "클립.mp4", "kind": "mp4", "bytes": 4}])
        d = clip_store.job_dir(job_id); d.mkdir(parents=True)
        (d / "클립.mp4").write_bytes(b"MP4!")
        r = client.get(f"{JOBS_URL}/{job_id}/download", params={"file": "클립.mp4"}, headers=_token(STAFF_USER))
        assert r.status_code == 200 and r.content == b"MP4!" and r.headers["content-type"].startswith("video/mp4")
        r = client.get(f"{JOBS_URL}/{job_id}/download", params={"file": "../secret"}, headers=_token(STAFF_USER))
        assert r.status_code == 404   # files[] 에 없는 이름은 존재 여부와 무관하게 404

    def test_delete_done_evicts_manual(self, client, repo):
        job_id = _seed_done(repo, files=[{"name": "a.mp4", "kind": "mp4", "bytes": 1}])
        r = client.delete(f"{JOBS_URL}/{job_id}", headers=_token(STAFF_USER))
        assert r.status_code == 200 and r.json()["status"] == "expired"
        assert repo.jobs[job_id]["evicted_reason"] == "manual"


class TestListAndResolve:
    def test_mine_lists_only_own_with_store_info(self, client, repo):
        _seed_done(repo, owner=STAFF_USER)
        _seed_done(repo, owner=OTHER_USER)
        data = client.get("/api/clip-jobs", headers=_token(STAFF_USER)).json()
        assert len(data["jobs"]) == 1 and data["jobs"][0]["meeting_title"] == "테스트 회의"
        assert data["store"]["max_bytes"] == settings.clip_store_max_bytes
        assert data["store"]["ttl_days"] == settings.clip_store_ttl_days

    def test_resolve_midx(self, client):
        r = client.get("/api/clip-jobs/resolve?midx=138295", headers=_token(STAFF_USER))
        assert r.status_code == 200 and r.json()["meeting_id"] == MEETING_ID
        assert client.get("/api/clip-jobs/resolve?midx=1", headers=_token(STAFF_USER)).status_code == 404
        assert client.get("/api/clip-jobs/resolve?midx=abc", headers=_token(STAFF_USER)).status_code == 400


class TestOffsetAndIndex:
    def test_put_offset_validates_and_saves(self, client, repo):
        url = f"/api/meetings/{MEETING_ID}/clip-offset"
        assert client.put(url, json={"time_offset": "x"}, headers=_token(STAFF_USER)).status_code == 400
        assert client.put(url, json={"time_offset": 99999}, headers=_token(STAFF_USER)).status_code == 400
        r = client.put(url, json={"time_offset": -42.5}, headers=_token(STAFF_USER))
        assert r.status_code == 200 and repo.offsets[MEETING_ID] == -42.5

    def test_clip_index_uses_builder(self, client, monkeypatch):
        async def fake_index(supabase, meeting):
            return {"meeting_id": meeting["id"], "kms_midx": meeting["kms_midx"], "duration": 3600,
                    "source": "official", "time_offset": 0.0, "speakers": [], "warnings": []}

        monkeypatch.setattr(clips_module, "build_clip_index", fake_index)
        r = client.get(f"/api/meetings/{MEETING_ID}/clip-index", headers=_token(STAFF_USER))
        assert r.status_code == 200 and r.json()["source"] == "official"
        assert client.get(f"/api/meetings/{uuid.uuid4()}/clip-index", headers=_token(STAFF_USER)).status_code == 404


class TestAutoClips:
    """자동 클립(2026-09-10) — 작업자 파드가 만든 잡은 로그인 5역할 누구나 보고 받는다. 지우는 것은 관리자만."""

    FILE = "김지호_테스트 회의_3.mp4"

    def _auto(self, repo, status="done"):
        jid = str(uuid.uuid4())
        repo.jobs[jid] = {
            "id": jid, "meeting_id": MEETING_ID, "owner_user_id": None, "owner_username": "자동",
            "label": "김지호", "speaker_name": "김지호", "source_kind": "ai", "origin": "auto", "compress": True,
            "segments": [{"start": 99.0, "end": 131.0, "no": 3}], "merge": False, "with_srt": True,
            "status": status, "total_seconds": 32.0, "progress": 0.0,
            "files": [{"name": self.FILE, "kind": "mp4", "bytes": 10}] if status == "done" else [],
            "bytes_total": 10 if status == "done" else 0,
            "created_at": datetime.now(timezone.utc).isoformat(), "expires_at": None,
        }
        if status == "done":
            d = clip_store.job_dir(jid)
            d.mkdir(parents=True, exist_ok=True)
            (d / self.FILE).write_bytes(b"x" * 10)
        return jid

    def test_any_staff_sees_and_downloads_auto_clip(self, client, repo):
        jid = self._auto(repo)
        r = client.get(f"{JOBS_URL}/{jid}", headers=_token(OTHER_USER))
        assert r.status_code == 200
        body = r.json()
        assert body["origin"] == "auto" and body["compress"] is True
        assert body["segments"] == [{"start": 99.0, "end": 131.0, "no": 3}]
        d = client.get(f"{JOBS_URL}/{jid}/download", params={"file": self.FILE}, headers=_token(OTHER_USER))
        assert d.status_code == 200 and d.content == b"x" * 10

    def test_meeting_list_has_notice_and_only_auto(self, client, repo):
        self._auto(repo)
        client.post(JOBS_URL, json=_body(), headers=_token(STAFF_USER))     # 수동 잡 — 자동 목록에 안 섞인다
        r = client.get(f"/api/meetings/{MEETING_ID}/auto-clips", headers=_token(OTHER_USER))
        assert r.status_code == 200
        body = r.json()
        assert [j["origin"] for j in body["jobs"]] == ["auto"]
        assert "공유하기 전에" in body["notice"] and body["ttl_days"] == settings.clip_auto_ttl_days

    def test_recent_list_carries_meeting_title(self, client, repo):
        self._auto(repo)
        r = client.get("/api/auto-clips?days=3", headers=_token(STAFF_USER))
        assert r.status_code == 200 and r.json()["jobs"][0]["meeting_title"] == MEETING["title"]

    def test_only_admin_deletes_and_not_while_worker_runs_it(self, client, repo):
        done = self._auto(repo)
        running = self._auto(repo, status="running")
        assert client.delete(f"{JOBS_URL}/{done}", headers=_token(STAFF_USER)).status_code == 403
        assert client.delete(f"{JOBS_URL}/{running}", headers=_token(TEST_ADMIN_USER)).status_code == 409
        r = client.delete(f"{JOBS_URL}/{done}", headers=_token(TEST_ADMIN_USER))
        assert r.status_code == 200 and r.json()["status"] == "expired"

    def test_auto_queue_does_not_block_staff_requests(self, client, repo, monkeypatch):
        monkeypatch.setattr(settings, "clip_job_max_active", 1)
        monkeypatch.setattr(settings, "clip_job_max_queued", 1)
        for _ in range(5):
            self._auto(repo, status="queued")
        r = client.post(JOBS_URL, json=_body(), headers=_token(STAFF_USER))
        assert r.status_code == 202
        assert repo.jobs[r.json()["job_id"]]["origin"] == "manual"

    def test_status_and_enqueue_are_admin_only(self, client, repo, monkeypatch):
        assert client.get("/api/auto-clips/status", headers=_token(STAFF_USER)).status_code == 403
        st = client.get("/api/auto-clips/status", headers=_token(TEST_ADMIN_USER))
        assert st.status_code == 200 and {"queued", "disk_free_bytes", "auto_max_bytes"} <= set(st.json())
        from app.services import auto_clip_service

        calls = []

        async def fake_enqueue(repo_, meeting):
            calls.append(meeting["id"])
            return {"meeting_id": meeting["id"], "jobs": 2}

        monkeypatch.setattr(auto_clip_service, "enqueue_meeting", fake_enqueue)
        old = self._auto(repo)
        assert client.post(f"/api/auto-clips/enqueue?meeting_id={MEETING_ID}",
                           headers=_token(STAFF_USER)).status_code == 403
        r = client.post(f"/api/auto-clips/enqueue?meeting_id={MEETING_ID}", headers=_token(TEST_ADMIN_USER))
        assert r.status_code == 200 and calls == [MEETING_ID]
        assert repo.jobs[old]["status"] == "expired"                     # 예전 자동 클립은 지우고 다시 만든다


class TestCouncilGuest:
    """의회망 비로그인 손님 (2026-09-11) — 대역 안이면 워크벤치를 쓰고, 기록은 브라우저(X-Guest-Id)별로 갈린다.

    대역은 문서용 예시(RFC 5737). 실제 값은 클러스터 ConfigMap 에만 있다.
    """
    IN = {"X-Real-IP": "192.0.2.150"}
    GID_A = "11111111-2222-3333-4444-555555555555"
    GID_B = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    @pytest.fixture(autouse=True)
    def _ranges(self, monkeypatch):
        monkeypatch.setattr(settings, "council_network_ranges", "192.0.2.146-158")

    def test_guest_can_create_and_list_own_jobs(self, client, repo):
        r = client.post(JOBS_URL, json=_body(), headers={**self.IN, "X-Guest-Id": self.GID_A})
        assert r.status_code == 202, r.text
        job = repo.jobs[r.json()["job_id"]]
        assert job["owner_user_id"] is None and job["owner_username"] == f"guest:{self.GID_A}"
        mine = client.get("/api/clip-jobs", headers={**self.IN, "X-Guest-Id": self.GID_A}).json()
        assert [j["job_id"] for j in mine["jobs"]] == [r.json()["job_id"]]
        # 다른 브라우저 손님에게는 안 보인다
        other = client.get("/api/clip-jobs", headers={**self.IN, "X-Guest-Id": self.GID_B}).json()
        assert other["jobs"] == []
        assert client.get(f"{JOBS_URL}/{r.json()['job_id']}",
                          headers={**self.IN, "X-Guest-Id": self.GID_B}).status_code == 404

    def test_outside_range_still_401(self, client):
        assert client.get("/api/clip-jobs", headers={"X-Real-IP": "192.0.2.159"}).status_code == 401
        assert client.post(JOBS_URL, json=_body(), headers={"X-Real-IP": "198.51.100.1"}).status_code == 401

    def test_spoofed_xff_first_entry_does_not_count(self, client):
        """Traefik 이 덮어쓴 X-Real-IP 가 대역 밖이면, 방문자가 XFF 첫 칸에 대역 주소를 써 넣어도 손님이 아니다."""
        h = {"X-Real-IP": "198.51.100.1", "X-Forwarded-For": "192.0.2.150, 198.51.100.1"}
        assert client.get("/api/clip-jobs", headers=h).status_code == 401

    def test_guest_cannot_use_admin_or_offset_routes(self, client):
        assert client.get("/api/clip-jobs?scope=all", headers=self.IN).status_code == 403
        assert client.post("/api/clip-jobs/sweep", headers=self.IN).status_code == 401
        assert client.put(f"/api/meetings/{MEETING_ID}/clip-offset", json={"offset": 1},
                          headers=self.IN).status_code == 401

    def test_logged_in_user_on_council_network_keeps_own_identity(self, client, repo):
        r = client.post(JOBS_URL, json=_body(), headers={**self.IN, **_token(STAFF_USER)})
        assert r.status_code == 202
        assert repo.jobs[r.json()["job_id"]]["owner_username"] == "staff1"

    def test_bad_guest_id_falls_into_shared_bucket(self, client, repo):
        r = client.post(JOBS_URL, json=_body(), headers={**self.IN, "X-Guest-Id": "x" * 80})
        assert repo.jobs[r.json()["job_id"]]["owner_username"] == "guest:shared"

    def test_network_endpoint(self, client):
        body = client.get("/api/auth/network", headers=self.IN).json()
        assert body["council_network"] is True and body["ip"] == "192.0.2.150"
        # 2026-09-16 추가 — 로그인 요구 대역 판정과 앱 설치 안내 주소를 함께 준다
        assert body["login_required"] is False
        assert body["app_install_guide_url"].startswith("https://")
        assert client.get("/api/auth/network", headers={"X-Real-IP": "198.51.100.1"}).json()["council_network"] is False

    def test_empty_ranges_turn_it_off(self, client, monkeypatch):
        monkeypatch.setattr(settings, "council_network_ranges", "")
        assert client.get("/api/clip-jobs", headers=self.IN).status_code == 401


class TestMembersSearch:
    def test_name_must_be_hangul(self, client):
        assert client.get("/api/clip-meetings/by-member?name=a,b)", headers=_token(STAFF_USER)).status_code in (400, 422)
        assert client.get("/api/clip-meetings/by-member?name=박상현", ).status_code == 401

    def test_union_of_label_and_mention(self, client, monkeypatch):
        seen = {}

        def fake(client_, name):
            seen["name"] = name
            return ["m1", "m2"]
        monkeypatch.setattr(clips_module, "find_meetings_by_member", fake)
        r = client.get("/api/clip-meetings/by-member?name=박상현", headers=_token(STAFF_USER))
        assert r.status_code == 200 and r.json() == {"name": "박상현", "meeting_ids": ["m1", "m2"]}
        assert seen["name"] == "박상현"
