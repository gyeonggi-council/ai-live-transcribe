# -*- coding: utf-8 -*-
"""라이브 녹음(mp3) 전체를 운영 라이브 경로로 다시 전사해 `_fetch_ai_subs.py` 형식으로 덤프한다.

모델 A/B 를 **회의 전체**에서 같은 속기록에 대고 채점하기 위한 드라이버(2026-09-08). 창 컷·프롬프트(운영 글로서리
900자 + 직전 창 꼬리)·사전 후처리는 `stt_eval.transcribe_batch`/`live_batch_stt` 와 같다. 실시간 GPT 교정
(`live_corrector`)은 포함하지 않는다 — 두 모델 모두 같은 조건이라 상대 비교는 유효하다.

사용 (파드 /tmp/eval, PYTHONPATH=/app):
    python scripts/replay_live.py --audio /app/recordings/<id>.mp3 --meeting <id> --model gpt-transcribe \
        --out _ai_<id8>_replay_gt.txt [--chunk 1800] [--start 0] [--max-seconds N]
    python scripts/eval_live_text.py _steno_<mntsId>.txt _ai_<id8>_replay_gt.txt _livecer_<id8>_replay_gt.json
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

from app.core.config import settings  # noqa: E402
from stt_eval import RATE, extract_pcm, transcribe_batch, transcribe_batch_live  # noqa: E402


def _hms(sec: float) -> str:
    s = int(sec)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


async def run(args: argparse.Namespace) -> None:
    from app.core.database import get_supabase_client
    from app.services.dictionary import get_default_dictionary
    from app.services.glossary_service import format_glossary_prompt, load_meeting_glossary

    prompt = format_glossary_prompt(
        load_meeting_glossary(get_supabase_client(), args.meeting), max_terms=200, max_chars=900
    )
    dictionary = get_default_dictionary()
    byps = RATE * 2
    offset, n_lines, t0 = float(args.start), 0, time.time()
    prev_tail = ""
    chunk_stats: list[dict] = []
    with open(args.out, "w", encoding="utf-8") as f:
        while True:
            if args.max_seconds and offset - args.start >= args.max_seconds:
                break
            pcm = extract_pcm(args.audio, args.chunk, offset)
            if len(pcm) < byps * 5:
                break
            if args.fixed_window:
                finals, stats = await transcribe_batch(pcm, args.model, prompt, None, args.window)
            else:
                # 운영 규칙 재현(조기 flush·in-flight) — 창 실험은 이쪽. prev_tail 은 30분 청크 사이에도 이어진다
                finals, stats = await transcribe_batch_live(
                    pcm, args.model, prompt, None, window=args.window, min_flush=args.min_flush,
                    pause_flush=args.pause_flush, prev_tail=prev_tail,
                )
                prev_tail = stats.pop("prev_tail", prev_tail)
            chunk_stats.append({k: v for k, v in stats.items() if k != "window_starts"})
            starts = stats.get("window_starts") or [0.0] * len(finals)
            for t, text in zip(starts, finals):
                corrected = dictionary.correct(text)
                f.write(f"[{_hms(offset + t)}] ?: {corrected.strip() or text}\n")
                n_lines += 1
            f.flush()
            print(f"[replay] {args.model} {_hms(offset)}+{len(pcm) / byps:.0f}s → 누적 {n_lines}줄 ({time.time() - t0:.0f}s)", flush=True)
            offset += len(pcm) / byps
            if len(pcm) < args.chunk * byps - byps:
                break
    print(f"[replay] 끝 {args.out}: {n_lines}줄, {_hms(offset)} 까지, {time.time() - t0:.0f}s")
    if chunk_stats:
        # 조건별 창·ready_lag 분포 — 창 축소 실험의 "예상 영상 지연 목표" 근거 (청크별 + 합산)
        import json
        durs = [d for c in chunk_stats for d in ([c.get("window_mean")] * 0)]  # placeholder, 합산은 아래
        agg = {
            "model": args.model, "window": args.window, "min_flush": args.min_flush, "pause_flush": args.pause_flush,
            "audio": os.path.basename(args.audio), "start": args.start, "max_seconds": args.max_seconds,
            "windows": sum(c.get("windows", 0) for c in chunk_stats),
            "silent_windows": sum(c.get("silent_windows", 0) for c in chunk_stats),
            "api_calls": sum(c.get("api_calls", 0) for c in chunk_stats),
            "dup_dropped": sum(c.get("dup_dropped", 0) for c in chunk_stats),
            "overlap_trimmed_chars": sum(c.get("overlap_trimmed_chars", 0) for c in chunk_stats),
            "ready_lag_p95_max_over_chunks": max((c.get("ready_lag_p95") or 0) for c in chunk_stats),
            "ready_lag_p99_max_over_chunks": max((c.get("ready_lag_p99") or 0) for c in chunk_stats),
            "window_mean_weighted": round(
                sum((c.get("window_mean") or 0) * c.get("windows", 0) for c in chunk_stats)
                / max(1, sum(c.get("windows", 0) for c in chunk_stats)), 2),
            "chunks": chunk_stats, "lines": n_lines, "elapsed_sec": round(time.time() - t0),
        }
        del durs
        with open(args.out + ".stats.json", "w", encoding="utf-8") as sf:
            json.dump(agg, sf, ensure_ascii=False, indent=1)
        print(f"[replay] 통계 {args.out}.stats.json · 창 {agg['windows']} 평균 {agg['window_mean_weighted']}s · "
              f"ready_lag p95≤{agg['ready_lag_p95_max_over_chunks']} p99≤{agg['ready_lag_p99_max_over_chunks']} · "
              f"에코 폐기 {agg['dup_dropped']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--meeting", required=True, help="운영 글로서리 프롬프트를 만들 회의 id")
    ap.add_argument("--model", default=settings.live_batch_model)
    ap.add_argument("--out", required=True)
    ap.add_argument("--chunk", type=int, default=1800, help="ffmpeg 추출 단위(초) — 메모리 상한(30분 ≈ 86MB PCM)")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--max-seconds", type=float, default=0.0)
    ap.add_argument("--window", type=float, default=settings.live_batch_window_seconds, help="최대 창(초)")
    ap.add_argument("--min-flush", type=float, default=settings.live_batch_min_flush_seconds, help="조기 flush 최소 버퍼(초)")
    ap.add_argument("--pause-flush", type=float, default=settings.live_batch_pause_flush_seconds, help="조기 flush 꼬리 무음(초)")
    ap.add_argument("--fixed-window", action="store_true",
                    help="옛 방식(고정 창, 조기 flush 없음) — 09-08 결과 재현용. 기본은 운영 규칙 재현(live_window_sim)")
    args = ap.parse_args()
    if not settings.openai_api_key:
        print("OPENAI_API_KEY 미설정")
        return 1
    asyncio.run(run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
