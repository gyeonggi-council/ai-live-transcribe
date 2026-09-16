"""사람 이름 퍼지 매칭 — 순수 함수(설정·DB 를 끌어오지 않는다, 2026-09-15).

`clip_draft_index._jamo`·`_resolve_name` 과 `kms_angun_service.rank_councilors` 의 규칙을 그대로 옮겼다.
그 모듈들을 import 하면 설정·httpx·supabase 가 따라와 `rag_context` 를 순수하게 시험할 수 없어서다.

규칙: 정확 일치 → 글자 유사도(성·글자수 같으면 +0.1, 0.75 이상) → 자모 유사도(글자수 같을 때, 성 같으면 +0.05, 0.78 이상).
사용자가 "이자영 의원"이라 적거나 STT 가 모음·받침을 틀려도(이자영→이자형 0.767) 명단 이름으로 맞춘다.
근소 동점(0.05 미만)은 `prefer`(이 회의에서 실제로 말한 사람) 쪽, 완전 동점은 None — 아무나 고르면 다른 사람 발언이 된다.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Iterable

_JAMO_L = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JAMO_V = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_JAMO_T = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"


def jamo(s: str) -> str:
    out = []
    for ch in s:
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            out.append(_JAMO_L[code // 588] + _JAMO_V[code % 588 // 28] + _JAMO_T[code % 28].strip())
        else:
            out.append(ch)
    return "".join(out)


def _norm(name: str) -> str:
    return (name or "").replace(" ", "")


def _score(n: str, cand: str) -> float:
    if cand == n:
        return 1.0
    best = 0.0
    r = SequenceMatcher(None, n, cand).ratio()
    if cand[0] == n[0] and len(cand) == len(n):
        r = min(0.999, r + 0.1)
    if r >= 0.75:
        best = r
    if len(cand) == len(n):
        j = SequenceMatcher(None, jamo(n), jamo(cand)).ratio()
        if cand[0] == n[0]:
            j = min(0.999, j + 0.05)
        if j >= 0.78:
            best = max(best, j)
    return best


def similarity(a: str, b: str) -> float:
    """두 이름의 유사도(0~1, 문턱 미만은 0) — 같은 사람의 다른 표기인지 볼 때."""
    a, b = _norm(a), _norm(b)
    return _score(a, b) if a and b else 0.0


def resolve_person(raw: str, candidates: Iterable[str], *, prefer: Iterable[str] = ()) -> str | None:
    """raw → candidates 중 한 이름. 못 맞추거나 누구인지 가릴 수 없으면 None."""
    n = _norm(raw)
    if not n:
        return None
    scored: dict[str, float] = {}
    for c in candidates:
        cand = _norm(c)
        if cand:
            sc = _score(n, cand)
            if sc > 0:
                scored[cand] = max(sc, scored.get(cand, 0.0))
    if not scored:
        return None
    ranked = sorted(scored.items(), key=lambda kv: -kv[1])
    top_name, top = ranked[0]
    if top < 1.0 and len(ranked) > 1 and top - ranked[1][1] < 0.05:
        near = [name for name, sc in ranked if top - sc < 0.05]
        preferred = {_norm(p) for p in prefer}
        hit = [name for name in near if name in preferred]
        if len(hit) == 1:
            return hit[0]
        if abs(top - ranked[1][1]) < 1e-9:
            return None
    return top_name
