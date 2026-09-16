# -*- coding: utf-8 -*-
"""속기 정답 vs AI 자막 윈도우 정렬 대조 → 오인식 near-miss 쌍 출력. 읽기 전용.

사용: python scripts/_align_compare.py <steno_file> <ai_file> <out_tag>
출력: _diff_<out_tag>.txt
"""
import re
import sys
from difflib import SequenceMatcher

sys.stdout.reconfigure(encoding="utf-8")

steno_file = sys.argv[1] if len(sys.argv) > 1 else "_steno_15580.txt"
ai_file = sys.argv[2] if len(sys.argv) > 2 else "_ai_99ae52d7.txt"
tag = sys.argv[3] if len(sys.argv) > 3 else "99ae52d7"

steno_raw = open(steno_file, encoding="utf-8").read()
ai_raw = open(ai_file, encoding="utf-8").read()


def norm(s):
    return re.sub(r"\s+", "", s)


steno_sentences = []
for line in steno_raw.splitlines():
    line = line.strip().lstrip(">")
    if not line:
        continue
    if line.startswith("○"):
        # 화자 헤더. 두 포맷 지원:
        #   A) "○ 위원장" (발언은 다음 줄들) → 헤더만이면 버림
        #   B) "○ 위원장 고은정  의석을 정돈…" (인라인 발언) → 발언부만 취함
        rest = line.lstrip("○").strip()
        parts = re.split(r"\s{2,}", rest, maxsplit=1)
        if len(parts) == 2 and len(norm(parts[1])) >= 4:
            line = parts[1]
        else:
            continue
    if re.fullmatch(r"\(.*\)", line):
        continue
    if re.fullmatch(r"[가-힣]{2,4}", line):
        continue
    for sent in re.split(r"(?<=[.?!])\s+", line):
        sent = sent.strip()
        if len(norm(sent)) >= 4:
            steno_sentences.append(sent)

ai_lines = []
for line in ai_raw.splitlines():
    m = re.match(r"\[(\d\d:\d\d:\d\d)\]\s*(.*?):\s*(.*)", line)
    if m:
        ai_lines.append((m.group(1), m.group(2), m.group(3)))

print(f"# {tag}: steno sents {len(steno_sentences)}, ai lines {len(ai_lines)}", file=sys.stderr)

W = 25
ptr = 0
pairs = []
for hms, spk, ai_text in ai_lines:
    an = norm(ai_text)
    if len(an) < 4:
        continue
    best_r, best_j, best_s = 0.0, -1, ""
    lo, hi = max(0, ptr - 5), min(len(steno_sentences), ptr + W)
    for j in range(lo, hi):
        r = SequenceMatcher(None, an, norm(steno_sentences[j])).ratio()
        if r > best_r:
            best_r, best_j, best_s = r, j, steno_sentences[j]
    if best_j >= 0:
        ptr = best_j
        pairs.append((hms, spk, ai_text, best_s, best_r))

near = [p for p in pairs if 0.55 <= p[4] < 0.965]
print(f"# {tag}: near-miss pairs {len(near)}", file=sys.stderr)

with open(f"_diff_{tag}.txt", "w", encoding="utf-8") as f:
    for hms, spk, ai_text, steno_text, r in near:
        f.write(f"[{hms}] r={r:.2f}\n  AI : {ai_text}\n  속기: {steno_text}\n\n")
print(f"# wrote _diff_{tag}.txt", file=sys.stderr)
