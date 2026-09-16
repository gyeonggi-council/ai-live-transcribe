"""속기록 ↔ AI 자막 정렬 공용 모듈 (평가 스크립트 전용, 제품코드 아님).

왜 따로 있나 — `_score_accuracy.py` 식 "앞으로만 가는 포인터 ±25 창" 정렬은 집행부의 긴 업무보고처럼
속기록에 없는(또는 유사도가 낮은) 구간을 만나면 포인터가 멈추고, 이후 자막 전부가 그 자리의 화자에게
붙는다(2026-09-05 안행위 2차 재생성분에서 실측 — 위원 라인 621→146 으로 붕괴). 화자 지표는 정렬이
틀리면 통째로 틀리므로, 전 구간 단조(monotonic) 동적계획 정렬로 바꾼다.

- 유사도: 공백 제거 후 문자 바이그램 Jaccard (SequenceMatcher 보다 ~50배 빠르고 STT 오인식에 둔감)
- 정렬: AI 라인 i 를 속기 문장 j 에 단조 비감소로 대응. 속기 건너뛰기 페널티는 작게(자막이 속기보다
  촘촘하므로 같은 j 반복 허용), 대각 띠(band) 밖은 보지 않는다.
- 결과: 각 AI 라인의 (j, sim). sim < min_sim 이면 미정렬(None) — 채점에서 제외한다.
"""

from __future__ import annotations

import re

MEMBER_TOKENS = {"위원장", "부위원장", "위원", "의원", "의장", "부의장"}
# 이름이 아닌 2~4자 직책 토큰 — speaker_name 이 이름으로 오인하지 않게 한다.
TITLES = (
    "부위원장",
    "위원장",
    "위원",
    "의원",
    "의장",
    "부의장",
    "국장",
    "과장",
    "실장",
    "본부장",
    "단장",
    "처장",
    "담당관",
    "전문위원",
    "교육감",
    "부교육감",
    "지사",
    "도지사",  # 본회의 "도지사 추미애" — "지사" 정확일치로는 못 거른다(2026-09-08)
    "부지사",
    "감사관",
    "기획관",
    "청장",
    "관장",
    "대변인",
    "원장",
    "소장",
    "총장",
    "센터장",
    "차장",
    "부장",
    "팀장",
    "사무처장",
    "차관",
    "장관",
)


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def speaker_name(header: str) -> str | None:
    """'위원장 문형근' / '최효숙 의원' / '여성가족국장 박연경' → 이름부(2-4자)."""
    # '김영훈(화성3) 의원' — 지역구 괄호는 이름에서 뗀다 (393회 본회의 속기 실측)
    for tok in re.sub(r"\([^)]*\)", "", header or "").split():
        if re.fullmatch(r"[가-힣]{2,4}", tok) and tok not in TITLES:
            return tok
    return None


def is_member(header: str) -> bool:
    """속기 헤더 또는 AI 라벨이 위원(의원)인가 — 토큰 정확 일치('수석전문위원' 은 아님)."""
    return any(tok in MEMBER_TOKENS for tok in (header or "").split())


def parse_steno(raw: str) -> list[tuple[str | None, str, bool]]:
    """속기 본문 → [(화자 이름, 문장, 위원 여부)]. 본문은 '(N시 M분 개의)' 뒤부터 말미 명부 전까지."""
    items: list[tuple[str | None, str, bool]] = []
    cur, cur_m, in_body = None, False, False
    for line in raw.splitlines():
        line = line.strip().lstrip(">")
        if not line:
            continue
        if not in_body:
            if re.fullmatch(r"\(\d+시.*개의.*\)", line):
                in_body = True
            continue
        if line.startswith("○"):
            rest = line.lstrip("○").strip()
            if re.match(
                r"(출석위원|위원 아닌|출석전문위원|출석공무원|기타참석자|기록공무원)", rest
            ):
                break
            parts = re.split(r"\s{2,}", rest, maxsplit=1)
            cur, cur_m = speaker_name(parts[0]), is_member(parts[0])
            if len(parts) == 2 and len(norm(parts[1])) >= 4:
                line = parts[1]
            else:
                continue
        if re.fullmatch(r"\(.*\)", line) or re.fullmatch(r"[가-힣]{2,4}", line):
            continue
        for sent in re.split(r"(?<=[.?!])\s+", line):
            if len(norm(sent)) >= 4:
                items.append((cur, sent.strip(), cur_m))
    return items


def _bigrams(s: str) -> frozenset:
    s = norm(s)
    return frozenset(s[k : k + 2] for k in range(len(s) - 1))


def align(
    ai_texts: list[str],
    steno_texts: list[str],
    *,
    band: int = 400,
    min_sim: float = 0.25,
    skip_pen: float = 0.02,
) -> list[tuple[int, float] | None]:
    """AI 라인 → (속기 문장 인덱스, 유사도) 단조 정렬. 미정렬은 None.

    dp[i][j] = sim(i,j) + max_{j'≤j}(dp[i-1][j'] − skip_pen·(j−j'−1)+)  — 띠 폭 band 안에서만.
    """
    n, m = len(ai_texts), len(steno_texts)
    if not n or not m:
        return [None] * n
    A = [_bigrams(t) for t in ai_texts]
    B = [_bigrams(t) for t in steno_texts]
    NEG = -1e9
    prev = None  # dict j -> score (이전 행, 띠 안)
    back: list[dict[int, int]] = []
    for i in range(n):
        center = int(i * m / n)
        lo, hi = max(0, center - band), min(m, center + band + 1)
        a = A[i]
        cur: dict[int, float] = {}
        bp: dict[int, int] = {}
        if prev is None:
            for j in range(lo, hi):
                b = B[j]
                cur[j] = (len(a & b) / len(a | b) if (a or b) else 0.0) - skip_pen * j
                bp[j] = -1
        else:
            # 왼쪽에서 오른쪽으로 running max (건너뛰기 페널티 포함)
            run, run_j = NEG, -1
            for j in range(lo, hi):
                p = prev.get(j, NEG)
                if p > run:
                    run, run_j = p, j
                b = B[j]
                s = len(a & b) / len(a | b) if (a or b) else 0.0
                cur[j] = s + run
                bp[j] = run_j
                run -= skip_pen  # 다음 j 로 갈수록 건너뛴 만큼 감점
        back.append(bp)
        prev = cur
    # backtrack
    j = max(prev, key=prev.get)
    path = [0] * n
    for i in range(n - 1, -1, -1):
        path[i] = j
        j = back[i][j] if back[i][j] >= 0 else j
    out: list[tuple[int, float] | None] = []
    for i, j in enumerate(path):
        a, b = A[i], B[j]
        s = len(a & b) / len(a | b) if (a or b) else 0.0
        out.append((j, s) if s >= min_sim else None)
    return out


def score(ai_labels: list[str], steno_items: list, mapping: list) -> dict:
    """정렬된 쌍에서 위원/집행부 분리 지표를 센다 (eval_speaker_attribution.py 지표 정의)."""
    from collections import Counter

    c: Counter = Counter()
    conf_member: Counter = Counter()
    conf_official: Counter = Counter()
    pairs = 0
    for ai_spk, mp in zip(ai_labels, mapping, strict=False):
        if mp is None:
            continue
        pairs += 1
        s_spk, _, s_member = steno_items[mp[0]]
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
                c["wrong_member" if (ai_member and ai_name) else "member_to_official"] += 1
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
    return {
        "ai_lines": len(ai_labels),
        "aligned_pairs": pairs,
        "speaker_match_rate": round(match / total, 4) if total else 0.0,
        "member_total": c["member_total"],
        "member_match": c["member_match"],
        "member_match_rate": (
            round(c["member_match"] / c["member_total"], 4) if c["member_total"] else 0.0
        ),
        "wrong_member": c["wrong_member"],
        "member_to_official": c["member_to_official"],
        "official_total": c["official_total"],
        "official_match": c["official_match"],
        "official_match_rate": (
            round(c["official_match"] / c["official_total"], 4) if c["official_total"] else 0.0
        ),
        "official_unnamed": c["official_unnamed"],
        "official_wrong_name": c["official_wrong_name"],
        "official_to_member": c["official_to_member"],
        "top_confusions_member": [[s, a, n] for (s, a), n in conf_member.most_common(10)],
        "top_confusions_official": [[s, a, n] for (s, a), n in conf_official.most_common(10)],
    }


def print_score(m: dict, title: str = "") -> None:
    if title:
        print(f"--- {title}")
    print(f"aligned_pairs        = {m['aligned_pairs']} / {m['ai_lines']}")
    print(
        f"member_match_rate    = {m['member_match_rate']:.4f}  ({m['member_match']}/{m['member_total']})  ★주지표"
    )
    print(f"  wrong_member       = {m['wrong_member']}   (위원 A → 다른 위원 B)")
    print(f"  member_to_official = {m['member_to_official']}   (위원 → 집행부/미지정)")
    print(
        f"official_match_rate  = {m['official_match_rate']:.4f}  ({m['official_match']}/{m['official_total']})"
    )
    print(f"  official_unnamed   = {m['official_unnamed']}   ('집행부'/미지정 — 오류와 분리)")
    print(f"  official_wrong_name= {m['official_wrong_name']}")
    print(f"  official_to_member = {m['official_to_member']}   (집행부 → 위원, 위험)")
    print("top confusion pairs — 정답 위원 (steno→ai):")
    for s_name, a_name, cnt in m["top_confusions_member"]:
        print(f"  {cnt:4d}  {s_name} → {a_name}")
    print("top confusion pairs — 정답 집행부 (steno→ai):")
    for s_name, a_name, cnt in m["top_confusions_official"]:
        print(f"  {cnt:4d}  {s_name} → {a_name}")


if __name__ == "__main__":
    # 자체 검사: 속기에 없는 장문 블록(업무보고)이 중간에 끼어도 그 뒤 정렬이 복구되는가.
    steno = [f"의원 여러분 안건 제{k}항을 상정합니다 이의 없으십니까" for k in range(40)]
    ai = (
        steno[:20]
        + [f"보고 드리겠습니다 예산 {k}억 원 집행 현황입니다" for k in range(30)]
        + steno[20:]
    )
    ai = [t.replace("상정", "상점") for t in ai]  # STT 오인식 흉내
    res = align(ai, steno)
    assert all(r and r[0] == i for i, r in enumerate(res[:20])), res[:20]
    assert all(r is None for r in res[20:50]), "속기에 없는 블록은 미정렬이어야 한다"
    assert all(r and r[0] == i + 20 for i, r in enumerate(res[50:])), res[50:]
    print("ok")
