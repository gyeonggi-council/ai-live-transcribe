"""영상추출기(exe) 배포/자동업데이트 채널 서비스

version.json 매니페스트와 설치파일을 backend/data/tools/extractor 에 보관한다.
exe 클라이언트는 GET /api/tools/extractor/version.json 을 폴링하여
새 버전이면 url 에서 설치파일을 내려받아 자동업데이트한다 (brew 식).

- 매니페스트 쓰기는 tmp 파일 + os.replace 로 원자적 (다운로드 중 절단 방지)
- 설치파일은 1MB 청크 스트리밍 저장 (76MB+ 파일 전체 read() 금지)
- 새 버전 저장 시 직전 1개만 보관하고 더 오래된 설치파일은 삭제
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import BinaryIO, Optional, Tuple

# 상대 경로는 백엔드 루트 기준으로 고정 (기동 위치에 따라 저장/조회가 갈리지 않게
# — live_recorder 패턴)
_BACKEND_ROOT = Path(__file__).resolve().parents[2]

# 배포 산출물 보관 디렉토리 (테스트에서 monkeypatch 가능하도록 모듈 전역)
RELEASE_DIR: Path = _BACKEND_ROOT / "data" / "tools" / "extractor"

# 매니페스트 파일명
MANIFEST_NAME = "manifest.json"

# 다운로드 엔드포인트 경로 (version.json url 필드용)
DOWNLOAD_PATH = "/api/tools/extractor/download"

# 설치파일 최대 크기 (200MB)
MAX_INSTALLER_SIZE = 200 * 1024 * 1024

# 스트리밍 청크 크기 (1MB)
_CHUNK_SIZE = 1024 * 1024

# 보관할 설치파일 개수 (현재 + 직전 1개)
_KEEP_INSTALLERS = 2


class InstallerTooLargeError(Exception):
    """설치파일이 최대 허용 크기(200MB)를 초과했을 때."""


def _release_dir() -> Path:
    """배포 디렉토리 절대경로 (RELEASE_DIR가 상대면 백엔드 루트 기준)."""
    base = Path(RELEASE_DIR)
    return base if base.is_absolute() else _BACKEND_ROOT / base


def resolve_release_path(name: str) -> Path:
    """배포 디렉토리 내부 경로만 허용합니다 (path traversal 방지 — agenda_files 가드 패턴).

    Raises:
        ValueError: 경로가 배포 디렉토리를 벗어나는 경우
    """
    base = _release_dir().resolve()
    candidate = (base / name).resolve()
    if candidate != base and not str(candidate).startswith(str(base) + os.sep):
        raise ValueError("잘못된 파일 경로입니다.")
    return candidate


def installer_filename(version: str) -> str:
    """버전별 설치파일 표준 파일명."""
    return f"ggc-extractor-setup-{version}.exe"


def load_manifest() -> Optional[dict]:
    """배포 매니페스트를 읽습니다. 없거나 손상되었으면 None."""
    path = _release_dir() / MANIFEST_NAME
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def save_manifest(manifest: dict) -> None:
    """배포 매니페스트를 원자적으로 저장합니다 (tmp 파일 + os.replace)."""
    directory = _release_dir()
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(directory), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, directory / MANIFEST_NAME)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def store_installer(fileobj: BinaryIO, version: str) -> Tuple[Path, str, int]:
    """설치파일을 1MB 청크 스트리밍으로 저장합니다 (전체 read() 금지 — 76MB+).

    Returns:
        (저장 경로, sha256 hex, 바이트 크기)

    Raises:
        InstallerTooLargeError: 200MB 초과
        ValueError: version에서 유도한 경로가 배포 디렉토리를 벗어나는 경우
    """
    directory = _release_dir()
    directory.mkdir(parents=True, exist_ok=True)
    dest = resolve_release_path(installer_filename(version))

    hasher = hashlib.sha256()
    size = 0
    fd, tmp_name = tempfile.mkstemp(dir=str(directory), suffix=".part")
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = fileobj.read(_CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_INSTALLER_SIZE:
                    raise InstallerTooLargeError(
                        f"설치파일이 {MAX_INSTALLER_SIZE // (1024 * 1024)}MB를 초과합니다."
                    )
                hasher.update(chunk)
                out.write(chunk)
        os.replace(tmp_name, dest)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

    _prune_old_installers(current=dest)
    return dest, hasher.hexdigest(), size


def _prune_old_installers(current: Path) -> None:
    """현재 + 직전 1개만 남기고 더 오래된 설치파일을 삭제합니다."""
    installers = [p for p in _release_dir().glob("*.exe") if p != current]
    installers.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for old in installers[_KEEP_INSTALLERS - 1:]:
        try:
            old.unlink()
        except OSError:
            pass


def build_download_url(request, settings) -> str:
    """다운로드 절대 URL을 만듭니다.

    settings.public_base_url이 있으면 그것을, 없으면 요청의 base_url에서 유도.
    """
    base = (settings.public_base_url or "").strip().rstrip("/")
    if not base:
        base = str(request.base_url).rstrip("/")
    return f"{base}{DOWNLOAD_PATH}"
