"""실시간 화자 구분 서비스 (OpenAI gpt-4o-transcribe-diarize 배치, 경로 B).

경로 A(openai_realtime_stt)가 디코딩한 24kHz mono PCM16을 그대로 받아 채널별로
롤링 버퍼에 누적하고, 일정 길이마다 WAV로 감싸 diarize 배치 API를 호출한다.
응답의 segments[].speaker(대문자 A/B/…)를 시간 겹침으로 경로 A 자막에 매칭해
화자 라벨("화자 N")을 부여하고 subtitle_corrected 이벤트로 브로드캐스트한다.

핵심 설계:
  - 경로 A의 PCM을 재사용 → ffmpeg 중복 없음, 두 경로가 동일한 오디오-초 시계 공유.
  - diarize 입력은 PCM에 WAV 헤더만 붙임(두 번째 ffmpeg 불필요).
  - 텍스트는 건드리지 않고 speaker만 갱신(3초 commit 분절 ≠ 화자 턴 분절이라 텍스트 덮으면 중복).
  - 실패해도 경로 A 자막은 그대로 유지(무해).
  - in-flight diarize 태스크를 채널별로 추적 → stop()/drop_channel에서 취소·회수(좀비/stale-write 방지).

알려진 한계 (★Phase 후속에서 해결 예정):
  - speaker 라벨("A"/"B")은 배치(호출) 내부에서만 일관된 익명 라벨이라, 12초 배치 경계를 넘으면
    동일 인물의 화자 번호가 바뀔 수 있다. 채널 전역 화자 동일성은 known_speaker_references
    (의원 목소리 샘플 등록)로만 안정화 가능 — 사용자 요청대로 "실명 식별"은 후속 단계.

검증된 계약 (정식 문서 + openai 2.26 SDK 소스):
  POST /v1/audio/transcriptions, model=gpt-4o-transcribe-diarize,
  response_format="diarized_json", chunking_strategy="auto", language="ko"
  → resp.segments[].{speaker:str("A".."Z"), start:float, end:float, text:str, id:str}
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
import wave
from dataclasses import dataclass, field
from typing import Any, Optional

from openai import AsyncOpenAI

from app.api.websocket import manager
from app.core.config import settings
from app.core.database import get_supabase_client
from app.services.speaker_cue_tracker import speaker_cue_tracker
from app.services.voiceprint_service import voiceprint_service

logger = logging.getLogger(__name__)

# diarize 호출 최소 오디오 길이(초)
_MIN_FLUSH_SECONDS = 2.0
# diarize API 타임아웃(초)
_DIARIZE_API_TIMEOUT = 90.0
# 25MB 한도(가장 보수적). 24kHz mono 16-bit 기준 약 9분. inflight가 길어질 때 버퍼 상한.
_MAX_BYTES = 24 * 1024 * 1024


@dataclass
class _ChannelBuffer:
    """채널 단위 PCM 누적 버퍼."""

    channel_id: str
    meeting_id: str
    # 버퍼 첫 PCM 청크의 오디오-초 오프셋(경로 A와 공유하는 시계 기준)
    chunk_start_offset: float
    data: bytearray = field(default_factory=bytearray)
    last_ingest_monotonic: float = field(default_factory=time.monotonic)


def _pcm_to_wav(pcm: bytes, rate: int) -> bytes:
    """raw PCM16 mono를 WAV 컨테이너로 감싼다 (ffmpeg 불필요)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def _attr(obj: Any, key: str, default: Any = None) -> Any:
    """SDK 모델(속성) / dict(키) 양쪽에서 안전하게 값을 읽는다."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _speaker_label(raw: Any) -> Optional[str]:
    """diarize speaker("A","B",…) → "화자 N". known_speaker 이름이면 그대로 사용."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if len(s) == 1 and "A" <= s.upper() <= "Z":
        return f"화자 {ord(s.upper()) - ord('A') + 1}"
    return s


class DiarizeService:
    """채널별 PCM 롤링 버퍼 → diarize 배치 → 자막 speaker 부여."""

    def __init__(self) -> None:
        self._client: Optional[AsyncOpenAI] = None
        self._enabled = False
        self._buffers: dict[str, _ChannelBuffer] = {}
        self._sweeper: Optional[asyncio.Task] = None  # type: ignore[type-arg]
        # 채널별 diarize 동시성 1건 제한 플래그
        self._inflight: set[str] = set()
        # 채널별 in-flight 태스크 추적 (취소/회수용)
        self._tasks: dict[str, set[asyncio.Task]] = {}  # type: ignore[type-arg]
        # councilor_id → (이름, data URL) 캐시 (불변 — 한 번 로드). 동적 known-set 조립용.
        self._vp_cache: dict[str, tuple[str, str]] = {}
        # cue tracker가 비활성/위원장 미지정일 때의 정적 폴백 캐시 (채널별)
        self._static_known: dict[str, list[tuple[str, str]]] = {}

    # ─── lifespan ────────────────────────────────────────────────────

    async def start(self) -> None:
        if not settings.diarize_enabled:
            logger.info("DiarizeService disabled via settings")
            return
        if not settings.openai_api_key:
            logger.warning("DiarizeService: OPENAI_API_KEY 없음 — 비활성")
            return
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._enabled = True
        self._sweeper = asyncio.create_task(self._sweep_loop(), name="diarize-sweeper")
        logger.info(
            "DiarizeService started (model=%s, buffer=%.1fs)",
            settings.diarize_model, settings.diarize_buffer_seconds,
        )

    async def stop(self) -> None:
        if self._sweeper and not self._sweeper.done():
            self._sweeper.cancel()
            try:
                await self._sweeper
            except asyncio.CancelledError:
                pass
        self._sweeper = None
        # 진행 중 diarize 태스크 전부 취소·회수
        all_tasks = [t for tasks in self._tasks.values() for t in tasks if not t.done()]
        for t in all_tasks:
            t.cancel()
        if all_tasks:
            await asyncio.gather(*all_tasks, return_exceptions=True)
        self._tasks.clear()
        self._buffers.clear()
        self._inflight.clear()
        self._vp_cache.clear()
        self._static_known.clear()
        self._enabled = False
        logger.info("DiarizeService stopped")

    # ─── 입력 (경로 A의 PCM 펌프에서 호출) ──────────────────────────────

    def ingest_pcm(
        self, channel_id: str, meeting_id: str, pcm: bytes, offset_sec: float
    ) -> None:
        """경로 A에서 디코딩된 PCM 청크를 누적한다. 버퍼가 차면 flush를 트리거."""
        if not self._enabled or not pcm:
            return
        buf = self._buffers.get(channel_id)
        if buf is None:
            buf = _ChannelBuffer(
                channel_id=channel_id, meeting_id=meeting_id, chunk_start_offset=offset_sec
            )
            self._buffers[channel_id] = buf
        buf.data.extend(pcm)
        buf.last_ingest_monotonic = time.monotonic()

        rate = settings.openai_realtime_audio_rate
        # inflight가 비정상적으로 길어질 때 무한 누적 방지 — 앞에서 잘라내고 오프셋 보정
        if len(buf.data) > _MAX_BYTES:
            drop = len(buf.data) - _MAX_BYTES
            del buf.data[:drop]
            buf.chunk_start_offset += drop / (rate * 2)

        buffered_sec = len(buf.data) / (rate * 2)
        if buffered_sec >= settings.diarize_buffer_seconds:
            self._flush(channel_id)

    async def drop_channel(self, channel_id: str) -> None:
        """채널 STT 종료 시 진행 태스크 취소 + 버퍼 정리 (stale-write 방지)."""
        tasks = self._tasks.pop(channel_id, set())
        live = [t for t in tasks if not t.done()]
        for t in live:
            t.cancel()
        if live:
            await asyncio.gather(*live, return_exceptions=True)
        self._buffers.pop(channel_id, None)
        self._inflight.discard(channel_id)
        self._static_known.pop(channel_id, None)

    # ─── flush ───────────────────────────────────────────────────────

    def _flush(self, channel_id: str) -> None:
        # peek(get) — 실제 처리가 확정될 때만 pop하여 inflight/길이부족 시 버퍼 보존(데이터 유실 방지)
        buf = self._buffers.get(channel_id)
        if buf is None:
            return
        rate = settings.openai_realtime_audio_rate
        if len(buf.data) < int(rate * 2 * _MIN_FLUSH_SECONDS):
            return  # 버퍼 유지 → 다음 ingest에서 누적
        if channel_id in self._inflight:
            return  # 버퍼 유지 → 직전 호출 종료 후 다음 flush에서 처리
        self._buffers.pop(channel_id, None)  # 처리 확정 시에만 분리
        self._inflight.add(channel_id)
        t = asyncio.create_task(self._transcribe_and_apply(buf))
        self._tasks.setdefault(channel_id, set()).add(t)
        t.add_done_callback(lambda fut, c=channel_id: self._tasks.get(c, set()).discard(fut))

    async def _sweep_loop(self) -> None:
        """오디오가 멈춰 부분 버퍼가 남으면 주기적으로 flush한다."""
        try:
            while True:
                await asyncio.sleep(settings.diarize_buffer_seconds)
                now = time.monotonic()
                stale = [
                    cid for cid, b in self._buffers.items()
                    if now - b.last_ingest_monotonic > settings.diarize_buffer_seconds
                ]
                for cid in stale:
                    self._flush(cid)
        except asyncio.CancelledError:
            return

    def _get_known_speakers(self, channel_id: str, meeting_id: str) -> list[tuple[str, str]]:
        """현재 known-speaker set을 동적으로 조립한다.

        cue tracker가 추적한 [위원장 + 현재 위원 + 직전 위원]의 voiceprint를 사용하고,
        cue가 없으면(위원장 미지정/위원회 미해석/cue 비활성) 위원회 정적 ≤4로 폴백한다.
        """
        try:
            ids = speaker_cue_tracker.current_known_councilor_ids(channel_id)
        except Exception as e:
            logger.debug("cue known-ids failed ch=%s: %s", channel_id, e)
            ids = []
        if ids:
            out: list[tuple[str, str]] = []
            for cid in ids:
                ks = self._vp_cache.get(cid)
                if ks is None:
                    try:
                        ks = voiceprint_service.get_voiceprint_for_councilor(cid)
                    except Exception:
                        ks = None
                    if ks:
                        self._vp_cache[cid] = ks
                if ks:
                    out.append(ks)
            if out:
                return out
        # 폴백: 위원회 정적 known-speaker (세션당 1회 조회)
        if channel_id not in self._static_known:
            try:
                self._static_known[channel_id] = voiceprint_service.get_known_speakers_for_meeting(meeting_id)
            except Exception as e:
                logger.debug("static known-speaker fetch failed ch=%s: %s", channel_id, e)
                self._static_known[channel_id] = []
        return self._static_known[channel_id]

    async def _transcribe_and_apply(self, buf: _ChannelBuffer) -> None:
        try:
            if not self._client:
                return
            rate = settings.openai_realtime_audio_rate
            wav = _pcm_to_wav(bytes(buf.data), rate)
            create_kwargs = dict(
                model=settings.diarize_model,
                file=("chunk.wav", io.BytesIO(wav), "audio/wav"),
                response_format="diarized_json",
                chunking_strategy="auto",
                language="ko",
            )
            # 실명 화자 식별: 회의 위원회에 등록된 ≤4명 목소리를 전달 → speaker가 실제 의원명이 됨
            known = self._get_known_speakers(buf.channel_id, buf.meeting_id)
            if known:
                create_kwargs["extra_body"] = {
                    "known_speaker_names": [n for n, _ in known],
                    "known_speaker_references": [d for _, d in known],
                }
            try:
                result = await asyncio.wait_for(
                    self._client.audio.transcriptions.create(**create_kwargs),
                    timeout=_DIARIZE_API_TIMEOUT,
                )
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                logger.warning("diarize api timeout ch=%s", buf.channel_id)
                return
            except Exception as e:
                logger.warning("diarize api failed ch=%s: %s", buf.channel_id, e)
                return

            segments = _attr(result, "segments") or []
            if not segments:
                logger.debug("diarize: no segments ch=%s", buf.channel_id)
                return
            logger.info(
                "diarize: %d segments ch=%s (offset=%.1fs, %.1fs audio)",
                len(segments), buf.channel_id, buf.chunk_start_offset,
                len(buf.data) / (rate * 2),
            )
            await self._apply_segments(buf, segments)
        finally:
            self._inflight.discard(buf.channel_id)

    # ─── 매칭 + DB 갱신 + 브로드캐스트 ─────────────────────────────────

    async def _apply_segments(self, buf: _ChannelBuffer, segments: list[Any]) -> None:
        """diarize 세그먼트를 경로 A 자막과 시간 겹침으로 매칭해 화자를 부여한다."""
        supabase = get_supabase_client()
        tol = settings.diarize_match_tolerance_seconds
        rate = settings.openai_realtime_audio_rate

        # 세그먼트 절대 시간 범위 산출
        seg_list = []
        for seg in segments:
            label = _speaker_label(_attr(seg, "speaker"))
            # 익명(단일 대문자→"화자 N")이고 위원 질의 턴이면 = 집행부 상대 → 집행부 라벨로 보정
            if label and label.startswith("화자 ") and speaker_cue_tracker.in_questioning_turn(buf.channel_id):
                label = speaker_cue_tracker.current_official_label(buf.channel_id)
            start = float(_attr(seg, "start", 0.0) or 0.0) + buf.chunk_start_offset
            end = float(_attr(seg, "end", 0.0) or 0.0) + buf.chunk_start_offset
            if not label or end <= start:
                continue
            seg_list.append({"start": start, "end": end, "speaker": label})
        if not seg_list:
            return

        buffered_sec = len(buf.data) / (rate * 2)
        window_start = max(0.0, buf.chunk_start_offset - tol)
        window_end = buf.chunk_start_offset + buffered_sec + tol

        # 구간 겹침 필터: start_time <= window_end AND end_time >= window_start
        # (start_time만 거르면 window 경계에 걸친 자막을 놓침)
        try:
            res = (
                supabase.table("subtitles")
                .select("id, start_time, end_time, speaker")
                .eq("meeting_id", buf.meeting_id)
                .lte("start_time", window_end)
                .gte("end_time", window_start)
                .order("start_time")
                .execute()
            )
            candidates = res.data or []
        except Exception as e:
            logger.warning("diarize: subtitles query failed ch=%s: %s", buf.channel_id, e)
            return

        # 이 버퍼가 "소유"하는 핵심 구간 (tolerance 제외) — 경계 자막을 한 버퍼에서만 처리해
        # 인접 버퍼 간 재매칭으로 인한 화자 flip-flop/중복 broadcast를 방지한다.
        core_start = buf.chunk_start_offset
        core_end = buf.chunk_start_offset + buffered_sec

        for c in candidates:
            s0 = float(c["start_time"])
            s1 = float(c.get("end_time") or s0)
            if s1 < s0:
                s1 = s0
            # 자막 중점이 이 버퍼 핵심 구간에 속할 때만 소유(경계 자막은 인접 버퍼가 담당)
            mid = (s0 + s1) / 2.0
            if not (core_start <= mid < core_end):
                continue
            best_seg = None
            best_overlap = 0.0
            for seg in seg_list:
                overlap = min(s1, seg["end"]) - max(s0, seg["start"])
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_seg = seg
            if best_seg is None or best_overlap <= 0.0:
                continue
            new_speaker = best_seg["speaker"]
            if (c.get("speaker") or None) == new_speaker:
                continue

            try:
                supabase.table("subtitles").update(
                    {"speaker": new_speaker}
                ).eq("id", c["id"]).execute()
            except Exception as e:
                logger.warning("diarize: speaker update failed id=%s: %s", c["id"], e)
                continue

            try:
                await manager.broadcast_corrected_subtitle(
                    buf.channel_id,
                    {
                        "id": c["id"],
                        "speaker": new_speaker,
                        "meeting_id": buf.meeting_id,
                        "source": "diarize",
                    },
                )
            except Exception as e:
                logger.debug("diarize: broadcast failed: %s", e)


# 싱글톤 (경로 A·main lifespan에서 공유)
diarize_service = DiarizeService()
