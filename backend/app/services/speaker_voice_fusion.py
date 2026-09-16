"""VOD 음성 화자 융합 — 텍스트 화자귀속 결과를 창(window) 단위 화자 임베딩으로 교정 (2026-09-05).

왜: 화자 라벨은 `text_speaker_service` 가 자막 텍스트만 읽어 붙이고, 단서가 없으면 직전 화자를
유지한다. 그래서 턴 교대를 놓친 구간 전체가 한 의원에게 붙는다(속기 대조 실측: 위원 발언 일치율
74~85%). 이 모듈은 같은 회의 안에서 "텍스트 단서가 확실한 창"(호명 뒤 발언·자기소개·위원장 진행 멘트)
을 앵커로 삼아 라벨별 목소리 기준(centroid)을 만들고, 나머지 창을 목소리로 다시 판정한다.

설계 (계획서 Phase 1a — 군집·등록 없음):
  창      텍스트 라벨이 같고 간격 <1s 인 연속 라인을 ≤10s 로 묶는다. 라인은 원자 — 자르지 않고
          자기 창의 판정을 상속. <window_min 창은 판정 제외. (라인 시각은 글자수 비례 추정이라
          라인 단위로 임베딩하지 않는다.)
  앵커    ① 위원장 라벨 + 진행 멘트  ② 호명("다음은 OO 의원님 질의/진행해 주시기…") 뒤 60초 안의
          **첫 비(非)위원장 창 2개** — 상임위 의사 규칙상 호명 다음 발언자는 그 위원이므로 텍스트 라벨이
          틀렸어도 그 위원으로 고정한다(2026-09-05 실측: 텍스트가 턴 시작을 놓친 경우가 많았다)
          ③ 자기소개("OOO 위원입니다" / "건설국장 OOO입니다") 창 + 다음 같은 라벨 창
          앵커가 하나도 없는 라벨은 "앵커 목소리로 설명되지 않는 그 라벨 창"(폴백)으로 기준을 만들되,
          폴백 기준은 R1 의 덮어쓰기 대상이 되지 않는다(남의 목소리를 자기 것으로 삼는 사고 방지).
  기준    순도 필터(centroid 와 cos<τ_purity 제거) → 부트스트랩: 텍스트 라벨과 음성 판정이 **일치**하는
          확신 창만 앵커에 추가(순환 오염 없음) → 재계산. 앵커 ≥2 이면 "신뢰".
  턴      호명 ~ "OO 의원님 수고하셨습니다" 사이는 그 위원의 질의 턴 — 위원장·그 위원·집행부만 발언한다.
          턴 안에서 다른 위원 라벨이 붙은 창은 그 위원(목소리 일치) 아니면 집행부로 고친다(R4).
  판정    R0 단서 창은 유지 · R1 best≠t, s(best)≥τ_override & 마진≥τ_margin → best(앵커 라벨만)
          R2 t 가 위원이고 s(t)<τ_reject → "집행부"(직책 미상) · R3 그 외 유지
임베딩은 서브프로세스 워커(`speaker_embedding_worker.py`, sherpa-onnx CPU)가 뽑는다. 실패는 전부
호출측(vod_stt_service)이 warning 으로 삼키고 텍스트 결과를 유지한다(fail-soft).
"""

from __future__ import annotations

# ruff: noqa: N803, N806  (numpy 행렬 E·X·C·S 는 관례상 대문자)

import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.core.proc_priority import LOW_PRIORITY
from app.services.text_speaker_service import _NAME_TITLE_INTRO, _TITLE_NAME_INTRO

logger = logging.getLogger(__name__)

RATE = 16000
GENERIC_OFFICIAL = "집행부"
_MEMBER_TOKENS = {"위원", "위원장", "부위원장", "의원", "의장", "부의장"}
# 위원장 진행 멘트 — 이 문구가 든 위원장 라벨 창은 위원장 목소리 앵커
_CHAIR_CUE = re.compile(
    r"상정|의결|선포|이의\s*없|질의\s*(?:하세요|해\s*주시|종결)|다음은|의사일정|산회|개의|정회|속개|"
    r"수고하셨습니다|수고\s*많으|질의하실\s*(?:위원|의원)"
)
# 호명 — "다음은 OO 의원님 질의/진행/발언해 주시기 바랍니다" (STT 가 '진위해' 로 깨도 '주시기/바랍니다' 로 잡는다)
#   동사를 엄격히 — 집행부의 "OO 위원님 말씀하신 대로" 는 호명이 아니다. 텍스트 라벨이 위원장인지는
#   보지 않는다(위원장 라인이 다른 사람으로 붙는 일이 잦아, 그걸 조건으로 걸면 호명 절반을 놓친다).
_CALL_RE = re.compile(
    r"([가-힣]{2,4})\s*(?:부위원장|위원|의원)(?:님)?[^가-힣]{0,3}"
    r"(?:질의|출의|진행|발언|말씀\s*(?:부탁|해\s*주|하시기)|주시기|바랍니다|하세요|해\s*주|하시기|하시겠|차례|주십시오)"
)
_NEXT_RE = re.compile(r"다음(?:은|으로)?\s*([가-힣]{2,4})\s*(?:위원|의원)")
# 동사 없는 호명 — "다음 질의하실 의원이 계십니까? 네. 이자영 의원님." (같은 라인에 '다음/질의하실' 문맥이 있을 때만)
_CALL_BARE = re.compile(
    r"(?:다음|질의하실|계십니까)[^\n]*?([가-힣]{2,4})\s*(?:위원|의원)님?\s*[.。!?]?\s*$"
)
# 자기소개 — "성남 출신 문승호입니다" (명부 이름 + 입니다; 위원/의원 없이도)
_SELFINTRO_NAME = re.compile(r"([가-힣]{2,4})\s*(?:위원|의원)?\s*입니다")
_TURN_END = re.compile(r"수고\s*(?:하셨|많으셨)|(?:위원|의원)님?\s*(?:감사합니다|고맙습니다)")
_SELFINTRO_MEMBER = re.compile(r"([가-힣]{2,4})\s*(?:위원|의원)\s*입니다")


def _fuzzy(name: str, names: dict[str, str] | set[str], threshold: float = 0.66) -> str | None:
    """STT 가 깨뜨린 이름('이자영')을 명부 이름('이자형')에 맞춘다. 정확 일치 우선, 아니면 ratio≥threshold."""
    from difflib import SequenceMatcher

    if name in names:
        return name

    def sim(c: str) -> float:
        r = SequenceMatcher(None, name, c).ratio()
        if len(c) == len(name):
            # 자리별 일치, 성씨(첫 글자)는 가중 2 — STT 는 이름 끝 글자를 자주 틀리고 성씨는 거의 안 틀린다.
            # ('이자영' → 이자형 ○ / 전자영 × · '김희철' → 김회철 ○ / 김동희 ×)
            w = [2.0] + [1.0] * (len(c) - 1)
            pos = sum(wt for wt, x, y in zip(w, name, c, strict=False) if x == y) / sum(w)
            return 0.5 * r + 0.5 * pos
        return r

    scored = sorted(((sim(c), c) for c in names), reverse=True)
    if not scored or scored[0][0] < threshold:
        return None
    if len(scored) > 1 and scored[1][0] >= scored[0][0] - 1e-9:
        return None  # 동점('김영은' → 김영희/김영훈) — 엉뚱한 사람에게 앵커를 주느니 포기
    return scored[0][1]


@dataclass
class FusionConfig:
    """보정 노브 — `scripts/eval_voice_fusion.py` 결과로 맞춘다(모델 교체 시 재보정)."""

    window_max_seconds: float = 10.0
    window_min_seconds: float = 1.5
    gap_max_seconds: float = 1.0
    cos_override: float = 0.55  # R1: 다른 화자로 덮어쓰는 최소 유사도
    cos_override_official: float = (
        0.55  # R1: 집행부 라벨 창을 위원으로 덮어쓸 때. 0.65 로 올려 봤으나 집행부→위원
    )
    # 오류는 그대로(93→92)이고 위원 정확도만 깎여 같은 값으로 둔다(2026-09-05)
    cos_margin: float = 0.10  # R1: 1위-2위 차
    cos_reject: float = 0.35  # R2: 텍스트 위원 라벨 기각 → "집행부"
    cos_purity: float = 0.45  # 앵커 순도(centroid 와의 최소 유사도)
    min_anchors: int = 2  # 신뢰 centroid 최소 앵커 수
    boot_rounds: int = 2  # 부트스트랩 반복
    call_window_seconds: float = 60.0
    call_anchor_windows: int = 2  # 호명 뒤 앵커로 고정할 창 수
    turn_scoping: bool = True  # 질의 턴 규칙(R4)
    fallback_centroids: bool = True  # 앵커 없는 라벨의 폴백 기준(후보 경쟁용 — R1·R2 대상 아님)
    passes: int = 3  # 판정 → 라벨 갱신 → 기준 재계산 → 재판정 횟수
    cut_after_question: bool = False  # 물음표로 끝나는 라인 뒤에서 창을 끊는다(질문→답변 경계, 실험)
    threads: int = 1
    timeout_seconds: int = 1200
    model_path: str = "models/speaker.onnx"

    @classmethod
    def from_settings(cls) -> FusionConfig:
        from app.core.config import settings

        c = cls()
        for f in (
            "cos_override",
            "cos_override_official",
            "cos_margin",
            "cos_reject",
            "cos_purity",
            "window_max_seconds",
            "window_min_seconds",
            "threads",
            "timeout_seconds",
            "model_path",
        ):
            v = getattr(settings, f"voice_{f}", None)
            if v is not None:
                setattr(c, f, v)
        return c


def is_member_label(label: str | None) -> bool:
    toks = (label or "").split()
    return bool(toks) and toks[-1] in _MEMBER_TOKENS


def label_name(label: str | None) -> str:
    toks = (label or "").split()
    return toks[0] if toks and toks[0] not in _MEMBER_TOKENS else ""


# ── 1. 창 ──────────────────────────────────────────────────────────────────
def _is_turn_boundary(text: str, cut_after_question: bool = False) -> tuple[bool, bool]:
    """(이 라인 앞에서 창을 끊는가, 이 라인 뒤에서 끊는가). 호명·턴 종료 뒤와 자기소개 앞은 화자가 바뀐다 —
    텍스트 라벨이 같아 한 창으로 묶이면 위원장 호명과 위원의 첫 발언이 한 임베딩이 된다(2026-09-05 실측)."""
    after = bool(
        _CALL_RE.search(text)
        or _NEXT_RE.search(text)
        or _CALL_BARE.search(text)
        or _TURN_END.search(text)
        or (cut_after_question and text.rstrip().endswith("?"))
    )
    before = bool(
        _SELFINTRO_NAME.search(text)
        or _TITLE_NAME_INTRO.search(text)
        or _NAME_TITLE_INTRO.search(text)
    )
    return before, after


def build_windows(subs: list[dict], cfg: FusionConfig) -> list[dict]:
    """[{label, start, end, lines:[idx], cue, short, turn}] — 시간순 전제."""
    wins: list[dict] = []
    cur: dict | None = None
    cut_next = False
    for i, s in enumerate(subs):
        st, en = float(s.get("start_time") or 0), float(s.get("end_time") or 0)
        if en <= st:
            en = st + 0.5
        label = s.get("speaker") or None
        before, after = _is_turn_boundary(s.get("text") or "", cfg.cut_after_question)
        if (
            cur is not None
            and cur["label"] == label
            and not cut_next
            and not before
            and st - cur["end"] < cfg.gap_max_seconds
            and en - cur["start"] <= cfg.window_max_seconds
        ):
            cur["end"] = en
            cur["lines"].append(i)
        else:
            cur = {"label": label, "start": st, "end": en, "lines": [i], "cue": False, "turn": None}
            wins.append(cur)
        cut_next = after
    for w in wins:
        w["short"] = (w["end"] - w["start"]) < cfg.window_min_seconds
    return wins


# ── 2. 앵커·턴 ─────────────────────────────────────────────────────────────
def _member_labels(subs: list[dict], roster: list[dict]) -> dict[str, str]:
    """명부 이름 → 자막에 쓰인 라벨 문자열(없으면 '이름 직위')."""
    seen: dict[str, str] = {}
    for s in subs:
        lab = s.get("speaker") or ""
        n = label_name(lab)
        if n and is_member_label(lab) and n not in seen:
            seen[n] = lab
    out = {}
    for m in roster:
        n = m.get("name")
        if not n:
            continue
        role = m.get("role") or "위원"
        out[n] = seen.get(n, f"{n} {role if role in ('위원장', '부위원장') else '위원'}")
    return out


def find_anchors(
    wins: list[dict], subs: list[dict], roster: list[dict], cfg: FusionConfig
) -> dict[str, list[int]]:
    """라벨 → 앵커 창 인덱스. 단서가 든 창은 `cue=True`(R0 보호). 호명 뒤 창은 라벨을 그 위원으로 고정.
    질의 턴(호명 ~ 수고하셨습니다)을 창의 `turn` 에 (위원 라벨) 로 표시한다."""
    anchors: dict[str, list[int]] = {}
    chair_names = {m["name"] for m in roster if (m.get("role") or "") == "위원장" and m.get("name")}
    labels_of = _member_labels(subs, roster)
    win_of_line = {i: wi for wi, w in enumerate(wins) for i in w["lines"]}

    def add(label: str, wi: int) -> None:
        if wins[wi]["short"]:
            return
        lst = anchors.setdefault(label, [])
        if wi not in lst:
            lst.append(wi)
        wins[wi]["cue"] = True

    member_names = {n for n in labels_of if n not in chair_names}
    for wi, w in enumerate(wins):
        label = w["label"]
        name = label_name(label) if label else ""
        joined = " ".join((subs[i].get("text") or "") for i in w["lines"])
        if name in chair_names and _CHAIR_CUE.search(joined):  # ① 위원장 진행 멘트
            add(label, wi)
        intro = set(_SELFINTRO_MEMBER.findall(joined))  # ③ 자기소개 (위원)
        intro |= {n for _, n in _TITLE_NAME_INTRO.findall(joined)}  #    집행부 양방향
        intro |= {n for n, _ in _NAME_TITLE_INTRO.findall(joined)}
        if name and name in intro:
            add(label, wi)
            for wj in range(wi + 1, min(wi + 4, len(wins))):
                if wins[wj]["label"] == label:
                    add(label, wj)
                    break
            continue
        # 명부 위원의 자기소개("성남 출신 문승호입니다" / "광주 출신 이자영 의원입니다")인데 라벨이 다르면
        # 그 위원으로 고정. 퍼지 매칭은 '출신'·'의원입니다' 문맥이 있을 때만(아무 'OO입니다' 나 이름으로 보지 않게)
        #   위원장 라벨 창은 '출신' 이 있을 때만(위원장이 남을 "OO 출신 XXX입니다" 로 소개하지는 않는다)
        if not w["short"] and (name not in chair_names or "출신" in joined):
            fuzzy_ok = bool(re.search(r"출신|(?:위원|의원)\s*입니다", joined))
            for cand in _SELFINTRO_NAME.findall(joined):
                hit = (
                    cand
                    if cand in member_names
                    else (_fuzzy(cand, member_names) if fuzzy_ok else None)
                )
                if hit:
                    w["label"] = labels_of[hit]
                    add(labels_of[hit], wi)
                    break

    # ② 호명 → 턴 시작. STT 가 이름을 깨뜨리면(이자형→이자영) 명부와 퍼지 매칭한다.
    #    패턴 셋을 모두 시도한다 — 첫 패턴이 '질의하실' 같은 낱말을 이름으로 잡으면 뒤 패턴 차례가 와야 한다.
    calls: list[tuple[int, str, float]] = []  # (line idx, member label, t0)
    for i, s in enumerate(subs):
        text = s.get("text") or ""
        if _TURN_END.search(text):
            continue
        for pat in (_CALL_RE, _NEXT_RE, _CALL_BARE):
            hit = None
            for m in pat.finditer(text):
                hit = _fuzzy(m.group(1), member_names)
                if hit:
                    break
            if hit:
                calls.append((i, labels_of[hit], float(s.get("start_time") or 0)))
                break
    ends = [float(s.get("start_time") or 0) for s in subs if _TURN_END.search(s.get("text") or "")]
    call_lines = {i for i, _, _ in calls}
    for k, (i, label, t0) in enumerate(calls):
        got = 0
        for wj in range(win_of_line.get(i, 0) + 1, len(wins)):
            w = wins[wj]
            if w["start"] - t0 > cfg.call_window_seconds:
                break
            texts = " ".join((subs[x].get("text") or "") for x in w["lines"])
            if _TURN_END.search(texts) or any(x in call_lines for x in w["lines"]):
                break  # 턴이 끝났거나 다음 호명 — 그 뒤는 다른 사람이다
            if w["short"] or w["cue"]:
                continue  # 자기소개·진행 멘트로 이미 고정된 창은 건너뛴다(명시 단서 우선)
            if _CHAIR_CUE.search(texts):
                continue  # 위원장 진행 멘트(라벨과 무관하게 텍스트로 판단)
            if w["label"] != label:
                w["orig_label"] = w["label"]
                w["label"] = (
                    label  # 텍스트가 턴 시작을 놓침 → 호명된 위원으로 고정 (기준 검증 뒤 되돌릴 수 있다)
                )
            w["forced"] = label
            add(label, wj)
            got += 1
            if got >= cfg.call_anchor_windows:
                break
        if cfg.turn_scoping:
            t_next = calls[k + 1][2] if k + 1 < len(calls) else float("inf")
            t_end = min([t for t in ends if t > t0] + [float("inf")])
            t1 = min(t_next, t_end)
            for wj in range(win_of_line.get(i, 0) + 1, len(wins)):
                if wins[wj]["start"] >= t1:
                    break
                wins[wj]["turn"] = label
    return anchors


# ── 3. 기준(centroid) ───────────────────────────────────────────────────────
def _centroid(E: np.ndarray, idxs: list[int]) -> np.ndarray:
    c = E[idxs].mean(axis=0)
    return c / (np.linalg.norm(c) + 1e-9)


def build_centroids(
    E: np.ndarray, wins: list[dict], anchors: dict[str, list[int]], cfg: FusionConfig
) -> dict[str, tuple[np.ndarray, int, bool]]:
    """라벨 → (centroid, 앵커 수, anchored). anchored=False 는 폴백(텍스트 다수결) 기준."""
    valid = [wi for wi, w in enumerate(wins) if not w["short"] and np.any(E[wi])]
    by_label: dict[str, list[int]] = {}
    for wi in valid:
        if wins[wi]["label"]:
            by_label.setdefault(wins[wi]["label"], []).append(wi)

    def majority(idxs: list[int]) -> list[int]:
        """앵커가 두 목소리로 갈리면(사회 대행·호명 오탐) 다수 쪽만. 2-평균(코사인), 중심 간 cos<τ_override 일 때."""
        if len(idxs) < 6:
            return idxs
        X = E[idxs]
        c0 = X[0]
        c1 = X[int(np.argmin(X @ c0))]
        assign = np.zeros(len(idxs), dtype=bool)
        for _ in range(6):
            assign = (X @ c1) > (X @ c0)
            if assign.all() or (~assign).all():
                return idxs
            c0 = X[~assign].mean(axis=0)
            c0 /= np.linalg.norm(c0) + 1e-9
            c1 = X[assign].mean(axis=0)
            c1 /= np.linalg.norm(c1) + 1e-9
        if float(c0 @ c1) >= cfg.cos_override or min(assign.sum(), (~assign).sum()) < 3:
            return idxs
        big = assign if assign.sum() >= (~assign).sum() else ~assign
        return [idxs[k] for k in np.flatnonzero(big)]

    def refine(seed_map: dict[str, list[int]]) -> dict[str, list[int]]:
        out = {}
        for label, idxs in seed_map.items():
            keep = majority(list(idxs))
            for _ in range(2):  # 순도 필터 2회
                if len(keep) < cfg.min_anchors:
                    break
                c = _centroid(E, keep)
                nxt = [wi for wi in keep if float(E[wi] @ c) >= cfg.cos_purity]
                if len(nxt) < cfg.min_anchors:
                    break
                keep = nxt
            if keep:
                out[label] = keep
        return out

    seeds = refine(
        {lab: [wi for wi in a if wi in by_label.get(lab, [])] for lab, a in anchors.items()}
    )
    anchored = set(seeds)

    def scores(seed_map: dict[str, list[int]]):
        names = [lab for lab, idxs in seed_map.items() if len(idxs) >= cfg.min_anchors]
        if not names:
            return names, None
        C = np.stack([_centroid(E, seed_map[lab]) for lab in names])
        return names, E @ C.T

    # 부트스트랩: 텍스트 라벨 == 음성 1위(확신) 인 창을 앵커에 추가 — 순환 오염 없음
    for _ in range(cfg.boot_rounds):
        names, S = scores(seeds)
        if S is None:
            break
        grown = {lab: list(idxs) for lab, idxs in seeds.items()}
        for wi in valid:
            t = wins[wi]["label"]
            if not t or t not in names:
                continue
            row = S[wi]
            j = int(row.argmax())
            second = float(np.partition(row, -2)[-2]) if len(row) > 1 else -1.0
            if names[j] == t and row[j] >= cfg.cos_override and row[j] - second >= cfg.cos_margin:
                if wi not in grown[t]:
                    grown[t].append(wi)
        seeds = refine(grown)

    # 폴백: 앵커 없는 라벨 — 앵커 목소리로 설명되는 창(어느 앵커 기준과 cos≥τ_override)을 뺀 나머지
    if cfg.fallback_centroids:
        names, S = scores(seeds)
        for label, idxs in by_label.items():
            if label in seeds:
                continue
            rest = [wi for wi in idxs if S is None or float(S[wi].max()) < cfg.cos_override]
            if len(rest) >= 3:
                fb = refine({label: rest})
                if label in fb:
                    seeds[label] = fb[label]
    # 호명으로 강제한 앵커가 순도·다수 필터에서 떨어졌으면 목소리가 그 위원이 아니었다는 뜻 — 고정을 풀고
    # 원래 텍스트 라벨로 되돌려 일반 규칙에 맡긴다(호명 뒤 다른 사람이 먼저 말한 경우).
    for wi, w in enumerate(wins):
        f = w.get("forced")
        if f and wi not in seeds.get(f, []) and wi in anchors.get(f, []):
            w["cue"] = False
            w["label"] = w.get("orig_label", w["label"])
            w["forced"] = None
    return {
        lab: (_centroid(E, idxs), len(idxs), lab in anchored) for lab, idxs in seeds.items() if idxs
    }


# ── 4. 판정 ─────────────────────────────────────────────────────────────────
def decide(
    E: np.ndarray,
    wins: list[dict],
    cents: dict[str, tuple[np.ndarray, int, bool]],
    cfg: FusionConfig,
    vice_labels: frozenset[str] = frozenset(),
) -> list[tuple[str | None, str]]:
    """창별 (새 라벨 또는 None=유지, 규칙 이름)."""
    reliable = [lab for lab, (_, n, _) in cents.items() if n >= cfg.min_anchors]
    if not reliable:
        return [(None, "R3")] * len(wins)
    C = np.stack([cents[lab][0] for lab in reliable])
    r1_ok = {lab for lab in reliable if cents[lab][2]}  # R1 대상은 앵커 라벨만
    strong = cfg.cos_override + 0.15  # 구조 규칙(턴·단서)을 뒤집을 만큼 강한 목소리 증거
    # R5 후보: 명부에 부위원장이 있으면 그들, 없으면(명부 원천 둘 다 역할이 '위원'뿐이다) 앵커 있는 위원 전원
    r5_cands = [v for v in vice_labels if v in r1_ok] or [
        lab for lab in r1_ok if is_member_label(lab) and not lab.endswith("위원장")
    ]
    out: list[tuple[str | None, str]] = []
    for wi, w in enumerate(wins):
        t = w["label"]
        if w["cue"]:
            # R5: 사회 대행 — 위원장 진행 멘트 창인데 목소리가 위원장보다 어느 위원(앵커)과 훨씬 강하게 일치.
            #     위원장 기준 자체가 두 목소리로 오염돼 있을 수 있어 절대값이 아니라 상대 비교로 본다.
            if (
                t
                and t.endswith("위원장")
                and not t.endswith("부위원장")
                and np.any(E[wi])
                and t in cents
                and r5_cands
            ):
                s_chair = float(E[wi] @ cents[t][0])
                s_v, v = max((float(E[wi] @ cents[c][0]), c) for c in r5_cands)
                if s_v >= cfg.cos_override + 0.10 and s_v - s_chair >= cfg.cos_margin / 2:
                    out.append((v, "R5"))
                    continue
            out.append((None, "R0"))
            continue
        if w["short"] or not np.any(E[wi]):
            out.append((None, "R3"))
            continue
        row = E[wi] @ C.T
        turn = w.get("turn")
        # 턴 안에서는 그 위원·위원장·집행부만 후보 — 다른 위원 라벨은 목소리가 아주 강할 때만(끼어들기)
        cand = [
            j
            for j, lab in enumerate(reliable)
            if not (
                turn
                and is_member_label(lab)
                and lab != turn
                and not lab.endswith("위원장")
                and row[j] < strong
            )
        ]
        if not cand:
            out.append((None, "R3"))
            continue
        j = max(cand, key=lambda k: row[k])
        best, s_best = reliable[j], float(row[j])
        # 마진은 앵커 라벨끼리만 — 폴백 기준은 남의 목소리가 섞여 마진을 잠식한다
        s_second = max(
            (float(row[k]) for k in cand if k != j and reliable[k] in r1_ok), default=-1.0
        )
        s_t = float(E[wi] @ cents[t][0]) if t in cents else None
        t_anchored = bool(t and t in cents and cents[t][2] and cents[t][1] >= cfg.min_anchors)
        # R4: 턴 안의 다른 위원 라벨 — 목소리 증거가 있을 때만: 호명된 위원과 일치 → 그 위원,
        #     자기 라벨(앵커)과 불일치 → 집행부. 둘 다 아니면 건드리지 않는다(호명을 놓친 턴일 수 있다).
        if (
            turn
            and t
            and is_member_label(t)
            and t != turn
            and not t.endswith("위원장")
            and s_best < strong
        ):
            s_turn = float(E[wi] @ cents[turn][0]) if turn in cents else -1.0
            if s_turn >= cfg.cos_override:
                out.append((turn, "R4"))
                continue
            if t_anchored and s_t is not None and s_t < cfg.cos_reject:
                out.append((GENERIC_OFFICIAL, "R4"))
                continue
        need_margin = cfg.cos_margin * (
            0.5 if s_best >= strong else 1.0
        )  # 아주 강한 일치는 마진을 덜 요구
        need_s = (
            cfg.cos_override_official
            if (t and not is_member_label(t) and is_member_label(best))
            else cfg.cos_override
        )
        if best != t and best in r1_ok and s_best >= need_s and s_best - s_second >= need_margin:
            out.append((best, "R1"))
            continue
        # R2 는 앵커 라벨만 — 폴백 기준은 남의 목소리일 수 있어 진짜 발언을 강등시킨 사례가 있었다
        if t and is_member_label(t) and s_t is not None and t_anchored and s_t < cfg.cos_reject:
            out.append((GENERIC_OFFICIAL, "R2"))
            continue
        out.append((None, "R3"))
    return out


def apply_decisions(
    wins: list[dict], decisions: list[tuple[str | None, str]], subs: list[dict]
) -> dict[str, int]:
    stats = {"R0": 0, "R1": 0, "R2": 0, "R3": 0, "R4": 0, "R5": 0, "changed_lines": 0}
    for w, (new, rule) in zip(wins, decisions, strict=False):
        stats[rule] += 1
        final = (
            new if new is not None else w["label"]
        )  # 호명으로 고정된 창은 w["label"] 이 이미 바뀌어 있다
        if final is None:
            continue
        for i in w["lines"]:
            if subs[i].get("speaker") != final:
                subs[i]["speaker"] = final
                stats["changed_lines"] += 1
    return stats


# ── 5. 오케스트레이션 ──────────────────────────────────────────────────────
# 하위 프로세스는 생중계 STT 와 같은 파드에서 돈다 — 경합하면 생중계가 먼저다. 임베딩 워커는 스스로
# `os.nice(10)` 하고, ffmpeg 는 `app.core.proc_priority` 로 낮춘다(VOD 등록 직후 낮에도 자동 생성, 2026-09-10).
async def extract_pcm(mp4_path: str | Path, pcm_path: str | Path) -> None:
    proc = await asyncio.create_subprocess_exec(
        *LOW_PRIORITY,
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(mp4_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(RATE),
        "-f",
        "s16le",
        str(pcm_path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await asyncio.wait_for(proc.communicate(), timeout=1800)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg pcm 추출 실패 rc={proc.returncode}: {err[:200].decode('utf-8', 'ignore')}"
        )


async def run_worker(
    pcm_path: str | Path, wins: list[dict], cfg: FusionConfig, workdir: Path
) -> np.ndarray:
    spans = [[w["start"], w["end"]] for w in wins]
    cache_dir = os.environ.get("VOICE_EMB_CACHE")  # 평가 반복용(운영에서는 비움)
    cache = None
    if cache_dir:
        key = hashlib.sha1(
            (json.dumps(spans) + str(pcm_path) + cfg.model_path).encode()
        ).hexdigest()[:16]
        cache = Path(cache_dir) / f"emb_{key}.npy"
        if cache.exists():
            E = np.load(cache).astype(np.float32)
            return _normalize(E)
    win_json = workdir / "windows.json"
    out_npy = workdir / "emb.npy"
    win_json.write_text(json.dumps(spans), encoding="utf-8")
    worker = Path(__file__).with_name("speaker_embedding_worker.py")
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(worker),
        "--pcm",
        str(pcm_path),
        "--windows",
        str(win_json),
        "--out",
        str(out_npy),
        "--model",
        cfg.model_path,
        "--threads",
        str(cfg.threads),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout=cfg.timeout_seconds)
    except TimeoutError:
        proc.kill()
        raise RuntimeError(f"임베딩 워커 타임아웃 {cfg.timeout_seconds}s") from None
    if proc.returncode != 0:
        raise RuntimeError(
            f"임베딩 워커 실패 rc={proc.returncode}: {err[-300:].decode('utf-8', 'ignore')}"
        )
    E = np.load(out_npy).astype(np.float32)
    if cache is not None:
        np.save(cache, E)
    return _normalize(E)


def _normalize(E: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(E, axis=1, keepdims=True)
    return np.where(norms > 0, E / np.maximum(norms, 1e-9), 0.0).astype(np.float32)


def canonicalize_member_labels(subs: list[dict], roster: list[dict]) -> int:
    """같은 위원이 '국중범 위원'/'국중범 위원장', '서혜진 위원'/'서혜진 의원' 처럼 갈린 라벨을 하나로.
    명부 이름당 라벨 하나(먼저 쓰인 것). 반환: 바뀐 라인 수."""
    canon = _member_labels(subs, roster)
    n = 0
    for s in subs:
        lab = s.get("speaker") or ""
        if is_member_label(lab):
            c = canon.get(label_name(lab))
            if c and c != lab:
                s["speaker"] = c
                n += 1
    return n


async def fuse_voice_speakers(
    subs: list[dict],
    roster: list[dict],
    *,
    mp4_path: str | Path | None = None,
    pcm_path: str | Path | None = None,
    cfg: FusionConfig | None = None,
    debug: dict | None = None,
) -> dict[str, Any]:
    """자막(in-place)의 speaker 를 음성으로 교정. 반환: 통계. mp4_path 또는 pcm_path 중 하나 필수."""
    cfg = cfg or FusionConfig.from_settings()
    if not subs:
        return {"skipped": "no subtitles"}
    if not Path(cfg.model_path).exists():
        return {"skipped": f"model not found: {cfg.model_path}"}
    subs.sort(key=lambda s: float(s.get("start_time") or 0))
    canon_changed = canonicalize_member_labels(subs, roster)
    wins = build_windows(subs, cfg)
    workdir = Path(tempfile.mkdtemp(prefix="voicefuse_"))
    try:
        if pcm_path is None:
            if not mp4_path:
                raise ValueError("mp4_path 또는 pcm_path 가 필요합니다")
            pcm_path = workdir / "audio.pcm"
            await extract_pcm(mp4_path, pcm_path)
        E = await run_worker(pcm_path, wins, cfg, workdir)
        anchors = find_anchors(wins, subs, roster, cfg)
        labels_of = _member_labels(subs, roster)
        vice_labels = frozenset(
            labels_of[m["name"]]
            for m in roster
            if (m.get("role") or "") == "부위원장" and m.get("name") in labels_of
        )
        stats: dict[str, Any] = {}
        for p in range(max(1, cfg.passes)):
            cents = build_centroids(E, wins, anchors, cfg)
            decisions = decide(E, wins, cents, cfg, vice_labels)
            st = apply_decisions(wins, decisions, subs)
            for w, (new, _) in zip(
                wins, decisions, strict=False
            ):  # 다음 패스는 갱신된 라벨을 텍스트 라벨로 본다
                if new is not None:
                    w["label"] = new
            stats = (
                st
                if not stats
                else {**st, "changed_lines": stats["changed_lines"] + st["changed_lines"]}
            )
            stats[f"pass{p + 1}_changed"] = st["changed_lines"]
        stats.update(
            {
                "windows": len(wins),
                "canonicalized": canon_changed,
                "turns": len({w["turn"] for w in wins if w.get("turn")}),
                "anchors": {lab: len(v) for lab, v in anchors.items()},
                "reliable": sorted(
                    f"{lab}{'' if a else '(폴백)'}"
                    for lab, (_, n, a) in cents.items()
                    if n >= cfg.min_anchors
                ),
            }
        )
        if debug is not None:
            debug.update({"wins": wins, "E": E, "cents": cents, "decisions": decisions})
        return stats
    finally:
        for p in workdir.glob("*"):
            try:
                p.unlink()
            except OSError:
                pass
        try:
            workdir.rmdir()
        except OSError:
            pass
