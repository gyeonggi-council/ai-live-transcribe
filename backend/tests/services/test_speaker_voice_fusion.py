"""speaker_voice_fusion 순수 로직 검증 — 모델 없이 합성 벡터로 창·앵커·기준·판정 규칙을 고정한다."""

from __future__ import annotations

# ruff: noqa: N806  (numpy 행렬 E·A·B·C·V 는 관례상 대문자)

import numpy as np
import pytest

from app.services import speaker_voice_fusion as svf

CFG = svf.FusionConfig(
    cos_override=0.55, cos_margin=0.10, cos_reject=0.35, cos_purity=0.45, min_anchors=2
)
ROSTER = [
    {"name": "김위장", "role": "위원장"},
    {"name": "박위원", "role": "위원"},
    {"name": "이위원", "role": "위원"},
]


def _sub(i: int, label: str | None, text: str = "발언", dur: float = 3.0, gap: float = 0.2) -> dict:
    st = i * (dur + gap)
    return {"start_time": st, "end_time": st + dur, "text": text, "speaker": label}


def _unit(rng, d=16):
    v = rng.normal(size=d)
    return v / np.linalg.norm(v)


def _voice(base, rng, noise=0.15):
    v = base + rng.normal(size=base.shape) * noise
    return v / np.linalg.norm(v)


# ── 창 ──────────────────────────────────────────────────────────────────────
def test_build_windows_groups_same_label_and_caps_length():
    subs = [_sub(i, "박위원 위원") for i in range(6)]  # 6 × 3.2s 연속 → 10s 상한으로 나뉜다
    wins = svf.build_windows(subs, CFG)
    assert [len(w["lines"]) for w in wins] == [3, 3]
    assert all(w["label"] == "박위원 위원" for w in wins)


def test_build_windows_breaks_on_label_change_and_gap():
    subs = [_sub(0, "박위원 위원"), _sub(1, "이위원 위원"), _sub(2, "이위원 위원")]
    subs[2]["start_time"] += 5  # 5초 공백
    subs[2]["end_time"] += 5
    wins = svf.build_windows(subs, CFG)
    assert [w["label"] for w in wins] == ["박위원 위원", "이위원 위원", "이위원 위원"]


def test_short_window_marked():
    wins = svf.build_windows([_sub(0, "박위원 위원", dur=1.0)], CFG)
    assert wins[0]["short"] is True


# ── 앵커 ────────────────────────────────────────────────────────────────────
def test_call_line_anchors_next_windows_of_called_member_not_the_chair():
    subs = [
        _sub(0, "김위장 위원장", "다음은 박위원 위원 질의하세요"),
        _sub(1, "박위원 위원", "네 질의하겠습니다"),
        _sub(2, "박위원 위원", "두 번째 질문입니다"),
        _sub(3, "박위원 위원", "세 번째"),
    ]
    subs[2]["start_time"] += 1.5
    subs[2]["end_time"] += 1.5  # 창을 나누기 위한 공백
    subs[3]["start_time"] += 3.0
    subs[3]["end_time"] += 3.0
    wins = svf.build_windows(subs, CFG)
    anchors = svf.find_anchors(wins, subs, ROSTER, CFG)
    # 호명 라인 자체는 위원장 진행 멘트 → 위원장 앵커. 호명된 박위원은 뒤 창 2개만 앵커.
    assert anchors["김위장 위원장"] == [0]
    assert anchors["박위원 위원"] == [1, 2]
    assert wins[3]["cue"] is False


def test_selfintro_anchors_member_and_official():
    subs = [
        _sub(0, "이위원 위원", "안녕하십니까 이위원 위원입니다"),
        _sub(1, "홍국장 건설국장", "건설국장 홍국장입니다"),
        _sub(2, "홍국장 건설국장", "보고드리겠습니다"),
    ]
    subs[2]["start_time"] += 1.5
    subs[2]["end_time"] += 1.5
    wins = svf.build_windows(subs, CFG)
    anchors = svf.find_anchors(wins, subs, ROSTER, CFG)
    assert anchors["이위원 위원"] == [0]
    assert anchors["홍국장 건설국장"] == [1, 2]


# ── 기준·판정 ────────────────────────────────────────────────────────────────
def _scenario(seed=0):
    """3 목소리(A=위원장, B=박위원, C=집행부). 텍스트가 C 의 창 일부를 B 로 잘못 붙였다."""
    rng = np.random.default_rng(seed)
    A, B, C = _unit(rng), _unit(rng), _unit(rng)
    labels = ["김위장 위원장"] * 3 + ["박위원 위원"] * 6 + ["이위원 위원"] * 2
    voices = (
        [A] * 3 + [B] * 4 + [C] * 2 + [C] * 2
    )  # 박위원 라벨 6창 중 뒤 2창은 실제 C, 이위원 2창도 실제 C
    subs = []
    for i, lab in enumerate(labels):
        text = (
            "상정합니다 이의 없으십니까"
            if i == 0
            else ("네 박위원 위원입니다" if i == 3 else "발언")
        )
        subs.append(_sub(i, lab, text))
        subs[-1]["start_time"] += i * 1.5
        subs[-1]["end_time"] += i * 1.5  # 창이 라인마다 나뉘게
    wins = svf.build_windows(subs, CFG)
    E = np.stack([_voice(v, rng) for v in voices]).astype(np.float32)
    return subs, wins, E


def test_purity_filter_drops_wrong_text_windows_and_r1_r2_fix_them():
    subs, wins, E = _scenario()
    anchors = svf.find_anchors(wins, subs, ROSTER, CFG)
    assert anchors["김위장 위원장"] == [0]
    cents = svf.build_centroids(E, wins, anchors, CFG)
    # 박위원은 자기소개 앵커(창 3, 4) + 부트스트랩(창 5, 6) — 실제 C 인 창 7, 8 은 추가되지 않는다
    assert anchors["박위원 위원"] == [3, 4]
    assert cents["박위원 위원"][1] == 4 and cents["박위원 위원"][2] is True
    # 이위원 라벨은 창 2개 < 3 이라 폴백 기준도 없음
    assert "이위원 위원" not in cents
    decisions = svf.decide(E, wins, cents, CFG)
    rules = [r for _, r in decisions]
    assert rules[0] == "R0"  # 진행 멘트 창은 보호
    assert rules[3:5] == ["R0", "R0"] and rules[5:7] == ["R3", "R3"]  # 진짜 박위원 창은 유지
    assert rules[7:9] == ["R2", "R2"]  # C 목소리인데 박위원 라벨 → 집행부 강등
    stats = svf.apply_decisions(wins, decisions, subs)
    assert stats["changed_lines"] == 2
    assert all(s["speaker"] == svf.GENERIC_OFFICIAL for s in subs[7:9])


def test_r1_overrides_to_other_reliable_speaker_with_margin():
    subs, wins, E = _scenario()
    # 위원장 목소리인데 박위원으로 붙은 창을 하나 만든다 (창 3·4 는 자기소개 앵커라 R0 — 5 를 쓴다)
    E[5] = E[0]
    anchors = svf.find_anchors(wins, subs, ROSTER, CFG)
    anchors["김위장 위원장"] = [0, 1, 2]
    cents = svf.build_centroids(E, wins, anchors, CFG)
    decisions = svf.decide(E, wins, cents, CFG)
    assert decisions[5] == ("김위장 위원장", "R1")


def test_r5_hands_chair_cue_window_to_vice_chair_by_voice():
    """사회 대행: 위원장 진행 멘트 창인데 목소리가 부위원장이면 부위원장으로."""
    rng = np.random.default_rng(1)
    A, V = _unit(rng), _unit(rng)
    subs = [
        _sub(0, "김위장 위원장", "다음은 박위원 위원 질의하세요"),
        _sub(1, "김위장 위원장", "이의 없으십니까"),
        _sub(2, "김위장 위원장", "가결되었음을 선포합니다"),
        _sub(3, "이위원 위원", "네 이위원 위원입니다"),
        _sub(4, "이위원 위원", "질의하겠습니다"),
    ]
    for i, s in enumerate(subs):
        s["start_time"] += i * 1.5
        s["end_time"] += i * 1.5
    roster = [
        {"name": "김위장", "role": "위원장"},
        {"name": "이위원", "role": "부위원장"},
        {"name": "박위원", "role": "위원"},
    ]
    wins = svf.build_windows(subs, CFG)
    E = np.stack(
        [_voice(A, rng), _voice(A, rng), _voice(V, rng), _voice(V, rng), _voice(V, rng)]
    ).astype(np.float32)
    anchors = svf.find_anchors(wins, subs, roster, CFG)
    cents = svf.build_centroids(E, wins, anchors, CFG)
    decisions = svf.decide(E, wins, cents, CFG, frozenset({"이위원 위원"}))
    assert decisions[2] == ("이위원 위원", "R5")  # 위원장 라벨 + 진행 멘트지만 목소리는 부위원장
    assert decisions[1] == (None, "R0")
    # 명부에 부위원장 역할이 없어도(vice_labels 비움) 앵커 있는 위원 전원을 후보로 같은 판정
    assert svf.decide(E, wins, cents, CFG)[2] == ("이위원 위원", "R5")


def test_no_reliable_centroid_keeps_everything():
    subs, wins, E = _scenario()
    decisions = svf.decide(E, wins, {}, CFG)
    assert all(new is None for new, _ in decisions)


def test_bootstrap_only_adds_windows_that_agree_with_text():
    subs, wins, E = _scenario()
    anchors = {"박위원 위원": [3, 4]}  # 앵커 2개만 주고 시작
    cents = svf.build_centroids(E, wins, anchors, CFG)
    assert (
        cents["박위원 위원"][1] == 4
    )  # 텍스트=박위원 & 음성=B 인 창(5,6)만 추가, C 창(7,8)은 추가 안 됨
    assert cents["박위원 위원"][2] is True


def test_fuzzy_name_rejects_ties():
    assert (
        svf._fuzzy("이자영", {"이자형", "이병숙", "전자영"}) == "이자형"
    )  # 성씨 가중 — 전자영보다 이자형
    assert svf._fuzzy("김희철", {"김회철", "김동희"}) == "김회철"
    assert svf._fuzzy("김영은", {"김영희", "김영훈"}) is None  # 동점이면 포기
    assert svf._fuzzy("질의하실", {"김영희", "김영훈"}) is None


@pytest.mark.asyncio
async def test_fuse_skips_without_model(tmp_path):
    cfg = svf.FusionConfig(model_path=str(tmp_path / "none.onnx"))
    out = await svf.fuse_voice_speakers([_sub(0, "박위원 위원")], ROSTER, pcm_path="x", cfg=cfg)
    assert "skipped" in out
