"""속기 정답 화자 vs AI 자막 화자 일치율 + 최다 혼동쌍 리포트. 읽기 전용 평가 도구 (제품코드 아님).

정렬은 `_steno_align.align`(단조 DP, 문자 바이그램) — `_score_accuracy.py` 식 포인터 정렬은
집행부 장문 보고 구간에서 멈춰 이후 라인이 전부 오귀속되는 결함이 있어 쓰지 않는다(2026-09-05).

사용: python scripts/eval_speaker_attribution.py _steno_15594.txt _ai_0ce6f043.txt [out.json]
출력: stdout — 위원/집행부 분리 지표 + 최다 혼동쌍(steno→ai) 상위 10. out.json 을 주면 지표를 저장.

지표 (2026-09-05 분리 — 이전에는 위원·집행부를 섞어 하나로 셌다):
  member_match_rate   정답이 위원(위원장·부위원장·위원·의원·의장·부의장)인 라인의 이름 일치율 (주지표)
  wrong_member        정답 위원 A 를 AI 가 다른 위원 B 로 붙인 수 (가장 위험한 오류)
  member_to_official  정답 위원인데 AI 가 집행부/미지정으로 붙인 수
  official_match_rate 정답이 집행부인 라인의 이름 일치율
  official_unnamed    정답 집행부인데 AI 가 "집행부"(직책 미상)만 붙인 수 — 오류와 분리 보고
  official_to_member  정답 집행부인데 AI 가 위원으로 붙인 수 (위험)
"""

import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from _steno_align import align, is_member, parse_steno, speaker_name  # noqa: E402

steno_file = sys.argv[1]
ai_file = sys.argv[2]
json_out = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] != "-" else None
# 정렬 확신 문턱(바이그램 Jaccard). 기본 0.25. 올리면 정렬이 불확실한 라인을 채점에서 뺀다 —
# "채점기 오차를 뺀 일치율" 을 볼 때 0.45 정도로 준다.
min_sim = float(sys.argv[4]) if len(sys.argv) > 4 else 0.25

steno_items = parse_steno(open(steno_file, encoding="utf-8").read())

# --- ai 파싱: [HH:MM:SS] 화자: 텍스트 ---
ai_lines = []
for line in open(ai_file, encoding="utf-8").read().splitlines():
    m = re.match(r"\[(\d\d:\d\d:\d\d)\]\s*(.*?):\s*(.*)", line)
    if m:
        ai_lines.append((m.group(1), m.group(2), m.group(3)))

print(f"# steno sents {len(steno_items)}, ai lines {len(ai_lines)}")

mapping = align([t for _, _, t in ai_lines], [s for _, s, _ in steno_items], min_sim=min_sim)
pairs = []  # (hms, ai_spk, steno_spk, steno_member, sim)
for (hms, spk, _), mp in zip(ai_lines, mapping):
    if mp is None:
        continue
    j, sim = mp
    s_spk, _, s_member = steno_items[j]
    pairs.append((hms, spk, s_spk, s_member, sim))

# --- 화자 일치율 + 혼동쌍 (steno 정답 화자 → ai 화자), 위원/집행부 분리 ---
c = Counter()
conf_member = Counter()  # 정답 위원 라인의 혼동쌍
conf_official = Counter()  # 정답 집행부 라인의 혼동쌍
for _, ai_spk, s_spk, s_member, _ in pairs:
    if not s_spk:
        continue
    ai_spk = (ai_spk or "").strip()
    ai_name = speaker_name(ai_spk) if ai_spk and ai_spk != "?" else None
    ai_member = is_member(ai_spk)
    ai_repr = ai_name or ai_spk or "?"
    if s_member:
        c["member_total"] += 1
        if ai_name == s_spk:
            c["member_match"] += 1
        else:
            conf_member[(s_spk, ai_repr)] += 1
            if ai_member and ai_name:
                c["wrong_member"] += 1
            else:
                c["member_to_official"] += 1
    else:
        c["official_total"] += 1
        if ai_name == s_spk:
            c["official_match"] += 1
        else:
            conf_official[(s_spk, ai_repr)] += 1
            if ai_member and ai_name:
                c["official_to_member"] += 1
            elif ai_spk in ("집행부", "?", ""):
                c["official_unnamed"] += 1
            else:
                c["official_wrong_name"] += 1

total = c["member_total"] + c["official_total"]
match = c["member_match"] + c["official_match"]
metrics = {
    "ai_lines": len(ai_lines),
    "aligned_pairs": len(pairs),
    "speaker_match_rate": round(match / total, 4) if total else 0.0,
    "member_total": c["member_total"],
    "member_match_rate": (
        round(c["member_match"] / c["member_total"], 4) if c["member_total"] else 0.0
    ),
    "wrong_member": c["wrong_member"],
    "member_to_official": c["member_to_official"],
    "official_total": c["official_total"],
    "official_match_rate": (
        round(c["official_match"] / c["official_total"], 4) if c["official_total"] else 0.0
    ),
    "official_unnamed": c["official_unnamed"],
    "official_wrong_name": c["official_wrong_name"],
    "official_to_member": c["official_to_member"],
    "top_confusions_member": [[s, a, n] for (s, a), n in conf_member.most_common(10)],
    "top_confusions_official": [[s, a, n] for (s, a), n in conf_official.most_common(10)],
}
print(f"aligned_pairs        = {metrics['aligned_pairs']} / {len(ai_lines)}")
print(
    f"speaker_match_rate   = {metrics['speaker_match_rate']:.4f}  ({match}/{total})  (구 지표, 위원+집행부 혼합)"
)
print(
    f"member_match_rate    = {metrics['member_match_rate']:.4f}  ({c['member_match']}/{c['member_total']})  ★주지표"
)
print(f"  wrong_member       = {c['wrong_member']}   (위원 A → 다른 위원 B)")
print(f"  member_to_official = {c['member_to_official']}   (위원 → 집행부/미지정)")
print(
    f"official_match_rate  = {metrics['official_match_rate']:.4f}  ({c['official_match']}/{c['official_total']})"
)
print(f"  official_unnamed   = {c['official_unnamed']}   ('집행부'/미지정 — 오류와 분리)")
print(f"  official_wrong_name= {c['official_wrong_name']}")
print(f"  official_to_member = {c['official_to_member']}   (집행부 → 위원, 위험)")
print("top confusion pairs — 정답 위원 (steno→ai):")
for (s_name, a_name), cnt in conf_member.most_common(10):
    print(f"  {cnt:4d}  {s_name} → {a_name}")
print("top confusion pairs — 정답 집행부 (steno→ai):")
for (s_name, a_name), cnt in conf_official.most_common(10):
    print(f"  {cnt:4d}  {s_name} → {a_name}")
if json_out:
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    print(f"# wrote {json_out}")
