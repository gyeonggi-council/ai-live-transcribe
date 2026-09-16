"""자동 클립 작업자 — `python -m app.workers.auto_clip_worker` (k8s Deployment `ggc-live-transcribe-clipper`).

생중계 STT 가 도는 api 파드에서 몇 시간씩 인코딩하지 않으려고 파드를 떼어 냈다(2026-09-10). k8s 가 이 파드를
cpu 1·mem 1Gi 로 묶으므로 인코딩이 폭주하거나 메모리가 터져도 이 파드만 재시작되고 자막 서비스는 그대로다.

  기동   running 으로 남은 자동 잡 → queued (auto_clip_service.recover)
  루프   30분마다 대상 회의 스캔(scan_and_enqueue) · 매번 대기 잡 1개 실행(run_next) · 할 일 없으면 60초 쉰다
  종료   SIGTERM(배포·재시작) → 도는 잡을 queued 로 되돌리고 ffmpeg 를 죽인 뒤 끝낸다(ClipJobService._run 이 처리)
"""

from __future__ import annotations

import asyncio
import logging
import signal
import time

from app.core.config import settings
from app.core.database import get_supabase_client
from app.repositories.clip_job_repository import ClipJobRepository
from app.services import auto_clip_service
from app.services.clip_job_service import ClipJobService

logger = logging.getLogger("auto_clip_worker")

IDLE_SECONDS = 60


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def run(stop: asyncio.Event) -> None:
    def repo_factory() -> ClipJobRepository:
        return ClipJobRepository(get_supabase_client())

    service = ClipJobService()
    service.configure(repo_factory)
    await asyncio.to_thread(auto_clip_service.recover, repo_factory())
    logger.info("자동 클립 작업자 시작 (스캔 %d분 · 최근 %d일 · CRF %d · 자동분 %.1fGB · 디스크 여유 하한 %.0fGB)",
                settings.clip_auto_scan_minutes, settings.clip_auto_max_age_days, settings.clip_auto_crf,
                settings.clip_auto_max_bytes / 1024**3, settings.clip_auto_min_free_bytes / 1024**3)

    next_scan = 0.0
    while not stop.is_set():
        repo = repo_factory()
        if time.monotonic() >= next_scan:
            next_scan = time.monotonic() + max(1, settings.clip_auto_scan_minutes) * 60
            try:
                r = await auto_clip_service.scan_and_enqueue(repo)
                if r.get("meetings"):
                    logger.info("자동 클립 스캔: %s", r["meetings"])
            except Exception as e:  # noqa: BLE001
                logger.warning("자동 클립 스캔 실패(다음 주기에 재시도): %s", e)

        work = asyncio.create_task(auto_clip_service.run_next(repo, service))
        stopper = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait({work, stopper}, return_when=asyncio.FIRST_COMPLETED)
        if stopper in done and not work.done():
            service._stopping = True   # noqa: SLF001 — 도는 잡을 cancelled 가 아니라 queued 로 되돌린다
            work.cancel()
            await asyncio.gather(work, return_exceptions=True)
            break
        stopper.cancel()
        try:
            ran = work.result()
        except Exception as e:  # noqa: BLE001
            logger.warning("자동 클립 실행 오류: %s", e)
            ran = None
        if not ran:
            await _sleep_or_stop(stop, IDLE_SECONDS)
    logger.info("자동 클립 작업자 종료")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s - %(message)s")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    if not settings.clip_auto_enabled:
        logger.info("CLIP_AUTO_ENABLED=false — 자동 클립 작업자는 대기만 한다")
        await stop.wait()
        return
    await run(stop)


if __name__ == "__main__":
    asyncio.run(main())
