"""kordoc(npm) 기반 hwpx 변환 서비스.

kordoc(MIT, 버전 3.13.0 고정)의 CLI를 npx로 실행해
- 마크다운 → 공문서 서식 hwpx 생성 (generate + --preset 회의록)
- hwpx → 마크다운 추출 (향후 외부 hwpx 뷰어/편집용)
을 수행한다.

설계 원칙:
- 명령은 항상 리스트로 실행(shell 미사용) — 인젝션 여지 차단.
- Windows에서 npx는 npx.cmd일 수 있으므로 shutil.which("npx") 결과(전체 경로)를 사용.
- npx 존재 여부는 프로세스 생애 동안 캐시(is_available).
- 실패 시 stderr를 포함한 RuntimeError, 타임아웃 120초, 임시파일은 finally 정리.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import tempfile

#: kordoc npm 패키지 버전 — 검증된 버전으로 고정한다.
KORDOC_VERSION = "3.13.0"

#: 기본 subprocess 타임아웃(초)
_DEFAULT_TIMEOUT = 120.0

#: kordoc 서브프로세스 동시 실행 상한 — 노트북 백엔드(단일 머신) 보호.
#  node 프로세스가 요청 수만큼 폭주해 CPU/메모리를 고갈시키지 않도록
#  markdown_to_hwpx/hwpx_to_markdown이 공유하는 전역 세마포어로 제한한다.
_KORDOC_MAX_CONCURRENT = 2
_KORDOC_SEMAPHORE = asyncio.Semaphore(_KORDOC_MAX_CONCURRENT)

#: npx 경로 캐시 sentinel — _UNSET이면 아직 조회 전.
_UNSET = object()
_NPX_PATH_CACHE: object = _UNSET


def _npx_path() -> str | None:
    """npx 실행 파일 경로를 반환한다(캐시).

    Windows에서는 npx.cmd일 수 있으므로 shutil.which 결과(전체 경로)를 그대로 쓴다.
    미설치 환경이면 None (None 결과도 캐시됨).
    """
    global _NPX_PATH_CACHE
    if _NPX_PATH_CACHE is _UNSET:
        _NPX_PATH_CACHE = shutil.which("npx")
    return _NPX_PATH_CACHE  # type: ignore[return-value]


def is_available() -> bool:
    """kordoc 실행 가능 여부(npx 존재)를 반환한다. 결과는 캐시된다."""
    return _npx_path() is not None


def _base_command() -> list[str]:
    """kordoc 명령 프리픽스 [npx, -y, kordoc@<버전>]을 조립한다.

    npx가 없으면 RuntimeError.
    """
    npx = _npx_path()
    if npx is None:
        raise RuntimeError(
            "npx를 찾을 수 없습니다 — kordoc 실행에는 Node.js(npm)가 필요합니다."
        )
    return [npx, "-y", f"kordoc@{KORDOC_VERSION}"]


async def _run(cmd: list[str], timeout: float = _DEFAULT_TIMEOUT) -> bytes:
    """명령을 서브프로세스로 실행하고 stdout을 반환한다.

    - shell을 사용하지 않고 리스트 그대로 exec한다.
    - 타임아웃 초과 시 프로세스를 강제 종료하고 RuntimeError.
    - 비정상 종료(returncode != 0) 시 stderr 내용을 포함한 RuntimeError.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:  # 실행 파일 없음/권한 문제 등
        raise RuntimeError(f"kordoc 실행 시작 실패: {exc}") from exc

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        with contextlib.suppress(Exception):
            await proc.wait()
        raise RuntimeError(f"kordoc 실행 시간 초과({timeout:.0f}초)")

    if proc.returncode != 0:
        err = (stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(f"kordoc 실행 실패(exit {proc.returncode}): {err}")
    return stdout or b""


async def markdown_to_hwpx(markdown: str, preset: str = "회의록") -> bytes:
    """마크다운을 kordoc으로 변환해 hwpx 바이트를 반환한다.

    명령: npx -y kordoc@3.13.0 generate <md파일> -o <hwpx파일> --preset <preset>
    (검증됨: 회의록 preset으로 정식 공문서 서식 hwpx 생성)

    실패(비정상 종료/빈 출력) 시 RuntimeError. 임시파일은 finally에서 정리한다.
    동시 실행은 _KORDOC_SEMAPHORE로 제한된다(노트북 백엔드 보호).
    """
    base = _base_command()
    async with _KORDOC_SEMAPHORE:
        tmpdir = tempfile.mkdtemp(prefix="kordoc_")
        md_path = os.path.join(tmpdir, "input.md")
        hwpx_path = os.path.join(tmpdir, "output.hwpx")
        try:
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(markdown)

            cmd = base + ["generate", md_path, "-o", hwpx_path, "--preset", preset]
            await _run(cmd, timeout=_DEFAULT_TIMEOUT)

            data = b""
            if os.path.exists(hwpx_path):
                with open(hwpx_path, "rb") as f:
                    data = f.read()
            if not data:
                raise RuntimeError(
                    "kordoc이 hwpx 출력 파일을 생성하지 못했습니다(빈 출력)."
                )
            return data
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


async def hwpx_to_markdown(data: bytes) -> str:
    """hwpx 바이트를 kordoc으로 파싱해 마크다운 문자열을 반환한다.

    명령: npx -y kordoc@3.13.0 <hwpx파일> -o <md파일>
    (검증됨: 자체 생성 hwpx를 완벽 추출 — 향후 외부 hwpx 뷰어/편집용)

    실패(비정상 종료/출력 없음) 시 RuntimeError. 임시파일은 finally에서 정리한다.
    동시 실행은 _KORDOC_SEMAPHORE로 제한된다(노트북 백엔드 보호).
    """
    base = _base_command()
    async with _KORDOC_SEMAPHORE:
        tmpdir = tempfile.mkdtemp(prefix="kordoc_")
        hwpx_path = os.path.join(tmpdir, "input.hwpx")
        md_path = os.path.join(tmpdir, "output.md")
        try:
            with open(hwpx_path, "wb") as f:
                f.write(data)

            cmd = base + [hwpx_path, "-o", md_path]
            await _run(cmd, timeout=_DEFAULT_TIMEOUT)

            if not os.path.exists(md_path):
                raise RuntimeError("kordoc이 마크다운 출력 파일을 생성하지 못했습니다.")
            with open(md_path, "r", encoding="utf-8") as f:
                return f.read()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
