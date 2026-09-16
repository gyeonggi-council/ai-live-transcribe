# -*- coding: utf-8 -*-
"""클립 저장소 — 순수 파일 I/O (동기, DB 무관)

레이아웃 (k8s: PVC /app/clips, 로컬: backend/clips):
    <root>/jobs/<job_id>/<파일명>.mp4 (+ .srt)   ← 완료물, 보존 대상
    <root>/work/<job_id>/part_000.mp4 …           ← 작업 중간물, 완료·실패 즉시 삭제

job_id 와 파일명은 URL 파라미터로 들어오므로 여기서 경로 탈출을 막는다.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path

from app.core.config import settings

_BACKEND_ROOT = Path(__file__).resolve().parents[2]

SAFE_JOB_ID_RE = re.compile(r"^[0-9a-fA-F-]{8,64}$")
# 파일명: 경로 구분자·부모 참조·선행 점 금지 (한글·공백·괄호는 허용)
_BAD_NAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class UnsafePathError(ValueError):
    """job_id 또는 파일명이 저장소 밖을 가리킨다."""


def clip_root() -> Path:
    base = Path(settings.clip_store_dir)
    return base if base.is_absolute() else _BACKEND_ROOT / base


def ensure_dirs() -> None:
    """jobs/·work/ 생성 (로컬 개발용 — k8s 는 마운트가 만든다)."""
    (clip_root() / "jobs").mkdir(parents=True, exist_ok=True)
    (clip_root() / "work").mkdir(parents=True, exist_ok=True)


def _check_job_id(job_id: str) -> str:
    if not SAFE_JOB_ID_RE.fullmatch(str(job_id or "")):
        raise UnsafePathError("job_id 형식이 올바르지 않습니다.")
    return str(job_id)


def job_dir(job_id: str) -> Path:
    return clip_root() / "jobs" / _check_job_id(job_id)


def work_dir(job_id: str) -> Path:
    return clip_root() / "work" / _check_job_id(job_id)


def safe_file(job_id: str, name: str) -> Path:
    """다운로드용 파일 경로. 이름이 저장소 밖을 가리키면 UnsafePathError."""
    name = str(name or "")
    if not name or name.startswith(".") or ".." in name or _BAD_NAME_RE.search(name):
        raise UnsafePathError("파일명이 올바르지 않습니다.")
    base = job_dir(job_id)
    path = (base / name)
    try:
        path.resolve().relative_to(base.resolve())
    except ValueError as e:  # pragma: no cover - 방어적
        raise UnsafePathError("파일명이 올바르지 않습니다.") from e
    return path


def usage_bytes() -> int:
    """jobs/ 아래 전체 바이트 (완료물만 센다 — work/ 는 일시적)."""
    total = 0
    root = clip_root() / "jobs"
    if not root.exists():
        return 0
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                continue
    return total


def estimate_bytes(total_seconds: float) -> int:
    """구간 총 길이(초) → 예상 바이트. KMS mp4 ≈ 2 Mbps (실측 후 보정: settings.clip_bytes_per_second)."""
    return int(max(0.0, float(total_seconds)) * settings.clip_bytes_per_second)


def dir_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                continue
    return total


def remove_job_files(job_id: str) -> int:
    """jobs/·work/ 의 잡 디렉터리를 지우고 회수한 바이트를 돌려준다."""
    freed = 0
    for d in (job_dir(job_id), work_dir(job_id)):
        if d.exists():
            freed += dir_bytes(d)
            shutil.rmtree(d, ignore_errors=True)
    return freed


def sweep_orphan_dirs(known_job_ids: set[str], max_age_seconds: float) -> list[str]:
    """DB 가 모르는 디렉터리(재시작으로 고아가 된 것)를 정리한다.

    max_age_seconds 보다 오래된 것만 — 잡 생성 직후 DB insert 와 디렉터리 생성 사이의
    찰나에 지우는 사고를 막는다.
    """
    removed: list[str] = []
    now = time.time()
    for sub in ("jobs", "work"):
        base = clip_root() / sub
        if not base.exists():
            continue
        for entry in base.iterdir():
            try:
                if not entry.is_dir() or entry.name in known_job_ids:
                    continue
                if now - entry.stat().st_mtime < max_age_seconds:
                    continue
                shutil.rmtree(entry, ignore_errors=True)
                removed.append(f"{sub}/{entry.name}")
            except OSError:
                continue
    return removed
