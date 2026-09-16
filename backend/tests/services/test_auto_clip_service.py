# -*- coding: utf-8 -*-
"""자동 클립(2026-09-10) — 대상 회의 스캔 · 의원별 잡 · 파일 번호 규칙 · 디스크/예산 가드 · 복구

사용자 결정: AI 자막이 끝난 회의의 의원 전원 영상을 서버가 미리 잘라(720p) 둔다. 서버가 다운되면 안 된다.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.services import auto_clip_service as auto
from app.services import clip_store
from app.services.clip_job_service import MAX_ATTEMPTS

M1 = {"id": "m1", "title": "제393회 제3차 도시환경위원회 [2026-09-08]", "meeting_date": "2026-09-08",
      "vod_url": "https://kms.ggc.go.kr/mp4//mp4media2/dosi/20260908_dosi.mp4", "duration_seconds": 12510,
      "status": "ended", "subtitle_stage": "ai"}
M2 = {**M1, "id": "m2", "title": "제393회 제2차 경제노동위원회 [2026-09-09]", "meeting_date": "2026-09-09"}

SPEAKERS = [
    {"name": "김태희", "segments": [
        {"idx": 0, "start": 1172.0, "end": 1199.0, "named": True},
        {"idx": 1, "start": 6661.0, "end": 7520.0, "named": True},
        {"idx": 2, "start": 11491.0, "end": 12006.0, "named": True}]},
    {"name": "이혜원", "segments": [{"idx": 0, "start": 3000.0, "end": 3600.0, "named": True}]},
    {"name": "", "segments": [{"idx": 0, "start": 10.0, "end": 20.0, "named": True}]},   # 이름 없음 → 버린다
]


def _index(source="ai", speakers=SPEAKERS):
    return {"source": source, "duration": 12510, "speakers": speakers}


class FakeRepo:
    def __init__(self, meetings=(), jobs=()):
        self.meetings = list(meetings)
        self.jobs = {j["id"]: dict(j) for j in jobs}
        self.client = object()
        self.since = None
        self.next_calls = 0
        self.evicted = []

    def insert(self, row):
        self.jobs[row["id"]] = dict(row)
        return dict(row)

    def get(self, job_id):
        return dict(self.jobs[job_id]) if job_id in self.jobs else None

    def update(self, job_id, patch):
        self.jobs[job_id].update(patch)

    def list_auto_candidate_meetings(self, since):
        self.since = since
        return [dict(m) for m in self.meetings]

    def meetings_with_auto_jobs(self, ids):
        return {j["meeting_id"] for j in self.jobs.values() if j.get("origin") == "auto" and j["meeting_id"] in ids}

    def next_queued_auto(self):
        self.next_calls += 1
        q = sorted((j for j in self.jobs.values() if j.get("origin") == "auto" and j["status"] == "queued"),
                   key=lambda j: j["created_at"])
        return dict(q[0]) if q else None

    def list_active(self, origin=None):
        return [dict(j) for j in self.jobs.values() if j["status"] in ("queued", "running")
                and (origin is None or j.get("origin", "manual") == origin)]

    def list_evictable(self):
        return sorted((dict(j) for j in self.jobs.values() if j["status"] == "done" and not j.get("evicted_at")),
                      key=lambda j: j["created_at"])

    def mark_evicted(self, job_id, reason):
        self.jobs[job_id].update({"status": "expired", "evicted_at": "now", "evicted_reason": reason,
                                  "files": [], "bytes_total": 0})
        self.evicted.append(job_id)


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "clip_store_dir", str(tmp_path / "clips"))
    monkeypatch.setattr(settings, "clip_auto_enabled", True)
    clip_store.ensure_dirs()
    auto._reset_for_tests()
    yield
    auto._reset_for_tests()


# ─── 인덱스 → 의원별 잡 ─────────────────────────────────────────────────


class TestBuildJobs:
    def test_one_job_per_member_with_list_numbers_like_the_workbench(self):
        """번호 = 그 의원 구간 목록의 순번(idx+1) — 워크벤치·설치형과 같은 파일 이름이 나와야 한 폴더에 모인다."""
        spk = [{"name": "전자영", "segments": [
            {"idx": 4, "start": 100.0, "end": 200.0, "named": False},       # 의사진행 항목 — 자동으로는 안 자른다
            {"idx": 7, "start": 300.0, "end": 400.0, "named": True}]}]
        rows = auto.build_jobs_for_index(M1, _index("official", spk))
        assert len(rows) == 1
        r = rows[0]
        assert r["segments"] == [{"start": 299.0, "end": 401.0, "no": 8}]     # 앞뒤 1초
        assert (r["origin"], r["compress"], r["merge"], r["with_srt"]) == ("auto", True, False, True)
        assert (r["owner_username"], r["owner_user_id"], r["label"], r["speaker_name"]) == ("자동", None, "전자영", "전자영")
        assert r["source_kind"] == "official" and r["status"] == "queued" and r["vod_url"] == M1["vod_url"]

    def test_members_without_name_or_named_segments_are_skipped(self):
        rows = auto.build_jobs_for_index(M1, _index())
        assert [r["label"] for r in rows] == ["김태희", "이혜원"]
        assert [s["no"] for s in rows[0]["segments"]] == [1, 2, 3]

    def test_no_index_means_no_jobs(self):
        assert auto.build_jobs_for_index(M1, _index("none", [])) == []


# ─── 스캔 ───────────────────────────────────────────────────────────────


class TestScan:
    @pytest.mark.asyncio
    async def test_enqueues_new_meetings_once(self, monkeypatch):
        repo = FakeRepo([M1, M2], jobs=[{"id": "old", "meeting_id": "m2", "origin": "auto", "status": "done",
                                          "created_at": "2026-09-09T00:00:00+00:00"}])
        built = []

        async def fake_index(client, meeting):
            built.append(meeting["id"])
            return _index()

        monkeypatch.setattr(auto, "build_clip_index", fake_index)
        await auto.scan_and_enqueue(repo, today=date(2026, 9, 10))
        assert built == ["m1"]                                    # m2 는 이미 자동 잡이 있다
        assert repo.since == (date(2026, 9, 10) - timedelta(days=settings.clip_auto_max_age_days)).isoformat()
        assert sum(1 for j in repo.jobs.values() if j["meeting_id"] == "m1") == 2
        await auto.scan_and_enqueue(repo, today=date(2026, 9, 10))
        assert built == ["m1"]                                    # 다음 스캔에서 다시 만들지 않는다

    @pytest.mark.asyncio
    async def test_empty_index_is_not_rebuilt_every_scan(self, monkeypatch):
        repo = FakeRepo([M1])
        built = []

        async def fake_index(client, meeting):
            built.append(meeting["id"])
            return _index("none", [])

        monkeypatch.setattr(auto, "build_clip_index", fake_index)
        await auto.scan_and_enqueue(repo)
        await auto.scan_and_enqueue(repo)
        assert built == ["m1"] and repo.jobs == {}

    @pytest.mark.asyncio
    async def test_disabled_does_nothing(self, monkeypatch):
        monkeypatch.setattr(settings, "clip_auto_enabled", False)
        repo = FakeRepo([M1])
        assert (await auto.scan_and_enqueue(repo))["enabled"] is False and repo.since is None

    @pytest.mark.asyncio
    async def test_foreign_vod_is_skipped(self, monkeypatch):
        repo = FakeRepo([{**M1, "vod_url": "https://example.com/x.mp4"}])

        async def fake_index(client, meeting):
            raise AssertionError("인덱스를 세우지 않는다")

        monkeypatch.setattr(auto, "build_clip_index", fake_index)
        await auto.scan_and_enqueue(repo)
        assert repo.jobs == {}


# ─── 실행 가드 ─────────────────────────────────────────────────────────


def _auto_job(jid, created, status="queued", total=50.0, **over):
    return {"id": jid, "meeting_id": "m1", "origin": "auto", "compress": True, "status": status,
            "total_seconds": total, "created_at": created, "attempts": 0, **over}


class StubService:
    def __init__(self):
        self.ran = []

    async def _run(self, job_id):
        self.ran.append(job_id)


class TestRunNext:
    @pytest.mark.asyncio
    async def test_low_disk_pauses_and_notifies_once(self, monkeypatch):
        sent = []
        monkeypatch.setattr("app.services.notification_service.create_notification_record",
                            lambda client, t, title, msg, *a, **k: sent.append((t, title)))
        repo = FakeRepo(jobs=[_auto_job("j1", "2026-09-10T00:00:00+00:00")])
        svc = StubService()
        low = lambda: (False, 5 * 1024 ** 3)       # noqa: E731
        assert await auto.run_next(repo, svc, disk_check=low) is None
        assert await auto.run_next(repo, svc, disk_check=low) is None
        assert svc.ran == [] and repo.next_calls == 0          # 큐를 보지도 않는다
        assert sent == [("auto_clip", "자동 클립 일시 중지")]     # 6시간에 한 번

    @pytest.mark.asyncio
    async def test_runs_oldest_queued_auto_job(self):
        repo = FakeRepo(jobs=[_auto_job("new", "2026-09-10T02:00:00+00:00"),
                              _auto_job("old", "2026-09-10T01:00:00+00:00")])
        svc = StubService()
        assert await auto.run_next(repo, svc, disk_check=lambda: (True, 50 * 1024 ** 3)) == "old"
        assert svc.ran == ["old"]

    @pytest.mark.asyncio
    async def test_nothing_queued(self):
        assert await auto.run_next(FakeRepo(), StubService(), disk_check=lambda: (True, 1 << 40)) is None

    def _done_on_disk(self, jid, size, origin, days_ago):
        created = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
        d = clip_store.job_dir(jid)
        d.mkdir(parents=True, exist_ok=True)
        (d / "a.mp4").write_bytes(b"x" * size)
        return {"id": jid, "meeting_id": "m0", "origin": origin, "status": "done", "bytes_total": size,
                "files": [{"name": "a.mp4", "kind": "mp4", "bytes": size}], "created_at": created,
                "expires_at": (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()}

    @pytest.mark.asyncio
    async def test_waits_instead_of_deleting_staff_clips(self, monkeypatch):
        """저장 상한이 수동 클립으로 차 있으면 자동 잡은 기다린다 — 사람이 받아 둔 것을 자동 때문에 지우지 않는다."""
        monkeypatch.setattr(settings, "clip_store_max_bytes", 1000)
        monkeypatch.setattr(settings, "clip_auto_bytes_per_second", 10)
        manual = self._done_on_disk("aaaaaaaa-0000-4000-8000-00000000000a", 800, "manual", 1)
        repo = FakeRepo(jobs=[manual, _auto_job("q1", "2026-09-10T00:00:00+00:00", total=50.0)])
        svc = StubService()
        assert await auto.run_next(repo, svc, disk_check=lambda: (True, 1 << 40)) is None
        assert svc.ran == [] and repo.evicted == []

    @pytest.mark.asyncio
    async def test_evicts_old_auto_clips_to_make_room(self, monkeypatch):
        monkeypatch.setattr(settings, "clip_store_max_bytes", 1000)
        monkeypatch.setattr(settings, "clip_auto_bytes_per_second", 10)
        old_auto = self._done_on_disk("aaaaaaaa-0000-4000-8000-000000000001", 800, "auto", 2)
        repo = FakeRepo(jobs=[old_auto, _auto_job("q1", "2026-09-10T00:00:00+00:00", total=50.0)])
        svc = StubService()
        assert await auto.run_next(repo, svc, disk_check=lambda: (True, 1 << 40)) == "q1"
        assert repo.evicted == [old_auto["id"]]


class TestRecover:
    def test_running_back_to_queued_and_repeated_restart_fails(self):
        r1, r2, m = ("aaaaaaaa-0000-4000-8000-0000000000%02d" % i for i in (1, 2, 3))
        repo = FakeRepo(jobs=[_auto_job(r1, "t", status="running", attempts=1),
                              _auto_job(r2, "t", status="running", attempts=MAX_ATTEMPTS),
                              {**_auto_job(m, "t", status="running"), "origin": "manual"}])
        assert auto.recover(repo) == 1
        assert repo.jobs[r1]["status"] == "queued"
        assert repo.jobs[r2]["status"] == "failed"
        assert repo.jobs[m]["status"] == "running"            # 수동 잡은 api 파드 몫
