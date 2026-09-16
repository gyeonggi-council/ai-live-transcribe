"""라이브 방송 오디오 MP3 녹음 (자막 정확도 검증용).

배치 STT(live_batch_stt)가 디코딩한 PCM(24kHz mono)을 ffmpeg lame 인코더로
흘려 meeting별 mp3 파일에 이어 붙인다. OpenAI 비용 0 — 로컬 인코딩/저장만 한다
(48kbps 기준 시간당 약 21MB).

타임스탬프 정렬: 자막 start/end는 '수신된 오디오-초' 시계이고, 녹음도 수신된
오디오만 담는다. 정회로 끊겨도 양쪽 모두 그 구간을 건너뛰므로
mp3 재생 위치 ≈ 자막 start_time (같은 meeting의 첫 녹음이 0초부터 시작한 경우).

같은 meeting의 세션 재시작(정회→재개)은 같은 파일에 append 한다 —
mp3 프레임은 단순 연결로도 재생 호환된다.

동시성 안전장치 (리뷰 확정 결함 대응):
  - 채널별 asyncio.Lock으로 start/stop 직렬화 (동시 start TOCTOU → 좀비 인코더 방지)
  - 같은 meeting을 다른 채널이 이미 녹음 중이면 시작 거부 (이중 append 파일 손상 방지)
  - write 실패 시 즉시 등록 해제 + 분리된 태스크로 정리 (STT 읽기 루프 비차단)

다운로드: GET /api/meetings/{id}/recording (meetings API — 크기 스냅샷 bounded 스트리밍).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

# 인코더 종료(출력 flush) 대기 시간 (초)
_ENCODER_REAP_TIMEOUT = 10.0
# stdin 쓰기 백프레셔 타임아웃 (초) — 인코더가 멎으면 녹음만 포기하고 STT는 계속
_WRITE_TIMEOUT = 5.0

# 파일명에 쓸 meeting_id 허용 패턴 (경로 조작 방지 — UUID/채널 ID만, fullmatch로 개행 차단)
SAFE_ID_RE = re.compile(r"[A-Za-z0-9-]{1,64}")

# 상대 경로 설정은 백엔드 루트 기준으로 고정 (기동 위치에 따라 저장/조회가 갈리지 않게)
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _record_dir() -> Path:
    base = Path(settings.live_record_dir)
    return base if base.is_absolute() else _BACKEND_ROOT / base


def recording_path(meeting_id: str) -> Optional[Path]:
    """meeting의 녹음 파일 경로. 식별자가 안전하지 않으면 None."""
    if not SAFE_ID_RE.fullmatch(meeting_id or ""):
        return None
    return _record_dir() / f"{meeting_id}.mp3"


def bytes_per_second() -> int:
    """녹음 mp3의 초당 바이트 (CBR — 시간↔바이트 선형 매핑용)."""
    m = re.match(r"(\d+)", settings.live_record_bitrate or "")
    kbps = int(m.group(1)) if m else 48
    return kbps * 1000 // 8


def recording_offset(meeting_id: str) -> float:
    """녹음 시작 시점의 오디오-초 오프셋 (자막 start_time ↔ mp3 재생 위치 매핑용).

    mp3 위치 = 자막 start_time - 이 값. 녹음이 회의 처음부터면 0.
    (회의 중간에 녹음이 시작된 경우 — 예: 기능 배포 직후 — 만 0이 아니다.)
    """
    path = recording_path(meeting_id)
    if path is None:
        return 0.0
    sidecar = path.with_suffix(".offset")
    try:
        return float(sidecar.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0.0


def recording_sessions(meeting_id: str) -> list[dict]:
    """녹음 세션 인덱스 [{clock, byte}, ...] — 자막 시계 ↔ 파일 바이트 정밀 매핑.

    서버 재시작 시 오디오 시계는 DB 기준으로 '되감길' 수 있지만 파일은 계속
    append되므로 단일 오프셋으로는 위치가 틀어진다. 세션마다 (시작 시계,
    시작 바이트)를 기록해 구간별 선형 매핑을 가능하게 한다.
    파일 위치 = byte + (자막시간 - clock) × bytes_per_second.
    """
    path = recording_path(meeting_id)
    if path is None:
        return []
    out: list[dict] = []
    try:
        for line in path.with_suffix(".sessions").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                import json

                d = json.loads(line)
                out.append({"clock": float(d["clock"]), "byte": int(d["byte"])})
            except (ValueError, KeyError, TypeError):
                continue
    except OSError:
        pass
    return out


def _prune_old_recordings() -> None:
    """보존 기간이 지난 녹음 파일 삭제 (디스크 무한 증가 방지). 동기 — to_thread로 호출."""
    days = settings.live_record_retention_days
    if days <= 0:
        return
    cutoff = time.time() - days * 86400
    try:
        for f in _record_dir().glob("*.mp3"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    f.with_suffix(".offset").unlink(missing_ok=True)
                    f.with_suffix(".sessions").unlink(missing_ok=True)
                    logger.info("recorder: pruned old recording %s (>%dd)", f.name, days)
            except OSError:
                # 열려 있는(append 중) 파일 등 — 다음 기회에
                continue
    except OSError:
        pass


@dataclass
class _Recording:
    meeting_id: str
    proc: asyncio.subprocess.Process
    file: BinaryIO


class LiveAudioRecorder:
    """채널별 PCM → ffmpeg lame → meeting별 mp3 append."""

    def __init__(self) -> None:
        self._recs: dict[str, _Recording] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        # write-실패 경로의 분리 정리 태스크 (GC 방지 + stop_all에서 회수)
        self._cleanup_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]

    def _lock(self, channel_id: str) -> asyncio.Lock:
        return self._locks.setdefault(channel_id, asyncio.Lock())

    async def start(
        self, channel_id: str, meeting_id: str, start_offset_sec: float = 0.0
    ) -> None:
        """채널 녹음을 시작한다 (이미 있으면 재시작). 실패는 STT에 영향 없음.

        start_offset_sec: 이 시점의 오디오-초 시계 값. 새 파일 생성 시 사이드카에
        기록해 자막 타임스탬프 ↔ mp3 재생 위치 매핑(구간 재생)에 사용한다.
        같은 meeting 재개(append)면 기존 사이드카를 유지한다.
        """
        if not settings.live_record_enabled:
            return
        async with self._lock(channel_id):
            old = self._recs.pop(channel_id, None)
            if old is not None:
                await self._dispose(old, channel_id)

            # 같은 meeting을 다른 채널이 이미 녹음 중 → 이중 append 파일 손상 방지
            for other_ch, rec in self._recs.items():
                if rec.meeting_id == meeting_id:
                    logger.warning(
                        "recorder: meeting %s 이미 ch=%s가 녹음 중 — ch=%s 녹음 생략",
                        meeting_id, other_ch, channel_id,
                    )
                    return

            path = recording_path(meeting_id)
            if path is None:
                logger.warning("recorder: unsafe meeting id %r — 녹음 생략", meeting_id)
                return
            try:
                await asyncio.to_thread(_prune_old_recordings)
                path.parent.mkdir(parents=True, exist_ok=True)
                f = open(path, "ab")
                size_at_open = path.stat().st_size
                # 새 파일이면 오디오-초 오프셋 사이드카 기록 (단순 매핑 폴백용).
                if size_at_open == 0:
                    path.with_suffix(".offset").write_text(
                        f"{start_offset_sec:.2f}", encoding="utf-8"
                    )
                # 세션 인덱스 append — 재시작으로 시계가 되감겨도 구간별 정밀 매핑 가능
                import json as _json

                with open(path.with_suffix(".sessions"), "a", encoding="utf-8") as sf:
                    sf.write(_json.dumps(
                        {"clock": round(start_offset_sec, 2), "byte": size_at_open}
                    ) + "\n")
            except OSError as e:
                logger.warning("recorder: 파일 열기 실패 %s: %s", path, e)
                return
            try:
                proc = await asyncio.create_subprocess_exec(
                    "ffmpeg",
                    "-hide_banner", "-loglevel", "error",
                    "-f", "s16le",
                    "-ar", str(settings.openai_realtime_audio_rate),
                    "-ac", "1",
                    "-i", "pipe:0",
                    "-vn",
                    "-codec:a", "libmp3lame",
                    "-b:a", settings.live_record_bitrate,
                    "-f", "mp3",
                    "pipe:1",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=f,  # mp3 프레임을 파일에 직접 append
                    stderr=asyncio.subprocess.DEVNULL,
                )
            except (FileNotFoundError, OSError) as e:
                logger.warning("recorder: ffmpeg 인코더 시작 실패 — 녹음 비활성: %s", e)
                f.close()
                return
            self._recs[channel_id] = _Recording(meeting_id=meeting_id, proc=proc, file=f)
            logger.info(
                "recorder: started ch=%s → %s (%s)", channel_id, path, settings.live_record_bitrate
            )

    async def write(self, channel_id: str, pcm: bytes) -> None:
        """PCM 청크를 인코더에 쓴다. 어떤 실패도 STT 파이프라인을 막지 않는다."""
        rec = self._recs.get(channel_id)
        if rec is None or not pcm:
            return
        try:
            if rec.proc.returncode is not None or rec.proc.stdin is None:
                raise BrokenPipeError("encoder dead")
            rec.proc.stdin.write(pcm)
            await asyncio.wait_for(rec.proc.stdin.drain(), timeout=_WRITE_TIMEOUT)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("recorder: write 실패 ch=%s — 녹음 중단: %s", channel_id, e)
            # 즉시 등록 해제(이후 write는 no-op) + 정리는 분리 태스크 — read 루프 비차단
            dead = self._recs.pop(channel_id, None)
            if dead is not None:
                t = asyncio.create_task(self._dispose(dead, channel_id, kill_first=True))
                self._cleanup_tasks.add(t)
                t.add_done_callback(self._cleanup_tasks.discard)

    async def stop(self, channel_id: str) -> None:
        """채널 녹음을 종료한다 (인코더 출력 flush 후 파일 닫기)."""
        async with self._lock(channel_id):
            rec = self._recs.pop(channel_id, None)
            if rec is not None:
                await self._dispose(rec, channel_id)

    async def _dispose(self, rec: _Recording, channel_id: str, kill_first: bool = False) -> None:
        """인코더 종료 + 파일 닫기. rec은 이미 _recs에서 분리된 상태여야 한다."""
        try:
            if kill_first and rec.proc.returncode is None:
                # 이미 고장난 인코더 — flush 기대 없이 즉시 종료
                try:
                    rec.proc.kill()
                except ProcessLookupError:
                    pass
            if rec.proc.stdin and not rec.proc.stdin.is_closing():
                rec.proc.stdin.close()
        except Exception:
            pass
        try:
            await asyncio.wait_for(rec.proc.wait(), _ENCODER_REAP_TIMEOUT)
        except (asyncio.TimeoutError, ProcessLookupError):
            try:
                rec.proc.kill()
            except ProcessLookupError:
                pass
        try:
            rec.file.close()
        except Exception:
            pass
        logger.info("recorder: stopped ch=%s (meeting=%s)", channel_id, rec.meeting_id)

    async def stop_all(self) -> None:
        for channel_id in list(self._recs.keys()):
            await self.stop(channel_id)
        pending = [t for t in self._cleanup_tasks if not t.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def is_recording(self, channel_id: str) -> bool:
        rec = self._recs.get(channel_id)
        return rec is not None and rec.proc.returncode is None


# 싱글톤 (live_batch_stt에서 사용)
live_recorder = LiveAudioRecorder()
