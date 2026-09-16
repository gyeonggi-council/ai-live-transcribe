"""라이브 자막 배치 STT 서비스 (live_stt_mode="batch" — 저비용·고정확 기본 엔진).

Realtime WS 스트리밍 대신, HLS 오디오를 N초 윈도우로 모아 일반 배치 전사 API
(/v1/audio/transcriptions, gpt-4o-transcribe)로 전사한다.

왜 배치인가 (사용자 요구: "10~20초 지연 OK, 정확도·비용 최우선"):
  - 비용: 배치 전사 ≈ $0.006/오디오분(~$0.36/시간/채널). Realtime WS의 오디오 토큰
    과금 대비 약 1/10. 무음(정회) 윈도우는 API 호출 자체를 생략 → 0원.
  - 정확도: 15초 윈도우 문맥(Realtime 3초 commit 분절 대비) + 글로서리 prompt 바이어스
    (gpt-realtime-whisper는 prompt 미지원이었음) + 직전 윈도우 전사 꼬리 문맥 연결.
  - 지연: 윈도우 15초 + API 2~5초 ≈ 17~20초 (허용 범위 내). interim 이벤트는 없다.

파이프라인:
  m3u8 poll → TS 세그먼트 → persistent ffmpeg(mpegts→24kHz mono PCM16)
    → 윈도우 버퍼(기본 15초) → 꼬리의 조용한 지점에서 컷(단어 중간 절단 방지)
    → 무음이면 폐기, 아니면 WAV 래핑 → 배치 전사(prompt=글로서리+직전 문맥)
    → 사전/이름 교정 → 문장 분리(타임스탬프 비례 배분)
    → subtitle_created 브로드캐스트 + DB 저장 + live_corrector 큐 적재

OpenAiRealtimeSttService와 동일한 공개 인터페이스를 제공하므로 AutoSttManager와
channels API가 변경 없이 사용한다 (get_channel_stt_service 팩토리가 모드 분기).
PCM 샘플레이트는 realtime 경로와 동일(openai_realtime_audio_rate=24kHz)하게 유지해
diarize_service(같은 시계·레이트 가정)를 켜도 그대로 호환된다.
"""

from __future__ import annotations

import asyncio
import io
import math
import logging
import time
import uuid
import wave
from array import array
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from openai import AsyncOpenAI

from app.api.websocket import manager
from app.core.config import settings
from app.core.database import get_supabase_client
from app.services.dictionary import get_default_dictionary
from app.services.diarize_service import diarize_service
from app.services.hls_parser import HlsPlaylistParser, ts_audio_seconds
from app.services.live_corrector import live_corrector
from app.services.live_recorder import live_recorder
from app.services.name_corrector import correct_member_names, correct_staff_names
from app.services.material_request_detector import material_request_detector
from app.services.meeting_clock import record_anchor as record_clock_anchor
from app.services.speaker_cue_tracker import speaker_cue_tracker
from app.services.vod_stt_service import add_sentence_breaks

logger = logging.getLogger(__name__)

# 의회 용어 사전 (STT 오인식 보정)
_dictionary = get_default_dictionary()

# m3u8 폴링 간격 (초)
POLL_INTERVAL = 1.0
# 채널당 보관하는 HLS 세그먼트 수 (2초×20 = 40초, ≈4MB). 브라우저가 접속 즉시 20초 전에서
# 재생을 시작하게 하는 보관분 — 원본 CDN 재생목록은 6초뿐이다 (api/channels.py hls 라우트).
HLS_RING_SEGMENTS = 20
# PCM 무진전(스트림 정지) 감지 타임아웃 (초) → 세션 재시작
STALL_TIMEOUT = 90.0
# 자동 재연결 최대 대기 (초)
MAX_RECONNECT_DELAY = 30.0
# ffmpeg 종료 reap 대기 (초)
FFMPEG_REAP_TIMEOUT = 5.0
# 배치 전사 API 타임아웃 (초)
API_TIMEOUT = 60.0
# ffmpeg stdout 1회 read 단위 (초)
READ_CHUNK_SECONDS = 0.5
# 스트림이 멈췄을 때 부분 윈도우 강제 flush 최소 길이 (초)
MIN_FORCE_FLUSH_SECONDS = 2.0
# ★강제 flush 발동 기준: 마지막 PCM 수신 후 이 시간(초) 이상 지나야 '진짜 정지'로 본다.
#   HLS는 세그먼트(통상 4~10초) 단위 버스트 유입이라, 단순 read 타임아웃(2초)마다
#   flush하면 15초 윈도우가 세그먼트 길이로 붕괴(정확도·비용 설계 무력화)한다.
FORCE_FLUSH_IDLE_SECONDS = 8.0
# stop() 시 in-flight 전사 대기/잔여 버퍼 최종 전사 타임아웃 (초)
STOP_FLUSH_TIMEOUT = 20.0
# stop() 잔여 버퍼 최종 전사 최소 길이 (초)
MIN_FINAL_FLUSH_SECONDS = 1.0
# 전사 실패 후 재시도 쿨다운(초) — 복원된 버퍼가 즉시 재flush되어
# 지속 장애(쿼터 소진 등) 시 핫 루프가 되는 것을 방지한다.
FAILURE_RETRY_SECONDS = 5.0
# 조용한 컷 지점 탐색 구간(윈도우 꼬리) — 창 길이에 비례한다(12초 창에서 2.5초 = 옛 절대값과 바이트 동일,
# 8초 창은 1.67초). 절대값 2.5 를 두면 8초 창에서는 꼬리 31% 를 뒤져 실효 창이 5.5초까지 줄어든다(2026-09-14).
CUT_SEARCH_RATIO = 2.5 / 12.0
CUT_SEARCH_MIN_SECONDS = 1.5
# RMS 블록 길이(초)
CUT_BLOCK_SECONDS = 0.3
# 전사 호출이 밀릴 때 버퍼 상한 (24kHz mono 16-bit 기준 약 9분) — 초과분은 앞에서 폐기
MAX_BUFFER_BYTES = 24 * 1024 * 1024
# RMS 계산 시 샘플 보폭 (8 → 24kHz에서 3kHz 등가 샘플링, 음성 유무 판별에 충분)
RMS_STRIDE = 8
# 시각 기준점(meeting_clock_anchors)을 새로 남기는 방송 공백 기준(초).
# 이보다 오래 끊겼다 이어지면 자막 시계는 그 공백을 건너뛰지만 실제 시각은 흘렀다 —
# 정회가 대표적이다. 그 순간 기준점을 남겨야 VOD 의 실제 시각이 어긋나지 않는다.
CLOCK_ANCHOR_GAP_SECONDS = 60.0
# 기준점 기록 시 디코더가 재생목록 엣지보다 뒤처진 양(초)을 모를 때의 기본값
# (프런트 NEXT_PUBLIC_SYNC_EDGE_LAG_SEC 기본값과 같은 가정)
DEFAULT_EDGE_LAG_SECONDS = 3.0

# 문장 시각 배분(time_sentences)의 말소리 판정 단위(초) / 쉼으로 치는 최소 틈(초) /
# 앞뒤가 쉼인 이보다 짧은 소리는 잡음으로 버린다(초) — 값은 scripts/eval_live_timing.py 로 정했다.
VOICE_BLOCK_SECONDS = 0.1
MIN_PAUSE_SECONDS = 0.25
BLIP_SECONDS = 0.3


def _pcm_to_wav(pcm: bytes, rate: int) -> bytes:
    """raw PCM16 mono를 WAV 컨테이너로 감싼다 (ffmpeg 불필요)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def _window_rms(pcm: bytes, stride: int = RMS_STRIDE) -> float:
    """int16 PCM의 RMS(0~32767). stride 샘플링으로 가볍게 계산한다."""
    if len(pcm) < 2:
        return 0.0
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    picked = samples[::stride]
    if not picked:
        return 0.0
    acc = 0
    for s in picked:
        acc += s * s
    return (acc / len(picked)) ** 0.5


def _has_speech(pcm: bytes, rate: int) -> bool:
    """윈도우 안에 발화로 볼 만한 블록(0.3초, RMS≥임계)이 하나라도 있는가.

    평균 RMS는 '긴 무음 + 짧은 발언' 윈도우를 무음으로 오판해 발언을 버린다(누락).
    최대 블록 기준은 짧은 발언도 살린다.
    """
    if len(pcm) < 2:
        return False
    thr = float(settings.live_batch_silence_rms)
    block = max(2, int(CUT_BLOCK_SECONDS * rate * 2))
    if len(pcm) <= block:
        return _window_rms(pcm) >= thr
    for pos in range(0, len(pcm) - block + 1, block):
        if _window_rms(pcm[pos : pos + block]) >= thr:
            return True
    return _window_rms(pcm[-block:]) >= thr


def _cut_search_seconds(window_seconds: float) -> float:
    """조용한 컷 지점을 뒤지는 꼬리 길이(초) — 창 길이의 CUT_SEARCH_RATIO, 최소 CUT_SEARCH_MIN_SECONDS."""
    return max(CUT_SEARCH_MIN_SECONDS, window_seconds * CUT_SEARCH_RATIO)


def _find_quiet_cut(pcm: bytes, rate: int, window_seconds: float) -> int:
    """윈도우 꼬리(_cut_search_seconds)에서 가장 조용한 블록 중앙의 바이트 오프셋을 찾는다.

    단어 중간 절단을 피하기 위한 간이 VAD. '의미 있게 조용한' 지점(절대 무음 임계값
    또는 구간 평균의 절반 미만)이 있을 때만 일찍 자르고, 균일한 발화면 윈도우 끝에서
    자른다. 반환값은 항상 짝수(샘플 경계)다.
    """
    byps = rate * 2
    window_bytes = min(len(pcm), int(window_seconds * byps))
    window_bytes -= window_bytes % 2
    search_bytes = int(_cut_search_seconds(window_seconds) * byps)
    block_bytes = max(2, int(CUT_BLOCK_SECONDS * byps))
    lo = max(0, window_bytes - search_bytes)
    if window_bytes - lo <= block_bytes:
        return window_bytes

    best_pos = window_bytes
    best_rms = float("inf")
    step = max(2, block_bytes // 2)
    pos = lo
    while pos + block_bytes <= window_bytes:
        rms = _window_rms(pcm[pos : pos + block_bytes])
        if rms < best_rms:
            best_rms = rms
            best_pos = pos + block_bytes // 2
        pos += step

    overall = _window_rms(pcm[lo:window_bytes])
    quiet_threshold = max(float(settings.live_batch_silence_rms), overall * 0.5)
    if best_rms >= quiet_threshold:
        return window_bytes  # 조용한 지점 없음(연속 발화) → 윈도우 끝에서 컷
    return best_pos - (best_pos % 2)


def _strip_overlap(prev_tail: str, cur: str, min_overlap: int = 6) -> str:
    """직전 윈도우와의 verbatim 중복(프롬프트 에코)을 제거한다.

    gpt-4o-transcribe는 prompt(직전 전사 꼬리)를 출력에 되풀이할 수 있다 —
    특히 새 오디오가 짧거나 조용할 때. 두 가지를 처리한다:
      1) 윈도우 전체가 직전 텍스트 안에 그대로 있으면 통째로 폐기
         (드물게 실제 반복 발언도 떨어질 수 있으나 에코 소음 제거가 더 중요)
      2) 직전 꼬리의 접미사 == 현재의 접두사(min_overlap자 이상)면 겹친 만큼 절단
    """
    cur_s = (cur or "").strip()
    if not cur_s:
        return ""
    p = (prev_tail or "").strip()
    if not p:
        return cur_s
    if cur_s in p:
        return ""
    max_k = min(len(p), len(cur_s))
    for k in range(max_k, min_overlap - 1, -1):
        if p.endswith(cur_s[:k]):
            return cur_s[k:].lstrip()
    return cur_s


def _percentile(values, pct: float) -> Optional[float]:
    """최근접 순위 백분위 (표본 없으면 None). 계측 요약용 — 통계적 엄밀성보다 단순함."""
    vals = sorted(float(v) for v in values)
    if not vals:
        return None
    k = max(0, min(len(vals) - 1, int(round(pct / 100.0 * len(vals) + 0.5)) - 1))
    return vals[k]


def _voiced_spans(pcm: bytes, rate: int) -> list[list[float]]:
    """창 안에서 말소리가 난 구간들 [[시작, 끝], ...] (창 기준 초).

    MIN_PAUSE 보다 짧은 틈은 붙이고, 앞뒤가 쉼인 BLIP 초 미만의 짧은 소리(책상·마이크 잡음)는 버린다 —
    그런 잡음에 첫 문장을 맞추면 말보다 2~3초 먼저 뜬다 (2026-09-11 ch60 대조).
    """
    thr = float(settings.live_batch_silence_rms)
    byps = rate * 2
    block = max(2, int(VOICE_BLOCK_SECONDS * rate) * 2)
    spans: list[list[float]] = []
    for pos in range(0, len(pcm) - block + 1, block):
        if _window_rms(pcm[pos : pos + block]) < thr:
            continue
        a, b = pos / byps, (pos + block) / byps
        if spans and a - spans[-1][1] < MIN_PAUSE_SECONDS:
            spans[-1][1] = b
        else:
            spans.append([a, b])
    return [s for s in spans if s[1] - s[0] >= BLIP_SECONDS] or spans


def time_sentences(
    lines: list[str], start: float, end: float, pcm: bytes | None = None, rate: int = 0
) -> list[tuple[str, float, float]]:
    """문장들에 [시작, 끝] 을 준다 — 창 안에서 '말소리가 난 시간' 에만 글자 수 비례로 배분한다.

    예전엔 창 전체(앞뒤 무음 포함)에 비례 배분해, 쉼으로 시작하는 창의 첫 문장이 말보다 먼저 떴다 —
    의원 발언이 끝나고 다음 발언까지의 쉼 동안 다음 자막이 먼저 나왔다 (2026-09-11 사용자 신고).
    말 시작 ±1초 비율 90.2 → 97.2% (ch60 네 구간 563건, docs/live-sync-eval-2026-09.md). 문장 시작을 쉼 끝에
    맞추는 규칙은 창 안쪽 문장을 오히려 늦게 만들어(92.9 → 78.6%) 넣지 않았다.
    말소리를 못 찾으면(PCM 없음·전부 문턱 아래) 창 전체 하나를 말소리로 보고 예전과 같게 배분한다.
    """
    if not lines:
        return []
    spans = (_voiced_spans(pcm, rate) if pcm and rate else []) or [[0.0, max(0.0, end - start)]]
    voiced = sum(b - a for a, b in spans)
    total_chars = sum(len(ln) for ln in lines) or 1
    starts: list[float] = []
    cum = 0
    for ln in lines:
        v, acc = voiced * cum / total_chars, 0.0
        for idx, (a, b) in enumerate(spans):
            if v < acc + (b - a) or idx == len(spans) - 1:
                break
            acc += b - a
        starts.append(min(b, a + (v - acc)))
        cum += len(ln)
    ends = starts[1:] + [spans[-1][1]]
    return [(ln, round(start + s, 2), round(start + e, 2)) for ln, s, e in zip(lines, starts, ends)]


def split_sentences_with_timestamps(
    text: str, start: float, end: float, pcm: bytes | None = None, rate: int = 0
) -> list[tuple[str, float, float]]:
    """윈도우 전사 텍스트를 문장으로 나누고 시각을 준다 (time_sentences)."""
    lines = [ln.strip() for ln in add_sentence_breaks(text).split("\n") if ln.strip()]
    return time_sentences(lines, start, end, pcm, rate)


SYNC_TARGET_MIN_SEC = 8
SYNC_TARGET_MAX_SEC = 60


def live_sync_target_sec() -> int:
    """/live 영상 지연 목표(초) — settings.live_sync_target_sec 를 8~60 으로 클램프. 채널 상태 응답과
    stt_status 가 이 값을 싣고 프런트가 hls.js liveSyncDuration 으로 쓴다(?sync=N 이 있으면 그쪽이 이긴다)."""
    try:
        v = int(settings.live_sync_target_sec)
    except (TypeError, ValueError):
        v = 20
    return max(SYNC_TARGET_MIN_SEC, min(SYNC_TARGET_MAX_SEC, v))


class LiveBatchSttService:
    """채널 HLS 스트림을 윈도우 배치 전사로 자막화한다 (공개 인터페이스 = realtime 서비스 호환)."""

    def __init__(self) -> None:
        self._active_tasks: dict[str, asyncio.Task] = {}  # type: ignore[type-arg]
        self._parsers: dict[str, HlsPlaylistParser] = {}
        # 채널별 최근 세그먼트 (seq, 길이초, 원본 URL, bytes, 첫 음성의 자막 시계) — 깊은 재생목록용 보관분
        self._hls_ring: dict[str, deque[tuple[int, float, str, bytes, Optional[float]]]] = {}
        # 채널별 '지금까지 ffmpeg 에 넣은 음성' 의 끝 = 다음 세그먼트 첫 음성의 자막 시계.
        # ffmpeg 가 그 음성을 모두 내놓으면 _audio_sec 과 같아진다 (세그먼트마다 AAC 프레임 수로 센다).
        self._fed_clock: dict[str, float] = {}
        self._meeting_ids: dict[str, str] = {}
        self._subtitle_counter: dict[str, int] = {}
        self._last_error: dict[str, str] = {}
        self._reconnect_count: dict[str, int] = {}
        # 채널별 누적 오디오 시계(초) — diarize와 공유하는 기준
        self._audio_sec: dict[str, float] = {}
        # 채널별 start() 직렬화 락 — AutoSTT의 ensure 루프와 상태변경 핸들러가
        # 동시에 start()를 부르면 둘 다 '실행 중 아님'을 보고 세션을 이중 기동,
        # 추적 안 되는 고아 세션이 같은 오디오 시계를 2배속으로 오염시키고
        # 전사 API를 이중 호출(비용 2배)한다 (2026-06-12 실측 사고).
        self._start_locks: dict[str, asyncio.Lock] = {}
        # 윈도우 버퍼 + 버퍼 첫 바이트의 오디오-초 오프셋
        self._buffers: dict[str, bytearray] = {}
        self._buffer_start: dict[str, float] = {}
        # 마지막 PCM 수신 시각 (워치독)
        self._last_pcm_time: dict[str, float] = {}
        # 채널당 전사 동시성 1건 (순서 보존) — 채널별 단일 in-flight 태스크로 추적
        self._inflight: set[str] = set()
        self._transcribe_tasks: dict[str, asyncio.Task] = {}  # type: ignore[type-arg]
        # 세션 세대 토큰: start/stop마다 증가. 구세션 고아 태스크의 stale write
        # (브로드캐스트/DB/상태 재생성/_inflight 오해제)를 무효화한다.
        self._generation: dict[str, int] = {}
        # stop() 진행 중 표시 — in-flight 대기 동안 finally의 _maybe_flush가
        # 새 전사 태스크를 띄워 고아가 되는 것을 차단한다.
        self._stopping: set[str] = set()
        # 무음 스킵 카운터 (비용 절감 가시화)
        self._silence_skipped: dict[str, int] = {}
        self._api_calls: dict[str, int] = {}
        # 마지막 전사 실패 시각 — 재시도 쿨다운 (지속 장애 핫 루프 방지)
        self._last_failure_time: dict[str, float] = {}
        # 프롬프트 에코 중복으로 폐기한 윈도우 수 (디버그 가시화)
        self._dup_skipped: dict[str, int] = {}
        # 서버 기준 자막 생성 상태 (모든 시청자에게 동일하게 방송)
        self._last_emit_wall: dict[str, float] = {}   # 마지막 자막 방출 시각 (monotonic)
        self._emit_gaps: dict[str, list[float]] = {}  # 최근 자막 간격(평균 계산용, ≤8개)
        # 자막 준비 지연 계측 (창 단위, 최근 100개) — 영상 지연 목표(프런트
        # liveSyncDuration)를 실측으로 정하기 위한 근거. ready_lag = 방출 시점
        # 오디오 시계 − 창 시작 = "창의 첫 발화가 몇 초 전이었나" (2026-09-03).
        self._api_secs: dict[str, deque] = {}
        self._ready_lags: dict[str, deque] = {}
        # 수집 지연 계측 (2026-09-14): 최신 세그먼트를 재생목록에서 본 벽시계(_edge_wall)로
        #   edge_lag = (_fed_clock − _audio_sec) + (지금 − _edge_wall)
        # = 디코더가 우리 재생목록 엣지(브라우저가 보는 엣지)보다 몇 초 뒤인가. 창마다
        #   sync_need = ready_lag + edge_lag  가 "영상이 최소 이만큼은 엣지 뒤여야 자막이 안 늦는다" 이고
        # 회의 전체 sync_need 의 p99 + 1 이 영상 지연 목표(settings.live_sync_target_sec)의 근거다.
        self._edge_wall: dict[str, float] = {}
        self._edge_lags: dict[str, deque] = {}
        self._sync_needs: dict[str, deque] = {}
        self._status_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]
        # 글로서리 prompt + 직전 윈도우 전사 꼬리(문맥 연결)
        self._glossary_prompts: dict[str, str] = {}
        self._prev_tail: dict[str, str] = {}
        # 빠른 재시작 시 HLS 백로그 스킵 플래그 (재시작 중복 방지)
        self._skip_backlog: dict[str, bool] = {}
        # 시각 기준점(meeting_clock_anchors)을 마지막으로 남긴 시각 — 채널당 세션 1회 + 긴 공백마다
        self._clock_anchor_at: dict[str, float] = {}
        # subtitle_stage 'none→draft' 승격 완료 meeting_id 셋
        self._stage_promoted: set[str] = set()
        self._persist_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]
        self._client: AsyncOpenAI | None = None

    # ─── 공개 인터페이스 (AutoSttManager / channels API 호환) ─────────────

    async def start(self, channel_id: str, stream_url: str, *, meeting_id: str | None = None) -> None:
        """채널 STT 처리를 시작한다 (이미 실행 중이면 재시작).

        ★채널별 락으로 직렬화 — 동시 start()가 둘 다 '실행 중 아님'을 보고
        세션을 이중 기동하면 고아 세션이 시계·녹음을 오염시키고 비용이 2배가 된다.
        """
        lock = self._start_locks.setdefault(channel_id, asyncio.Lock())
        async with lock:
            await self._start_locked(channel_id, stream_url, meeting_id=meeting_id)

    async def _start_locked(
        self, channel_id: str, stream_url: str, *, meeting_id: str | None = None
    ) -> None:
        if channel_id in self._active_tasks:
            existing = self._active_tasks[channel_id]
            # ★같은 meeting으로 이미 정상 실행 중이면 no-op (멱등) — 시청자 폴링이
            #   유발하는 ensure 경쟁이 살아있는 세션을 취소·재시작하는 폭풍 방지
            #   (2026-07-22 ch1 실증: 27명 시청 채널만 start↔cancel 무한 루프)
            if (
                not existing.done()
                and meeting_id
                and self._meeting_ids.get(channel_id) == meeting_id
            ):
                logger.info(
                    "Channel %s: STT already running for meeting %s — skip restart",
                    channel_id, meeting_id,
                )
                return
            await self.stop(channel_id)

        if not settings.openai_api_key:
            logger.error("Channel %s: OPENAI_API_KEY not configured", channel_id)
            return

        if self._client is None:
            self._client = AsyncOpenAI(api_key=settings.openai_api_key)

        if meeting_id:
            self._meeting_ids[channel_id] = meeting_id

        logger.info(
            "Starting batch STT for channel %s: %s (meeting=%s, model=%s, window=%.0fs)",
            channel_id, stream_url, meeting_id or "none",
            settings.live_batch_model, settings.live_batch_window_seconds,
        )

        # 새 세션 세대 — 이전 세대 고아 태스크의 stale write 무효화
        self._generation[channel_id] = self._generation.get(channel_id, 0) + 1

        # 정회→재개 등 같은 meeting 재시작 시 오디오 시계를 기존 자막 끝에서 이어받는다.
        # (동기 Supabase 호출 — 이벤트 루프 블로킹 방지 위해 스레드로 오프로딩)
        base, seed_tail, last_created = 0.0, "", None
        if meeting_id and meeting_id != channel_id:
            base, seed_tail, last_created = await asyncio.to_thread(self._resume_state, meeting_id)

        # 빠른 재시작이면 플레이리스트 백로그(직전 세션이 이미 전사한 오디오)를 스킵
        # → 서버 재시작 시 마지막 자막이 한 번 더 나오는 중복 방지.
        self._skip_backlog[channel_id] = self._is_quick_restart(last_created)
        if self._skip_backlog[channel_id]:
            logger.info("Channel %s: quick restart — HLS 백로그 스킵 (중복 방지)", channel_id)

        parser = HlsPlaylistParser()
        self._parsers[channel_id] = parser
        self._subtitle_counter[channel_id] = 0
        self._audio_sec[channel_id] = base
        self._buffers[channel_id] = bytearray()
        self._buffer_start[channel_id] = base
        self._last_pcm_time[channel_id] = time.monotonic()
        self._silence_skipped[channel_id] = 0
        self._api_calls[channel_id] = 0
        # 새 세션(정회 재개 포함)의 첫 PCM 에서 시각 기준점을 다시 남긴다
        self._clock_anchor_at.pop(channel_id, None)
        # 재시작 후에도 중복 가드가 동작하도록 직전 자막 텍스트를 시드
        self._prev_tail[channel_id] = seed_tail[-settings.live_batch_context_chars:] if seed_tail else ""

        # 구조 인지형 화자 추적 (위원회 명부 + 집행부 staff 명부 로드 → 이름 교정 roster로도 사용)
        # 내부가 동기 Supabase 조회(명부/voiceprint/staff)라 DB 사전 로드와 같은
        # 방식으로 스레드 오프로드 — 이벤트 루프 블로킹 방지.
        try:
            await asyncio.to_thread(
                speaker_cue_tracker.start_channel, channel_id, meeting_id or channel_id
            )
        except Exception as e:
            logger.debug("cue tracker start skipped ch=%s: %s", channel_id, e)

        # 요구자료 감지기 채널 상태 초기화
        try:
            material_request_detector.start_channel(channel_id, meeting_id or channel_id)
        except Exception as e:
            logger.debug("material request start skipped ch=%s: %s", channel_id, e)

        # DB 용어사전을 후처리 교정기에 병합 — 관리자가 /admin/dictionary에서
        # 추가한 교정 쌍이 라이브 자막에도 적용되도록 STT 시작 시 새로 로드.
        # (이전엔 하드코딩 사전만 사용되어 DB 항목이 라이브에 반영 안 됐음)
        try:
            await asyncio.to_thread(_dictionary.load_from_db, get_supabase_client())
        except Exception as de:
            logger.debug("DB 사전 로드 스킵 ch=%s: %s", channel_id, de)

        # 회의별 글로서리 prompt (의원명/용어/의안명 → 전사 표기 바이어스)
        # 매 윈도우 재전송되므로 글자수 캡으로 prompt 토큰 비용 상한.
        try:
            if meeting_id and meeting_id != channel_id:
                from app.services.glossary_service import format_glossary_prompt, load_meeting_glossary
                terms = await asyncio.to_thread(
                    load_meeting_glossary, get_supabase_client(), meeting_id
                )
                # 매 윈도우 재전송되므로 글자수 캡 — 의원명(리스트 앞)이 우선 보존된다.
                # 900자: 본회의 등 전원(142명) 명부 + 핵심 절차용어까지 수용
                # (이름 정확도 최우선 — 프롬프트 토큰 증가분 ≈ +$0.07/시간 수용)
                self._glossary_prompts[channel_id] = format_glossary_prompt(
                    terms, max_terms=200, max_chars=900
                )
            else:
                self._glossary_prompts[channel_id] = ""
        except Exception:
            self._glossary_prompts[channel_id] = ""

        # 라이브 오디오 MP3 녹음 시작 (자막 검증용 — 실패해도 STT에 영향 없음).
        # base(오디오 시계 시작점)를 넘겨 자막 타임스탬프 ↔ mp3 위치 매핑을 기록.
        try:
            await live_recorder.start(channel_id, meeting_id or channel_id, start_offset_sec=base)
        except Exception as e:
            logger.debug("recorder start skipped ch=%s: %s", channel_id, e)

        task = asyncio.create_task(
            self._run_with_reconnect(channel_id, stream_url, parser),
            name=f"stt-batch-{channel_id}",
        )
        self._active_tasks[channel_id] = task

        # 자막 생성 상태 방송 루프 (전 채널 공용, 최초 1회 기동)
        if self._status_task is None or self._status_task.done():
            self._status_task = asyncio.create_task(
                self._status_broadcast_loop(), name="stt-status-broadcast"
            )

    async def stop(self, channel_id: str) -> None:
        """채널 STT 처리를 중지한다.

        순서가 중요하다: ① 세션(새 PCM) 중지 → ② in-flight 전사 완료 대기(결과 보존)
        → ③ 잔여 버퍼 최종 전사(폐회 발언 보존) → ④ 세대 증가(고아 무효화) → ⑤ 정리.
        ④가 ⑤보다 앞이어야 늦게 도착한 고아 콜백이 정리를 되돌리지 못한다.
        """
        self._stopping.add(channel_id)
        try:
            task = self._active_tasks.pop(channel_id, None)
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            # in-flight 전사 회수: 정상 완료를 기다리고(자막 보존), 늦으면 취소
            t = self._transcribe_tasks.pop(channel_id, None)
            if t and not t.done():
                try:
                    await asyncio.wait_for(t, STOP_FLUSH_TIMEOUT)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass  # wait_for가 태스크를 취소·회수함
                except Exception:
                    pass

            # 잔여 버퍼(마지막 윈도우 미만 분량 — 산회 선언 등) 최종 전사
            try:
                await self._flush_remaining(channel_id)
            except Exception as e:
                logger.debug("final flush skipped ch=%s: %s", channel_id, e)

            # 이후 도착하는 어떤 stale 콜백도 무효화
            self._generation[channel_id] = self._generation.get(channel_id, 0) + 1
        finally:
            self._stopping.discard(channel_id)

        parser = self._parsers.pop(channel_id, None)
        if parser:
            await parser.close()

        for d in (
            self._subtitle_counter, self._meeting_ids, self._audio_sec,
            self._buffers, self._buffer_start, self._last_pcm_time,
            self._silence_skipped, self._api_calls, self._last_failure_time,
            self._glossary_prompts, self._prev_tail, self._last_error,
            self._dup_skipped, self._skip_backlog,
            self._last_emit_wall, self._emit_gaps, self._hls_ring, self._fed_clock,
            self._edge_wall,
        ):
            d.pop(channel_id, None)
        self._inflight.discard(channel_id)

        await diarize_service.drop_channel(channel_id)
        speaker_cue_tracker.drop_channel(channel_id)
        material_request_detector.drop_channel(channel_id)
        live_corrector.drop_channel(channel_id)
        try:
            await live_recorder.stop(channel_id)
        except Exception as e:
            logger.debug("recorder stop skipped ch=%s: %s", channel_id, e)
        manager.clear_history(channel_id)
        logger.info("Stopped batch STT for channel %s", channel_id)

    async def _flush_remaining(self, channel_id: str) -> None:
        """stop 직전 잔여 버퍼를 1회 전사한다 (무음/극소량이면 폐기)."""
        buf = self._buffers.get(channel_id)
        if not buf:
            return
        rate = settings.openai_realtime_audio_rate
        byps = rate * 2
        if len(buf) < int(byps * MIN_FINAL_FLUSH_SECONDS):
            return
        pcm = bytes(buf)
        buf.clear()
        start_sec = self._buffer_start.get(channel_id, 0.0)
        dur = len(pcm) / byps
        self._buffer_start[channel_id] = start_sec + dur
        if not _has_speech(pcm, rate):
            return
        meeting_id = self._meeting_ids.get(channel_id, channel_id)
        gen = self._generation.get(channel_id, 0)
        try:
            await asyncio.wait_for(
                self._transcribe_window(channel_id, meeting_id, pcm, start_sec, dur, gen),
                timeout=STOP_FLUSH_TIMEOUT,
            )
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

    async def stop_all(self) -> None:
        """모든 활성 채널 STT를 중지하고 잔여 비동기 태스크를 회수한다.

        전사 태스크는 stop()이 채널별로 회수한다. persist(DB insert) 태스크는
        취소하지 않고 완료를 기다린다 — 셧다운 시 마지막 자막 유실 방지.
        """
        channel_ids = list(self._active_tasks.keys())
        for channel_id in channel_ids:
            await self.stop(channel_id)
        if self._status_task and not self._status_task.done():
            self._status_task.cancel()
            try:
                await self._status_task
            except asyncio.CancelledError:
                pass
        self._status_task = None
        leftover = [t for t in self._transcribe_tasks.values() if not t.done()]
        for t in leftover:
            t.cancel()
        if leftover:
            await asyncio.gather(*leftover, return_exceptions=True)
        pending_persist = [t for t in self._persist_tasks if not t.done()]
        if pending_persist:
            await asyncio.gather(*pending_persist, return_exceptions=True)
        logger.info("Stopped all batch STT channels (%d)", len(channel_ids))

    def is_running(self, channel_id: str) -> bool:
        task = self._active_tasks.get(channel_id)
        return task is not None and not task.done()

    @property
    def active_channels(self) -> list[str]:
        """현재 실행 중인 채널 ID 목록."""
        return [cid for cid, t in self._active_tasks.items() if not t.done()]

    def audio_clock_for_meeting(self, meeting_id: str) -> float | None:
        """이 meeting을 STT 중인 채널의 현재 오디오-초 시계 (없으면 None).

        녹음 오프셋 사이드카가 없는 레거시 파일의 위치 매핑 추정에 사용:
        오프셋 ≈ 현재 시계 - (파일 크기 / 초당 바이트).
        """
        for ch, mid in self._meeting_ids.items():
            if mid == meeting_id and self.is_running(ch):
                return self._audio_sec.get(ch)
        return None

    def get_debug_info(self, channel_id: str) -> dict:
        task = self._active_tasks.get(channel_id)
        last_pcm = self._last_pcm_time.get(channel_id)
        elapsed = round(time.monotonic() - last_pcm, 1) if last_pcm is not None else None
        rate = settings.openai_realtime_audio_rate
        buffered = len(self._buffers.get(channel_id, b"")) / (rate * 2)
        return {
            "channel_id": channel_id,
            "engine": "openai_batch",
            "model": settings.live_batch_model,
            "window_seconds": settings.live_batch_window_seconds,
            "task_exists": task is not None,
            "task_done": task.done() if task else None,
            "task_exception": str(task.exception()) if task and task.done() and task.exception() else None,
            "last_pcm_secs_ago": elapsed,
            "audio_sec": round(self._audio_sec.get(channel_id, 0.0), 1),
            # fed_sec − audio_sec = ffmpeg 가 아직 안 내놓은 음성(초). 늘 작아야 한다 — 벌어지면 PDT 가 틀린다
            "fed_sec": round(self._fed_clock.get(channel_id, 0.0), 2),
            # 디코더가 우리 재생목록 엣지보다 몇 초 뒤인가 (순간값) — None 이면 아직 세그먼트를 못 봤다
            "edge_lag_sec": self._edge_lag_now(channel_id),
            "buffered_sec": round(buffered, 1),
            "subtitle_count": self._subtitle_counter.get(channel_id, 0),
            "api_calls": self._api_calls.get(channel_id, 0),
            "silence_skipped": self._silence_skipped.get(channel_id, 0),
            "dup_skipped": self._dup_skipped.get(channel_id, 0),
            "active_ws_rooms": list(manager.active_connections.keys()),
            "last_error": self._last_error.get(channel_id),
            "reconnect_count": self._reconnect_count.get(channel_id, 0),
        }

    # ─── 세션 수명주기 ───────────────────────────────────────────────────

    def _resume_state(self, meeting_id: str) -> tuple[float, str, Optional[str]]:
        """같은 meeting 재시작 시 이어받을 상태.

        Returns:
            (오디오 시계 시작점=기존 자막 최대 end_time,
             마지막 자막 텍스트 — 재시작 후에도 중복 가드(prev_tail)가 동작하도록 시드,
             마지막 자막 created_at — '빠른 재시작' 판정용)
        """
        try:
            res = (
                get_supabase_client()
                .table("subtitles")
                .select("end_time, text, created_at")
                .eq("meeting_id", meeting_id)
                .order("end_time", desc=True)
                .limit(1)
                .execute()
            )
            if res.data:
                row = res.data[0]
                return (
                    float(row.get("end_time") or 0.0),
                    str(row.get("text") or ""),
                    row.get("created_at"),
                )
        except Exception as e:
            logger.debug("resume state query failed (meeting=%s): %s", meeting_id, e)
        return 0.0, "", None

    @staticmethod
    def _is_quick_restart(last_created_at: Optional[str], window_seconds: float = 120.0) -> bool:
        """마지막 자막이 최근(기본 2분 이내)이면 '빠른 재시작'으로 본다.

        빠른 재시작이면 HLS 플레이리스트 백로그(직전 15~30초)가 이미 직전 세션에서
        전사된 오디오이므로 다시 먹이면 자막이 중복된다 → 백로그 스킵.
        반대로 정회 후 재개처럼 오래 지났으면 백로그는 미전사 신규 오디오라 먹인다.
        """
        if not last_created_at:
            return False
        try:
            ts = datetime.fromisoformat(str(last_created_at).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - ts).total_seconds() < window_seconds
        except ValueError:
            return False

    async def _run_with_reconnect(
        self, channel_id: str, stream_url: str, parser: HlsPlaylistParser
    ) -> None:
        # 세대를 진입 시 1회만 캡처 — 재연결 시 현재 세대를 다시 읽으면
        # 고아 세션이 새 세대로 '부활'해 자가종료 가드를 우회한다.
        gen = self._generation.get(channel_id, 0)
        delay = 1.0
        while True:
            if self._generation.get(channel_id, 0) != gen:
                logger.warning("Channel %s: stale session (gen %d) not reconnecting", channel_id, gen)
                return
            session_start = time.monotonic()
            try:
                await self._run(channel_id, stream_url, parser, gen)
                elapsed = time.monotonic() - session_start
                if elapsed < 5.0:
                    # 비정상적으로 짧은 세션(ffmpeg 즉시 사망 등) → 백오프 유지
                    self._reconnect_count[channel_id] = self._reconnect_count.get(channel_id, 0) + 1
                    self._last_error[channel_id] = f"short_session_{elapsed:.1f}s"
                    logger.warning(
                        "Channel %s: session ended after %.1fs (too short), backing off %.0fs",
                        channel_id, elapsed, delay,
                    )
                else:
                    logger.info("Channel %s: batch STT session ended, reconnecting...", channel_id)
                    self._last_error[channel_id] = "session_ended_normally"
                    delay = 1.0
            except asyncio.CancelledError:
                logger.info("Channel %s: batch STT cancelled", channel_id)
                return
            except FileNotFoundError as e:
                logger.error("Channel %s: ffmpeg not found — STT disabled for channel: %s", channel_id, e)
                self._last_error[channel_id] = f"ffmpeg_missing: {e}"
                return
            except Exception as e:
                self._last_error[channel_id] = f"{type(e).__name__}: {e}"
                self._reconnect_count[channel_id] = self._reconnect_count.get(channel_id, 0) + 1
                logger.error("Channel %s: batch STT failed: %s, retrying in %.0fs", channel_id, e, delay)

            await asyncio.sleep(delay)
            delay = min(delay * 2, MAX_RECONNECT_DELAY)

    async def _run(
        self, channel_id: str, stream_url: str, parser: HlsPlaylistParser, gen: int = -1
    ) -> None:
        """ffmpeg를 띄우고 HLS→PCM→윈도우 버퍼 파이프라인을 돌린다.

        gen: 이 세션의 세대 토큰. 어떤 경로로든 추적이 끊긴 고아 세션이
        살아남아도 내부 루프들이 세대 불일치를 보고 스스로 종료한다
        (공유 오디오 시계 오염·이중 전사 비용 차단).
        """
        http_client = httpx.AsyncClient(timeout=30.0)
        ffmpeg_proc: asyncio.subprocess.Process | None = None
        # 새 ffmpeg — 앞 ffmpeg 가 삼킨 음성은 사라졌으니 넣은 음성 시계를 실제 PCM 시계로 다시 맞춘다
        self._fed_clock[channel_id] = self._audio_sec.get(channel_id, 0.0)
        try:
            ffmpeg_proc = await self._spawn_ffmpeg()
            tasks = [
                asyncio.create_task(self._feed_segments(channel_id, stream_url, parser, http_client, ffmpeg_proc, gen)),
                asyncio.create_task(self._read_pcm_loop(channel_id, ffmpeg_proc, gen)),
                asyncio.create_task(self._watchdog(channel_id)),
            ]
            try:
                done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in done:
                    exc = t.exception()
                    if exc and not isinstance(exc, asyncio.CancelledError):
                        logger.error("Channel %s: task error: %s", channel_id, exc)
            finally:
                for t in tasks:
                    if not t.done():
                        t.cancel()
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for r in results:
                    if isinstance(r, BaseException) and not isinstance(r, asyncio.CancelledError):
                        logger.debug("Channel %s: child task exited with: %s", channel_id, r)
        finally:
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

    # ─── HLS 세그먼트 보관 (깊은 재생목록) ────────────────────────────────

    def _remember_segment(
        self, channel_id: str, seq: int, dur: float, url: str, data: bytes, clock: Optional[float] = None
    ) -> None:
        ring = self._hls_ring.get(channel_id)
        if ring is None:
            ring = self._hls_ring[channel_id] = deque(maxlen=HLS_RING_SEGMENTS)
        # Wowza 재시작으로 chunklist 가 바뀌면 seq 가 끊긴다 — 불연속 재생목록을 만들지 않게 비운다
        if ring and ring[-1][0] + 1 != seq:
            ring.clear()
        ring.append((seq, dur, url, data, clock))

    def get_hls_window(
        self, channel_id: str
    ) -> tuple[Optional[float], Optional[float], list[tuple[int, float, str, Optional[float]]]]:
        """(원본 재생목록 창 초, TARGETDURATION, 보관 세그먼트 [(seq, 길이초, 원본 URL, 자막 시계)]).

        api/channels.py 의 hls 라우트가 이것으로 깊은 재생목록을 만든다 (자막 시계는 PDT 로 싣는다).
        """
        parser = self._parsers.get(channel_id)
        origin_window = getattr(parser, "window_seconds", None) if parser else None
        target = getattr(parser, "target_duration", None) if parser else None
        ring = self._hls_ring.get(channel_id) or ()
        return origin_window, target, [(seq, dur, url, clock) for seq, dur, url, _, clock in ring]

    def get_hls_segment(self, channel_id: str, seq: int) -> Optional[bytes]:
        for s, _, _, data, _ in self._hls_ring.get(channel_id) or ():
            if s == seq:
                return data
        return None

    async def _feed_segments(
        self,
        channel_id: str,
        stream_url: str,
        parser: HlsPlaylistParser,
        http_client: httpx.AsyncClient,
        ffmpeg_proc: asyncio.subprocess.Process,
        gen: int = -1,
    ) -> None:
        assert ffmpeg_proc.stdin is not None
        first_poll = True
        while True:
            # 고아 세션 자가종료 — 새 세션이 시작돼 세대가 바뀌었으면 즉시 끝낸다
            if gen >= 0 and self._generation.get(channel_id, 0) != gen:
                logger.warning("Channel %s: stale feeder (gen %d) self-terminating", channel_id, gen)
                return
            if ffmpeg_proc.returncode is not None:
                logger.error("Channel %s: ffmpeg died (rc=%s), ending feeder", channel_id, ffmpeg_proc.returncode)
                return
            try:
                seen_at = time.monotonic()  # 이 폴링에서 본 엣지의 벽시계 (edge_lag 계측)
                all_segments = await parser.fetch_segments(stream_url)
                new_segments = parser.get_new_segments(all_segments)
                if first_poll:
                    first_poll = False
                    if self._skip_backlog.get(channel_id):
                        # 빠른 재시작: 백로그(직전 세션이 이미 전사한 ~15-30초)는
                        # 파서에 '본 것'으로만 기록하고 버린다 → 자막 중복 방지.
                        # 1회성 — 내부 재연결에서 재발동해 신규 오디오를 버리지 않게 소진.
                        self._skip_backlog[channel_id] = False
                        logger.info(
                            "Channel %s: %d개 백로그 세그먼트 스킵", channel_id, len(new_segments)
                        )
                        await asyncio.sleep(POLL_INTERVAL)
                        continue
                for segment_url in new_segments:
                    try:
                        resp = await http_client.get(segment_url)
                        resp.raise_for_status()
                        clock = self._fed_clock.get(channel_id, 0.0)
                        ffmpeg_proc.stdin.write(resp.content)
                        await ffmpeg_proc.stdin.drain()
                        entry = parser.entries.get(segment_url)
                        # EXTINF('2.0' 반올림)가 아니라 실제 음성 길이로 더한다 — 이어 더하면 벌어진다
                        audio = ts_audio_seconds(resp.content) or (entry[1] if entry else 0.0)
                        self._fed_clock[channel_id] = clock + audio
                        # 엣지 벽시계는 _fed_clock 과 같은 폴링 스냅숏으로 함께 갱신한다 — 세그먼트 여러 개를 한 폴링에
                        # 받을 때 뒤에 갱신하면 그 사이 완료된 전사가 새 시계 + 옛 경과시간으로 edge_lag 를 과대 기록한다(Codex 09-14)
                        self._edge_wall[channel_id] = seen_at
                        if entry:
                            self._remember_segment(channel_id, entry[0], entry[1], segment_url, resp.content, clock)
                    except (BrokenPipeError, ConnectionResetError):
                        logger.error("Channel %s: ffmpeg stdin broken, ending feeder", channel_id)
                        return
                    except Exception as e:
                        logger.warning("Channel %s: segment fetch failed: %s", channel_id, e)
                # 새 세그먼트가 없으면 엣지가 안 움직인 것 — 옛 벽시계를 두어 edge_lag 가 그만큼 자란다
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("Channel %s: poll failed: %s", channel_id, e)
            await asyncio.sleep(POLL_INTERVAL)

    # ─── PCM 수집 → 윈도우 flush ────────────────────────────────────────

    async def _read_pcm_loop(
        self, channel_id: str, ffmpeg_proc: asyncio.subprocess.Process, gen: int = -1
    ) -> None:
        assert ffmpeg_proc.stdout is not None
        rate = settings.openai_realtime_audio_rate
        bytes_per_sec = rate * 2
        chunk_bytes = max(2, int(bytes_per_sec * READ_CHUNK_SECONDS))
        meeting_id = self._meeting_ids.get(channel_id, channel_id)
        feed_diarize = meeting_id != channel_id

        while True:
            # 고아 세션 자가종료 — 공유 오디오 시계(_audio_sec)를 오염시키기 전에
            # 세대 불일치를 감지해 끝낸다 (이중 기동 시 시계 2배속 사고 방지)
            if gen >= 0 and self._generation.get(channel_id, 0) != gen:
                logger.warning("Channel %s: stale PCM loop (gen %d) self-terminating", channel_id, gen)
                return
            try:
                pcm = await asyncio.wait_for(ffmpeg_proc.stdout.read(chunk_bytes), timeout=2.0)
            except asyncio.TimeoutError:
                # HLS는 세그먼트 단위 버스트 유입이라 read 공백 2초는 정상이다.
                # '마지막 PCM 후 FORCE_FLUSH_IDLE_SECONDS 경과'일 때만 진짜 정지로
                # 보고 부분 윈도우를 강제 flush한다 (15초 윈도우 붕괴 방지).
                idle = time.monotonic() - self._last_pcm_time.get(channel_id, time.monotonic())
                if idle >= FORCE_FLUSH_IDLE_SECONDS:
                    self._maybe_flush(channel_id, force=True)
                continue
            if not pcm:
                logger.info("Channel %s: ffmpeg PCM stream ended", channel_id)
                self._maybe_flush(channel_id, force=True)
                await asyncio.sleep(0.5)
                return

            now_mono = time.monotonic()
            pcm_gap = now_mono - self._last_pcm_time.get(channel_id, now_mono)
            self._last_pcm_time[channel_id] = now_mono
            offset_sec = self._audio_sec.get(channel_id, 0.0)
            # 실제 시각 표시용 기준점 — 세션 첫 PCM 과 긴 공백(정회) 재개 때만 한 줄
            self._note_clock_anchor(channel_id, meeting_id, offset_sec, pcm_gap)

            # MP3 녹음 (자막 검증용) — 내부에서 모든 실패를 흡수한다
            await live_recorder.write(channel_id, pcm)

            buf = self._buffers.setdefault(channel_id, bytearray())
            if not buf:
                self._buffer_start[channel_id] = offset_sec
            buf.extend(pcm)

            # 화자 구분(경로 B)을 켜면 같은 PCM을 공유한다 (기본 OFF — 비용)
            if feed_diarize and settings.diarize_enabled:
                try:
                    diarize_service.ingest_pcm(channel_id, meeting_id, pcm, offset_sec)
                except Exception as de:
                    logger.debug("Channel %s: diarize ingest skipped: %s", channel_id, de)

            self._audio_sec[channel_id] = offset_sec + len(pcm) / bytes_per_sec
            self._maybe_flush(channel_id)

    def _note_clock_anchor(
        self, channel_id: str, meeting_id: str, clock_sec: float, pcm_gap_sec: float
    ) -> None:
        """자막 시계 ↔ 실제 시각 기준점을 남긴다 (세션 첫 PCM · 긴 공백 재개).

        왜 여기인가: 자막 시계는 **수신된 오디오**만 센다. 정회로 방송이 끊기면 시계는
        멈추지만 실제 시각은 흐르므로, 재개 지점마다 짝을 남겨야 VOD 에서 "이 장면이
        몇 시였나"가 어긋나지 않는다(migration 037).

        기록하는 실제 시각은 **지금 − edge_lag** 이다 — 방금 디코딩한 소리는 재생목록
        엣지보다 그만큼 앞서 방송된 것이다(_edge_lag_now 와 같은 정의).
        """
        if meeting_id == channel_id:
            return  # 회의 레코드가 없는 채널 — 기준점을 걸어 둘 곳이 없다
        last = self._clock_anchor_at.get(channel_id)
        if last is not None and pcm_gap_sec < CLOCK_ANCHOR_GAP_SECONDS:
            return
        self._clock_anchor_at[channel_id] = time.monotonic()
        edge_lag = self._edge_lag_now(channel_id)
        if edge_lag is None:
            edge_lag = DEFAULT_EDGE_LAG_SECONDS
        wall = datetime.now(timezone.utc) - timedelta(seconds=edge_lag)
        task = asyncio.create_task(
            asyncio.to_thread(
                record_clock_anchor, get_supabase_client(), meeting_id, clock_sec, wall
            )
        )
        self._persist_tasks.add(task)
        task.add_done_callback(self._persist_tasks.discard)

    def _maybe_flush(self, channel_id: str, force: bool = False) -> None:
        """윈도우가 찼으면(또는 강제 시) 버퍼를 잘라 전사 태스크를 띄운다.

        채널당 전사 1건만 동시 실행(순서 보존). in-flight 중에는 버퍼가 계속 자라며
        완료 콜백에서 다시 flush를 시도한다. 버퍼 상한 초과분은 앞에서 폐기한다.
        """
        if channel_id in self._stopping:
            return  # stop() 진행 중 — 새 전사 태스크 생성 금지(고아 방지)
        buf = self._buffers.get(channel_id)
        if not buf:
            return
        rate = settings.openai_realtime_audio_rate
        byps = rate * 2

        if len(buf) > MAX_BUFFER_BYTES:
            drop = len(buf) - MAX_BUFFER_BYTES
            drop -= drop % 2
            del buf[:drop]
            self._buffer_start[channel_id] = self._buffer_start.get(channel_id, 0.0) + drop / byps
            logger.warning("Channel %s: window buffer overflow, dropped %.1fs", channel_id, drop / byps)

        if channel_id in self._inflight:
            return

        # 직전 전사 실패 후 쿨다운 — 복원된 버퍼의 즉시 재시도(핫 루프) 방지
        last_fail = self._last_failure_time.get(channel_id)
        if last_fail is not None and time.monotonic() - last_fail < FAILURE_RETRY_SECONDS:
            return

        buffered_sec = len(buf) / byps
        window = settings.live_batch_window_seconds
        if force:
            if buffered_sec < MIN_FORCE_FLUSH_SECONDS:
                return
            cut = len(buf) - (len(buf) % 2)
        elif buffered_sec >= window:
            # 최대 윈도우 도달(연속 발화) → 꼬리의 조용한 지점에서 컷, 나머지 이월
            if buffered_sec <= window:
                cut = len(buf) - (len(buf) % 2)
            else:
                cut = _find_quiet_cut(bytes(buf), rate, window)
                cut = max(2, min(cut, len(buf) - (len(buf) % 2)))
        elif buffered_sec >= settings.live_batch_min_flush_seconds and self._tail_is_pause(buf, byps):
            # 발화 멈춤(문장 경계) → 조기 flush: 자연 분절(누락↓) + 지연 단축
            cut = len(buf) - (len(buf) % 2)
        else:
            return
        pcm = bytes(buf[:cut])
        del buf[:cut]
        start_sec = self._buffer_start.get(channel_id, 0.0)
        dur = len(pcm) / byps
        self._buffer_start[channel_id] = start_sec + dur

        # 발화 블록이 전혀 없는 윈도우는 API 호출 없이 폐기 (정회/휴지 비용 0)
        if not _has_speech(pcm, rate):
            self._silence_skipped[channel_id] = self._silence_skipped.get(channel_id, 0) + 1
            return

        meeting_id = self._meeting_ids.get(channel_id, channel_id)
        gen = self._generation.get(channel_id, 0)
        self._inflight.add(channel_id)
        t = asyncio.create_task(
            self._transcribe_window(channel_id, meeting_id, pcm, start_sec, dur, gen)
        )
        self._transcribe_tasks[channel_id] = t

        def _reap(fut: asyncio.Task, c: str = channel_id) -> None:
            if self._transcribe_tasks.get(c) is fut:
                self._transcribe_tasks.pop(c, None)

        t.add_done_callback(_reap)

    @staticmethod
    def _tail_is_pause(buf: bytearray, byps: int) -> bool:
        """버퍼 꼬리가 발화 멈춤(무음)인지 — 조기 flush(문장 경계 분절) 판정."""
        tail_bytes = int(settings.live_batch_pause_flush_seconds * byps)
        tail_bytes -= tail_bytes % 2
        if tail_bytes < 2 or len(buf) < tail_bytes:
            return False
        return _window_rms(bytes(buf[-tail_bytes:])) < settings.live_batch_silence_rms

    # ─── 전사 + 자막 방출 ────────────────────────────────────────────────

    def _build_prompt(self, channel_id: str) -> str:
        """글로서리 + 직전 윈도우 전사 꼬리를 전사 prompt로 합성한다."""
        parts = []
        glossary = self._glossary_prompts.get(channel_id) or ""
        if glossary:
            parts.append(glossary)
        tail = self._prev_tail.get(channel_id) or ""
        if tail:
            # whisper 계열 prompt 관례: 직전 전사 '원문'을 그대로 이어붙인다.
            # ("직전 발언:" 같은 라벨은 모델이 출력에 되풀이하는 에코를 유발)
            parts.append(tail)
        return "\n".join(parts)

    def _restore_window(self, channel_id: str, pcm: bytes, start_sec: float, gen: int) -> None:
        """전사 실패한 윈도우 오디오를 버퍼 앞에 되돌린다 (영구 유실 방지).

        _inflight 직렬화 덕에 실패 pcm과 현 버퍼는 항상 시간적으로 연속이므로
        prepend가 안전하다. 다음 flush에서 합산 재전사되고, 지속 장애 시에는
        MAX_BUFFER_BYTES 상한이 오래된 오디오부터 폐기하는 회로차단기 역할을 한다.
        """
        if self._generation.get(channel_id) != gen:
            return  # 세션이 바뀜 — 죽은 채널 버퍼를 되살리지 않는다
        buf = self._buffers.get(channel_id)
        if buf is None:
            return
        buf[:0] = pcm
        self._buffer_start[channel_id] = start_sec

    async def _transcribe_window(
        self, channel_id: str, meeting_id: str, pcm: bytes, start_sec: float, dur: float, gen: int
    ) -> None:
        try:
            if not self._client:
                return
            rate = settings.openai_realtime_audio_rate
            wav = _pcm_to_wav(pcm, rate)
            create_kwargs: dict = {
                "model": settings.live_batch_model,
                "file": ("window.wav", io.BytesIO(wav), "audio/wav"),
                "language": "ko",
            }
            prompt = self._build_prompt(channel_id)
            if prompt:
                create_kwargs["prompt"] = prompt

            api_t0 = time.monotonic()
            try:
                self._api_calls[channel_id] = self._api_calls.get(channel_id, 0) + 1
                result = await asyncio.wait_for(
                    self._client.audio.transcriptions.create(**create_kwargs),
                    timeout=API_TIMEOUT,
                )
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                logger.warning("Channel %s: batch transcription timeout (%.1fs window)", channel_id, dur)
                self._last_error[channel_id] = "transcription_timeout"
                self._last_failure_time[channel_id] = time.monotonic()
                self._restore_window(channel_id, pcm, start_sec, gen)
                return
            except Exception as e:
                logger.warning("Channel %s: batch transcription failed: %s", channel_id, e)
                self._last_error[channel_id] = f"{type(e).__name__}: {e}"
                self._last_failure_time[channel_id] = time.monotonic()
                self._restore_window(channel_id, pcm, start_sec, gen)
                return

            self._last_failure_time.pop(channel_id, None)
            if self._generation.get(channel_id) != gen:
                return  # stop/재시작됨 — stale 결과 폐기

            api_sec = time.monotonic() - api_t0
            ready_lag = self._record_window_metrics(channel_id, start_sec=start_sec, api_sec=api_sec)
            edge_lag = (self._edge_lags.get(channel_id) or [None])[-1]
            sync_need = (self._sync_needs.get(channel_id) or [None])[-1]
            # 회의 전체 분포는 이 로그로 집계한다(상태 방송은 최근 100창). text_tokens 는 프롬프트(글로서리+꼬리)
            # 토큰 실측 — 청구서와 대조할 유일한 근거(코드 주석의 +$0.07/h 와 추정 +$0.3~0.5/h 가 갈린다).
            usage = getattr(result, "usage", None) if not isinstance(result, dict) else result.get("usage")
            text_tokens = getattr(getattr(usage, "input_token_details", None), "text_tokens", None)
            logger.info(
                "Channel %s: window %.1fs api %.2fs ready_lag %.1fs edge_lag %s sync_need %s text_tokens %s",
                channel_id, dur, api_sec, ready_lag, edge_lag, sync_need, text_tokens,
            )

            if isinstance(result, dict):
                text = (result.get("text") or "").strip()
            else:
                text = (getattr(result, "text", "") or "").strip()
            if not text:
                return

            # 사전 보정(숫자변환 포함) → 위원 이름 명부 교정 (윈도우 전체 문맥으로 적용)
            corrected = _dictionary.correct(text)
            text = corrected if corrected.strip() else text
            try:
                roster = speaker_cue_tracker.roster_names(channel_id)
                if roster:
                    text = correct_member_names(text, roster)
                # 의원명 교정 직후 집행부 공무원 이름 교정 (staff_roster 명부)
                staff = speaker_cue_tracker.staff_names(channel_id)
                if staff:
                    text = correct_staff_names(text, staff)
            except Exception as e:
                logger.debug("name correct skipped: %s", e)

            # 프롬프트 에코 중복 제거 — 직전 윈도우와 겹친 부분 절단/전체 폐기
            prev_tail = self._prev_tail.get(channel_id, "")
            text = _strip_overlap(prev_tail, text)
            if not text:
                self._dup_skipped[channel_id] = self._dup_skipped.get(channel_id, 0) + 1
                logger.debug("Channel %s: duplicate window dropped (prompt echo)", channel_id)
                return  # _prev_tail은 유지 (다음 윈도우 비교 기준)

            # 다음 윈도우 prompt에 이어 붙일 문맥 꼬리 갱신
            self._prev_tail[channel_id] = text[-settings.live_batch_context_chars:]

            await self._emit_sentences(channel_id, meeting_id, text, start_sec, start_sec + dur, gen, pcm)
        finally:
            # 세대가 일치할 때만 — 고아 태스크가 신세션의 in-flight 게이트를 풀거나
            # 죽은 채널의 flush를 되살리지 못하게 한다.
            if self._generation.get(channel_id) == gen:
                self._inflight.discard(channel_id)
                # in-flight 동안 쌓인 버퍼가 윈도우를 넘겼으면 곧바로 다음 전사
                self._maybe_flush(channel_id)

    async def _emit_sentences(
        self, channel_id: str, meeting_id: str, text: str, start: float, end: float, gen: int,
        pcm: bytes | None = None,
    ) -> None:
        """윈도우 전사를 문장 단위 자막으로 분리해 브로드캐스트 + DB 저장한다."""
        # 서버 기준 생성 상태 갱신 (상태 방송용 — 평균 간격 실측 포함)
        now_wall = time.monotonic()
        prev_wall = self._last_emit_wall.get(channel_id)
        if prev_wall is not None and 2.0 <= now_wall - prev_wall <= 40.0:
            gaps = self._emit_gaps.setdefault(channel_id, [])
            gaps.append(now_wall - prev_wall)
            del gaps[:-8]
        self._last_emit_wall[channel_id] = now_wall

        rate = settings.openai_realtime_audio_rate
        for sentence, s0, s1 in split_sentences_with_timestamps(text, start, end, pcm, rate):
            if self._generation.get(channel_id) != gen:
                return  # 방출 도중 stop/재시작 — 정리된 히스토리를 되살리지 않는다
            counter = self._subtitle_counter.get(channel_id, 0)
            self._subtitle_counter[channel_id] = counter + 1

            subtitle_data = {
                "subtitle": {
                    "id": str(uuid.uuid4()),
                    "meeting_id": meeting_id,
                    "text": sentence,
                    "start_time": s0,
                    "end_time": s1,
                    "confidence": None,
                    "speaker": None,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            }

            logger.info("Channel %s: [STT-batch] %s", channel_id, sentence[:80])
            await manager.broadcast_subtitle(channel_id, subtitle_data)

            # 라이브 GPT 사후 교정 큐 (글로서리 바이어스 — '교정 중'→'교정됨')
            try:
                live_corrector.enqueue(
                    channel_id, meeting_id, subtitle_data["subtitle"]["id"], sentence
                )
            except Exception as e:
                logger.debug("live correct enqueue skipped: %s", e)

            # 구조 인지형 단서 감지 (호명/자기소개 → 화자 추적 상태 갱신)
            try:
                speaker_cue_tracker.observe(channel_id, sentence)
            except Exception as e:
                logger.debug("cue observe skipped: %s", e)

            # 요구자료 감지 (의원 자료 제출 요구 — 프리필터 후 디바운스 LLM 판정)
            try:
                material_request_detector.observe(
                    channel_id, meeting_id, subtitle_data["subtitle"]
                )
            except Exception as e:
                logger.debug("material request observe skipped: %s", e)

            if meeting_id != channel_id:
                t = asyncio.create_task(self._persist_subtitle(subtitle_data))
                self._persist_tasks.add(t)
                t.add_done_callback(self._persist_tasks.discard)

    async def _persist_subtitle(self, subtitle_data: dict) -> None:
        """자막을 Supabase에 저장 (fire-and-forget, 추적됨).

        동기 Supabase 클라이언트라 스레드로 오프로딩 — 이벤트 루프 블로킹 방지.
        """
        try:
            await asyncio.to_thread(self._persist_subtitle_sync, subtitle_data)
        except Exception as e:
            logger.warning("Failed to persist subtitle %s: %s", subtitle_data["subtitle"].get("id", "?"), e)

    def _persist_subtitle_sync(self, subtitle_data: dict) -> None:
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
            "kind": "live",  # 실시간 방송 자막 — AI 자막과 비교용으로 보존
        }).execute()
        if meeting_id not in self._stage_promoted:
            try:
                get_supabase_client().table("meetings").update(
                    {"subtitle_stage": "draft"}
                ).eq("id", meeting_id).eq("subtitle_stage", "none").execute()
                self._stage_promoted.add(meeting_id)
            except Exception as se:
                logger.debug("subtitle_stage promote skipped: %s", se)

    # ─── 자막 생성 상태 방송 (서버 단일 진실 — 모든 시청자 동일) ────────────

    def _record_window_metrics(self, channel_id: str, *, start_sec: float, api_sec: float) -> float:
        """창 하나의 계측값을 기록하고 준비 지연(초)을 돌려준다.

        ready_lag = 지금 오디오 시계 − 창 시작. 창의 첫 발화가 실제로 몇 초 전이었나 —
        영상을 라이브 엣지에서 최소 이만큼(+수집 지연)은 늦춰야 자막이 항상 먼저 준비된다.
        """
        ready_lag = round(max(0.0, self._audio_sec.get(channel_id, 0.0) - start_sec), 1)
        self._api_secs.setdefault(channel_id, deque(maxlen=100)).append(round(api_sec, 2))
        self._ready_lags.setdefault(channel_id, deque(maxlen=100)).append(ready_lag)
        edge = self._edge_lag_now(channel_id)
        if edge is not None:
            self._edge_lags.setdefault(channel_id, deque(maxlen=100)).append(edge)
            self._sync_needs.setdefault(channel_id, deque(maxlen=100)).append(round(ready_lag + edge, 1))
        return ready_lag

    def _edge_lag_now(self, channel_id: str) -> Optional[float]:
        """디코더(_audio_sec)가 우리 재생목록 엣지보다 몇 초 뒤인가 — 셋 중 하나라도 없으면 None.

        (_fed_clock − _audio_sec) = ffmpeg 가 아직 안 내놓은 음성, (지금 − _edge_wall) = 최신
        세그먼트를 재생목록에서 본 뒤 흐른 시간. 브라우저의 estimateLiveEdge 도 같은 식으로 전진한다.
        """
        wall = self._edge_wall.get(channel_id)
        fed = self._fed_clock.get(channel_id)
        audio = self._audio_sec.get(channel_id)
        if wall is None or fed is None or audio is None:
            return None
        return round(max(0.0, (fed - audio) + (time.monotonic() - wall)), 1)

    def get_sync_info(self, channel_id: str) -> dict:
        """영상 지연 목표와 그 근거 계측값 — GET /api/channels/{id}/stt/status 가 그대로 돌려준다.

        sync_target_recommended 는 진단용이다(최근 100창 sync_need 최댓값 + 1, 표본 20 미만이면 None).
        클라이언트는 쓰지 않는다 — 목표는 회의 전체 로그의 p99 를 보고 사람이 env 로 정한다.
        """
        ready_lags = self._ready_lags.get(channel_id) or ()
        edge_lags = self._edge_lags.get(channel_id) or ()
        sync_needs = self._sync_needs.get(channel_id) or ()
        need_max = max(sync_needs) if sync_needs else None
        return {
            "sync_target_sec": live_sync_target_sec(),
            "window_seconds": settings.live_batch_window_seconds,
            "min_flush_seconds": settings.live_batch_min_flush_seconds,
            "pause_flush_seconds": settings.live_batch_pause_flush_seconds,
            "model": settings.live_batch_model,
            "samples": len(ready_lags),
            "ready_lag_p50": _percentile(ready_lags, 50),
            "ready_lag_p95": _percentile(ready_lags, 95),
            "ready_lag_max": max(ready_lags) if ready_lags else None,
            "edge_lag_last": edge_lags[-1] if edge_lags else None,
            "edge_lag_p95": _percentile(edge_lags, 95),
            "sync_need_p95": _percentile(sync_needs, 95),
            "sync_need_max": need_max,
            "sync_target_recommended": (
                max(SYNC_TARGET_MIN_SEC, min(SYNC_TARGET_MAX_SEC, math.ceil(need_max + 1.0)))
                if need_max is not None and len(sync_needs) >= 20 else None
            ),
        }

    def _build_status_payload(self, channel_id: str) -> dict:
        """채널의 현재 자막 생성 상태를 서버 관점에서 판정한다.

        state:
          generating = 최근 30초 내 자막 방출 (정상 생성 중)
          listening  = 스트림은 살아 있으나 발언이 없음 (무음 — 발언 시작 대기)
          idle       = 스트림 정지/미가동 (정회·방송 종료 가능성)
        """
        now = time.monotonic()
        last_emit = self._last_emit_wall.get(channel_id)
        since_emit = round(now - last_emit, 1) if last_emit is not None else None
        last_pcm = self._last_pcm_time.get(channel_id)
        stream_alive = last_pcm is not None and (now - last_pcm) < 10.0

        if not self.is_running(channel_id):
            state = "idle"
        elif since_emit is not None and since_emit < 30.0:
            state = "generating"
        elif stream_alive:
            state = "listening"
        else:
            state = "idle"

        gaps = self._emit_gaps.get(channel_id) or []
        avg = round(sum(gaps) / len(gaps), 1) if len(gaps) >= 2 else None
        api_secs = self._api_secs.get(channel_id) or ()
        ready_lags = self._ready_lags.get(channel_id) or ()
        edge_lags = self._edge_lags.get(channel_id) or ()
        sync_needs = self._sync_needs.get(channel_id) or ()
        parser = self._parsers.get(channel_id)
        return {
            "state": state,
            "seconds_since_subtitle": since_emit,
            "avg_interval": avg,
            # 자막 준비 지연 계측 — 프런트 영상 지연 목표의 근거 (window.__syncDebug 로 확인)
            "api_sec_last": api_secs[-1] if api_secs else None,
            "ready_lag_last": ready_lags[-1] if ready_lags else None,
            "ready_lag_p95": _percentile(ready_lags, 95),
            # 수집 지연(디코더 ↔ 재생목록 엣지)과 그 합 — 영상 지연 목표 = ceil(sync_need_p99 + 1) 의 근거
            "edge_lag_last": edge_lags[-1] if edge_lags else None,
            "edge_lag_p95": _percentile(edge_lags, 95),
            "sync_need_p95": _percentile(sync_needs, 95),
            "sync_need_max": max(sync_needs) if sync_needs else None,
            "samples": len(ready_lags),
            # 지금 적용 중인 영상 지연 목표(서버 env)와 창 길이 — 프런트 진단·게이지 상수의 근거
            "sync_target_sec": live_sync_target_sec(),
            "window_seconds": settings.live_batch_window_seconds,
            # 원본 재생목록 깊이(초) — 영상 지연 목표가 이보다 깊으면 접속 직후 톱업 정지
            "hls_window_sec": getattr(parser, "window_seconds", None) if parser else None,
            # 영상-자막 정밀 동기화 앵커: 지금까지 디코딩한 누적 오디오 초.
            # 자막 start_time/end_time과 같은 시계 — 프런트가 영상 재생 위치를
            # 이 시계로 역산해 "영상이 그 발언에 도달하는 순간" 자막을 표시한다.
            "audio_clock": round(self._audio_sec.get(channel_id, 0.0), 1),
            # 현재 이 채널을 보고 있는 시청자 수 (자막 WS 룸 연결 수)
            "viewers": len(manager.active_connections.get(channel_id, [])),
        }

    async def _status_broadcast_loop(self) -> None:
        """2초마다 활성 채널의 생성 상태를 채널 룸에 방송한다.

        프런트 상태 바가 '각 브라우저의 수신 시점'이 아니라 백엔드의 실제 상태를
        표시하게 한다 — 방송 중간에 들어온 시청자도 즉시 올바른 상태를 본다.
        """
        try:
            while True:
                await asyncio.sleep(2.0)
                for channel_id in self.active_channels:
                    try:
                        payload = self._build_status_payload(channel_id)
                        await manager.broadcast_stt_status(channel_id, payload)
                    except Exception as e:
                        logger.debug("stt status broadcast failed ch=%s: %s", channel_id, e)
        except asyncio.CancelledError:
            return

    # ─── 워치독 ──────────────────────────────────────────────────────────

    async def _watchdog(self, channel_id: str) -> None:
        """PCM이 STALL_TIMEOUT 동안 전혀 안 들어오면 세션을 끝내 재연결을 유도한다."""
        while True:
            await asyncio.sleep(STALL_TIMEOUT / 2)
            last = self._last_pcm_time.get(channel_id, time.monotonic())
            if time.monotonic() - last > STALL_TIMEOUT:
                logger.warning(
                    "Channel %s: no PCM for %.0fs, forcing session restart",
                    channel_id, time.monotonic() - last,
                )
                return


# 싱글톤 접근은 openai_realtime_stt.get_channel_stt_service() 팩토리로 일원화한다.
# (별도 접근자를 두면 상태가 분리된 두 번째 인스턴스가 생겨 이중 STT 위험)
