# -*- coding: utf-8 -*-
"""클립 썸네일 — 잘라 둔 mp4 의 한 프레임을 뽑아 잡 디렉터리에 캐시한다 (2026-09-16).

왜 서버에서 뽑나:
    회의 썸네일(`thumbnail_service`)과 같은 이유다 — 브라우저 `<video preload="metadata">`
    로 만들게 두면 클립 한 장마다 파일을 받아야 한다. 추출 기록 한 화면에 클립이 100개씩
    깔리므로 그대로 두면 화면을 여는 것만으로 수백 MB 다.

회의 썸네일과 다른 점:
    **원본이 로컬 PVC 파일**이다. KMS 브라우저 헤더도, 네트워크 대기도 없다 —
    한 장에 수십 ms 로 끝난다. 그래서 세마포어 값이 넉넉하고 타임아웃도 짧다.

저장 위치는 `clip_store.thumb_path()` = `jobs/<job_id>/.thumb_NNN.jpg`.
잡이 지워지면(TTL·용량·수동) 디렉터리째 사라지므로 **정리 코드가 따로 없다.**
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

from app.core.proc_priority import LOW_PRIORITY
from app.services import clip_store

logger = logging.getLogger(__name__)

# 캡처 지점 — 클립 앞에 여유 1초가 붙어 있어(pad_before) 3초면 발언자 화면이다.
# 짧은 구간은 절반 지점.
CAPTURE_SECONDS = 3.0
# 카드 격자용이라 320px 면 2배 화면에서도 충분하다 (원본 720p)
THUMBNAIL_WIDTH = 320
FFMPEG_TIMEOUT_SEC = 20

# 생중계 STT 와 같은 파드(CPU 2코어)라 동시 추출을 묶는다.
# 로컬 파일이라 한 장이 수십 ms 이므로 2개면 한 화면(수십 장)이 1초 안에 찬다.
_semaphore = asyncio.Semaphore(2)
# 같은 썸네일을 동시에 두 번 뽑지 않는다 (목록이 같은 카드를 두 번 그리는 순간)
_locks: dict[str, asyncio.Lock] = {}
# 실패 기억 — 못 뽑는 파일을 매 요청마다 재시도하면 ffmpeg 폭주가 된다
_failed_until: dict[str, float] = {}
FAILURE_BACKOFF_SEC = 600


def _key(job_id: str, index: int) -> str:
    return f"{job_id}:{index}"


def _cached(path: Path) -> Path | None:
    try:
        if path.is_file() and path.stat().st_size > 0:
            return path
    except OSError:
        pass
    return None


def _build_command(mp4_path: Path, at_seconds: float, out_path: Path) -> list[str]:
    """프레임 1장 추출. `-ss` 는 `-i` 앞 — 디코딩 없이 건너뛴다."""
    return [
        *LOW_PRIORITY,
        "ffmpeg",
        "-nostdin",
        "-loglevel", "error",
        "-y",
        "-ss", f"{max(0.0, at_seconds):.3f}",
        "-i", str(mp4_path),
        "-frames:v", "1",
        "-vf", f"scale={THUMBNAIL_WIDTH}:-2",
        "-q:v", "6",
        "-f", "image2",
        str(out_path),
    ]


async def ensure_clip_thumbnail(
    job_id: str, index: int, mp4_path: Path, duration_seconds: float | None = None
) -> Path | None:
    """캐시가 있으면 그 경로를, 없으면 뽑아서 경로를 돌려준다. 실패하면 None."""
    try:
        target = clip_store.thumb_path(job_id, index)
    except clip_store.UnsafePathError:
        return None

    cached = _cached(target)
    if cached:
        return cached
    if not mp4_path.is_file():
        return None

    key = _key(job_id, index)
    failed_at = _failed_until.get(key)
    if failed_at and failed_at > time.monotonic():
        return None

    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        # 락을 기다리는 동안 다른 요청이 만들었을 수 있다
        cached = _cached(target)
        if cached:
            return cached
        async with _semaphore:
            return await _extract(key, target, mp4_path, duration_seconds)


async def _extract(
    key: str, target: Path, mp4_path: Path, duration_seconds: float | None
) -> Path | None:
    at = CAPTURE_SECONDS
    if duration_seconds and duration_seconds > 0:
        at = min(CAPTURE_SECONDS, duration_seconds / 2)

    # 임시 파일을 **같은 디렉터리**에 만든다 — 같은 파일시스템이라 os.replace 가 원자적이고,
    # 파드 루트가 읽기전용(readOnlyRootFilesystem)이라 PVC 밖에는 쓸 수 없다.
    tmp_path = target.with_suffix(".jpg.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("클립 썸네일 디렉터리 생성 실패: %s", exc)
        return None

    try:
        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *_build_command(mp4_path, at, tmp_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=FFMPEG_TIMEOUT_SEC
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            logger.warning("클립 썸네일 시간 초과: %s", key)
            _failed_until[key] = time.monotonic() + FAILURE_BACKOFF_SEC
            return None

        if proc.returncode != 0 or not _cached(tmp_path):
            logger.warning(
                "클립 썸네일 실패: %s rc=%s %s",
                key,
                proc.returncode,
                (stderr or b"").decode(errors="replace")[:300],
            )
            _failed_until[key] = time.monotonic() + FAILURE_BACKOFF_SEC
            return None

        os.replace(str(tmp_path), str(target))
        logger.info(
            "클립 썸네일 생성: %s %.2fs %dB", key, time.monotonic() - started,
            target.stat().st_size,
        )
        _failed_until.pop(key, None)
        return target
    except Exception as exc:  # noqa: BLE001 — 썸네일은 실패해도 화면이 자리표시로 계속된다
        logger.warning("클립 썸네일 중 오류: %s %s", key, exc)
        _failed_until[key] = time.monotonic() + FAILURE_BACKOFF_SEC
        return None
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
