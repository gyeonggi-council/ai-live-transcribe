"""화자 임베딩 모델 타당성·임계값 보정 (Phase 0b 스파이크). 읽기 전용 평가 도구 (제품코드 아님).

속기록(정답 화자)에 정렬한 AI 자막으로 '정답 화자 창(window)'을 만들고, 각 창의 임베딩을
사전학습 ONNX 모델(sherpa-onnx, CPU)로 뽑아 다음을 잰다.
  1. same/diff 화자 쌍의 코사인 분포 → EER (모델이 이 방송 오디오에서 화자를 가르는가)
  2. 앵커 시뮬레이션: 화자별 처음 K개 창을 앵커로 centroid → 나머지 창 top-1 정확도
     (Phase 1a 의 "앵커 centroid + 창 판정" 이 얼마나 맞을지 미리 본다)
  3. 처리 속도(RTF)·최대 RSS

사용 (파드 /tmp/eval 에서, PYTHONPATH=/app:/tmp/eval/pylib):
  python scripts/eval_voice_calibration.py --meeting <id> --steno _steno_N.txt \
      --model models/a.onnx [--model models/b.onnx] [--pcm pcm_<id8>.raw] [--out out.json]
--pcm 이 없으면 vod_url 에서 ffmpeg 로 16kHz mono s16le 를 추출해 그 경로에 저장한다(재사용).
"""

from __future__ import annotations

# ruff: noqa: N803, N806  (numpy 행렬은 관례상 대문자)

import argparse
import json
import os
import resource
import subprocess
import sys
import time

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _steno_align import align, parse_steno  # noqa: E402  (정렬·파싱 공용 모듈)

RATE = 16000


def align_subs(subs: list[dict], steno: list) -> list[tuple[dict, str | None, bool, float]]:
    """AI 자막 → (자막, 정답 화자, 위원 여부, 유사도). 미정렬은 화자 None·유사도 0."""
    mapping = align([s.get("text") or "" for s in subs], [t for _, t, _ in steno])
    out = []
    for s, mp in zip(subs, mapping, strict=False):
        if mp is None:
            out.append((s, None, False, 0.0))
        else:
            j, sim = mp
            spk, _, mem = steno[j]
            out.append((s, spk, mem, sim))
    return out


# ── 창 만들기 (Phase 1a 와 같은 규칙: 같은 화자 연속, 간격 <1s, ≤max, ≥min) ──
def build_windows(aligned, max_s=10.0, min_s=1.5) -> list[dict]:
    wins: list[dict] = []
    cur = None
    for s, spk, mem, r in aligned:
        if not spk:
            cur = None
            continue
        st, en = float(s.get("start_time") or 0), float(s.get("end_time") or 0)
        if en <= st:
            continue
        if cur and cur["spk"] == spk and st - cur["end"] < 1.0 and en - cur["start"] <= max_s:
            cur["end"] = en
            cur["n"] += 1
        else:
            cur = {"spk": spk, "member": mem, "start": st, "end": en, "n": 1}
            wins.append(cur)
    return [w for w in wins if w["end"] - w["start"] >= min_s]


def ensure_pcm(vod_url: str, pcm_path: str) -> float:
    if not os.path.exists(pcm_path) or os.path.getsize(pcm_path) < RATE * 2 * 10:
        t0 = time.monotonic()
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-user_agent",
                "Mozilla/5.0",
                "-i",
                vod_url,
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(RATE),
                "-f",
                "s16le",
                pcm_path,
            ],
            check=True,
            timeout=3600,
        )
        print(f"# pcm extracted in {time.monotonic() - t0:.0f}s", file=sys.stderr)
    return os.path.getsize(pcm_path) / (RATE * 2)


def embed_windows(
    model_path: str, pcm: np.memmap, wins: list[dict], threads: int = 1
) -> tuple[np.ndarray, float]:
    import sherpa_onnx  # /tmp/eval/pylib

    cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=model_path, num_threads=threads, debug=False, provider="cpu"
    )
    ext = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
    embs = np.zeros((len(wins), ext.dim), dtype=np.float32)
    t0 = time.monotonic()
    for i, w in enumerate(wins):
        a, b = int(w["start"] * RATE), int(w["end"] * RATE)
        x = np.asarray(pcm[a:b], dtype=np.float32) / 32768.0
        st = ext.create_stream()
        st.accept_waveform(sample_rate=RATE, waveform=x)
        st.input_finished()
        embs[i] = np.asarray(ext.compute(st), dtype=np.float32)
    embs /= np.linalg.norm(embs, axis=1, keepdims=True) + 1e-9
    return embs, time.monotonic() - t0


def eer(scores_same: np.ndarray, scores_diff: np.ndarray) -> tuple[float, float]:
    """EER 과 그 지점의 임계값. FRR = same 중 임계 미만, FAR = diff 중 임계 이상."""
    same_sorted, diff_sorted = np.sort(scores_same), np.sort(scores_diff)
    ths = np.linspace(-1, 1, 2001)
    frr = np.searchsorted(same_sorted, ths, side="left") / max(1, len(same_sorted))
    far = 1.0 - np.searchsorted(diff_sorted, ths, side="left") / max(1, len(diff_sorted))
    i = int(np.argmin(np.abs(frr - far)))
    return float((frr[i] + far[i]) / 2), float(ths[i])


def anchor_sim(embs: np.ndarray, wins: list[dict], k: int) -> dict:
    """화자별 처음 k 창 = 앵커(centroid), 나머지 창 top-1 정확도 (+ 마진 0.10 적용 시)."""
    by_spk: dict[str, list[int]] = {}
    for i, w in enumerate(wins):
        by_spk.setdefault(w["spk"], []).append(i)
    cents, rest = {}, []
    for spk, idxs in by_spk.items():
        if len(idxs) < k + 2:
            continue
        c = embs[idxs[:k]].mean(axis=0)
        cents[spk] = c / (np.linalg.norm(c) + 1e-9)
        rest.extend(idxs[k:])
    if not cents:
        return {"k": k, "speakers": 0}
    names = list(cents)
    C = np.stack([cents[n] for n in names])
    S = embs[rest] @ C.T
    top = S.argmax(axis=1)
    srt = np.sort(S, axis=1)
    margin = srt[:, -1] - (srt[:, -2] if S.shape[1] > 1 else 0)
    truth = np.array([names.index(wins[i]["spk"]) if wins[i]["spk"] in cents else -1 for i in rest])
    mem = np.array([wins[i]["member"] for i in rest])
    ok = top == truth
    conf = (srt[:, -1] >= 0.6) & (margin >= 0.10)
    return {
        "k": k,
        "speakers": len(names),
        "windows": int(len(rest)),
        "top1_acc": round(float(ok.mean()), 4),
        "top1_acc_member": round(float(ok[mem].mean()), 4) if mem.any() else None,
        "top1_acc_official": round(float(ok[~mem].mean()), 4) if (~mem).any() else None,
        "confident_share": round(float(conf.mean()), 4),
        "confident_acc": round(float(ok[conf].mean()), 4) if conf.any() else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--meeting", required=True)
    ap.add_argument("--steno", required=True)
    ap.add_argument("--model", action="append", required=True)
    ap.add_argument("--pcm")
    ap.add_argument("--out")
    ap.add_argument("--threads", type=int, default=1)
    args = ap.parse_args()

    from app.core.database import get_supabase_client
    from app.services.subtitle_select import prefer_ai_subtitles

    sb = get_supabase_client()
    m = (
        sb.table("meetings")
        .select("vod_url,title")
        .eq("id", args.meeting)
        .limit(1)
        .execute()
        .data[0]
    )
    rows, off = [], 0
    while True:
        r = (
            sb.table("subtitles")
            .select("start_time,end_time,text,speaker,kind")
            .eq("meeting_id", args.meeting)
            .order("start_time")
            .range(off, off + 999)
            .execute()
        )
        rows.extend(r.data or [])
        if not r.data or len(r.data) < 1000:
            break
        off += 1000
    subs = prefer_ai_subtitles(rows)
    steno = parse_steno(open(args.steno, encoding="utf-8").read())
    aligned = align_subs(subs, steno)
    wins = build_windows(aligned)
    n_spk = len({w["spk"] for w in wins})
    print(
        f"# {m['title']}: subs {len(subs)}, steno {len(steno)}, aligned {len(aligned)}, windows {len(wins)}, speakers {n_spk}"
    )

    pcm_path = args.pcm or f"pcm_{args.meeting[:8]}.raw"
    audio_sec = ensure_pcm(m["vod_url"], pcm_path)
    pcm = np.memmap(pcm_path, dtype=np.int16, mode="r")
    print(
        f"# audio {audio_sec / 60:.1f} min, window audio {sum(w['end'] - w['start'] for w in wins) / 60:.1f} min"
    )

    spk_arr = np.array([w["spk"] for w in wins])
    same_mask = spk_arr[:, None] == spk_arr[None, :]
    iu = np.triu_indices(len(wins), k=1)
    result = {
        "meeting": args.meeting,
        "title": m["title"],
        "windows": len(wins),
        "speakers": n_spk,
        "models": {},
    }
    for mp in args.model:
        embs, sec = embed_windows(mp, pcm, wins, args.threads)
        S = embs @ embs.T
        sc, sm = S[iu], same_mask[iu]
        e, t = eer(sc[sm], sc[~sm])
        res = {
            "dim": int(embs.shape[1]),
            "embed_sec": round(sec, 1),
            "rtf": round(sec / max(1e-9, sum(w["end"] - w["start"] for w in wins)), 4),
            "eer": round(e, 4),
            "eer_threshold": round(t, 3),
            "same_p50": round(float(np.median(sc[sm])), 3),
            "same_p10": round(float(np.percentile(sc[sm], 10)), 3),
            "diff_p50": round(float(np.median(sc[~sm])), 3),
            "diff_p90": round(float(np.percentile(sc[~sm], 90)), 3),
            "anchor_k2": anchor_sim(embs, wins, 2),
            "anchor_k4": anchor_sim(embs, wins, 4),
            "max_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 0),
        }
        result["models"][os.path.basename(mp)] = res
        print(
            f"== {os.path.basename(mp)}: dim {res['dim']} · embed {res['embed_sec']}s (RTF {res['rtf']}) · "
            f"EER {res['eer']:.3f} @ {res['eer_threshold']} · same p50 {res['same_p50']} p10 {res['same_p10']} · "
            f"diff p50 {res['diff_p50']} p90 {res['diff_p90']} · RSS {res['max_rss_mb']:.0f}MB"
        )
        for k in ("anchor_k2", "anchor_k4"):
            print(f"   {k}: {res[k]}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"# wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
