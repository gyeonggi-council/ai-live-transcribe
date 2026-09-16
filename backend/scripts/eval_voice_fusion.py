"""VOD 음성 화자 융합(speaker_voice_fusion) 오프라인 평가 — 배포 전에 정답 회의로 전/후를 잰다.

DB 의 현행 AI 자막(텍스트 화자귀속 결과)을 읽어 그대로 채점(before) → 융합을 돌린 뒤 채점(after).
임베딩 워커·모델은 파드 /tmp/eval 의 스파이크 환경(pylib·models)을 쓴다. 읽기 전용(DB 안 씀).

사용 (파드 /tmp/eval, PYTHONPATH=/app:/tmp/eval/pylib):
  python scripts/eval_voice_fusion.py --meeting <id> --steno _steno_N.txt --pcm pcm_<id8>.raw \
      --model models/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx \
      [--override 0.55 --margin 0.10 --reject 0.35 --purity 0.45 --boot 2] [--out out.json] [--dump after.txt]
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from _steno_align import align, parse_steno, print_score, score  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--meeting", required=True)
    ap.add_argument("--steno", required=True)
    ap.add_argument("--pcm", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--override", type=float)
    ap.add_argument("--margin", type=float)
    ap.add_argument("--reject", type=float)
    ap.add_argument("--purity", type=float)
    ap.add_argument("--boot", type=int)
    ap.add_argument("--min-anchors", type=int)
    ap.add_argument("--min-window", type=float)
    ap.add_argument("--window-max", type=float)
    ap.add_argument("--passes", type=int)
    ap.add_argument("--no-turn", action="store_true")
    ap.add_argument("--cut-question", action="store_true")
    ap.add_argument("--no-fallback", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--dump")
    args = ap.parse_args()

    # 융합 모듈: 파드에서는 scripts/ 에 복사된 사본(app.services 에 아직 없을 수 있다)
    try:
        import speaker_voice_fusion as svf
    except ImportError:
        from app.services import speaker_voice_fusion as svf

    from app.core.database import get_supabase_client
    from app.services.roster_loader import load_committee_with_roles
    from app.services.subtitle_select import prefer_ai_subtitles

    sb = get_supabase_client()
    m = (
        sb.table("meetings")
        .select("title,committee")
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
    roster = load_committee_with_roles(sb, m.get("committee"))
    steno = parse_steno(open(args.steno, encoding="utf-8").read())
    mapping = align([s.get("text") or "" for s in subs], [t for _, t, _ in steno])
    print(f"# {m['title']}: subs {len(subs)}, roster {len(roster)}, steno {len(steno)}")

    before = score([s.get("speaker") or "?" for s in subs], steno, mapping)
    print_score(before, "BEFORE (텍스트 화자귀속)")

    cfg = svf.FusionConfig(model_path=args.model)
    for k, f in (
        ("cos_override", "override"),
        ("cos_margin", "margin"),
        ("cos_reject", "reject"),
        ("cos_purity", "purity"),
        ("boot_rounds", "boot"),
        ("min_anchors", "min_anchors"),
    ):
        v = getattr(args, f)
        if v is not None:
            setattr(cfg, k, v)
    if args.min_window is not None:
        cfg.window_min_seconds = args.min_window
    if args.window_max is not None:
        cfg.window_max_seconds = args.window_max
    if args.passes is not None:
        cfg.passes = args.passes
    cfg.turn_scoping = not args.no_turn
    cfg.cut_after_question = args.cut_question
    cfg.fallback_centroids = not args.no_fallback
    os.environ.setdefault("VOICE_EMB_CACHE", os.path.join(os.getcwd(), "embcache"))
    os.makedirs(os.environ["VOICE_EMB_CACHE"], exist_ok=True)
    fused = copy.deepcopy(subs)
    dbg: dict = {}
    stats = asyncio.run(
        svf.fuse_voice_speakers(fused, roster, pcm_path=args.pcm, cfg=cfg, debug=dbg)
    )
    print(
        "# fusion stats:",
        json.dumps({k: v for k, v in stats.items() if k != "anchors"}, ensure_ascii=False),
    )
    print("# anchors:", json.dumps(stats.get("anchors", {}), ensure_ascii=False))
    after = score([s.get("speaker") or "?" for s in fused], steno, mapping)
    print_score(after, "AFTER (음성 융합)")
    # 잔여 오류 진단 — 정답 위원 라인 중 틀린 것: 규칙·창 길이·정답 라벨 유사도
    if dbg:
        from _steno_align import speaker_name as _sn

        wins, E, cents, decisions = dbg["wins"], dbg["E"], dbg["cents"], dbg["decisions"]
        win_of = {i: wi for wi, w in enumerate(wins) for i in w["lines"]}
        rows = []
        for i, (s, mp) in enumerate(zip(fused, mapping, strict=False)):
            if mp is None:
                continue
            gt, _, gt_member = steno[mp[0]]
            if not gt or not gt_member:
                continue
            if _sn(s.get("speaker") or "") == gt:
                continue
            wi = win_of.get(i)
            w = wins[wi] if wi is not None else None
            rule = decisions[wi][1] if wi is not None else "-"
            dur = round(w["end"] - w["start"], 1) if w else 0
            gt_label = next((l for l in cents if _sn(l) == gt), None)
            s_gt = round(float(E[wi] @ cents[gt_label][0]), 2) if (w and gt_label) else None
            rows.append(
                (
                    int(float(s.get("start_time") or 0)),
                    gt,
                    s.get("speaker") or "?",
                    subs[i].get("speaker") or "?",
                    rule,
                    dur,
                    s_gt,
                    (s.get("text") or "")[:30],
                )
            )
        from collections import Counter

        print(
            f"# 잔여 위원 오류 {len(rows)}건 — 규칙별 {dict(Counter(r[4] for r in rows))} · 짧은창(<{cfg.window_min_seconds}s) {sum(1 for r in rows if r[5] < cfg.window_min_seconds)}건 · 정답 기준 없음 {sum(1 for r in rows if r[6] is None)}건"
        )
        for t, gt, af, bf, rule, dur, s_gt, txt in rows[:40]:
            print(
                f"   {t//3600:02d}:{(t%3600)//60:02d}:{t%60:02d} 정답 {gt} | 후 {af} | 전 {bf} | {rule} {dur}s s_gt={s_gt} | {txt}"
            )
    print(
        f"## member_match_rate {before['member_match_rate']:.4f} → {after['member_match_rate']:.4f}  "
        f"wrong_member {before['wrong_member']} → {after['wrong_member']}  "
        f"official_to_member {before['official_to_member']} → {after['official_to_member']}"
    )
    if args.dump:
        with open(args.dump, "w", encoding="utf-8") as f:
            for s, s0 in zip(fused, subs, strict=False):
                t = int(float(s.get("start_time") or 0))
                mark = "*" if s.get("speaker") != s0.get("speaker") else " "
                f.write(
                    f"[{t//3600:02d}:{(t%3600)//60:02d}:{t%60:02d}]{mark} {s.get('speaker') or '?'} <= {s0.get('speaker') or '?'}: {s.get('text','')}\n"
                )
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "meeting": args.meeting,
                    "cfg": cfg.__dict__,
                    "stats": stats,
                    "before": before,
                    "after": after,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
