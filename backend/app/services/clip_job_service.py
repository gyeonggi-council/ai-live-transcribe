# -*- coding: utf-8 -*-
"""클립 잡 실행기 + 저장소 정리 — 영속 잡(clip_jobs)판

기존 speakers.py 의 인메모리 잡과 다른 점:
  - 상태가 DB 에 있어 파드가 재시작해도 잡이 남는다(기동 시 recover_interrupted 로 재개).
  - 완료물이 PVC(clip_store) 에 7일 보관된다. 보존은 TTL 과 바이트 상한 둘 다.
  - KMS 스로틀(연결당 ~0.3MB/s) 때문에 세그먼트는 순차, 잡은 세마포어로 동시 N개.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from app.core.config import settings
from app.services import clip_service, clip_store
from app.services.speaker_segments import _fetch_all_subtitles
from app.services.subtitle_select import prefer_ai_subtitles
from app.services.transcript_export import export_srt_merged, export_srt_range

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_iso(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _write_srt(path: Path, text: str) -> None:
    """UTF-8 BOM — 윈도 플레이어(팟플레이어 등) 한글 호환 (데스크톱 추출기와 동일)."""
    path.write_text(text, encoding="utf-8-sig")


class ClipJobService:
    """모듈 싱글턴 — main.lifespan 이 configure/recover/stop 을 부른다."""

    def __init__(self) -> None:
        self._repo_factory: Optional[Callable[[], object]] = None
        self._sem: Optional[asyncio.Semaphore] = None
        self._tasks: dict[str, asyncio.Task] = {}
        self._stopping = False

    # ------------------------------------------------------------ 배선
    def configure(self, repo_factory: Callable[[], object]) -> None:
        self._repo_factory = repo_factory
        self._sem = None
        self._stopping = False

    def _repo(self):
        if self._repo_factory is None:
            raise RuntimeError("ClipJobService 가 configure 되지 않았습니다.")
        return self._repo_factory()

    @property
    def semaphore(self) -> asyncio.Semaphore:
        if self._sem is None:
            self._sem = asyncio.Semaphore(max(1, settings.clip_job_max_active))
        return self._sem

    @property
    def active_task_ids(self) -> set[str]:
        return {k for k, t in self._tasks.items() if not t.done()}

    # ------------------------------------------------------------ 제출/취소
    def submit(self, job_id: str) -> asyncio.Task:
        task = asyncio.create_task(self._run(job_id), name=f"clip-job-{job_id[:8]}")
        self._tasks[job_id] = task
        task.add_done_callback(lambda _t: self._tasks.pop(job_id, None))
        return task

    async def cancel(self, job_id: str) -> bool:
        """running 이면 태스크 취소(ffmpeg kill 은 clip_service 가 CancelledError 에서 수행),
        queued 면 상태만 cancelled. 둘 다 아니면 False."""
        task = self._tasks.get(job_id)
        repo = self._repo()
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            # 차례를 기다리던(세마포어 앞) 태스크는 _run 본문에 들어가지 못해 DB 가 queued 로 남는다 —
            # API 는 "취소" 라고 답했는데 행이 남아 대기 상한을 먹고 재기동 때 다시 돌았다(2026-09-10 발견)
            job = repo.get(job_id)
            if job and job.get("status") == "queued":
                repo.update(job_id, {"status": "cancelled", "finished_at": _iso(_now()),
                                     "current_segment": None})
            return True
        job = repo.get(job_id)
        if job and job.get("status") in ("queued", "running"):
            repo.update(job_id, {"status": "cancelled", "finished_at": _iso(_now()),
                                 "current_segment": None})
            clip_store.remove_job_files(job_id)
            return True
        return False

    async def recover_interrupted(self, origin: str = "manual") -> int:
        """기동 시: 이전 프로세스가 남긴 queued/running 잡을 다시 돌린다.
        두 번 넘게 재시작에 걸린 잡은 failed 로 접는다(무한 루프 방지).
        api 파드는 manual 만 — 자동 클립은 작업자 파드가 따로 복구한다(auto_clip_service.recover)."""
        repo = self._repo()
        rows = await asyncio.to_thread(repo.list_active, origin)
        resumed = 0
        for job in rows:
            job_id = str(job["id"])
            if int(job.get("attempts") or 0) >= MAX_ATTEMPTS:
                repo.update(job_id, {
                    "status": "failed", "finished_at": _iso(_now()), "current_segment": None,
                    "error": "서버 재시작이 반복되어 중단했습니다. 다시 요청해 주세요.",
                })
                clip_store.remove_job_files(job_id)
                continue
            repo.update(job_id, {"status": "queued", "progress": 0.0, "current_segment": None})
            shutil.rmtree(clip_store.work_dir(job_id), ignore_errors=True)
            self.submit(job_id)
            resumed += 1
        if resumed:
            logger.info("클립 잡 복구: %d건 재개", resumed)
        return resumed

    async def stop(self) -> None:
        """종료 시 running 을 queued 로 되돌리고(재기동 후 재개) 태스크를 취소한다."""
        self._stopping = True
        tasks = [t for t in self._tasks.values() if not t.done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ------------------------------------------------------------ 실행
    async def _run(self, job_id: str) -> None:
        repo = self._repo()
        async with self.semaphore:
            job = repo.get(job_id)
            if not job or job.get("status") != "queued":
                return
            work = clip_store.work_dir(job_id)
            out_dir = clip_store.job_dir(job_id)
            attempts = int(job.get("attempts") or 0) + 1
            repo.update(job_id, {"status": "running", "started_at": _iso(_now()),
                                 "attempts": attempts, "progress": 0.0})
            try:
                work.mkdir(parents=True, exist_ok=True)
                out_dir.mkdir(parents=True, exist_ok=True)
                files = await self._extract(repo, job, work, out_dir)
                bytes_total = sum(int(f.get("bytes") or 0) for f in files)
                now = _now()
                ttl = settings.clip_auto_ttl_days if job.get("origin") == "auto" else settings.clip_store_ttl_days
                repo.update(job_id, {
                    "status": "done", "progress": 1.0, "current_segment": None,
                    "files": files, "bytes_total": bytes_total,
                    "finished_at": _iso(now),
                    "expires_at": _iso(now + timedelta(days=max(1, ttl))),
                })
            except asyncio.CancelledError:
                status = "queued" if self._stopping else "cancelled"
                patch = {"status": status, "current_segment": None}
                if status == "cancelled":
                    patch["finished_at"] = _iso(_now())
                    shutil.rmtree(out_dir, ignore_errors=True)
                try:
                    repo.update(job_id, patch)
                finally:
                    shutil.rmtree(work, ignore_errors=True)
                raise
            except Exception as e:  # noqa: BLE001
                logger.error("클립 잡 실패 (%s): %s", job_id, e)
                repo.update(job_id, {"status": "failed", "error": str(e)[:300],
                                     "current_segment": None, "finished_at": _iso(_now())})
                shutil.rmtree(out_dir, ignore_errors=True)
            finally:
                shutil.rmtree(work, ignore_errors=True)

    async def _extract(self, repo, job: dict, work: Path, out_dir: Path) -> list[dict]:
        job_id = str(job["id"])
        # no(목록 순번)는 파일 이름의 번호라 같이 옮긴다 — 빠뜨리면 전부 결과 순서 번호가 된다
        segments = [{"start": float(s["start"]), "end": float(s["end"]),
                     **({"no": int(s["no"])} if s.get("no") else {})}
                    for s in (job.get("segments") or [])]
        if not segments:
            raise RuntimeError("추출할 구간이 없습니다.")
        total = len(segments)
        merge = bool(job.get("merge")) and total > 1
        meeting = repo.get_meeting(str(job["meeting_id"])) or {}
        title = meeting.get("title") or ""
        label = job.get("label") or "클립"

        parts: list[Path] = []
        for idx, seg in enumerate(segments):
            repo.update(job_id, {"current_segment": idx + 1})
            part = work / f"part_{idx:03d}.mp4"
            await clip_service.extract_clip_mp4(job["vod_url"], seg["start"], seg["end"], part,
                                                compress=bool(job.get("compress")),
                                                crf=settings.clip_auto_crf)
            parts.append(part)
            repo.update(job_id, {"progress": round((idx + 1) / (total + 1), 3)})

        outputs: list[tuple[Path, list[dict]]] = []   # (mp4 경로, 그 파일에 든 구간들)
        if merge:
            out = out_dir / clip_service.build_job_filename(label, title, merged=True)
            await clip_service.concat_clips_mp4(parts, out)
            outputs.append((out, segments))
        else:
            # 번호 = 그 의원 구간 목록의 순번(화면이 보낸 no). 수동 자르기처럼 없으면 결과 순서.
            for i, (part, seg) in enumerate(zip(parts, segments)):
                name = clip_service.build_job_filename(label, title, seg.get("no") or i + 1)
                out = out_dir / name
                shutil.move(str(part), str(out))
                outputs.append((out, [seg]))

        files: list[dict] = []
        srt_subs: Optional[list[dict]] = None
        time_shift = 0.0
        if job.get("with_srt"):
            srt_subs, time_shift = await asyncio.to_thread(
                self._srt_source, repo, str(job["meeting_id"]), float(job.get("time_offset") or 0))
        for out, segs in outputs:
            files.append({"name": out.name, "kind": "mp4", "bytes": out.stat().st_size})
            if srt_subs:
                if len(segs) > 1:
                    text = export_srt_merged(srt_subs, segs, time_shift=time_shift)
                else:
                    text = export_srt_range(srt_subs, segs[0]["start"], segs[0]["end"],
                                            time_shift=time_shift)
                if text.strip():
                    srt_path = out.with_suffix(".srt")
                    _write_srt(srt_path, text)
                    files.append({"name": srt_path.name, "kind": "srt",
                                  "bytes": srt_path.stat().st_size})
        return files

    @staticmethod
    def _srt_source(repo, meeting_id: str, time_offset: float) -> tuple[list[dict], float]:
        """SRT 원천 자막 — AI 자막 우선, 없으면 실시간 자막(+오프셋). 실패하면 빈 목록."""
        try:
            subs = prefer_ai_subtitles(_fetch_all_subtitles(repo.client, meeting_id))
        except Exception as e:  # noqa: BLE001
            logger.info("SRT 자막 조회 실패(SRT 생략): %s", e)
            return [], 0.0
        is_live = bool(subs) and all(s.get("kind") == "live" for s in subs)
        return subs, (time_offset if is_live else 0.0)


clip_job_service = ClipJobService()


# ============================================================ 저장소 정리
def sweep_store(repo, *, now: Optional[datetime] = None, ttl_days: Optional[int] = None,
                max_bytes: Optional[int] = None, dry_run: bool = False,
                extra_free_bytes: int = 0, auto_max_bytes: Optional[int] = None,
                auto_extra_free_bytes: int = 0, manual_evictable: bool = True) -> dict:
    """① done & 만료 → ttl  ② 자동 클립이 자동분 예산을 넘으면 오래된 자동부터 capacity
    ③ 전체 사용량 > 상한 → **자동 클립부터**, 그다음 오래된 수동 순으로 capacity  ④ 고아 디렉터리.
    running/queued 는 절대 건드리지 않는다. dry_run 이면 후보만 돌려준다.

    자동 클립(2026-09-10)은 회의마다 수백 MB 씩 쌓이므로, 예전처럼 "오래된 것부터" 만 두면 담당자가
    손으로 받아 둔 수동 클립이 자동분에 밀려 먼저 지워진다 — 그래서 자동분이 늘 먼저 나간다.
    manual_evictable=False 는 자동 작업자가 자리를 만들 때 — 자동 클립만 지우고 수동은 절대 건드리지 않는다."""
    now = now or _now()
    ttl_days = settings.clip_store_ttl_days if ttl_days is None else ttl_days
    max_bytes = settings.clip_store_max_bytes if max_bytes is None else max_bytes
    auto_max_bytes = settings.clip_auto_max_bytes if auto_max_bytes is None else auto_max_bytes
    evictable = repo.list_evictable()
    evicted: list[dict] = []
    remaining: list[dict] = []

    def _bytes_of(job: dict) -> int:
        b = int(job.get("bytes_total") or 0)
        return b or clip_store.dir_bytes(clip_store.job_dir(str(job["id"])))

    def _evict(job: dict, reason: str) -> int:
        b = _bytes_of(job)
        if not dry_run:
            clip_store.remove_job_files(str(job["id"]))
            repo.mark_evicted(str(job["id"]), reason)
        evicted.append({"job_id": str(job["id"]), "reason": reason, "bytes": b})
        return b

    for job in evictable:
        exp = _parse_iso(job.get("expires_at"))
        created = _parse_iso(job.get("created_at"))
        expired = (exp is not None and exp <= now) or (
            exp is None and created is not None and created + timedelta(days=ttl_days) <= now)
        if expired:
            _evict(job, "ttl")
        else:
            remaining.append(job)

    used = clip_store.usage_bytes() - (sum(e["bytes"] for e in evicted) if dry_run else 0)

    def _created(j: dict) -> str:
        return str(j.get("created_at") or "")

    # 자동분 예산 — 자동 클립끼리만, 오래된 회의부터
    autos = sorted((j for j in remaining if j.get("origin") == "auto"), key=_created)
    auto_used = sum(_bytes_of(j) for j in autos)
    auto_target = auto_max_bytes - max(0, auto_extra_free_bytes)
    gone: set[str] = set()
    for job in autos:
        if auto_used <= auto_target:
            break
        b = _evict(job, "capacity")
        auto_used -= b
        used -= b
        gone.add(str(job["id"]))

    # 전체 상한 — 자동분 먼저, 그다음 수동(각각 오래된 순)
    target = max_bytes - max(0, extra_free_bytes)
    rest = [j for j in remaining if str(j["id"]) not in gone]
    for job in sorted(rest, key=lambda j: (0 if j.get("origin") == "auto" else 1, _created(j))):
        if used <= target or (not manual_evictable and job.get("origin") != "auto"):
            break
        used -= _evict(job, "capacity")

    orphans: list[str] = []
    if not dry_run:
        known = {str(j["id"]) for j in evictable} | {str(j["id"]) for j in repo.list_active()}
        orphans = clip_store.sweep_orphan_dirs(known, max_age_seconds=6 * 3600)

    return {"evicted": evicted, "orphans": orphans,
            "used_bytes": max(0, used), "max_bytes": max_bytes, "dry_run": dry_run}
