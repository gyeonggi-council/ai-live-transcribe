# -*- coding: utf-8 -*-
"""창 길이 실험 — 같은 회의·같은 구간에 돌린 조건별 결과를 짝지어 비교한다 (2026-09-14, 정본 docs/live-sync-eval-2026-09.md §4).

입력: eval_live_text.py 결과 `_livecer_<id8>_w<W>m<M>.json` 들(본회의) 또는 stt_eval.py 결과 `eval_<midx>_*_w<W>m<M>.json` 들(상임위)
+ 같은 접두의 `.stats.json`(replay_live) — 있으면 창·ready_lag 통계를 같이 낸다.
비교는 **세 조건 모두에서 채점된 청크(t0)** 만으로 한다(정렬이 안 된 청크가 조건마다 달라 평균이 흔들리는 함정).
판정 규칙(계획): ΔCER ≤ +1.0%p ∧ hyp/ref −3%p 이내 ∧ 5분 청크 승패(2%p) 패 ≤ 승 ∧ 인명 비용 비율 악화 없음 ∧ 에코 폐기 ≤ 기준 1.5배.

사용: python scripts/compare_window_runs.py --base w12m6 out/_livecer_2ea5c873_w12m6.json out/_livecer_2ea5c873_w8m6.json out/_livecer_2ea5c873_w8m4.json
"""
from __future__ import annotations

import argparse
import json
import os
import re


def _cond(path: str) -> str:
    m = re.search(r"_(w\d+(?:\.\d+)?m\d+(?:\.\d+)?(?:r\d+)?)", os.path.basename(path))  # 반복 런 접미 r2…
    return m.group(1) if m else os.path.basename(path)


def _load(path: str) -> dict:
    r = json.load(open(path, encoding="utf-8"))
    if "chunks" in r and r["chunks"] and "t0" in r["chunks"][0]:  # eval_live_text 형식
        chunks = {c["t0"]: c for c in r["chunks"] if c.get("aligned_lines", 3) >= 3}
        names = (r.get("error_classes") or {}).get("인명") or {}
        return {"cer": r["cer"], "chunks": chunks, "names_share": names.get("cost_share"), "ref": r.get("ref_chars")}
    # stt_eval 형식 — 청크 표가 없다(최상위 offset·cer·ref_chars·hyp_chars 뿐). 전체값으로만 비교한다.
    return {"cer": r.get("cer"), "chunks": {}, "names_share": None, "ref": r.get("ref_chars"),
            "hyp": r.get("hyp_chars"), "stats": r.get("stats") or {}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--base", default="w12m6")
    ap.add_argument("--margin", type=float, default=0.02, help="청크 승패 기준(2%p)")
    ap.add_argument("--chunks", action="store_true", help="공통 청크별 CER 표도 출력")
    # 정렬 실패 청크 배제 — 슬라이스 경계에서 참조 구간이 어긋나면 CER 이 100% 를 넘고(hyp ≫ ref) 가중 평균을 통째로 끌고 간다
    ap.add_argument("--max-cer", type=float, default=0.8, help="어느 조건에서든 CER 이 이보다 크면 그 청크 제외")
    ap.add_argument("--min-ref", type=int, default=600, help="참조 글자가 이보다 적은 청크 제외")
    args = ap.parse_args()
    runs = {_cond(f): (_load(f), f) for f in args.files}
    if args.base not in runs:
        raise SystemExit(f"기준 {args.base} 없음: {list(runs)}")
    no_chunks = [c for c, (r, _) in runs.items() if not r["chunks"]]
    if no_chunks and len(no_chunks) != len(runs):
        raise SystemExit(f"청크 표가 있는 결과와 없는 결과가 섞였다(비교 불가): 청크 없음 {no_chunks}")
    if no_chunks:
        # stt_eval 결과 — 같은 --offset/--seconds 로 돌린 것만 같은 구간이다. 전체 CER·hyp/ref·시뮬 통계로 비교.
        base, _ = runs[args.base]
        print(f"청크 표 없음(stt_eval 결과) — 전체 CER 비교. 기준 {args.base}: CER {base['cer']:.1%} · ref {base['ref']}자")
        print("| 조건 | CER | ΔCER | hyp/ref | 창 평균 | ready_lag p95/p99/max | 에코 폐기 | API 호출 |")
        print("|---|---|---|---|---|---|---|---|")
        for cond, (r, _) in sorted(runs.items(), key=lambda kv: kv[0] != args.base):
            if r["cer"] is None or not r["ref"]:
                raise SystemExit(f"{cond}: cer/ref_chars 없음 — 비교 불가")
            st = r["stats"]
            print(f"| {cond} | {r['cer']:.1%} | {r['cer'] - base['cer']:+.1%} | {(r['hyp'] or 0) / r['ref']:.3f} | "
                  f"{st.get('window_mean', '-')} | {st.get('ready_lag_p95', '-')}/{st.get('ready_lag_p99', '-')}/{st.get('ready_lag_max', '-')} | "
                  f"{st.get('dup_dropped', '-')} | {st.get('windows', '-')} |")
        return 0
    common = set.intersection(*(set(r["chunks"]) for r, _ in runs.values()))
    dropped = sorted(
        t for t in common
        if any(r["chunks"][t]["cer"] > args.max_cer or r["chunks"][t]["ref_chars"] < args.min_ref for r, _ in runs.values())
    )
    common -= set(dropped)
    if dropped:
        print(f"정렬 불량으로 제외한 청크 t0: {dropped}")
    base, _ = runs[args.base]

    def weighted(r: dict) -> tuple[float, float]:
        ref = sum(r["chunks"][t]["ref_chars"] for t in common)
        cost = sum(r["chunks"][t]["cer"] * r["chunks"][t]["ref_chars"] for t in common)
        hyp = sum(r["chunks"][t].get("hyp_chars", 0) for t in common)
        return (cost / max(1, ref), hyp / max(1, ref))

    b_cer, b_ratio = weighted(base)
    print(f"공통 청크 {len(common)}개 (기준 {args.base}: 전체 CER {base['cer']:.1%} · 공통 청크 CER {b_cer:.1%} · hyp/ref {b_ratio:.3f})")
    print("| 조건 | 공통청크 CER | ΔCER | hyp/ref | 청크 승/패/동 | 인명 비용 비율 | 창 평균 | ready_lag p95/p99 | 에코 폐기 |")
    print("|---|---|---|---|---|---|---|---|---|")
    for cond, (r, path) in sorted(runs.items(), key=lambda kv: kv[0] != args.base):
        cer, ratio = weighted(r)
        win = lose = tie = 0
        for t in common:
            d = r["chunks"][t]["cer"] - base["chunks"][t]["cer"]
            if cond == args.base:
                continue
            if d < -args.margin:
                win += 1
            elif d > args.margin:
                lose += 1
            else:
                tie += 1
        st_path = path.replace("_livecer_", "_ai_").replace(".json", ".txt.stats.json")
        st = json.load(open(st_path, encoding="utf-8")) if os.path.exists(st_path) else {}
        rl = f"{st.get('ready_lag_p95_max_over_chunks', '-')}/{st.get('ready_lag_p99_max_over_chunks', '-')}" if st else "-"
        print(f"| {cond} | {cer:.1%} | {cer - b_cer:+.1%} | {ratio:.3f} | {win}/{lose}/{tie} | "
              f"{(r['names_share'] or 0):.1%} | {st.get('window_mean_weighted', '-')} | {rl} | {st.get('dup_dropped', '-')} |")
    if args.chunks:
        conds = [c for c in runs]
        print("\n| t0(초) | ref 글자 | " + " | ".join(conds) + " | 정렬 줄 |")
        print("|---|---|" + "---|" * len(conds) + "---|")
        for t in sorted(common):
            row = [f"{runs[c][0]['chunks'][t]['cer']:.1%}" for c in conds]
            al = "/".join(str(runs[c][0]["chunks"][t].get("aligned_lines", "-")) for c in conds)
            print(f"| {t} | {base['chunks'][t]['ref_chars']} | " + " | ".join(row) + f" | {al} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
