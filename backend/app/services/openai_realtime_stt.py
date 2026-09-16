"""채널 실시간 자막 STT 서비스 (OpenAI Realtime transcription WebSocket).

Deepgram을 대체하는 라이브 STT 엔진(경로 A). 채널별 HLS 스트림을 모니터링하며
OpenAI Realtime 전사 세션으로 실시간 자막을 생성하고 WebSocket으로 브로드캐스트한다.

파이프라인:
  m3u8 fetch → 새 TS 세그먼트 다운로드 → persistent ffmpeg(mpegts→24kHz mono PCM16)
       → PCM 청크: (a) base64로 Realtime WS에 append, (b) diarize_service에 ingest
       → 주기적 commit(turn_detection=null) → transcription.delta(interim)/completed(final)
       → 브라우저 WebSocket broadcast + DB 저장

검증된 계약 (openai 2.26 SDK 소스 + 정식 문서 교차검증):
  - URL: wss://api.openai.com/v1/realtime?intent=transcription  (헤더 Authorization Bearer만, OpenAI-Beta 금지)
  - session.update: {session:{type:"transcription", audio:{input:{format:{type:"audio/pcm",rate:24000},
      transcription:{model,language}, turn_detection}}}}
  - append: {"type":"input_audio_buffer.append","audio":"<base64 PCM16>"}
  - commit: {"type":"input_audio_buffer.commit"}  (gpt-realtime-whisper는 turn_detection:null + 수동 commit 필수)
  - 이벤트: conversation.item.input_audio_transcription.delta(field "delta", interim)
            conversation.item.input_audio_transcription.completed(field "transcript", final)

화자 구분은 경로 B(diarize_service)가 비동기로 채운다 — 여기서 speaker는 항상 None.

타임스탬프 앵커링: 자막 [start,end]는 "발화가 커밋된 오디오 위치"로 정한다. _commit_loop가
commit을 보낼 때 그 시점 오디오-초 위치 [직전 commit, 이번 commit]를 채널별 deque에 push하고,
completed 이벤트 수신 시 deque에서 popleft하여 사용한다. 이렇게 해야 API 지연 동안 _pump_pcm가
밀어둔 오디오만큼 구간이 부풀거나 미래로 밀리지 않으며, diarize(경로 B)의 발화-위치 시계와 정렬된다.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import uuid
from collections import deque
from datetime import datetime, timezone

import httpx
import websockets

from app.api.websocket import manager
from app.core.config import settings
from app.core.database import get_supabase_client
from app.services.dictionary import get_default_dictionary
from app.services.diarize_service import diarize_service
from app.services.hls_parser import HlsPlaylistParser
from app.services.sentence_buffer import SentenceBuffer
from app.services.name_corrector import correct_member_names
from app.services.live_corrector import live_corrector
from app.services.speaker_cue_tracker import speaker_cue_tracker

logger = logging.getLogger(__name__)

# 의회 용어 사전 (STT 오인식 보정)
_dictionary = get_default_dictionary()

# m3u8 폴링 간격 (초)
POLL_INTERVAL = 1.0
# STT 무응답(전사 진전 없음) 감지 타임아웃 (초)
STALL_TIMEOUT = 90.0
# 자동 재연결 최대 대기 (초)
MAX_RECONNECT_DELAY = 30.0
# WS send 타임아웃 (초) — 백프레셔로 무한 대기/데드락 방지
WS_SEND_TIMEOUT = 15.0
# ffmpeg 종료 reap 대기 (초)
FFMPEG_REAP_TIMEOUT = 5.0


class OpenAiRealtimeSttService:
    """채널 HLS 스트림을 모니터링하며 OpenAI Realtime 전사로 실시간 자막을 생성한다.

    기존 ChannelSttService(Deepgram)와 동일한 공개 인터페이스를 유지하므로
    AutoSttManager가 변경 없이 사용할 수 있다.
    """

    def __init__(self) -> None:
        self._active_tasks: dict[str, asyncio.Task] = {}  # type: ignore[type-arg]
        self._parsers: dict[str, HlsPlaylistParser] = {}
        self._subtitle_counter: dict[str, int] = {}
        self._last_receive_time: dict[str, float] = {}
        self._last_error: dict[str, str] = {}
        self._reconnect_count: dict[str, int] = {}
        self._meeting_ids: dict[str, str] = {}  # channel_id → meeting UUID
        # 채널별 누적 오디오 시간(초) — bytes/(rate*2). 양 경로 공유 시계의 기준.
        self._audio_sec: dict[str, float] = {}
        # 채널별 commit 윈도우 deque: (start_sec, end_sec). completed 1건당 popleft.
        self._commit_windows: dict[str, deque] = {}  # type: ignore[type-arg]
        # 채널별 직전 commit 종료 위치(다음 윈도우 start) + 미커밋 누적 바이트
        self._commit_cursor: dict[str, float] = {}
        self._pending_bytes: dict[str, int] = {}
        # completed에 윈도우가 없을 때 폴백용 직전 종료 시각
        self._last_end_sec: dict[str, float] = {}
        # subtitle_stage 'none→draft' 승격 완료 meeting_id 셋
        self._stage_promoted: set[str] = set()
        # fire-and-forget DB persist 태스크 추적 (GC/셧다운 회수)
        self._persist_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]
        # 채널별 STT 세션 글로서리 프롬프트 (의원명/용어 → 표기 바이어스)
        self._glossary_prompts: dict[str, str] = {}
        # 채널별 interim 문장 병합 버퍼 (sentence_buffer_enabled=True 시 활성화)
        self._sentence_buffers: dict[str, SentenceBuffer] = {}

    # ─── 공개 인터페이스 (AutoSttManager 호환) ──────────────────────────

    async def start(self, channel_id: str, stream_url: str, *, meeting_id: str | None = None) -> None:
        """채널 STT 처리를 시작한다 (이미 실행 중이면 재시작)."""
        if channel_id in self._active_tasks:
            await self.stop(channel_id)

        if not settings.openai_api_key:
            logger.error("Channel %s: OPENAI_API_KEY not configured", channel_id)
            return

        if meeting_id:
            self._meeting_ids[channel_id] = meeting_id

        logger.info(
            "Starting OpenAI Realtime STT for channel %s: %s (meeting=%s, model=%s)",
            channel_id, stream_url, meeting_id or "none", settings.openai_realtime_stt_model,
        )

        # 정회(status=2)→재개 등 같은 meeting 재시작 시, 오디오 시계가 0으로 리셋되면
        # 기존 자막(0~N초)과 타임스탬프가 충돌하고 diarize 매칭이 깨진다.
        # DB에 남은 마지막 자막 종료 위치에서 시계를 이어받아 누적 연속성을 유지한다.
        base = 0.0
        if meeting_id and meeting_id != channel_id:
            base = self._initial_audio_offset(meeting_id)

        parser = HlsPlaylistParser()
        self._parsers[channel_id] = parser
        self._subtitle_counter[channel_id] = 0
        self._last_receive_time[channel_id] = time.monotonic()
        self._audio_sec[channel_id] = base
        self._commit_windows[channel_id] = deque()
        self._commit_cursor[channel_id] = base
        self._pending_bytes[channel_id] = 0
        self._last_end_sec[channel_id] = base

        # 구조 인지형 화자 추적 시작 (위원회 명부/위원장 로드 → 호명 단서로 현재 위원 추적)
        try:
            speaker_cue_tracker.start_channel(channel_id, meeting_id or channel_id)
        except Exception as e:
            logger.debug("cue tracker start skipped ch=%s: %s", channel_id, e)

        # 회의별 글로서리 프롬프트 로드 (의원명/용어 → STT 표기 바이어스)
        try:
            if meeting_id and meeting_id != channel_id:
                from app.core.database import get_supabase_client
                from app.services.glossary_service import load_meeting_glossary, format_glossary_prompt
                terms = load_meeting_glossary(get_supabase_client(), meeting_id)
                self._glossary_prompts[channel_id] = format_glossary_prompt(terms)
            else:
                self._glossary_prompts[channel_id] = ""
        except Exception:
            self._glossary_prompts[channel_id] = ""

        task = asyncio.create_task(
            self._run_with_reconnect(channel_id, stream_url, parser),
            name=f"stt-{channel_id}",
        )
        self._active_tasks[channel_id] = task

    async def stop(self, channel_id: str) -> None:
        """채널 STT 처리를 중지한다."""
        task = self._active_tasks.pop(channel_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        parser = self._parsers.pop(channel_id, None)
        if parser:
            await parser.close()

        self._subtitle_counter.pop(channel_id, None)
        self._last_receive_time.pop(channel_id, None)
        self._meeting_ids.pop(channel_id, None)
        self._audio_sec.pop(channel_id, None)
        self._commit_windows.pop(channel_id, None)
        self._commit_cursor.pop(channel_id, None)
        self._pending_bytes.pop(channel_id, None)
        self._last_end_sec.pop(channel_id, None)
        self._glossary_prompts.pop(channel_id, None)
        self._sentence_buffers.pop(channel_id, None)
        # diarize 버퍼/진행 태스크 + cue tracker 상태 정리
        await diarize_service.drop_channel(channel_id)
        speaker_cue_tracker.drop_channel(channel_id)
        manager.clear_history(channel_id)
        logger.info("Stopped OpenAI Realtime STT for channel %s", channel_id)

    async def stop_all(self) -> None:
        """모든 활성 채널 STT를 중지하고 잔여 persist 태스크를 회수한다."""
        channel_ids = list(self._active_tasks.keys())
        for channel_id in channel_ids:
            await self.stop(channel_id)
        pending = [t for t in self._persist_tasks if not t.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        logger.info("Stopped all STT channels (%d)", len(channel_ids))

    def is_running(self, channel_id: str) -> bool:
        task = self._active_tasks.get(channel_id)
        return task is not None and not task.done()

    @property
    def active_channels(self) -> list[str]:
        """현재 실행 중인 채널 ID 목록."""
        return [cid for cid, t in self._active_tasks.items() if not t.done()]

    def get_debug_info(self, channel_id: str) -> dict:
        task = self._active_tasks.get(channel_id)
        last_recv = self._last_receive_time.get(channel_id)
        elapsed = round(time.monotonic() - last_recv, 1) if last_recv is not None else None
        return {
            "channel_id": channel_id,
            "engine": "openai_realtime",
            "model": settings.openai_realtime_stt_model,
            "task_exists": task is not None,
            "task_done": task.done() if task else None,
            "task_exception": str(task.exception()) if task and task.done() and task.exception() else None,
            "last_recv_secs_ago": elapsed,
            "audio_sec": round(self._audio_sec.get(channel_id, 0.0), 1),
            "subtitle_count": self._subtitle_counter.get(channel_id, 0),
            "active_ws_rooms": list(manager.active_connections.keys()),
            "last_error": self._last_error.get(channel_id),
            "reconnect_count": self._reconnect_count.get(channel_id, 0),
        }

    # ─── 재연결 루프 ────────────────────────────────────────────────────

    def _initial_audio_offset(self, meeting_id: str) -> float:
        """같은 meeting 재시작 시 이어받을 오디오 시계 시작점(기존 자막 최대 end_time)."""
        try:
            res = (
                get_supabase_client()
                .table("subtitles")
                .select("end_time")
                .eq("meeting_id", meeting_id)
                .order("end_time", desc=True)
                .limit(1)
                .execute()
            )
            if res.data:
                return float(res.data[0].get("end_time") or 0.0)
        except Exception as e:
            logger.debug("initial audio offset query failed (meeting=%s): %s", meeting_id, e)
        return 0.0

    async def _run_with_reconnect(
        self, channel_id: str, stream_url: str, parser: HlsPlaylistParser
    ) -> None:
        delay = 1.0
        while True:
            session_start = time.monotonic()
            try:
                await self._run(channel_id, stream_url, parser)
                elapsed = time.monotonic() - session_start
                if elapsed < 5.0:
                    # 비정상적으로 짧은 세션(ffmpeg 즉시 사망/스트림 불가 등) = 사실상 실패
                    # → delay를 리셋하지 않고 백오프 유지(매 ~1초 재연결 폭주 방지)
                    self._reconnect_count[channel_id] = self._reconnect_count.get(channel_id, 0) + 1
                    self._last_error[channel_id] = f"short_session_{elapsed:.1f}s"
                    logger.warning(
                        "Channel %s: session ended after %.1fs (too short), backing off %.0fs",
                        channel_id, elapsed, delay,
                    )
                else:
                    logger.info("Channel %s: STT session ended, reconnecting...", channel_id)
                    self._last_error[channel_id] = "session_ended_normally"
                    delay = 1.0
            except asyncio.CancelledError:
                logger.info("Channel %s: STT cancelled", channel_id)
                return
            except FileNotFoundError as e:
                # ffmpeg 미설치 등 영구 실패 → 무한 재시도 금지, 채널 STT 포기
                logger.error("Channel %s: ffmpeg not found — STT disabled for channel: %s", channel_id, e)
                self._last_error[channel_id] = f"ffmpeg_missing: {e}"
                return
            except Exception as e:
                self._last_error[channel_id] = f"{type(e).__name__}: {e}"
                self._reconnect_count[channel_id] = self._reconnect_count.get(channel_id, 0) + 1
                logger.error("Channel %s: STT failed: %s, retrying in %.0fs", channel_id, e, delay)

            await asyncio.sleep(delay)
            delay = min(delay * 2, MAX_RECONNECT_DELAY)

    # ─── 단일 세션 실행 ──────────────────────────────────────────────────

    def _build_session_update(self, channel_id: str | None = None) -> dict:
        """transcription 세션 설정 메시지를 구성한다 (검증된 GA 구조)."""
        transcription: dict = {
            "model": settings.openai_realtime_stt_model,
            "language": "ko",
        }
        glossary = self._glossary_prompts.get(channel_id or "", "") if channel_id else ""
        # ★ gpt-realtime-whisper 는 transcription.prompt 미지원 → 넣으면 invalid_value 오류로
        #   세션이 즉시 끊겨 무한 재연결(자막 0건)된다. prompt를 지원하는 모델
        #   (gpt-4o-transcribe 계열)에서만 글로서리 바이어스를 첨부한다.
        if glossary and "whisper" not in settings.openai_realtime_stt_model.lower():
            transcription["prompt"] = glossary
        audio_input: dict = {
            "format": {"type": "audio/pcm", "rate": settings.openai_realtime_audio_rate},
            "transcription": transcription,
        }
        if settings.openai_realtime_turn_detection == "server_vad":
            # gpt-4o-transcribe 계열에서만 유효 — 서버 자동 분절(수동 commit 불필요)
            audio_input["turn_detection"] = {
                "type": "server_vad",
                "threshold": 0.5,
                "prefix_padding_ms": 300,
                "silence_duration_ms": 500,
            }
        else:
            # gpt-realtime-whisper 필수 — turn_detection:null + 주기적 수동 commit
            audio_input["turn_detection"] = None
        return {
            "type": "session.update",
            "session": {"type": "transcription", "audio": {"input": audio_input}},
        }

    async def _run(self, channel_id: str, stream_url: str, parser: HlsPlaylistParser) -> None:
        """Realtime WS에 연결하고 HLS→PCM을 스트리밍한다."""
        ws_url = settings.openai_realtime_ws_url
        headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
        http_client = httpx.AsyncClient(timeout=30.0)
        ffmpeg_proc: asyncio.subprocess.Process | None = None

        # 세션 시작 시 commit 추적 상태 초기화 (재연결마다 깨끗하게)
        self._commit_windows[channel_id] = deque()
        self._commit_cursor[channel_id] = self._audio_sec.get(channel_id, 0.0)
        self._pending_bytes[channel_id] = 0

        try:
            ffmpeg_proc = await self._spawn_ffmpeg()

            async with websockets.connect(
                ws_url, additional_headers=headers, max_size=None
            ) as ws:
                logger.info("Channel %s: OpenAI Realtime WS connected", channel_id)
                await ws.send(json.dumps(self._build_session_update(channel_id)))

                manual_commit = settings.openai_realtime_turn_detection != "server_vad"
                tasks = [
                    asyncio.create_task(self._feed_segments(channel_id, stream_url, parser, http_client, ffmpeg_proc)),
                    asyncio.create_task(self._pump_pcm(channel_id, ffmpeg_proc, ws)),
                    asyncio.create_task(self._receive_transcripts(channel_id, ws)),
                    asyncio.create_task(self._watchdog(channel_id, ws)),
                ]
                if manual_commit:
                    tasks.append(asyncio.create_task(self._commit_loop(channel_id, ws)))

                try:
                    done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for t in done:
                        exc = t.exception()
                        if exc and not isinstance(exc, asyncio.CancelledError):
                            logger.error("Channel %s: task error: %s", channel_id, exc)
                finally:
                    # 정상 종료·예외·취소 어느 경로든 모든 자식 태스크를 확실히 회수
                    for t in tasks:
                        if not t.done():
                            t.cancel()
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for r in results:
                        if isinstance(r, BaseException) and not isinstance(r, asyncio.CancelledError):
                            logger.debug("Channel %s: child task exited with: %s", channel_id, r)
        finally:
            # ffmpeg: stdin close → kill → wait(reap)로 좀비/FD 누수 방지
            if ffmpeg_proc is not None:
                try:
                    if ffmpeg_proc.stdin and not ffmpeg_proc.stdin.is_closing():
                        ffmpeg_proc.stdin.close()
                except Exception:
                    pass
                if ffmpeg_proc.returncode is None:
                    try:
                        ffmpeg_proc.kill()
                    except ProcessLookupError:
                        pass
                try:
                    await asyncio.wait_for(ffmpeg_proc.wait(), FFMPEG_REAP_TIMEOUT)
                except (asyncio.TimeoutError, ProcessLookupError):
                    pass
            await http_client.aclose()

    async def _spawn_ffmpeg(self) -> asyncio.subprocess.Process:
        """mpegts(stdin) → 24kHz mono s16le PCM(stdout) 변환용 persistent ffmpeg."""
        rate = settings.openai_realtime_audio_rate
        return await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-hide_banner", "-loglevel", "error",
            "-f", "mpegts", "-i", "pipe:0",
            "-vn",
            "-ac", "1",
            "-ar", str(rate),
            "-f", "s16le",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

    # ─── 태스크: HLS 세그먼트 다운로드 → ffmpeg stdin ──────────────────

    async def _feed_segments(
        self,
        channel_id: str,
        stream_url: str,
        parser: HlsPlaylistParser,
        http_client: httpx.AsyncClient,
        ffmpeg_proc: asyncio.subprocess.Process,
    ) -> None:
        assert ffmpeg_proc.stdin is not None
        while True:
            # ffmpeg가 죽었으면 세션 종료를 유도(_run의 FIRST_COMPLETED 트리거 → 재연결)
            if ffmpeg_proc.returncode is not None:
                logger.error("Channel %s: ffmpeg died (rc=%s), ending feeder", channel_id, ffmpeg_proc.returncode)
                return
            try:
                all_segments = await parser.fetch_segments(stream_url)
                new_segments = parser.get_new_segments(all_segments)
                for segment_url in new_segments:
                    try:
                        resp = await http_client.get(segment_url)
                        resp.raise_for_status()
                        ffmpeg_proc.stdin.write(resp.content)
                        await ffmpeg_proc.stdin.drain()
                    except (BrokenPipeError, ConnectionResetError):
                        logger.error("Channel %s: ffmpeg stdin broken, ending feeder", channel_id)
                        return
                    except Exception as e:
                        logger.warning("Channel %s: segment fetch failed: %s", channel_id, e)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("Channel %s: poll failed: %s", channel_id, e)
            await asyncio.sleep(POLL_INTERVAL)

    # ─── 태스크: ffmpeg stdout PCM → WS append + diarize ingest ────────

    async def _pump_pcm(
        self,
        channel_id: str,
        ffmpeg_proc: asyncio.subprocess.Process,
        ws: websockets.ClientConnection,
    ) -> None:
        assert ffmpeg_proc.stdout is not None
        rate = settings.openai_realtime_audio_rate
        bytes_per_sec = rate * 2  # 16-bit mono
        chunk_bytes = max(1, int(bytes_per_sec * settings.openai_realtime_chunk_seconds))
        meeting_id = self._meeting_ids.get(channel_id, channel_id)
        # channel-only 세션(폴백)은 DB 자막이 없어 diarize 매칭 대상이 없으므로 ingest 스킵
        feed_diarize = meeting_id != channel_id
        wall_start = time.monotonic()

        while True:
            pcm = await ffmpeg_proc.stdout.read(chunk_bytes)
            if not pcm:
                logger.info("Channel %s: ffmpeg PCM stream ended", channel_id)
                await asyncio.sleep(0.5)
                return

            offset_sec = self._audio_sec.get(channel_id, 0.0)

            # (a) Realtime WS로 append — 백프레셔로 무한 대기/데드락 방지 위해 타임아웃
            try:
                await asyncio.wait_for(
                    ws.send(json.dumps({
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(pcm).decode("ascii"),
                    })),
                    timeout=WS_SEND_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning("Channel %s: ws.send timeout (backpressure), reconnecting", channel_id)
                return  # FIRST_COMPLETED → 재연결

            self._pending_bytes[channel_id] = self._pending_bytes.get(channel_id, 0) + len(pcm)

            # (b) diarize 경로에 같은 PCM 누적 (DB 영속화되는 세션에서만)
            if feed_diarize:
                try:
                    diarize_service.ingest_pcm(channel_id, meeting_id, pcm, offset_sec)
                except Exception as de:
                    logger.debug("Channel %s: diarize ingest skipped: %s", channel_id, de)

            # 오디오 시계 전진
            self._audio_sec[channel_id] = offset_sec + len(pcm) / bytes_per_sec

            # realtime 페이싱: VOD가 실시간보다 너무 앞서면 throttle (라이브는 no-op)
            ahead = self._audio_sec[channel_id] - (time.monotonic() - wall_start)
            if ahead > 1.0:
                await asyncio.sleep(min(ahead - 0.5, 2.0))

    # ─── 태스크: 주기적 commit (turn_detection=null 모드) ───────────────

    async def _commit_loop(self, channel_id: str, ws: websockets.ClientConnection) -> None:
        rate = settings.openai_realtime_audio_rate
        min_bytes = int(rate * 2 * 0.2)  # 빈 버퍼 commit 방지(~0.2초)
        while True:
            await asyncio.sleep(settings.openai_realtime_commit_seconds)
            if self._pending_bytes.get(channel_id, 0) < min_bytes:
                continue
            # commit 직전 오디오 위치로 자막 윈도우 [직전 commit, 지금] 기록
            end = self._audio_sec.get(channel_id, 0.0)
            start = self._commit_cursor.get(channel_id, end)
            self._commit_windows.setdefault(channel_id, deque()).append((start, end))
            # deque 무한 증가 방지(completed 누락 대비) — 최근 50개만 유지
            wins = self._commit_windows[channel_id]
            while len(wins) > 50:
                wins.popleft()
            self._commit_cursor[channel_id] = end
            self._pending_bytes[channel_id] = 0
            try:
                await asyncio.wait_for(
                    ws.send(json.dumps({"type": "input_audio_buffer.commit"})), timeout=WS_SEND_TIMEOUT
                )
            except (asyncio.TimeoutError, Exception):
                return

    # ─── 태스크: WS 수신 → 자막 브로드캐스트 ────────────────────────────

    async def _receive_transcripts(
        self, channel_id: str, ws: websockets.ClientConnection
    ) -> None:
        async for raw in ws:
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Channel %s: invalid JSON from OpenAI", channel_id)
                continue

            ev_type = ev.get("type", "")
            if ev_type == "conversation.item.input_audio_transcription.delta":
                # 워치독 타이머는 '실제 전사 진전' 이벤트에서만 갱신
                self._last_receive_time[channel_id] = time.monotonic()
                text = (ev.get("delta") or "").strip()
                if text:
                    # interim은 미리보기이므로 숫자변환(convert) 없이 가벼운 사전 치환만
                    if settings.sentence_buffer_enabled:
                        sb = self._sentence_buffers.setdefault(
                            channel_id,
                            SentenceBuffer(settings.sentence_buffer_min_chars),
                        )
                        completed_sentence = sb.push(text)
                        preview = completed_sentence if completed_sentence is not None else sb.pending
                        await manager.broadcast_interim_subtitle(
                            channel_id, {"text": preview, "channel_id": channel_id}
                        )
                    else:
                        await manager.broadcast_interim_subtitle(
                            channel_id, {"text": text, "channel_id": channel_id}
                        )
            elif ev_type == "conversation.item.input_audio_transcription.completed":
                self._last_receive_time[channel_id] = time.monotonic()
                transcript = (ev.get("transcript") or "").strip()
                if transcript:
                    # completed 수신 시 버퍼를 flush해 미완성 interim 조각을 제거
                    buf = self._sentence_buffers.get(channel_id)
                    if buf:
                        buf.flush()
                    start_time, end_time = self._next_window(channel_id)
                    await self._emit_subtitle(channel_id, transcript, start_time, end_time)
            elif ev_type == "conversation.item.input_audio_transcription.failed":
                logger.warning("Channel %s: transcription failed: %s", channel_id, ev.get("error"))
            elif ev_type == "error":
                # 치명적 세션 오류 → 예외로 세션 종료 유도(재연결). 무한 무효 append 방지.
                err = ev.get("error") or {}
                logger.warning("Channel %s: realtime error: %s", channel_id, err)
                raise RuntimeError(f"realtime error: {err.get('code') or err.get('type') or err}")
            elif ev_type == "session.updated":
                logger.info("Channel %s: realtime session confirmed", channel_id)

    def _next_window(self, channel_id: str) -> tuple[float, float]:
        """completed 이벤트에 대응하는 [start,end] 오디오 구간을 반환한다.

        _commit_loop가 commit 시점에 기록한 윈도우를 FIFO로 꺼낸다(commit↔completed 1:1).
        윈도우가 없으면(server_vad 모드 등) 직전 종료~현재 오디오 위치로 폴백한다.
        """
        wins = self._commit_windows.get(channel_id)
        if wins:
            start, end = wins.popleft()
        else:
            start = self._last_end_sec.get(channel_id, 0.0)
            end = self._audio_sec.get(channel_id, start)
        if end < start:
            end = start
        self._last_end_sec[channel_id] = end
        return start, end

    async def _emit_subtitle(
        self, channel_id: str, transcript: str, start_time: float, end_time: float
    ) -> None:
        """확정 전사(transcript)를 자막으로 브로드캐스트 + DB 저장한다."""
        counter = self._subtitle_counter.get(channel_id, 0)
        self._subtitle_counter[channel_id] = counter + 1

        # 의회 용어 사전 보정 (숫자변환 포함). dictionary.correct는 단위테스트로 보장되므로 신뢰.
        # 빈 문자열로 붕괴하는 비정상 케이스만 원본 유지.
        corrected = _dictionary.correct(transcript)
        text = corrected if corrected.strip() else transcript
        # 위원 이름 명부 교정 (그 위원회 명부 밖 이름은 안 건드림)
        try:
            roster = speaker_cue_tracker.roster_names(channel_id)
            if roster:
                text = correct_member_names(text, roster)
        except Exception as e:
            logger.debug("name correct skipped: %s", e)

        real_meeting_id = self._meeting_ids.get(channel_id, channel_id)
        subtitle_data = {
            "subtitle": {
                "id": str(uuid.uuid4()),
                "meeting_id": real_meeting_id,
                "text": text,
                "start_time": round(start_time, 2),
                "end_time": round(end_time, 2),
                "confidence": None,
                "speaker": None,  # 경로 B(diarize)가 비동기로 채움
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        }

        logger.info("Channel %s: [STT] %s", channel_id, text[:80])
        await manager.broadcast_subtitle(channel_id, subtitle_data)

        # 라이브 GPT 사후 교정 큐에 적재 (글로서리 바이어스로 정확도 향상 → '교정됨' 전환).
        # 독립 서비스라 예외가 STT를 막지 않음.
        try:
            live_corrector.enqueue(
                channel_id, real_meeting_id, subtitle_data["subtitle"]["id"], text
            )
        except Exception as e:
            logger.debug("live correct enqueue skipped: %s", e)

        # 구조 인지형 단서 감지 (호명/자기소개/집행부 → diarize 동적 known-speaker 갱신)
        try:
            speaker_cue_tracker.observe(channel_id, text)
        except Exception as e:
            logger.debug("cue observe skipped: %s", e)

        if real_meeting_id != channel_id:
            t = asyncio.create_task(self._persist_subtitle(subtitle_data))
            self._persist_tasks.add(t)
            t.add_done_callback(self._persist_tasks.discard)

    async def _persist_subtitle(self, subtitle_data: dict) -> None:
        """자막을 Supabase에 저장 (fire-and-forget, 추적됨)."""
        try:
            sub = subtitle_data["subtitle"]
            meeting_id = sub["meeting_id"]
            get_supabase_client().table("subtitles").insert({
                "id": sub["id"],
                "meeting_id": meeting_id,
                "text": sub["text"],
                "start_time": sub["start_time"],
                "end_time": sub["end_time"],
                "speaker": sub["speaker"],
                "confidence": sub["confidence"],
                # ★kind 를 빼면 컬럼 기본값이 'ai' 라 실시간 자막이 AI 자막으로 저장된다.
                #   그러면 AI 자막 생성이 kind='ai' 를 지울 때 초안까지 함께 사라진다.
                "kind": "live",
            }).execute()
            if meeting_id not in self._stage_promoted:
                try:
                    get_supabase_client().table("meetings").update(
                        {"subtitle_stage": "draft"}
                    ).eq("id", meeting_id).eq("subtitle_stage", "none").execute()
                    self._stage_promoted.add(meeting_id)
                except Exception as se:
                    logger.debug("subtitle_stage promote skipped: %s", se)
        except Exception as e:
            logger.warning("Failed to persist subtitle %s: %s", subtitle_data["subtitle"].get("id", "?"), e)

    # ─── 태스크: 무응답 워치독 ──────────────────────────────────────────

    async def _watchdog(self, channel_id: str, ws: websockets.ClientConnection) -> None:
        while True:
            await asyncio.sleep(STALL_TIMEOUT / 2)
            last = self._last_receive_time.get(channel_id, time.monotonic())
            if time.monotonic() - last > STALL_TIMEOUT:
                logger.warning(
                    "Channel %s: no transcription progress for %.0fs, forcing reconnect",
                    channel_id, time.monotonic() - last,
                )
                await ws.close()
                return


# 전역 싱글톤 인스턴스
_channel_stt_service = None


def get_channel_stt_service():
    """채널 STT 서비스 싱글톤을 반환한다 (AutoSttManager 호환 팩토리명 유지).

    live_stt_mode 설정에 따라 엔진을 선택한다:
      - "batch"(기본): LiveBatchSttService — 윈도우 배치 전사 (저비용·고정확)
      - "realtime":    OpenAiRealtimeSttService — Realtime WS 스트리밍 (저지연·고비용)
    두 클래스는 동일한 공개 인터페이스를 제공한다.
    """
    global _channel_stt_service
    if _channel_stt_service is None:
        if settings.live_stt_mode == "realtime":
            _channel_stt_service = OpenAiRealtimeSttService()
        else:
            # 순환 import 방지를 위해 지연 import (live_batch_stt ← live_corrector 등 공유)
            from app.services.live_batch_stt import LiveBatchSttService

            _channel_stt_service = LiveBatchSttService()
    return _channel_stt_service
