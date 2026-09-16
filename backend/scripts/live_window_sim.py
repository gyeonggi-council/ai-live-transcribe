# -*- coding: utf-8 -*-
"""운영 라이브 STT 의 창 분절 규칙을 오프라인 PCM 에 그대로 적용하는 시뮬레이터 (2026-09-14).

`live_batch_stt._maybe_flush` 의 규칙 — ① 최대 창(`window`) 도달 → 꼬리의 조용한 지점 컷(`_find_quiet_cut`), 나머지 이월
② 버퍼 ≥ `min_flush` 이고 꼬리 `pause_flush` 초가 무음이면 조기 flush(문장 경계) ③ 발화 블록이 없는 창은 API 없이 폐기 —
과 `_read_pcm_loop` 의 0.5초 단위 판정, 채널당 in-flight 1건 차단(전사 중에는 버퍼가 자라고 완료 뒤 곧바로 재판정),
`_flush_remaining`(EOF 잔여 ≥1초) 을 흉내 낸다. 운영 코드는 손대지 않고 순수 함수(`_find_quiet_cut`·`_has_speech`·
`_window_rms`)를 그대로 import 한다 — `tests/test_live_window_sim.py` 가 같은 합성 PCM 으로 실제 `_maybe_flush` 와
컷 지점이 같음을 단언한다(규칙 복제의 갈라짐 방지).

`stt_eval.transcribe_batch` 의 고정 창 분할은 조기 flush 를 재현하지 못해(운영 12초 창의 실측 평균은 8.8초) 창 길이 실험의
비교 조건이 될 수 없다 — 창 축소 실험(docs/live-sync-eval-2026-09.md)은 이 시뮬레이터로 (12,6)·(8,6)·(8,4) 를 같은 오디오에 돌린다.

사용:
    sim = LiveWindowSimulator(pcm, RATE, window=8.0, min_flush=4.0)
    gen = sim.windows()
    win = next(gen)                       # SimWindow(start_sec, pcm, reason) — 무음 창은 나오지 않는다
    while True:
        api_sec = ...전사 호출 시간...
        try:
            win = gen.send(api_sec)       # in-flight 재현 — 다음 창은 이 시간이 지난 뒤에야 잘린다
        except StopIteration:
            break
    sim.stats()                           # 창 수·평균/p95 창·ready_lag p50/p95/p99 ...

ready_lag 는 운영 정의(`_record_window_metrics`)와 같다 — 방출 시점 오디오 시계 − 창 시작 = 컷까지 쌓인 버퍼 + API 시간.
"""
from __future__ import annotations

import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Generator, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings  # noqa: E402
from app.services.live_batch_stt import (  # noqa: E402
    MIN_FINAL_FLUSH_SECONDS,
    READ_CHUNK_SECONDS,
    _find_quiet_cut,
    _has_speech,
    _window_rms,
)


@dataclass
class SimWindow:
    start_sec: float
    pcm: bytes
    reason: str  # 'window' | 'pause' | 'eof'

    @property
    def dur(self) -> float:  # 채워진 뒤 계산 — 호출자가 rate 를 안다
        return 0.0


def _percentile(values, pct: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * pct / 100.0
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 2)


@dataclass
class LiveWindowSimulator:
    pcm: bytes
    rate: int
    window: float = float(settings.live_batch_window_seconds)
    min_flush: float = float(settings.live_batch_min_flush_seconds)
    pause_flush: float = float(settings.live_batch_pause_flush_seconds)
    # ★_find_quiet_cut·_has_speech 는 settings.live_batch_silence_rms 를 직접 읽는다 — 다른 값으로 실험하려면
    #   settings 를 monkeypatch 해야 운영과 같은 함수가 같은 임계값을 쓴다.
    silence_rms: float = float(settings.live_batch_silence_rms)
    chunk_sec: float = READ_CHUNK_SECONDS
    # 기록
    window_durs: list[float] = field(default_factory=list)
    ready_lags: list[float] = field(default_factory=list)
    api_secs: list[float] = field(default_factory=list)
    reasons: Counter = field(default_factory=Counter)
    silent_windows: int = 0

    @property
    def byps(self) -> int:
        return self.rate * 2

    def _tail_is_pause(self, buf: bytearray) -> bool:
        tail_bytes = int(self.pause_flush * self.byps)
        tail_bytes -= tail_bytes % 2
        if tail_bytes < 2 or len(buf) < tail_bytes:
            return False
        return _window_rms(bytes(buf[-tail_bytes:])) < self.silence_rms

    def _maybe_cut(self, buf: bytearray) -> Optional[tuple[int, str]]:
        """_maybe_flush 의 컷 판정 — (컷 바이트, 사유) 또는 None. 무음 폐기는 호출자가 판정한다."""
        buffered_sec = len(buf) / self.byps
        if buffered_sec >= self.window:
            if buffered_sec <= self.window:
                cut = len(buf) - (len(buf) % 2)
            else:
                cut = _find_quiet_cut(bytes(buf), self.rate, self.window)
                cut = max(2, min(cut, len(buf) - (len(buf) % 2)))
            return cut, "window"
        if buffered_sec >= self.min_flush and self._tail_is_pause(buf):
            return len(buf) - (len(buf) % 2), "pause"
        return None

    def windows(self) -> Generator[SimWindow, Optional[float], None]:
        buf = bytearray()
        buffer_start = 0.0
        t = 0.0  # 지금까지 들어온 오디오 초 (= 운영 _audio_sec)
        inflight_until = 0.0
        chunk_bytes = int(self.chunk_sec * self.byps)
        chunk_bytes -= chunk_bytes % 2
        pos = 0
        n = len(self.pcm)
        while pos < n:
            piece = self.pcm[pos:pos + chunk_bytes]
            # 운영은 API 완료(finally) 순간에 그때까지의 버퍼로 재판정한다 — 완료 시점이 이 0.5초 청크 안이면
            # 청크를 그 시점에서 잘라 앞부분만 넣고 판정한 뒤 나머지를 잇는다(Codex 09-14: 완료 뒤 무음 구간에서
            # 운영은 6초 조기 방출, 시뮬은 8초 컷이 되던 차이).
            if t < inflight_until - 1e-6 and inflight_until < t + len(piece) / self.byps - 1e-6:
                head_bytes = int(round((inflight_until - t) * self.byps))
                head_bytes -= head_bytes % 2
                if 0 < head_bytes < len(piece):
                    piece = piece[:head_bytes]
            pos += len(piece)
            buf.extend(piece)
            t += len(piece) / self.byps
            # in-flight 중엔 판정하지 않는다(운영: _maybe_flush 가 즉시 return). 끝나면 finally 의 재판정처럼
            # 같은 시점에 다시 본다 — API 0초면 연속으로 잘릴 수 있다.
            while t >= inflight_until - 1e-6:  # 부동소수 오차로 완료 시점을 놓치지 않게
                res = self._maybe_cut(buf)
                if res is None:
                    break
                cut, reason = res
                pcm = bytes(buf[:cut])
                del buf[:cut]
                start_sec = buffer_start
                dur = len(pcm) / self.byps
                buffer_start = start_sec + dur
                if not _has_speech(pcm, self.rate):
                    self.silent_windows += 1
                    break  # 운영: 폐기 뒤 return — 다음 청크에서 다시 본다
                api_sec = yield SimWindow(start_sec, pcm, reason)
                api_sec = float(api_sec or 0.0)
                self._record(reason, dur, ready_lag=(t - start_sec) + api_sec, api_sec=api_sec)
                inflight_until = t + api_sec
                if api_sec > 0:
                    break
        # EOF — _flush_remaining: 잔여 ≥ MIN_FINAL_FLUSH_SECONDS 이고 발화가 있으면 1회
        if len(buf) >= int(self.byps * MIN_FINAL_FLUSH_SECONDS):
            pcm = bytes(buf)
            dur = len(pcm) / self.byps
            if _has_speech(pcm, self.rate):
                api_sec = yield SimWindow(buffer_start, pcm, "eof")
                api_sec = float(api_sec or 0.0)
                self._record("eof", dur, ready_lag=(t - buffer_start) + api_sec, api_sec=api_sec)
            else:
                self.silent_windows += 1

    def _record(self, reason: str, dur: float, *, ready_lag: float, api_sec: float) -> None:
        self.reasons[reason] += 1
        self.window_durs.append(round(dur, 2))
        self.ready_lags.append(round(ready_lag, 2))
        self.api_secs.append(round(api_sec, 3))

    def stats(self) -> dict:
        w = self.window_durs
        return {
            "window": self.window, "min_flush": self.min_flush, "pause_flush": self.pause_flush,
            "windows": len(w), "silent_windows": self.silent_windows,
            "reasons": dict(self.reasons),
            "window_mean": round(sum(w) / len(w), 2) if w else None,
            "window_p50": _percentile(w, 50), "window_p95": _percentile(w, 95),
            "window_max": max(w) if w else None,
            "ready_lag_p50": _percentile(self.ready_lags, 50),
            "ready_lag_p95": _percentile(self.ready_lags, 95),
            "ready_lag_p99": _percentile(self.ready_lags, 99),
            "ready_lag_max": max(self.ready_lags) if self.ready_lags else None,
            "api_sec_p50": _percentile(self.api_secs, 50),
            "api_sec_p95": _percentile(self.api_secs, 95),
        }
