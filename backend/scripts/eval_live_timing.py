# -*- coding: utf-8 -*-
"""라이브 자막이 '말이 들리는 순간' 에 뜨는지 채점한다 (2026-09-11, 정본 docs/live-sync-eval-2026-09.md).

기준값(말 시작): 한국어 zipformer 토큰 시각(--asr zipformer, 기본)으로 자막 첫 글자를 찾는다.
whisper-1 단어 시각(--asr whisper)은 쉼 뒤 첫 단어를 쉼 쪽으로 늘려 잡아 0.5~3초씩 틀려 비교용으로만 둔다.

두 모드:
  --server MEETING --from T0 --to T1
      서버 녹음(mp3 + .sessions 색인) + DB 실시간 자막으로 '자막 시각(start_time)' 의 오차를 잰다.
      같은 창을 운영 코드의 time_sentences 로 다시 배분한 값도 함께 잰다 (규칙 전/후 비교).
  --e2e PREFIX
      e2e_sync_capture.js 가 남긴 PREFIX.webm(영상이 낸 음성) + PREFIX.json(WS 자막·화면 등장 벽시계)으로
      '화면에 뜬 순간' 의 오차를 잰다 — 시청자가 겪는 그대로.

오차 = 자막 시각 − 말 시작 (음수 = 말보다 일찍). 주 지표: |오차| ≤ 1.0초 비율.

사용 (파드 /tmp/eval, PYTHONPATH=/tmp/eval — 이 저장소 backend/app 사본을 /tmp/eval/app 에 둔다):
    python scripts/eval_live_timing.py --server <meeting_id> --from 21300 --to 21800 --out timing.json
    python scripts/eval_live_timing.py --e2e /tmp/eval/base1 --out e2e.json
"""
from __future__ import annotations

import argparse
import difflib
import io
import json
import re
import subprocess
import sys
import wave
from array import array
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

RATE = 16000
CHUNK_SEC = 480  # whisper 파일 한도(25MB) 안 — 16kHz wav 8분 ≈ 15MB
EDGE_SEC = 3.0  # 청크 가장자리 단어는 잘렸을 수 있어 버린다
FRAME_SEC = 0.02
_KEEP = re.compile(r"[0-9A-Za-z가-힣]")


def ffmpeg_pcm(src_args: list[str], rate: int, data: bytes | None = None) -> bytes:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", *src_args,
           "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "pipe:1"]
    return subprocess.run(cmd, input=data, capture_output=True, check=True).stdout


def wav_bytes(pcm: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def whisper_words(pcm: bytes, rate: int = RATE) -> list[tuple[str, float, float]]:
    from openai import OpenAI

    from app.core.config import settings

    client = OpenAI(api_key=settings.openai_api_key)
    byps = rate * 2
    step = CHUNK_SEC * byps
    out: list[tuple[str, float, float]] = []
    for off in range(0, len(pcm), step):
        piece = pcm[off: off + step]
        if len(piece) < byps:
            break
        r = client.audio.transcriptions.create(
            model="whisper-1",
            file=("a.wav", io.BytesIO(wav_bytes(piece, rate)), "audio/wav"),
            language="ko",
            response_format="verbose_json",
            timestamp_granularities=["word"],
        )
        base, dur = off / byps, len(piece) / byps
        for w in getattr(r, "words", None) or []:
            s, e = float(w.start), float(w.end)
            if (off > 0 and s < EDGE_SEC) or (off + step < len(pcm) and e > dur - EDGE_SEC):
                continue
            out.append((w.word, base + s, base + e))
    return out


ZIP_DIR = "/tmp/eval/models"  # sherpa-onnx-zipformer-korean-2024-06-24 의 int8 파일 (평가 전용, 이미지에 없다)
ZIP_CHUNK_SEC = 25.0


def zipformer_words(pcm: bytes, rate: int = RATE) -> list[tuple[str, float, float]]:
    """한국어 zipformer(오프라인 transducer) 토큰과 시각 — 토큰 시각이 말 시작과 ±0.1초 안이다.

    whisper 단어 시각은 쉼 앞뒤에서 0.5~3초씩 틀려(쉼 쪽으로 늘려 잡는다) 기준값으로 못 쓴다 (2026-09-11 대조).
    25초 조각을 조각 꼬리의 가장 조용한 0.1초에서 잘라 디코딩한다. (토큰, 시작, 다음 토큰 시작) 을 돌려준다.
    """
    import numpy as np
    import sherpa_onnx

    rec = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=f"{ZIP_DIR}/encoder-epoch-99-avg-1.int8.onnx", decoder=f"{ZIP_DIR}/decoder-epoch-99-avg-1.onnx",
        joiner=f"{ZIP_DIR}/joiner-epoch-99-avg-1.int8.onnx", tokens=f"{ZIP_DIR}/tokens.txt",
        num_threads=1, sample_rate=rate, feature_dim=80, decoding_method="greedy_search")
    x = np.frombuffer(pcm[: len(pcm) - len(pcm) % 2], dtype=np.int16).astype(np.float32) / 32768.0
    blk = int(0.1 * rate)
    toks: list[tuple[str, float]] = []
    pos = 0
    while pos < len(x):
        end = min(len(x), pos + int(ZIP_CHUNK_SEC * rate))
        if end < len(x):  # 꼬리 5초에서 가장 조용한 블록에서 자른다
            lo = end - 50 * blk
            energy = [float(np.mean(x[i:i + blk] ** 2)) for i in range(lo, end - blk, blk)]
            end = lo + blk * int(np.argmin(energy)) + blk // 2
        st = rec.create_stream()
        st.accept_waveform(rate, x[pos:end])
        rec.decode_stream(st)
        toks += [(t.replace("▁", "").strip(), pos / rate + ts) for t, ts in zip(st.result.tokens, st.result.timestamps)]
        pos = end
    toks = [t for t in toks if t[0]]
    return [(t, s, toks[i + 1][1] if i + 1 < len(toks) else s + 0.3) for i, (t, s) in enumerate(toks)]


def _chars(s: str) -> list[str]:
    return [c for c in s if _KEEP.match(c)]


def align_first_words(texts: list[str], words: list[tuple[str, float, float]]) -> list[int | None]:
    """각 자막의 첫 글자가 whisper 의 몇 번째 단어인가 (확신이 없으면 None)."""
    W: list[str] = []
    w_of: list[int] = []
    for k, (w, _, _) in enumerate(words):
        for c in _chars(w):
            W.append(c)
            w_of.append(k)
    S: list[str] = []
    first: list[int] = []
    for t in texts:
        first.append(len(S))
        S.extend(_chars(t))
    first.append(len(S))
    s2w: dict[int, int] = {}
    for a, b, n in difflib.SequenceMatcher(None, S, W, autojunk=False).get_matching_blocks():
        for j in range(n):
            s2w[a + j] = b + j
    out: list[int | None] = []
    for i in range(len(texts)):
        head = list(range(first[i], min(first[i + 1], first[i] + 8)))
        hit = [x for x in head if x in s2w]
        # 머리 8글자 중 75% 이상이 whisper 쪽 한 덩어리에 붙고, 첫 일치가 앞 2글자 안이어야 믿는다.
        # 앞 글자를 whisper 가 빠뜨린 경우('그' 등) 한 글자 앞으로 당기면 앞 단어에 붙는다 — 당기지 않는다.
        if (not head or len(hit) < max(3, int(0.75 * len(head))) or hit[0] - head[0] > 1
                or s2w[hit[-1]] - s2w[hit[0]] > 2 * len(head)):
            out.append(None)
            continue
        out.append(w_of[s2w[hit[0]]])
    return out


def frame_rms(pcm: bytes, rate: int = RATE) -> list[float]:
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    n = max(1, int(FRAME_SEC * rate))
    out = []
    for i in range(0, len(samples) - n + 1, n):
        blk = samples[i: i + n: 2]
        out.append((sum(s * s for s in blk) / len(blk)) ** 0.5)
    return out


def onset_threshold(frames: list[float]) -> float:
    srt = sorted(frames)
    noise, speech = srt[int(0.2 * len(srt))], srt[int(0.9 * len(srt))]
    return max(250.0, noise + 0.15 * (speech - noise))


def voiced_runs(frames: list[float], thr: float, bridge: float = 0.15) -> list[tuple[float, float]]:
    """문턱 이상 프레임의 연속 구간 (bridge 초보다 짧은 틈은 잇는다)."""
    runs: list[list[float]] = []
    for i, v in enumerate(frames):
        if v < thr:
            continue
        a, b = i * FRAME_SEC, (i + 1) * FRAME_SEC
        if runs and a - runs[-1][1] <= bridge:
            runs[-1][1] = b
        else:
            runs.append([a, b])
    return [(a, b) for a, b in runs]


def speech_onset(runs: list[tuple[float, float]], s: float, e: float) -> float:
    """whisper 단어 [s, e] 의 실제 말 시작.

    whisper 는 쉼 뒤 첫 단어를 쉼 쪽으로 늘려 잡는다(시작이 이르다). 그래서 단어 '끝' 을 품은 발성 덩어리를
    찾고 — 그 덩어리가 단어 시작 뒤에서 시작했으면(쉼 뒤) 덩어리 시작이 말 시작이고, 앞에서부터 이어졌으면
    (연속 발화 속) whisper 시작을 믿는다. 단어 끝이 쉼에 떨어졌으면 1.5초 안의 다음 덩어리 시작.
    """
    for a, b in runs:
        if a <= e - 0.05 < b or (e - 0.05 < a <= e + 1.5):
            return a if a >= s - 0.1 else s
    return s


def summarize(label: str, errs: list[float]) -> dict:
    if not errs:
        print(f"{label}: 표본 없음")
        return {"label": label, "n": 0}
    e = sorted(errs)
    n = len(e)

    def pct(lo: float, hi: float) -> float:
        return round(100.0 * sum(1 for x in e if lo <= x <= hi) / n, 1)

    d = {
        "label": label, "n": n,
        "within_1s": pct(-1.0, 1.0), "within_0_5s": pct(-0.5, 0.5),
        "early_gt_1s": round(100.0 * sum(1 for x in e if x < -1.0) / n, 1),
        "late_gt_1s": round(100.0 * sum(1 for x in e if x > 1.0) / n, 1),
        "median": round(e[n // 2], 2), "p10": round(e[int(0.1 * n)], 2), "p90": round(e[int(0.9 * n)], 2),
    }
    print(f"{label}: n={n}  ±1.0s {d['within_1s']}%  ±0.5s {d['within_0_5s']}%  "
          f"일찍>1s {d['early_gt_1s']}%  늦게>1s {d['late_gt_1s']}%  "
          f"중앙 {d['median']:+.2f}  p10 {d['p10']:+.2f}  p90 {d['p90']:+.2f}")
    return d


WORDS_CACHE: str | None = None  # --words-cache: 같은 구간을 규칙만 바꿔 다시 잴 때 인식 비용을 아낀다
ASR = "zipformer"  # --asr: zipformer(기준값 정본) | whisper(비교용 — 쉼 앞뒤 시각이 틀린다)


def truth_onsets(texts: list[str], pcm: bytes) -> list[float | None]:
    try:
        words = [tuple(w) for w in json.load(open(WORDS_CACHE, encoding="utf-8"))] if WORDS_CACHE else None
    except OSError:
        words = None
    if words is None:
        words = zipformer_words(pcm) if ASR == "zipformer" else whisper_words(pcm)
        if WORDS_CACHE:
            json.dump(words, open(WORDS_CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    runs = None if ASR == "zipformer" else voiced_runs(frame_rms(pcm), onset_threshold(frame_rms(pcm)))
    out: list[float | None] = []
    for k in align_first_words(texts, words):
        if k is None:
            out.append(None)
        else:
            out.append(words[k][1] if runs is None else speech_onset(runs, words[k][1], words[k][2]))
    print(f"{ASR} 토큰 {len(words)}개 · 기준값 확보 {sum(o is not None for o in out)}/{len(texts)}")
    return out


# ─── 서버 모드 ────────────────────────────────────────────────────────────


def _ts(v: str) -> float:
    return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()


def group_windows(rows: list[dict]) -> list[list[dict]]:
    """한 창에서 나온 문장들 — 연속(앞 끝 = 뒤 시작)이고 같은 순간에 저장됐다."""
    wins: list[list[dict]] = []
    for r in rows:
        if wins:
            p = wins[-1][-1]
            if abs(float(r["start_time"]) - float(p["end_time"])) < 0.02 and abs(_ts(r["created_at"]) - _ts(p["created_at"])) < 2.0:
                wins[-1].append(r)
                continue
        wins.append([r])
    return wins


def server_mode(mid: str, t0: float, t1: float) -> dict:
    from app.core.database import get_supabase_client
    from app.services.live_recorder import bytes_per_second, recording_path, recording_sessions

    try:
        from app.services.live_batch_stt import time_sentences
    except ImportError:
        time_sentences = None

    sessions = recording_sessions(mid)
    sess = [s for s in sessions if s["clock"] <= t0][-1]
    later = [s for s in sessions if s["byte"] > sess["byte"]]
    if later and later[0]["clock"] < t1:
        raise SystemExit(f"구간이 녹음 세션 경계({later[0]['clock']})를 넘는다 — --to 를 줄일 것")
    bps = bytes_per_second()
    path = recording_path(mid)

    def slice_pcm(a: float, b: float, rate: int) -> bytes:
        b0 = sess["byte"] + int((a - sess["clock"]) * bps)
        b1 = sess["byte"] + int((b - sess["clock"]) * bps)
        with open(path, "rb") as f:
            f.seek(b0)
            data = f.read(b1 - b0)
        return ffmpeg_pcm(["-f", "mp3", "-i", "pipe:0"], rate, data)

    rows = (
        get_supabase_client().table("subtitles")
        .select("id,text,start_time,end_time,created_at")
        .eq("meeting_id", mid).eq("kind", "live")
        .gte("start_time", t0).lt("start_time", t1)
        .order("start_time").execute().data
    )
    new_start: dict[str, float] = {}
    pos: dict[str, int] = {}
    for win in group_windows(rows):
        for i, r in enumerate(win):
            pos[r["id"]] = i
        if time_sentences:
            ws, we = float(win[0]["start_time"]), float(win[-1]["end_time"])
            timed = time_sentences([r["text"] for r in win], ws, we, slice_pcm(ws, we, 24000), 24000)
            for r, (_, s0, _) in zip(win, timed):
                new_start[r["id"]] = s0

    truth = truth_onsets([r["text"] for r in rows], slice_pcm(t0, t1 + 20, RATE))
    per, old, new = [], [], []
    for r, t in zip(rows, truth):
        if t is None:
            continue
        onset = t0 + t
        item = {"text": r["text"][:40], "onset": round(onset, 2), "pos": pos[r["id"]],
                "old": round(float(r["start_time"]) - onset, 2)}
        old.append(item["old"])
        if r["id"] in new_start:
            item["new"] = round(new_start[r["id"]] - onset, 2)
            new.append(item["new"])
        per.append(item)
    res = {"meeting": mid, "from": t0, "to": t1, "windows": len(group_windows(rows)),
           "old": summarize("현행 start_time", old),
           "new": summarize("새 배분 time_sentences", new), "items": per}
    summarize("  └ 새 배분 · 창 첫 문장", [it["new"] for it in per if "new" in it and it["pos"] == 0])
    summarize("  └ 새 배분 · 창 안쪽 문장", [it["new"] for it in per if "new" in it and it["pos"] > 0])
    return res


# ─── 종단(화면) 모드 ────────────────────────────────────────────────────────


def e2e_mode(prefix: str) -> dict:
    cap = json.load(open(prefix + ".json", encoding="utf-8"))
    pcm = ffmpeg_pcm(["-i", prefix + ".webm"], RATE)
    rec0 = cap["recStart"] / 1000.0
    dur = len(pcm) / (RATE * 2)
    subs = [s for s in cap["ws"] if s.get("text")]
    clock = cap["clock"]
    dom = cap["dom"]

    def calc_reveal(s: dict) -> float | None:
        # 페이지 게이팅과 같은 규칙: 영상 시계가 자막 시작을 넘은 첫 순간 (도착 이후)
        for c in clock:
            if c["wall"] >= s["wall"] and c.get("vc") is not None and c["vc"] >= s["start"]:
                return c["wall"] / 1000.0
        return None

    def dom_reveal(s: dict) -> float | None:
        for d in dom:
            if difflib.SequenceMatcher(None, d["text"], s["text"]).ratio() > 0.6:
                return d["wall"] / 1000.0
        return None

    truth = truth_onsets([s["text"] for s in subs], pcm)
    per, e_dom, e_calc = [], [], []
    for s, t in zip(subs, truth):
        rd, rc = dom_reveal(s), calc_reveal(s)
        if t is None or t < EDGE_SEC or t > dur - EDGE_SEC:
            continue
        onset = rec0 + t
        item = {"text": s["text"][:40], "onset_rec": round(t, 2)}
        if rd is not None:
            item["dom"] = round(rd - onset, 2)
            e_dom.append(item["dom"])
        if rc is not None:
            item["calc"] = round(rc - onset, 2)
            e_calc.append(item["calc"])
        per.append(item)
    return {"prefix": prefix, "audio_sec": round(dur, 1), "ws": len(subs),
            "dom": summarize("화면 등장(DOM)", e_dom),
            "calc": summarize("게이팅 재계산(videoClock≥start)", e_calc), "items": per}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server")
    ap.add_argument("--from", dest="t0", type=float)
    ap.add_argument("--to", dest="t1", type=float)
    ap.add_argument("--e2e")
    ap.add_argument("--out")
    ap.add_argument("--words-cache")
    ap.add_argument("--asr", default="zipformer", choices=["zipformer", "whisper"])
    ap.add_argument("--set", action="append", default=[],
                    help="live_batch_stt 상수 덮어쓰기 (예: PAUSE_SNAP_SECONDS=0.5) — 규칙 비교용")
    a = ap.parse_args()
    global WORDS_CACHE, ASR
    WORDS_CACHE = a.words_cache
    ASR = a.asr
    if a.set:
        from app.services import live_batch_stt

        for kv in a.set:
            k, v = kv.split("=", 1)
            setattr(live_batch_stt, k, float(v))
    res = server_mode(a.server, a.t0, a.t1) if a.server else e2e_mode(a.e2e)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
