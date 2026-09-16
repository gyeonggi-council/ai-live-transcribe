# -*- coding: utf-8 -*-
"""속기 정답 vs AI 자막 정확도 점수화. 읽기 전용 평가 도구 (제품코드 아님).

사용: python scripts/_score_accuracy.py <steno_file> <ai_file> <tag>
출력: _score_<tag>.json 저장 + 요약 stdout.

지표:
  1. mean_ratio        정렬 쌍 SequenceMatcher ratio 평균
  2. name_errors       '이름+직책' 패턴에서 이름이 다른 쌍 수
  3. numeral_errors    숫자열(콤마/공백 정규화) 불일치 쌍 수
  4. speaker_match_rate 화자 이름부 일치율 (ai '?'는 불일치)
"""
import json
import re
import sys
from difflib import SequenceMatcher

sys.stdout.reconfigure(encoding="utf-8")

steno_file = sys.argv[1]
ai_file = sys.argv[2]
tag = sys.argv[3]

steno_raw = open(steno_file, encoding="utf-8").read()
ai_raw = open(ai_file, encoding="utf-8").read()

TITLES = (
    "부위원장", "위원장", "위원", "의원", "국장", "과장", "실장",
    "본부장", "단장", "처장", "담당관", "전문위원",
)
TITLE_RE = "|".join(TITLES)  # 긴 직책 우선 (부위원장 > 위원장 > 위원)
# 이름과 직책 사이 공백 필수 → '이민사회국장' 같은 복합 부서직책 오탐 방지
NAME_TITLE_RE = re.compile(r"(?<![가-힣])([가-힣]{2,4})\s+(" + TITLE_RE + r")(?![장회])")


def name_titles(text):
    """텍스트에서 (이름, 직책) 추출. 직책성 단어('위원회' 등)는 이름에서 제외."""
    out = {}
    for name, title in NAME_TITLE_RE.findall(text):
        if any(t in name for t in TITLES):
            continue
        out.setdefault(title, set()).add(name)
    return out


def norm(s):
    return re.sub(r"\s+", "", s)


def speaker_name(header):
    """'위원장 문형근' / '최효숙 의원' / '여성가족국장 박연경' → 이름부(2-4자)."""
    for tok in header.split():
        if re.fullmatch(r"[가-힣]{2,4}", tok) and tok not in TITLES:
            return tok
    return None


# --- steno 파싱: (speaker, sentence) 목록. 문장 분리는 _align_compare.py와 동일 ---
steno_items = []  # (speaker or None, sentence)
cur_speaker = None
in_body = False
for line in steno_raw.splitlines():
    line = line.strip().lstrip(">")
    if not line:
        continue
    if not in_body:
        if re.fullmatch(r"\(\d+시.*개의.*\)", line):
            in_body = True
        continue
    if line.startswith("○"):
        rest = line.lstrip("○").strip()
        # 본문 종료: 말미 명부(출석위원/출석공무원 등)는 발언이 아님
        if re.match(r"(출석위원|위원 아닌|출석전문위원|출석공무원|기타참석자|기록공무원)", rest):
            break
        parts = re.split(r"\s{2,}", rest, maxsplit=1)
        cur_speaker = speaker_name(parts[0])
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
            steno_items.append((cur_speaker, sent))

# --- ai 파싱: [HH:MM:SS] 화자: 텍스트 ---
ai_lines = []
for line in ai_raw.splitlines():
    m = re.match(r"\[(\d\d:\d\d:\d\d)\]\s*(.*?):\s*(.*)", line)
    if m:
        ai_lines.append((m.group(1), m.group(2), m.group(3)))

print(f"# {tag}: steno sents {len(steno_items)}, ai lines {len(ai_lines)}")

# --- 윈도우 정렬 (시간순 ±25, _align_compare.py와 동일) ---
W = 25
ptr = 0
pairs = []  # (hms, ai_spk, ai_text, steno_spk, steno_text, ratio)
for hms, spk, ai_text in ai_lines:
    an = norm(ai_text)
    if len(an) < 4:
        continue
    best_r, best_j = 0.0, -1
    lo, hi = max(0, ptr - 5), min(len(steno_items), ptr + W)
    for j in range(lo, hi):
        r = SequenceMatcher(None, an, norm(steno_items[j][1])).ratio()
        if r > best_r:
            best_r, best_j = r, j
    if best_j >= 0:
        # 확신 있는 매치에서만 포인터 전진 (저품질 매치로 인한 드리프트 방지)
        if best_r >= 0.55:
            ptr = best_j
        s_spk, s_sent = steno_items[best_j]
        pairs.append((hms, spk, ai_text, s_spk, s_sent, best_r))

# --- 1. mean_ratio ---
mean_ratio = sum(p[5] for p in pairs) / len(pairs) if pairs else 0.0

# --- 2. name_errors: 같은 직책에 이름이 서로 다른 쌍 ---
name_errors = 0
name_error_examples = []
for hms, _, ai_text, _, s_sent, _ in pairs:
    ai_names = name_titles(ai_text)
    st_names = name_titles(s_sent)
    diffs = []
    for title in set(ai_names) & set(st_names):
        # 양쪽 모두에 상대편에 없는 이름이 있고, 그 둘이 유사(near-miss)할 때만
        # 오인식으로 계산 ('앉으셔서 위원' 같은 비이름 오탐은 한쪽에만 나타남)
        un_ai = ai_names[title] - st_names[title]
        un_st = st_names[title] - ai_names[title]
        for a_name in sorted(un_ai):
            for s_name in sorted(un_st):
                if SequenceMatcher(None, a_name, s_name).ratio() >= 0.3:
                    diffs.append({"title": title, "ai": a_name, "steno": s_name})
    if diffs:
        name_errors += 1
        name_error_examples.append({"time": hms, "ai": ai_text, "steno": s_sent, "diffs": diffs})


def numerals(text):
    t = re.sub(r"(?<=\d)[,\s]+(?=\d)", "", text)
    return sorted(re.findall(r"\d+", t))


# --- 3. numeral_errors ---
numeral_errors = 0
numeral_error_examples = []
for hms, _, ai_text, _, s_sent, _ in pairs:
    a_num, s_num = numerals(ai_text), numerals(s_sent)
    if (a_num or s_num) and a_num != s_num:
        numeral_errors += 1
        numeral_error_examples.append({"time": hms, "ai_nums": a_num, "steno_nums": s_num,
                                       "ai": ai_text, "steno": s_sent})

# --- 4. speaker_match_rate ---
spk_total = 0
spk_match = 0
for _, ai_spk, _, s_spk, _, _ in pairs:
    if not s_spk:
        continue
    spk_total += 1
    ai_name = speaker_name(ai_spk) if ai_spk and ai_spk != "?" else None
    if ai_name == s_spk:
        spk_match += 1
speaker_match_rate = spk_match / spk_total if spk_total else 0.0

result = {
    "tag": tag,
    "steno_sentences": len(steno_items),
    "ai_lines": len(ai_lines),
    "aligned_pairs": len(pairs),
    "mean_ratio": round(mean_ratio, 4),
    "name_errors": name_errors,
    "name_error_examples": name_error_examples,
    "numeral_errors": numeral_errors,
    "numeral_error_examples": numeral_error_examples,
    "speaker_match_rate": round(speaker_match_rate, 4),
    "speaker_matched": spk_match,
    "speaker_total": spk_total,
}

out_path = f"_score_{tag}.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"# wrote {out_path}")
print(f"mean_ratio        = {mean_ratio:.4f}  (pairs={len(pairs)})")
print(f"name_errors       = {name_errors}")
print(f"numeral_errors    = {numeral_errors}")
print(f"speaker_match_rate= {speaker_match_rate:.4f}  ({spk_match}/{spk_total})")
