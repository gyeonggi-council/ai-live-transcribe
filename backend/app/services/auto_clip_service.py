"""자동 클립 — AI 자막이 끝난 회의의 의원 발언 영상을 서버가 미리 잘라(720p 로 작게) 둔다 (2026-09-10).

사용자 결정: 설치형 추출기의 "확인 후 추출" 없이 **그 회의 의원 전원** 영상을 받기만 하게. 유튜브·휴대폰 공유용이라
용량을 줄인다. 서버가 다운되지 않아야 한다 — 그래서 이 모듈은 api 파드가 아니라 **별도 작업자 파드**
(`app/workers/auto_clip_worker.py`, k8s cpu 1·mem 1Gi)에서만 돈다.

    scan_and_enqueue  최근 N일 AI 자막 완료 회의 중 자동 잡이 없는 것 → build_clip_index → 의원마다 잡 1개
    run_next          가장 오래된 대기 자동 잡 1개 → ClipJobService._run(압축 추출) — 한 번에 하나
    recover           작업자 재기동 때 running 으로 남은 자동 잡을 queued 로(두 번 넘으면 failed)

잰 것(2026-09-10): 의원 구간이 회의의 82~95% 라 원본 그대로면 회의 1건 2.8~5.8GB(서버 여유 19GB).
720p CRF28 로 원본의 17%(회의 1건 ≈ 0.7GB), 1코어로 실시간의 5.4배(회의 1건 ≈ 43분).

가드:
  - 디스크 여유가 `clip_auto_min_free_bytes`(12GiB) 아래면 자르지 않는다(08-18 디스크 사고) — 알림 1회/6시간
  - 자동분 예산 `clip_auto_max_bytes`(5GiB) — 넘으면 오래된 자동 클립부터 지운다. **수동 클립은 자동 잡 때문에 지우지 않는다**
  - 파일 이름은 워크벤치·설치형과 같은 규칙(`이름_회의명_번호.mp4`, 번호 = 그 의원 구간 목록 순번 idx+1) —
    담당자가 세 경로로 받은 파일을 한 폴더에 모은다
  - 정확도는 99% 가 아니다(392회 위원회 전수 80.9%, docs/clip-slot-accuracy-eval-2026-09.md) — 화면이
    "공유 전 한 번 재생해 확인" 을 붙인다(사용자 선택)
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.services import clip_store
from app.services.clip_draft_index import build_clip_index
from app.services.clip_job_service import MAX_ATTEMPTS, sweep_store
from app.services.kms_angun_service import pad_and_merge
from app.services.kms_vod_resolver import is_allowed_vod_source

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
AUTO_OWNER = "자동"
NOTIFICATION_TYPE = "auto_clip"
LOW_DISK_NOTIFY_SECONDS = 6 * 3600

# 인덱스가 비어 잡을 못 만든 회의 — 작업자가 사는 동안 30분마다 다시 인덱스를 세우지 않게
_no_speakers: set[str] = set()
_last_low_disk_notice = 0.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def estimate_bytes(total_seconds: float) -> int:
    return int(max(0.0, float(total_seconds)) * settings.clip_auto_bytes_per_second)


def disk_free_bytes() -> int:
    root = clip_store.clip_root()
    return shutil.disk_usage(root if root.exists() else root.parent).free


def disk_ok() -> tuple[bool, int]:
    free = disk_free_bytes()
    return free >= settings.clip_auto_min_free_bytes, free


def build_jobs_for_index(meeting: dict, index: dict, *, now: Optional[datetime] = None) -> list[dict]:
    """인덱스 → 의원별 자동 잡 행. 이름 있는(named) 구간만, 앞뒤 여유 1초, 구간별 파일, SRT 포함."""
    source = index.get("source")
    if source not in ("official", "ai"):
        return []
    now = now or _now()
    pad = float(settings.clip_auto_pad_seconds)
    duration = meeting.get("duration_seconds") or index.get("duration") or None
    rows: list[dict] = []
    for spk in index.get("speakers") or []:
        name = str(spk.get("name") or "").strip()
        # 번호 = 그 의원 구간 목록의 순번(idx+1) — ClipEditor 가 보내는 no 와 같은 값이어야 파일 이름이 맞는다
        segs = [{"start": float(s["start"]), "end": float(s["end"]), "no": int(s["idx"]) + 1}
                for s in (spk.get("segments") or []) if s.get("named")]
        if not name or not segs:
            continue
        merged = pad_and_merge(segs, pad, pad, duration)
        total = round(sum(s["end"] - s["start"] for s in merged), 2)
        if total <= 0:
            continue
        rows.append({
            "id": str(uuid.uuid4()),
            "meeting_id": str(meeting["id"]),
            "owner_user_id": None,
            "owner_username": AUTO_OWNER,
            "label": name,
            "speaker_name": name,
            "source_kind": source,
            "segments": merged,
            "pad_before": pad,
            "pad_after": pad,
            "merge": False,
            "with_srt": True,
            "time_offset": 0.0,
            "vod_url": meeting.get("vod_url"),
            "total_seconds": total,
            "status": "queued",
            "attempts": 0,
            "progress": 0.0,
            "files": [],
            "bytes_total": 0,
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(days=max(1, settings.clip_auto_ttl_days))).isoformat(),
            "origin": "auto",
            "compress": True,
        })
    return rows


async def enqueue_meeting(repo, meeting: dict) -> dict:
    """회의 1건의 의원별 자동 잡을 큐에 넣는다(행만 — 자르기는 run_next)."""
    mid = str(meeting["id"])
    vod_url = meeting.get("vod_url")
    if not vod_url or not is_allowed_vod_source(vod_url):
        return {"meeting_id": mid, "jobs": 0, "skipped": "vod"}
    index = await build_clip_index(repo.client, meeting)
    rows = build_jobs_for_index(meeting, index)
    for row in rows:
        await asyncio.to_thread(repo.insert, row)
    if not rows:
        _no_speakers.add(mid)
    logger.info("자동 클립: %s 의원 %d명 큐에 넣음 (출처 %s)", meeting.get("title") or mid, len(rows),
                index.get("source"))
    return {"meeting_id": mid, "jobs": len(rows), "source": index.get("source")}


async def scan_and_enqueue(repo, *, today: Optional[date] = None) -> dict:
    """최근 `clip_auto_max_age_days` 일 AI 자막 완료 회의 중 자동 잡이 없는 것을 큐에 넣는다."""
    if not settings.clip_auto_enabled:
        return {"enabled": False, "meetings": []}
    today = today or datetime.now(KST).date()
    since = (today - timedelta(days=max(0, settings.clip_auto_max_age_days))).isoformat()
    meetings = await asyncio.to_thread(repo.list_auto_candidate_meetings, since)
    have = await asyncio.to_thread(repo.meetings_with_auto_jobs, [str(m["id"]) for m in meetings])
    out: list[dict] = []
    for m in meetings:
        mid = str(m["id"])
        if mid in have or mid in _no_speakers:
            continue
        try:
            out.append(await enqueue_meeting(repo, m))
        except Exception as e:  # noqa: BLE001 — 한 회의 실패가 나머지를 막지 않는다
            logger.warning("자동 클립: %s 큐 넣기 실패 — %s", mid, e)
    return {"enabled": True, "since": since, "candidates": len(meetings), "meetings": out}


def _notify_low_disk(repo, free: int) -> None:
    global _last_low_disk_notice
    if time.monotonic() - _last_low_disk_notice < LOW_DISK_NOTIFY_SECONDS and _last_low_disk_notice:
        return
    _last_low_disk_notice = time.monotonic()
    msg = (f"서버 디스크 여유가 {free / 1024**3:.1f}GB 로 기준({settings.clip_auto_min_free_bytes / 1024**3:.0f}GB) "
           "아래라 자동 클립을 멈췄습니다. 여유가 생기면 자동으로 이어서 자릅니다.")
    logger.warning("자동 클립: %s", msg)
    try:
        from app.services.notification_service import create_notification_record

        create_notification_record(repo.client, NOTIFICATION_TYPE, "자동 클립 일시 중지", msg)
    except Exception as e:  # noqa: BLE001
        logger.debug("자동 클립: 알림 실패(무시) — %s", e)


async def run_next(repo, service, *, disk_check: Callable[[], tuple[bool, int]] = disk_ok) -> Optional[str]:
    """가장 오래된 대기 자동 잡 1개를 끝까지 돌린다. 할 일이 없거나 멈춰야 하면 None."""
    ok, free = disk_check()
    if not ok:
        _notify_low_disk(repo, free)
        return None
    job = await asyncio.to_thread(repo.next_queued_auto)
    if not job:
        return None
    est = estimate_bytes(float(job.get("total_seconds") or 0))
    # 자리 만들기 — 자동 클립만 지운다(수동 클립은 자동 잡 때문에 지우지 않는다)
    await asyncio.to_thread(sweep_store, repo, extra_free_bytes=est, auto_extra_free_bytes=est,
                            manual_evictable=False)
    if clip_store.usage_bytes() + est > settings.clip_store_max_bytes:
        logger.info("자동 클립: 저장 상한에 수동 클립이 차 있어 기다린다 (필요 %.0fMB)", est / 1024**2)
        return None
    job_id = str(job["id"])
    await service._run(job_id)   # noqa: SLF001 — 같은 실행 경로(상태·파일·SRT)를 그대로 쓴다
    return job_id


def recover(repo) -> int:
    """작업자 기동 시: 이전 작업자가 남긴 running 자동 잡을 queued 로(두 번 넘게 걸리면 failed)."""
    n = 0
    for job in repo.list_active("auto"):
        if job.get("status") != "running":
            continue
        job_id = str(job["id"])
        if int(job.get("attempts") or 0) >= MAX_ATTEMPTS:
            repo.update(job_id, {"status": "failed", "finished_at": _now().isoformat(), "current_segment": None,
                                 "error": "작업자 재시작이 반복되어 중단했습니다."})
            clip_store.remove_job_files(job_id)
            continue
        repo.update(job_id, {"status": "queued", "progress": 0.0, "current_segment": None})
        shutil.rmtree(clip_store.work_dir(job_id), ignore_errors=True)
        n += 1
    if n:
        logger.info("자동 클립: 중단된 잡 %d건 다시 대기열로", n)
    return n


def status(repo) -> dict[str, Any]:
    """관리자 상태 — 큐·자동분 사용량·예산·디스크 여유."""
    active = repo.list_active("auto")
    done = [j for j in repo.list_evictable() if j.get("origin") == "auto"]
    free = disk_free_bytes()
    return {
        "enabled": settings.clip_auto_enabled,
        "queued": sum(1 for j in active if j.get("status") == "queued"),
        "running": sum(1 for j in active if j.get("status") == "running"),
        "done_jobs": len(done),
        "auto_used_bytes": sum(int(j.get("bytes_total") or 0) for j in done),
        "auto_max_bytes": settings.clip_auto_max_bytes,
        "store_used_bytes": clip_store.usage_bytes(),
        "store_max_bytes": settings.clip_store_max_bytes,
        "disk_free_bytes": free,
        "disk_min_free_bytes": settings.clip_auto_min_free_bytes,
        "ttl_days": settings.clip_auto_ttl_days,
        "crf": settings.clip_auto_crf,
    }


def _reset_for_tests() -> None:
    global _last_low_disk_notice
    _no_speakers.clear()
    _last_low_disk_notice = 0.0
