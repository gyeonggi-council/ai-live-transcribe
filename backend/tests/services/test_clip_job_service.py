# -*- coding: utf-8 -*-
"""클립 잡 실행기 — 영속 잡의 생명주기 · 재시작 복구 · 저장소 정리

ffmpeg 는 stub(test_clip_merge_job.py 의 stub_ffmpeg_pipeline 패턴)으로 대체하고,
DB 는 인메모리 가짜 리포지토리로 대체한다.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.config import settings
from app.services import clip_service, clip_store
from app.services.clip_job_service import ClipJobService, sweep_store

MEETING = {"id": "m1", "title": "제392회 [임시회] 제2차 건설교통위원회 [2026.07.21]",
           "meeting_date": "2026-07-21", "vod_url": "https://kms.ggc.go.kr/mp4/x.mp4"}
JOB_ID = "aaaaaaaa-1111-4222-8333-444444444444"


class FakeRepo:
    def __init__(self, jobs=None, subs=None):
        self.jobs = {j["id"]: dict(j) for j in (jobs or [])}
        self.subs = subs or []
        self.client = object()
        self.evicted = []

    def get(self, job_id):
        return dict(self.jobs[job_id]) if job_id in self.jobs else None

    def update(self, job_id, patch):
        self.jobs[job_id].update(patch)
        return dict(self.jobs[job_id])

    def get_meeting(self, meeting_id):
        return dict(MEETING)

    def list_active(self, origin=None):
        return [dict(j) for j in self.jobs.values() if j["status"] in ("queued", "running")
                and (origin is None or j.get("origin", "manual") == origin)]

    def list_evictable(self):
        return sorted((dict(j) for j in self.jobs.values()
                       if j["status"] == "done" and not j.get("evicted_at")),
                      key=lambda j: j["created_at"])

    def mark_evicted(self, job_id, reason):
        self.jobs[job_id].update({"status": "expired", "evicted_reason": reason,
                                  "evicted_at": "now", "files": [], "bytes_total": 0})
        self.evicted.append((job_id, reason))


def _job(**over):
    base = {"id": JOB_ID, "meeting_id": "m1", "label": "김지호 위원", "source_kind": "official",
            "segments": [{"start": 100.0, "end": 130.0}, {"start": 200.0, "end": 260.0}],
            "merge": True, "with_srt": True, "time_offset": 0.0, "vod_url": MEETING["vod_url"],
            "status": "queued", "attempts": 0, "progress": 0.0, "files": [], "bytes_total": 0,
            "created_at": datetime.now(timezone.utc).isoformat(), "expires_at": None}
    base.update(over)
    return base


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "clip_store_dir", str(tmp_path / "clips"))
    clip_store.ensure_dirs()
    return tmp_path / "clips"


@pytest.fixture
def stub_ffmpeg(monkeypatch):
    calls = {"extract": [], "concat": []}

    async def _extract(vod_url, start, end, out_path, **kw):
        calls["extract"].append((start, end))
        calls.setdefault("kw", []).append(kw)
        Path(out_path).write_bytes(b"P" * 100)

    async def _concat(parts, out_path):
        calls["concat"].append([str(p) for p in parts])
        Path(out_path).write_bytes(b"M" * 300)

    monkeypatch.setattr(clip_service, "extract_clip_mp4", _extract)
    monkeypatch.setattr(clip_service, "concat_clips_mp4", _concat)
    return calls


@pytest.fixture
def subs_source(monkeypatch):
    subs = [{"start_time": 101.0, "end_time": 104.0, "text": "안녕하십니까", "speaker": "김지호 위원", "kind": "ai"}]
    monkeypatch.setattr("app.services.clip_job_service._fetch_all_subtitles", lambda client, mid: subs)
    return subs


def _service(repo):
    svc = ClipJobService()
    svc.configure(lambda: repo)
    return svc


class TestRun:
    @pytest.mark.asyncio
    async def test_merged_job_writes_one_mp4_and_srt(self, store, stub_ffmpeg, subs_source):
        repo = FakeRepo([_job()])
        svc = _service(repo)
        await svc._run(JOB_ID)
        job = repo.jobs[JOB_ID]
        assert job["status"] == "done" and job["progress"] == 1.0
        names = [f["name"] for f in job["files"]]
        assert names[0] == "김지호 위원_제392회 제2차 건설교통위원회_합본.mp4"
        assert names[1] == "김지호 위원_제392회 제2차 건설교통위원회_합본.srt"
        assert job["bytes_total"] == sum(f["bytes"] for f in job["files"]) > 300
        assert stub_ffmpeg["extract"] == [(100.0, 130.0), (200.0, 260.0)]
        assert not clip_store.work_dir(JOB_ID).exists()
        assert job["expires_at"] and job["attempts"] == 1
        srt = (clip_store.job_dir(JOB_ID) / names[1]).read_text(encoding="utf-8-sig")
        assert "[김지호 위원] 안녕하십니까" in srt

    @pytest.mark.asyncio
    async def test_separate_files_named_by_list_number(self, store, stub_ffmpeg, subs_source):
        """번호는 화면이 보낸 목록 순번(no) — 2번·5번만 골랐으면 _2·_5 (고른 순서 1·2 가 아니다)."""
        repo = FakeRepo([_job(merge=False, with_srt=False, pad_before=1.0,
                              segments=[{"start": 99.0, "end": 131.0, "no": 2},
                                        {"start": 199.0, "end": 261.0, "no": 5}])])
        await _service(repo)._run(JOB_ID)
        names = [f["name"] for f in repo.jobs[JOB_ID]["files"]]
        assert names == ["김지호 위원_제392회 제2차 건설교통위원회_2.mp4",
                         "김지호 위원_제392회 제2차 건설교통위원회_5.mp4"]
        assert stub_ffmpeg["concat"] == []

    @pytest.mark.asyncio
    async def test_segments_without_number_use_output_order(self, store, stub_ffmpeg, subs_source):
        """수동 자르기·옛 요청처럼 no 가 없으면 결과 순서(1부터)."""
        repo = FakeRepo([_job(merge=False, with_srt=False)])
        await _service(repo)._run(JOB_ID)
        names = [f["name"] for f in repo.jobs[JOB_ID]["files"]]
        assert names == ["김지호 위원_제392회 제2차 건설교통위원회_1.mp4",
                         "김지호 위원_제392회 제2차 건설교통위원회_2.mp4"]

    @pytest.mark.asyncio
    async def test_ai_source_has_no_provisional_suffix(self, store, stub_ffmpeg, subs_source):
        """2026-09-10 부터 _AI잠정 을 붙이지 않는다 — 이름_회의명_번호 그대로."""
        repo = FakeRepo([_job(source_kind="ai", with_srt=False)])
        await _service(repo)._run(JOB_ID)
        assert repo.jobs[JOB_ID]["files"][0]["name"] == "김지호 위원_제392회 제2차 건설교통위원회_합본.mp4"

    @pytest.mark.asyncio
    async def test_failure_marks_failed_and_cleans(self, store, monkeypatch, subs_source):
        async def _boom(*a, **k):
            raise clip_service.ClipExtractError("ffmpeg 실패 (exit 1): x")

        monkeypatch.setattr(clip_service, "extract_clip_mp4", _boom)
        repo = FakeRepo([_job()])
        await _service(repo)._run(JOB_ID)
        job = repo.jobs[JOB_ID]
        assert job["status"] == "failed" and "ffmpeg" in job["error"]
        assert not clip_store.work_dir(JOB_ID).exists()
        assert not clip_store.job_dir(JOB_ID).exists()

    @pytest.mark.asyncio
    async def test_non_queued_job_is_skipped(self, store, stub_ffmpeg):
        repo = FakeRepo([_job(status="done")])
        await _service(repo)._run(JOB_ID)
        assert stub_ffmpeg["extract"] == []


class TestRecoverAndStop:
    @pytest.mark.asyncio
    async def test_recover_requeues_running_jobs(self, store, monkeypatch):
        repo = FakeRepo([_job(status="running", attempts=1)])
        svc = _service(repo)
        submitted = []
        monkeypatch.setattr(svc, "submit", lambda job_id: submitted.append(job_id))
        n = await svc.recover_interrupted()
        assert n == 1 and submitted == [JOB_ID]
        assert repo.jobs[JOB_ID]["status"] == "queued"

    @pytest.mark.asyncio
    async def test_recover_gives_up_after_two_attempts(self, store, monkeypatch):
        repo = FakeRepo([_job(status="running", attempts=2)])
        svc = _service(repo)
        monkeypatch.setattr(svc, "submit", lambda job_id: (_ for _ in ()).throw(AssertionError("no")))
        assert await svc.recover_interrupted() == 0
        assert repo.jobs[JOB_ID]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_stop_returns_running_to_queued(self, store, monkeypatch):
        async def _hang(*a, **k):
            await asyncio.sleep(3600)

        monkeypatch.setattr(clip_service, "extract_clip_mp4", _hang)
        repo = FakeRepo([_job()])
        svc = _service(repo)
        task = svc.submit(JOB_ID)
        for _ in range(20):
            await asyncio.sleep(0)
            if repo.jobs[JOB_ID]["status"] == "running":
                break
        assert repo.jobs[JOB_ID]["status"] == "running"
        await svc.stop()
        assert task.done()
        assert repo.jobs[JOB_ID]["status"] == "queued"

    @pytest.mark.asyncio
    async def test_cancel_marks_cancelled(self, store, monkeypatch):
        async def _hang(*a, **k):
            await asyncio.sleep(3600)

        monkeypatch.setattr(clip_service, "extract_clip_mp4", _hang)
        repo = FakeRepo([_job()])
        svc = _service(repo)
        svc.submit(JOB_ID)
        for _ in range(20):
            await asyncio.sleep(0)
            if repo.jobs[JOB_ID]["status"] == "running":
                break
        assert await svc.cancel(JOB_ID) is True
        assert repo.jobs[JOB_ID]["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_semaphore_limits_active(self, store, monkeypatch):
        monkeypatch.setattr(settings, "clip_job_max_active", 1)
        running = {"max": 0, "cur": 0}

        async def _slow(vod_url, start, end, out_path, **kw):
            running["cur"] += 1
            running["max"] = max(running["max"], running["cur"])
            await asyncio.sleep(0.01)
            Path(out_path).write_bytes(b"x")
            running["cur"] -= 1

        monkeypatch.setattr(clip_service, "extract_clip_mp4", _slow)
        monkeypatch.setattr("app.services.clip_job_service._fetch_all_subtitles", lambda c, m: [])
        ids = ["aaaaaaaa-1111-4222-8333-44444444440%d" % i for i in range(3)]
        repo = FakeRepo([_job(id=i, merge=False, with_srt=False,
                              segments=[{"start": 0, "end": 10}]) for i in ids])
        svc = _service(repo)
        await asyncio.gather(*(svc._run(i) for i in ids))
        assert running["max"] == 1
        assert all(repo.jobs[i]["status"] == "done" for i in ids)


class TestSweep:
    def _done(self, jid, created_days_ago, size, expires_days=7):
        created = datetime.now(timezone.utc) - timedelta(days=created_days_ago)
        d = clip_store.job_dir(jid)
        d.mkdir(parents=True, exist_ok=True)
        (d / "a.mp4").write_bytes(b"x" * size)
        return _job(id=jid, status="done", files=[{"name": "a.mp4", "kind": "mp4", "bytes": size}],
                    bytes_total=size, created_at=created.isoformat(),
                    expires_at=(created + timedelta(days=expires_days)).isoformat())

    def test_ttl_then_capacity_oldest_first_never_active(self, store):
        old = self._done("aaaaaaaa-0000-4000-8000-000000000001", 8, 100)     # 만료
        mid = self._done("aaaaaaaa-0000-4000-8000-000000000002", 3, 100)
        new = self._done("aaaaaaaa-0000-4000-8000-000000000003", 1, 100)
        act = _job(id="aaaaaaaa-0000-4000-8000-000000000004", status="running")
        repo = FakeRepo([old, mid, new, act])
        stat = sweep_store(repo, max_bytes=150)
        reasons = {e["job_id"][-1]: e["reason"] for e in stat["evicted"]}
        assert reasons == {"1": "ttl", "2": "capacity"}
        assert repo.jobs[new["id"]]["status"] == "done"
        assert repo.jobs[act["id"]]["status"] == "running"
        assert not clip_store.job_dir(old["id"]).exists()
        assert stat["used_bytes"] == 100

    def test_dry_run_changes_nothing(self, store):
        old = self._done("aaaaaaaa-0000-4000-8000-000000000001", 8, 100)
        repo = FakeRepo([old])
        stat = sweep_store(repo, dry_run=True)
        assert [e["reason"] for e in stat["evicted"]] == ["ttl"]
        assert repo.jobs[old["id"]]["status"] == "done"
        assert clip_store.job_dir(old["id"]).exists()


# ─── 자동 클립(031) — 압축·보관일·수동 우선 보호·대기 잡 취소 ─────────────────────


class TestAutoJobs:
    @pytest.mark.asyncio
    async def test_compress_flag_reaches_ffmpeg_and_auto_ttl_is_short(self, store, stub_ffmpeg, subs_source):
        repo = FakeRepo([_job(origin="auto", compress=True, merge=False,
                              segments=[{"start": 100.0, "end": 130.0, "no": 3}])])
        await _service(repo)._run(JOB_ID)
        assert repo.jobs[JOB_ID]["status"] == "done"
        assert stub_ffmpeg["kw"] and all(k.get("compress") is True for k in stub_ffmpeg["kw"])
        left = datetime.fromisoformat(repo.jobs[JOB_ID]["expires_at"]) - datetime.now(timezone.utc)
        assert timedelta(days=settings.clip_auto_ttl_days) - timedelta(minutes=1) < left \
            <= timedelta(days=settings.clip_auto_ttl_days)

    @pytest.mark.asyncio
    async def test_manual_job_is_not_compressed(self, store, stub_ffmpeg, subs_source):
        repo = FakeRepo([_job(merge=False)])
        await _service(repo)._run(JOB_ID)
        assert all(k.get("compress") is False for k in stub_ffmpeg["kw"])

    @pytest.mark.asyncio
    async def test_api_recovery_leaves_auto_jobs_to_the_worker(self, store, monkeypatch):
        auto_id = "aaaaaaaa-1111-4222-8333-555555555555"
        repo = FakeRepo([_job(status="running"), _job(id=auto_id, status="running", origin="auto")])
        svc = _service(repo)
        submitted = []
        monkeypatch.setattr(svc, "submit", lambda job_id: submitted.append(job_id))
        assert await svc.recover_interrupted() == 1
        assert submitted == [JOB_ID]
        assert repo.jobs[auto_id]["status"] == "running"      # 작업자 파드가 복구한다

    @pytest.mark.asyncio
    async def test_cancel_while_waiting_for_a_slot_is_recorded(self, store, monkeypatch):
        """차례를 기다리던 잡을 취소하면 DB 도 cancelled 여야 한다(예전엔 queued 로 남아 재기동 때 다시 돌았다)."""
        monkeypatch.setattr(settings, "clip_job_max_active", 1)

        async def _hang(*a, **k):
            await asyncio.sleep(3600)

        monkeypatch.setattr(clip_service, "extract_clip_mp4", _hang)
        waiting = "aaaaaaaa-1111-4222-8333-666666666666"
        repo = FakeRepo([_job(), _job(id=waiting)])
        svc = _service(repo)
        svc.submit(JOB_ID)
        svc.submit(waiting)
        for _ in range(20):
            await asyncio.sleep(0)
        assert repo.jobs[waiting]["status"] == "queued"
        assert await svc.cancel(waiting) is True
        assert repo.jobs[waiting]["status"] == "cancelled"
        await svc.stop()


class TestSweepAuto:
    def _done(self, jid, created_days_ago, size, origin="manual"):
        created = datetime.now(timezone.utc) - timedelta(days=created_days_ago)
        d = clip_store.job_dir(jid)
        d.mkdir(parents=True, exist_ok=True)
        (d / "a.mp4").write_bytes(b"x" * size)
        return _job(id=jid, status="done", origin=origin, files=[{"name": "a.mp4", "kind": "mp4", "bytes": size}],
                    bytes_total=size, created_at=created.isoformat(),
                    expires_at=(created + timedelta(days=7)).isoformat())

    def test_auto_budget_evicts_oldest_auto_only(self, store):
        manual_old = self._done("aaaaaaaa-0000-4000-8000-00000000000a", 5, 100)
        a1 = self._done("aaaaaaaa-0000-4000-8000-000000000001", 2, 100, "auto")
        a2 = self._done("aaaaaaaa-0000-4000-8000-000000000002", 1, 100, "auto")
        repo = FakeRepo([manual_old, a1, a2])
        stat = sweep_store(repo, max_bytes=10_000, auto_max_bytes=150)
        assert [e["job_id"] for e in stat["evicted"]] == [a1["id"]]
        assert repo.jobs[manual_old["id"]]["status"] == "done"

    def test_capacity_takes_auto_before_older_manual(self, store):
        manual_old = self._done("aaaaaaaa-0000-4000-8000-00000000000a", 5, 100)
        auto_new = self._done("aaaaaaaa-0000-4000-8000-000000000001", 1, 100, "auto")
        repo = FakeRepo([manual_old, auto_new])
        stat = sweep_store(repo, max_bytes=150, auto_max_bytes=10_000)
        assert [e["job_id"] for e in stat["evicted"]] == [auto_new["id"]]
        assert repo.jobs[manual_old["id"]]["status"] == "done"

    def test_worker_never_evicts_manual(self, store):
        manual = self._done("aaaaaaaa-0000-4000-8000-00000000000a", 1, 100)
        repo = FakeRepo([manual])
        stat = sweep_store(repo, max_bytes=150, extra_free_bytes=100, manual_evictable=False)
        assert stat["evicted"] == [] and repo.jobs[manual["id"]]["status"] == "done"
