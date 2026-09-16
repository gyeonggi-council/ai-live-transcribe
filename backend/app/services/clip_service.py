"""발언영상 클립 추출 서비스 — ffmpeg URL-seek 기반

# @TASK B2-clip - GET /speakers/clip 재작성용 추출 엔진

기존 구현은 전체 VOD(수 GB)를 임시파일로 선다운로드해 실사용 불가였다
(KMS는 연결당 ~0.3MB/s 스로틀 → 1.6GB VOD가 수십 분).
ffmpeg 입력 시킹(``-ss`` 를 ``-i`` 보다 앞에)은 HTTP Range로 필요한
바이트만 받아오므로 추출 시간이 대략 구간 길이에 비례한다.

- ``-ss`` 가 ``-i`` 뒤로 가면 출력 시킹(디코딩하며 전체 스트림 소비)이 되어
  전체 다운로드로 회귀한다. 인자 순서가 이 모듈의 존재 이유 — 테스트로 고정.
- KMS는 Referer/User-Agent 없으면 HTML 에러 페이지를 반환하므로
  ``-headers`` 로 주입한다 (parallel_download._DEFAULT_HEADERS 와 동일 값).
"""

import asyncio
import logging
import re
from pathlib import Path

from app.core.proc_priority import LOW_PRIORITY
from app.services.kms_vod_resolver import normalize_vod_download_url

logger = logging.getLogger(__name__)

# KMS 요청 헤더 (parallel_download._DEFAULT_HEADERS 참고) — ffmpeg -headers 는
# CRLF 로 구분된 단일 문자열을 받는다.
_FFMPEG_HTTP_HEADERS = (
    "User-Agent: Mozilla/5.0\r\n"
    "Referer: https://kms.ggc.go.kr/\r\n"
)


class ClipExtractError(RuntimeError):
    """ffmpeg 클립 추출 실패 (stderr 요약 포함)."""


def format_hms_compact(seconds: float) -> str:
    """초를 압축 표기로 변환합니다. 예: 1350 → "22m30s", 3723 → "1h02m03s".

    - 시간이 0이면 "h" 부분 생략
    - 초는 항상 2자리 패딩, 분은 시간이 있을 때만 2자리 패딩
    """
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    return f"{minutes}m{secs:02d}s"


def build_clip_filename(
    kms_midx: str | int | None,
    meeting_id: str,
    start: float,
    end: float,
    *,
    suffix: str = "",
) -> str:
    """클립 다운로드 파일명 규약: ggc_{kms_midx}_{start}-{end}{suffix}.mp4

    kms_midx 가 없으면 meeting_id 앞 8자를 사용합니다.
    suffix 는 출처 구분 표기(예: "_AI잠정") — 확장자 앞에 붙는다.
    """
    ident = str(kms_midx) if kms_midx else str(meeting_id)[:8]
    return f"ggc_{ident}_{format_hms_compact(start)}-{format_hms_compact(end)}{suffix}.mp4"


# ─── 워크벤치 파일명 규약 — 설치형 추출기(ggc_core.build_out_name)와 같은 값 ────────
# {라벨}_{회의명}_{번호}.mp4 · 합치기면 {라벨}_{회의명}_합본.mp4 (2026-09-10 담당자 요청, 설치형 v1.13)
_FILENAME_BAD_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_BRACKET_RE = re.compile(r"\[[^\]]*\]")


def sanitize_filename(name: str | None, max_len: int = 150) -> str:
    """파일명에 못 쓰는 문자를 공백으로, 연속 공백은 하나로."""
    cleaned = _FILENAME_BAD_RE.sub(" ", str(name or ""))
    return re.sub(r"\s+", " ", cleaned).strip()[:max_len]


def clean_title(title: str | None) -> str:
    """'제391회 [정례회] 제1차 OO위원회 [2026.06.10]' → '제391회 제1차 OO위원회'"""
    return re.sub(r"\s+", " ", _BRACKET_RE.sub(" ", str(title or ""))).strip()


def build_job_filename(
    label: str | None,
    meeting_title: str | None,
    number: int | None = None,
    *,
    merged: bool = False,
) -> str:
    """워크벤치 클립 파일명 — 담당자 요청(2026-09-10):

        {라벨}_{회의명}_{번호}.mp4     구간별 저장
        {라벨}_{회의명}_합본.mp4       하나로 합치기

    번호는 **그 의원 구간 목록의 순번**(1부터, 화면 목록 왼쪽 숫자)이지 고른 순서가 아니다 —
    3번 구간만 잘라도 `_3` 이라 파일과 목록 줄이 짝지어진다. 2026-09-08 규약에 있던 날짜·시작 시각·
    `_AI잠정` 은 뺐다. ★설치형 `ggc_core.build_out_name` 과 같은 값이다 — 담당자가 두 경로로 받은
    파일을 한 폴더에 모으므로 한쪽만 고치지 말 것.
    """
    head = f"{sanitize_filename(label) or '클립'}_{sanitize_filename(clean_title(meeting_title)) or '회의'}"
    return f"{head}_합본.mp4" if merged else f"{head}_{int(number or 1)}.mp4"


# 공유용 압축(자동 클립) — 유튜브·휴대폰으로 보낸다(2026-09-10 사용자 요청 "용량을 좀 줄이거나").
# KMS 원본은 720p H.264 Constrained Baseline 2.26Mbps 로 비효율적이라, 같은 720p 에서 CRF28 veryfast 로
# 원본의 17%(2분 33.9MB → 5.9MB), 1스레드로 실시간의 5.4배 속도였다(오르카서버 = poc-app 과 같은 EPYC 9454P).
# 화질은 캡처 비교로 얼굴·명패 글씨가 거의 같다. 1080p 원본이 오면 720p 로 내린다. 1스레드 = 1코어 안에서만 돈다.
def _compress_args(crf: int) -> list[str]:
    return [
        "-vf", "scale=-2:'min(720,ih)'",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(int(crf)),
        "-profile:v", "high", "-pix_fmt", "yuv420p", "-threads", "1",
        "-c:a", "aac", "-b:a", "64k", "-ac", "1",
    ]


def build_extract_cmd(
    vod_url: str,
    start: float,
    end: float,
    out_path: str | Path,
    *,
    compress: bool = False,
    crf: int = 28,
) -> list[str]:
    """구간 추출 ffmpeg 인자 리스트를 조립합니다 (shell 미사용).

    ★인자 순서가 핵심: ``-ss`` 가 ``-i`` 보다 앞(입력 시킹 = 필요 바이트만
    전송). 뒤로 가면 전체 스트림을 소비하는 출력 시킹으로 회귀한다.
    compress 면 `-c copy` 대신 720p 재인코딩 — 재인코딩이라 시작이 키프레임이 아니라 프레임 단위로 정확하다.
    """
    url = normalize_vod_download_url(vod_url)
    duration = end - start
    return [
        "ffmpeg", "-y",
        "-headers", _FFMPEG_HTTP_HEADERS,
        *(["-threads", "1"] if compress else []),   # 디코더도 1스레드
        "-ss", str(start),
        "-i", url,
        "-t", str(duration),
        *(_compress_args(crf) if compress else ["-c", "copy"]),
        "-movflags", "+faststart",
        str(out_path),
    ]


async def _run_ffmpeg(cmd: list[str], timeout: float) -> None:
    """ffmpeg 를 저우선순위 서브프로세스로 실행하고 실패 시 stderr 포함 예외를 던집니다.

    클립 추출은 생중계 STT 와 같은 파드에서 돈다. `-c copy` 라 CPU 는 거의 안 쓰지만 경합이 생기면
    STT ffmpeg 가 먼저다 (2026-09-08, `app.core.proc_priority`).
    """
    proc = await asyncio.create_subprocess_exec(
        *LOW_PRIORITY, *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.CancelledError:
        # 요청 취소(클라이언트 브라우저 중단)/서버 종료 — ffmpeg 를 kill 하지 않으면
        # KMS 대역폭을 계속 소모하는 고아 프로세스로 남는다. kill 후 취소 전파.
        proc.kill()
        raise
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise ClipExtractError(f"ffmpeg 실행 시간 초과 ({timeout:.0f}초)")

    if proc.returncode != 0:
        tail = (stderr or b"").decode(errors="replace")[-2000:]
        raise ClipExtractError(
            f"ffmpeg 실패 (exit {proc.returncode}): {tail}"
        )


async def extract_clip_mp4(
    vod_url: str,
    start: float,
    end: float,
    out_path: str | Path,
    *,
    compress: bool = False,
    crf: int = 28,
) -> None:
    """VOD URL에서 start~end 구간을 mp4로 추출합니다 (기본은 재인코딩 없이 copy, compress 면 720p 압축).

    KMS 연결당 스로틀(~0.3MB/s) 하에서 추출 시간 ≈ 구간 길이이므로,
    타임아웃은 구간 길이의 3배 + 여유 120초로 잡는다. 압축은 실시간의 5.4배라 이 안에 여유 있게 든다.
    """
    duration = end - start
    cmd = build_extract_cmd(vod_url, start, end, out_path, compress=compress, crf=crf)
    logger.info("클립 추출 시작%s: %.1f~%.1f초 (%s)", " (압축)" if compress else "", start, end, out_path)
    try:
        await _run_ffmpeg(cmd, timeout=duration * 3 + 120)
    except asyncio.CancelledError:
        # 취소 시 부분 산출물 정리 후 전파 (_run_ffmpeg 가 ffmpeg kill 은 수행)
        Path(out_path).unlink(missing_ok=True)
        raise

    out = Path(out_path)
    if not out.exists() or out.stat().st_size == 0:
        raise ClipExtractError("클립 파일이 생성되지 않았습니다.")


def _escape_concat_path(path: str) -> str:
    """concat demuxer 리스트 파일(file 'path')용 작은따옴표 이스케이프."""
    return path.replace("'", "'\\''")


async def concat_clips_mp4(
    parts: list[str | Path],
    out_path: str | Path,
) -> None:
    """여러 mp4 조각을 concat demuxer 로 재인코딩 없이 병합합니다."""
    if not parts:
        raise ClipExtractError("병합할 클립이 없습니다.")

    out = Path(out_path)
    list_path = out.with_name(out.name + ".concat.txt")
    lines = [
        f"file '{_escape_concat_path(Path(p).as_posix())}'" for p in parts
    ]
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_path),
        "-c", "copy",
        str(out),
    ]
    try:
        # 로컬 파일 remux 는 빠르다 — 조각 수에 비례한 여유만 둔다.
        await _run_ffmpeg(cmd, timeout=60 * len(parts) + 120)
    finally:
        list_path.unlink(missing_ok=True)

    if not out.exists() or out.stat().st_size == 0:
        raise ClipExtractError("병합 클립 파일이 생성되지 않았습니다.")
