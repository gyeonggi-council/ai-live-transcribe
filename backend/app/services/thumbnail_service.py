"""회의 영상 썸네일 — KMS MP4 의 한 프레임을 서버에서 뽑아 캐시한다.

왜 서버에서 뽑나 (2026-08-22 실측):
    KMS MP4 는 **fast-start 가 아니다** — `ftyp/free/mdat...moov` 순서라 moov 가
    파일 끝에 있고, 1시간짜리가 약 937MB · moov 만 3MB 다(4시간짜리는 그 몇 배).
    브라우저가 `<video preload="metadata">` 로 썸네일을 만들면 회의 한 건마다
    그 moov 를 통째로 받아야 해서, 대시보드에 3건만 띄워도 모바일에서 10MB 넘게
    받는다. 실제로 "영상이 느리다"는 신고로 이어졌다.

    반대로 ffmpeg 로 서버에서 한 번 뽑으면 **1초 · 18KB JPEG** 로 끝난다
    (ffmpeg 이 필요한 구간만 Range 로 받는다). 한 번 만들면 PVC 에 남는다.

KMS 는 브라우저 헤더(User-Agent·Referer)가 없으면 HTML 오류 페이지를 준다 —
그래서 `KMS_BROWSER_HEADERS` 를 ffmpeg 에 그대로 넘긴다.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# uploads 는 PVC 마운트라 재시작해도 남는다 (agenda_files 와 같은 관례)
THUMBNAIL_DIR = Path("uploads/thumbnails")

# 프레임 위치 — 회의 시작 직후 타이틀 화면을 피하되 너무 뒤로 가지 않는 지점
CAPTURE_SECONDS = 6
# 목록 썸네일이라 480px 면 2배 화면에서도 충분하다 (원본은 1280 이상)
THUMBNAIL_WIDTH = 480
FFMPEG_TIMEOUT_SEC = 90

# 동시 추출 상한 — 대시보드가 한 번에 여러 건을 요청해도 ffmpeg 가 몰리지 않게.
# (단일 노드 k3s 라 한 서비스가 CPU 를 다 먹으면 전체가 흔들린다)
_semaphore = asyncio.Semaphore(2)
# 회의별 락 — 같은 회의를 동시에 두 번 뽑지 않는다
_locks: dict[str, asyncio.Lock] = {}
# 실패 기억 — 실패한 회의를 매 요청마다 재시도하면 ffmpeg 폭주가 된다
_failed_until: dict[str, float] = {}
FAILURE_BACKOFF_SEC = 600


def thumbnail_path(meeting_id: str) -> Path:
    """회의 썸네일 캐시 경로. meeting_id 는 라우터에서 UUID 로 검증된 값만 온다."""
    return THUMBNAIL_DIR / f"{meeting_id}.jpg"


def _cached(meeting_id: str) -> Path | None:
    path = thumbnail_path(meeting_id)
    try:
        if path.is_file() and path.stat().st_size > 0:
            return path
    except OSError:
        pass
    return None


def _build_command(vod_url: str, out_path: Path) -> list[str]:
    from app.services.kms_vod_resolver import KMS_BROWSER_HEADERS

    headers = "".join(
        f"{k}: {v}\r\n"
        for k, v in KMS_BROWSER_HEADERS.items()
        if k.lower() != "user-agent"
    )
    return [
        "ffmpeg",
        "-nostdin",
        "-loglevel",
        "error",
        "-y",
        "-user_agent",
        KMS_BROWSER_HEADERS.get("User-Agent", "Mozilla/5.0"),
        *(["-headers", headers] if headers else []),
        # -ss 를 -i 앞에 두면 입력 단계에서 탐색한다(디코딩 없이 건너뛰어 빠르다)
        "-ss",
        str(CAPTURE_SECONDS),
        "-i",
        vod_url,
        "-frames:v",
        "1",
        "-vf",
        f"scale={THUMBNAIL_WIDTH}:-2",
        "-q:v",
        "6",
        "-f",
        "image2",
        str(out_path),
    ]


async def ensure_thumbnail(meeting_id: str, vod_url: str | None) -> Path | None:
    """캐시가 있으면 그 경로를, 없으면 뽑아서 경로를 돌려준다. 실패하면 None."""
    cached = _cached(meeting_id)
    if cached:
        return cached
    if not vod_url:
        return None

    failed_at = _failed_until.get(meeting_id)
    if failed_at and failed_at > time.monotonic():
        return None

    lock = _locks.setdefault(meeting_id, asyncio.Lock())
    async with lock:
        # 락을 기다리는 동안 다른 요청이 만들었을 수 있다
        cached = _cached(meeting_id)
        if cached:
            return cached

        async with _semaphore:
            return await _extract(meeting_id, vod_url)


async def _extract(meeting_id: str, vod_url: str) -> Path | None:
    from app.services.kms_vod_resolver import normalize_vod_download_url

    target = thumbnail_path(meeting_id)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("썸네일 디렉터리 생성 실패: %s", exc)
        return None

    # 부분 파일이 캐시로 남지 않도록 임시 파일에 쓰고 원자적으로 옮긴다
    tmp_fd, tmp_name = tempfile.mkstemp(prefix=f"thumb-{meeting_id}-", suffix=".jpg")
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)

    try:
        cmd = _build_command(normalize_vod_download_url(vod_url), tmp_path)
        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(), timeout=FFMPEG_TIMEOUT_SEC
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            logger.warning("썸네일 추출 시간 초과: meeting=%s", meeting_id)
            _failed_until[meeting_id] = time.monotonic() + FAILURE_BACKOFF_SEC
            return None

        if process.returncode != 0 or not tmp_path.is_file() or tmp_path.stat().st_size == 0:
            logger.warning(
                "썸네일 추출 실패: meeting=%s rc=%s %s",
                meeting_id,
                process.returncode,
                stderr.decode(errors="replace")[:300],
            )
            _failed_until[meeting_id] = time.monotonic() + FAILURE_BACKOFF_SEC
            return None

        shutil.move(str(tmp_path), str(target))
        logger.info(
            "썸네일 생성: meeting=%s %.1fs %dB",
            meeting_id,
            time.monotonic() - started,
            target.stat().st_size,
        )
        _failed_until.pop(meeting_id, None)
        return target
    except Exception as exc:  # noqa: BLE001 — 썸네일은 실패해도 서비스가 계속돼야 한다
        logger.warning("썸네일 추출 중 오류: meeting=%s %s", meeting_id, exc)
        _failed_until[meeting_id] = time.monotonic() + FAILURE_BACKOFF_SEC
        return None
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
