# -*- coding: utf-8 -*-
"""AI 자막 의원 구간(build_draft_from_ai 슬롯)의 정확도 — 정답은 KMS 공식 인덱스.

담당자 목표(2026-09-08): "AI 자막이 완료된 회의의 의원 발언 영상 정확도 99% 이상".
지금 몇 %인지 아무도 모르므로 먼저 잰다. 공식 인덱스(`질의답변(전자영 위원)` 등)와 AI 자막이 둘 다 있는
위원회 회의를 골라, AI 자막만으로 만든 슬롯을 공식 구간과 비교한다. 읽기 전용(DB 안 씀).

판정(공식 의원 구간 하나마다):
  correct  — 같은 이름의 AI 슬롯이 공식 구간을 COVER(80%) 이상 덮고, 다른 의원의 공식 구간을 INTRUDE(30초) 넘게 안 넘음
  missing  — 같은 이름의 AI 슬롯이 공식 구간과 전혀 안 겹침
  wrong    — 다른 이름의 AI 슬롯이 공식 구간의 50% 이상을 덮음(오귀속)
  partial  — 같은 이름이지만 덮은 비율이 COVER 미만
  overrun  — 덮었지만 남의 공식 구간을 INTRUDE 초 넘게 침범
정확도 = correct / 공식 의원 구간 수. 시작·끝 오차(AI − 공식)의 중앙값도 낸다 — 공식은 위원장 호명 시점,
AI 는 의원 첫 발언이라 시작이 늦는 것이 정상이며 그 분포를 본다.

사용 (파드 안, cwd /app):
  kubectl -n ggc-poc exec -i deploy/ggc-live-transcribe-api -c api -- python - --limit 15 < eval_clip_slots.py
  옵션: --meeting <id> (한 회의만) · --json out.json · --verbose (구간별 줄 출력)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from typing import Optional

sys.stdout.reconfigure(encoding="utf-8")

COVER = 0.80
INTRUDE = 30.0
WRONG_COVER = 0.50
# 공식 구간의 끝 = 다음 항목의 시작이라 위원장의 마무리·전환 멘트(수고하셨습니다 … 다음 안건)가 꼬리에 붙는다.
# AI 슬롯이 "수고하셨습니다" 에서 끝나는 건 맞는 것이므로, 남의 구간이 아닌 꼬리 90초까지는 덮은 것으로 친다.
TAIL_GRACE = 120.0


def _closing_ok(closing_name: str, slot_name: str) -> bool:
    try:
        from app.services.clip_draft_index import closing_matches
        return closing_matches(closing_name, slot_name)
    except ImportError:
        return closing_name == slot_name


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _official_member_segments(official: list[dict], norm) -> list[dict]:
    out = []
    for g in official:
        if not g.get("name"):
            continue
        for s in g["segments"]:
            if s.get("named"):
                out.append({"name": g["name"], "key": norm(g["name"]), "start": s["start"], "end": s["end"],
                            "title": s.get("title", "")})
    return sorted(out, key=lambda s: s["start"])


def _ai_segments(ai: list[dict], norm) -> list[dict]:
    out = []
    for g in ai:
        for s in g["segments"]:
            out.append({"name": g["name"], "key": norm(g["name"]), "start": s["start"], "end": s["end"],
                        "role": g.get("role", "")})
    return sorted(out, key=lambda s: s["start"])


def judge(official_segs: list[dict], ai_segs: list[dict],
          closings: Optional[list[tuple[float, str]]] = None, norm=None) -> list[dict]:
    """closings: (시각, 이름) — 위원장이 "OO 의원님 수고하셨습니다" 라고 닫은 지점. AI 슬롯이 자기 이름의
    마무리에서 끝났으면 공식 구간의 남은 꼬리(위원장 소감·다음 안건 준비)는 덮은 것으로 친다."""
    closings = closings or []
    rows = []
    for o in official_segs:
        length = max(1e-6, o["end"] - o["start"])
        same = [a for a in ai_segs if a["key"] == o["key"] and _overlap(a["start"], a["end"], o["start"], o["end"]) > 0]
        best = max(same, key=lambda a: _overlap(a["start"], a["end"], o["start"], o["end"]), default=None)
        row = {"name": o["name"], "start": o["start"], "end": o["end"], "title": o["title"],
               "verdict": "", "cover": 0.0, "intrude": 0.0, "d_start": None, "d_end": None, "ai": None}
        if best is None:
            wrong = [a for a in ai_segs if a["key"] != o["key"]
                     and _overlap(a["start"], a["end"], o["start"], o["end"]) / length >= WRONG_COVER]
            row["verdict"] = "wrong" if wrong else "missing"
            if wrong:
                row["ai"] = f"{wrong[0]['name']} {_hms(wrong[0]['start'])}~{_hms(wrong[0]['end'])}"
            rows.append(row)
            continue
        covered = sum(_overlap(a["start"], a["end"], o["start"], o["end"]) for a in same)
        last_end = max(a["end"] for a in same)
        tail = o["end"] - last_end
        closed_by_chair = any(_closing_ok(nm, o["name"]) and abs(t - last_end) <= 6 for t, nm in closings)
        if 0 < tail and (tail <= TAIL_GRACE or closed_by_chair):
            covered += tail
        cover = covered / length
        # 침범: 가장 잘 맞는 AI 슬롯이 다른 의원의 공식 구간과 겹친 초
        intrude = max((_overlap(best["start"], best["end"], x["start"], x["end"])
                       for x in official_segs if x["key"] != o["key"]), default=0.0)
        row.update({"cover": round(cover, 3), "intrude": round(intrude, 1),
                    "d_start": round(best["start"] - o["start"], 1), "d_end": round(best["end"] - o["end"], 1),
                    "ai": f"{_hms(best['start'])}~{_hms(best['end'])}"})
        if cover < COVER:
            row["verdict"] = "partial"
        elif intrude > INTRUDE:
            row["verdict"] = "overrun"
        else:
            row["verdict"] = "correct"
        rows.append(row)
    return rows


def _hms(sec: float) -> str:
    t = int(sec)
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"


async def evaluate(sb, meeting: dict, verbose: bool, mode: str = "hybrid") -> dict | None:
    from app.services import kms_angun_service as kms
    from app.services.clip_draft_index import _load_roster, build_draft_from_ai
    from app.services.speaker_segments import _fetch_all_subtitles, build_speaker_segments

    angun = await kms.fetch_angun(str(meeting["kms_midx"]))
    if not angun:
        return None
    official = kms.build_speakers(angun, meeting.get("duration_seconds") or None)
    official_segs = _official_member_segments(official, kms.norm_name)
    if len({s["key"] for s in official_segs}) < 2:
        return None  # 본회의(개의 한 줄) 등 — 정답이 없다
    roster = await asyncio.to_thread(_load_roster, sb, meeting)
    seg_result = await asyncio.to_thread(build_speaker_segments, sb, meeting)
    if mode == "labels":
        ai = build_draft_from_ai(seg_result, roster)
    else:
        subs = await asyncio.to_thread(_fetch_all_subtitles, sb, meeting["id"])
        ai_subs = [s for s in subs if s.get("kind") == "ai"] or subs
        ai = build_draft_from_ai(seg_result, roster, ai_subs, meeting.get("duration_seconds") or None,
                                 label_supplement=(mode == "hybrid"))
    ai_segs = _ai_segments(ai, kms.norm_name)
    closings = []
    if mode != "labels":
        from app.services.clip_draft_index import _closing_times
        closings = _closing_times(ai_subs, roster)
    rows = judge(official_segs, ai_segs, closings, kms.norm_name)
    # 공식 의원 구간과 전혀 안 겹치는 AI 슬롯(위원장 슬롯·오탐)
    extra = [a for a in ai_segs if not any(_overlap(a["start"], a["end"], o["start"], o["end"]) > 0 for o in official_segs)]
    counts = {k: sum(1 for r in rows if r["verdict"] == k) for k in ("correct", "missing", "wrong", "partial", "overrun")}
    ds = [r["d_start"] for r in rows if r["d_start"] is not None]
    de = [r["d_end"] for r in rows if r["d_end"] is not None]
    res = {"meeting_id": meeting["id"], "title": meeting.get("title"), "date": meeting.get("meeting_date"),
           "kms_midx": meeting.get("kms_midx"), "official": len(rows), "ai_slots": len(ai_segs), "extra": len(extra),
           "counts": counts, "accuracy": round(counts["correct"] / len(rows), 4) if rows else None,
           "d_start_median": round(statistics.median(ds), 1) if ds else None,
           "d_end_median": round(statistics.median(de), 1) if de else None, "rows": rows,
           "extra_rows": [{"name": a["name"], "start": a["start"], "end": a["end"]} for a in extra]}
    print(f"\n== {res['title']} [{res['date']}] midx={res['kms_midx']} 공식 {len(rows)} / AI 슬롯 {len(ai_segs)}"
          f" (공식과 무관 {len(extra)}) → 정확도 {res['accuracy']:.1%}  {counts}"
          f"  시작오차 중앙값 {res['d_start_median']}s 끝오차 {res['d_end_median']}s")
    for r in rows:
        if verbose or r["verdict"] != "correct":
            print(f"   [{r['verdict']:7}] {r['name']:5} 공식 {_hms(r['start'])}~{_hms(r['end'])} {r['title'][:24]:24}"
                  f" | AI {r['ai'] or '-':18} cover {r['cover']:.0%} intrude {r['intrude']}s")
    if verbose:
        for a in extra:
            print(f"   [extra  ] {a['name']:5} AI {_hms(a['start'])}~{_hms(a['end'])} ({a.get('role')})")
    return res


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=12, help="최근 AI 자막 완료 회의 몇 건을 볼지")
    ap.add_argument("--meeting", help="한 회의만")
    ap.add_argument("--json")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--mode", choices=["hybrid", "cues", "labels"], default="hybrid",
                    help="hybrid=호명 단서 뼈대+라벨 보조(현행) · cues=호명 단서만 · labels=화자 라벨만(09-08 이전)")
    args = ap.parse_args()

    from app.core.database import get_supabase_client
    sb = get_supabase_client()
    q = (sb.table("meetings").select("id,title,meeting_date,kms_midx,duration_seconds,committee,channel_id,subtitle_stage")
         .in_("subtitle_stage", ["ai", "reviewing", "final"]).not_.is_("kms_midx", "null")
         .order("meeting_date", desc=True))
    if args.meeting:
        q = q.eq("id", args.meeting)
    else:
        q = q.limit(args.limit * 2)  # 본회의 등 정답 없는 회의가 섞이므로 넉넉히
    meetings = q.execute().data or []
    results = []
    for m in meetings:
        if not args.meeting and len(results) >= args.limit:
            break
        try:
            r = await evaluate(sb, m, args.verbose, args.mode)
        except Exception as e:  # noqa: BLE001
            print(f"\n== {m.get('title')} 실패: {e!r}")
            continue
        if r:
            results.append(r)
    if not results:
        print("정답(공식 인덱스)과 AI 자막이 둘 다 있는 회의가 없습니다.")
        return 1
    total = sum(r["official"] for r in results)
    correct = sum(r["counts"]["correct"] for r in results)
    agg = {k: sum(r["counts"][k] for r in results) for k in results[0]["counts"]}
    print(f"\n합계: 회의 {len(results)}건 · 공식 구간 {total} · 정확도 {correct / total:.1%}  {agg}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"results": results, "total": total, "correct": correct, "counts": agg}, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
