# -*- coding: utf-8 -*-
"""자막(라이브 초안 또는 AI 완성본) 텍스트 정확도 — 속기록 대조 CER + 오류 분류.

"목소리(화자)로 글자 정확도를 올릴 수 있는가" 를 재기 위한 도구(2026-09-08). 목소리가 글자에
미치는 경로는 인명(호명·자기소개) 뿐이므로 **인명 오류의 글자 비용 비율이 곧 기대 상한**이다.

- 정렬: `_steno_align.align`(문자 바이그램 Jaccard, 단조 DP)로 자막 라인 ↔ 속기 문장.
  정렬은 **참조 구간의 경계**를 찾는 데만 쓰고, CER 은 청크(기본 300초) 단위로
  `stt_eval.norm_strict/edit_ops` 와 같은 정의(공백·문장부호 제외)로 잰다 — 12초 창을 글자수 비례로
  자른 자막 라인과 속기 문장은 1:1 이 아니라 쌍 단위 CER 은 경계 절단 오차가 크다.
- 속기록은 정제 문어체(간투사 제거)라 CER 절대값은 실제보다 높다 — 같은 회의 live vs ai 처럼
  **상대 비교**로 읽는다(`docs/stt-accuracy-eval-2026-09.md`).

사용 (backend 디렉터리에서):
    python scripts/_fetch_steno.py 15647                       # 속기록
    python scripts/_fetch_ai_subs.py <meeting_id> live         # 파드에서 (또는 ai)
    python scripts/eval_live_text.py _steno_15647.txt _ai_c226fbca_live.txt [out.json] [chunk_sec]
    python scripts/eval_live_text.py                           # 인자 없이 = 자체검사
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

from _steno_align import TITLES, align, is_member, parse_steno  # noqa: E402
from stt_eval import edit_ops, mine_word_substitutions, norm_spaced, norm_strict  # noqa: E402

_AI_LINE = re.compile(r"\[(\d\d):(\d\d):(\d\d)\]\s*(.*?):\s*(.*)")
_CHAIR_HDR = re.compile(r"^○\s*(?:부)?의장\s+([가-힣]{2,4})", re.M)
_ROLE_WORDS = set(TITLES) | {"도지사", "교육감", "의장", "부의장", "위원님", "의원님"}


def parse_ai(raw: str) -> list[tuple[float, str, str]]:
    out = []
    for line in raw.splitlines():
        m = _AI_LINE.match(line)
        if m:
            h, mi, s = (int(m.group(i)) for i in (1, 2, 3))
            out.append((h * 3600 + mi * 60 + s, m.group(4), m.group(5)))
    return out


def name_set(steno_raw: str, steno_items: list) -> set[str]:
    """인명 집합 = 속기 화자명 ∪ 말미 '○ 출석의원' 명단 (명부·DB 불필요).

    본문 정규식("OO 의원" 앞 토큰)은 '동료·그러면·밖에' 같은 일반어를 이름으로 오인해 쓰지 않는다.
    출석 명단은 이름이 구분자 없이 붙어 있어(강성삼고은정고찬석…) 줄마다 3자씩 자르고 2자 꼬리는
    2자 이름으로 본다 — 4자 성명은 놓친다(ponytail: 분류 통계용이라 감수).
    """
    names = {n for n, _, _ in steno_items if n}
    m = re.search(r"○\s*출석의원[^\n]*\n(.*?)(?=\n○|\Z)", steno_raw, re.S)
    if m:
        for line in m.group(1).splitlines():
            line = re.sub(r"\([^)]*\)", "", line).strip()
            while len(line) >= 3:
                names.add(line[:3])
                line = line[3:]
            if len(line) == 2:
                names.add(line)
    return {n for n in names if n not in _ROLE_WORDS}


def classify(ref: str, hyp: str, names: set[str]) -> str:
    toks = [t.rstrip("님") for t in ref.split()]
    if any(t in names or (len(t) > 3 and t[:3] in names) for t in toks):  # '김태희의원' 꼴만 접두 허용
        return "인명"
    if any(w in ref or w in hyp for w in _ROLE_WORDS):
        return "직책"
    if re.search(r"\d", ref + hyp):
        return "숫자"
    return "기타"


def evaluate(steno_raw: str, ai_raw: str, chunk_sec: int = 300) -> dict:
    steno = parse_steno(steno_raw)
    ai = parse_ai(ai_raw)
    if not steno or not ai:
        raise SystemExit(f"입력 비어 있음: steno {len(steno)} / ai {len(ai)}")
    names = name_set(steno_raw, steno)
    chairs = set(_CHAIR_HDR.findall(steno_raw))
    mapping = align([t for _, _, t in ai], [s for _, s, _ in steno])
    aligned = sum(1 for m in mapping if m)

    chunks: dict[int, dict] = defaultdict(lambda: {"hyp": [], "js": []})
    for (sec, _, text), mp in zip(ai, mapping):
        c = chunks[int(sec // chunk_sec)]
        c["hyp"].append(text)
        if mp:
            c["js"].append(mp[0])

    rows, subs_all = [], Counter()
    by_sec: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # section -> [cost, ref]
    for k in sorted(chunks):
        c = chunks[k]
        if len(c["js"]) < 3:
            continue
        j0, j1 = min(c["js"]), max(c["js"])
        ref_raw = " ".join(s for _, s, _ in steno[j0 : j1 + 1])
        hyp_raw = " ".join(c["hyp"])
        ref_s, hyp_s = norm_strict(ref_raw), norm_strict(hyp_raw)
        cost, _ = edit_ops(ref_s, hyp_s)
        kinds = Counter(
            "진행" if n in chairs else ("위원" if m else "집행부") for n, _, m in steno[j0 : j1 + 1]
        )
        section = kinds.most_common(1)[0][0]
        pairs, _ = mine_word_substitutions(norm_spaced(ref_raw), norm_spaced(hyp_raw))
        subs_all.update(pairs)
        rows.append({
            "t0": k * chunk_sec, "section": section, "cer": round(cost / max(1, len(ref_s)), 4),
            "ref_chars": len(ref_s), "hyp_chars": len(hyp_s), "aligned_lines": len(c["js"]),
        })
        by_sec[section][0] += cost
        by_sec[section][1] += len(ref_s)

    total_cost = sum(v[0] for v in by_sec.values())
    total_ref = sum(v[1] for v in by_sec.values())
    cls_count: Counter = Counter()
    cls_cost: Counter = Counter()
    for (r, h), n in subs_all.items():
        kind = classify(r, h, names)
        cls_count[kind] += n
        cls_cost[kind] += n * max(len(norm_strict(r)), len(norm_strict(h)))
    cost_sum = sum(cls_cost.values()) or 1
    return {
        "cer": round(total_cost / max(1, total_ref), 4),
        "ref_chars": total_ref,
        "aligned": aligned, "total_lines": len(ai), "steno_sents": len(steno),
        "chunks_scored": len(rows), "chunk_sec": chunk_sec,
        "by_section": {s: {"cer": round(v[0] / max(1, v[1]), 4), "ref_chars": v[1]} for s, v in by_sec.items()},
        "error_classes": {
            k: {"count": cls_count[k], "cost": cls_cost[k], "cost_share": round(cls_cost[k] / cost_sum, 3)}
            for k in ("인명", "직책", "숫자", "기타")
        },
        "top_substitutions": [
            {"ref": r, "hyp": h, "count": n, "class": classify(r, h, names)}
            for (r, h), n in subs_all.most_common(40)
        ],
        "chunks": rows,
    }


def _selftest() -> None:
    steno = "(10시00분 개의)\n○ 의장 홍길동  회의를 시작하겠습니다. 김회철 의원 질문하십시오.\n○ 김회철 의원  예산이 300억입니다. 감사합니다.\n"
    ai = "[00:00:01] ?: 회의를 시작하겠습니다.\n[00:00:05] ?: 김해철 의원 질문하십시오.\n[00:00:09] ?: 예산이 300억입니다.\n[00:00:12] ?: 감사합니다.\n"
    r = evaluate(steno, ai, chunk_sec=60)
    r["chunks"] and None
    assert r["aligned"] == 4, r
    assert r["error_classes"]["인명"]["count"] == 1, r["error_classes"]
    assert 0 < r["cer"] < 0.1, r["cer"]
    print("selftest ok", r["cer"], r["error_classes"]["인명"])


def main() -> int:
    if len(sys.argv) < 3:
        _selftest()
        return 0
    steno_raw = open(sys.argv[1], encoding="utf-8").read()
    ai_raw = open(sys.argv[2], encoding="utf-8").read()
    out = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] != "-" else None
    chunk = int(sys.argv[4]) if len(sys.argv) > 4 else 300
    r = evaluate(steno_raw, ai_raw, chunk)
    print(f"# {sys.argv[2]}: CER {r['cer']:.1%} (ref {r['ref_chars']}자, 청크 {r['chunks_scored']}, 정렬 {r['aligned']}/{r['total_lines']})")
    for s, v in r["by_section"].items():
        print(f"  구간 {s}: CER {v['cer']:.1%} ({v['ref_chars']}자)")
    for k, v in r["error_classes"].items():
        print(f"  오류 {k}: {v['count']}건 · 비용 {v['cost']} ({v['cost_share']:.0%})")
    for t in r["top_substitutions"][:15]:
        print(f"    {t['count']}× {t['ref']!r} → {t['hyp']!r} [{t['class']}]")
    if out:
        json.dump(r, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"# wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
