"""SpeakerCueTracker 단위 테스트 — 회의 구조 기반 실시간 화자 추적."""

import pytest

from app.services import speaker_cue_tracker as sct
from app.services.speaker_cue_tracker import SpeakerCueTracker, _ChannelState, _norm

CH = "ch8"


def _tracker_with_roster() -> SpeakerCueTracker:
    """위원장 c0 + 위원 c1/c2(voiceprint) + c3(voiceprint 없음) 명부로 채널 상태 주입."""
    t = SpeakerCueTracker()
    state = _ChannelState(
        committee="보건복지위원회",
        chair_id="c0",
        roster_index=[
            (_norm("정몽주"), "c0", True),   # 위원장
            (_norm("김민수"), "c1", True),
            (_norm("이영희"), "c2", True),
            (_norm("박철수"), "c3", False),  # voiceprint 미등록
        ],
    )
    t._states[CH] = state
    return t


def test_norm():
    assert _norm("김민수 의원") == "김민수"
    assert _norm("이영희 위원님") == "이영희"
    assert _norm("  박철수  ") == "박철수"


def test_observe_chair_call_sets_current_member():
    t = _tracker_with_roster()
    changed = t.observe(CH, "다음은 김민수 위원 질의해 주시기 바랍니다")
    assert changed is True
    assert t._states[CH].current_member_id == "c1"


def test_observe_self_intro():
    t = _tracker_with_roster()
    assert t.observe(CH, "이영희 위원입니다") is True
    assert t._states[CH].current_member_id == "c2"


def test_observe_fuzzy_matches_stt_error():
    """STT 오인식 '김민서'도 명부 '김민수'에 퍼지 매칭."""
    t = _tracker_with_roster()
    assert t.observe(CH, "다음은 김민서 위원 질의하겠습니다") is True
    assert t._states[CH].current_member_id == "c1"


def test_observe_member_rotation_sets_prev():
    t = _tracker_with_roster()
    t.observe(CH, "김민수 위원 질의하시기 바랍니다")
    t.observe(CH, "다음은 이영희 위원 질의하시기 바랍니다")
    st = t._states[CH]
    assert st.current_member_id == "c2"
    assert st.prev_member_id == "c1"


def test_observe_no_context_no_change():
    """발언 전환 맥락이 없으면 위원 변경 안 함."""
    t = _tracker_with_roster()
    assert t.observe(CH, "그 안건에 대한 자료입니다") is False
    assert t._states[CH].current_member_id is None


def test_observe_ignores_chair_word():
    """'위원장'은 위원 이름으로 오인식하지 않음(negative lookahead)."""
    t = _tracker_with_roster()
    t.observe(CH, "위원장입니다. 회의를 시작하겠습니다")
    assert t._states[CH].current_member_id is None


def test_observe_assembly_member_word():
    """국회식 '의원' 호명도 매칭(경기도의회=위원, 국회=의원 모두 지원)."""
    t = _tracker_with_roster()
    assert t.observe(CH, "다음은 김민수 의원님 질의해 주시기 바랍니다") is True
    assert t._states[CH].current_member_id == "c1"


def test_chair_word_not_misread_as_official():
    """'위원장'이 '원장'으로 집행부 직책 오인식되지 않음."""
    t = _tracker_with_roster()
    t.observe(CH, "위원장입니다. 다음 안건으로 넘어가겠습니다")
    assert t._states[CH].current_official_title is None


def test_observe_official_title():
    t = _tracker_with_roster()
    assert t.observe(CH, "보건복지국장 답변 드리겠습니다") is True
    assert t._states[CH].current_official_title == "보건복지국장"
    assert t.current_official_label(CH) == "집행부 보건복지국장"


def test_official_label_default():
    t = _tracker_with_roster()
    assert t.current_official_label(CH) == "집행부"


def test_current_known_ids_chair_current_prev():
    t = _tracker_with_roster()
    t.observe(CH, "김민수 위원 질의하시기 바랍니다")   # current=c1
    t.observe(CH, "다음은 이영희 위원 질의하시기 바랍니다")  # current=c2, prev=c1
    ids = t.current_known_councilor_ids(CH)
    assert ids == ["c0", "c2", "c1"]  # 위원장 + 현재 + 직전


def test_current_known_ids_excludes_no_voiceprint_member():
    """voiceprint 미등록 위원(c3)은 known set에서 제외(위원장은 항상 포함)."""
    t = _tracker_with_roster()
    t._states[CH].current_member_id = "c3"  # voiceprint 없음
    ids = t.current_known_councilor_ids(CH)
    assert ids == ["c0"]  # 위원장만


def test_current_known_ids_capped(monkeypatch):
    monkeypatch.setattr(sct.settings, "diarize_max_known_speakers", 2)
    t = _tracker_with_roster()
    t.observe(CH, "김민수 위원 질의하시기")
    t.observe(CH, "다음은 이영희 위원 질의하시기")
    ids = t.current_known_councilor_ids(CH)
    assert len(ids) == 2  # 상한 적용


def test_in_questioning_turn():
    t = _tracker_with_roster()
    assert t.in_questioning_turn(CH) is False
    t.observe(CH, "김민수 위원 질의하시기 바랍니다")
    assert t.in_questioning_turn(CH) is True


def test_unknown_channel_safe():
    t = SpeakerCueTracker()
    assert t.observe("nope", "김민수 위원 질의") is False
    assert t.current_known_councilor_ids("nope") == []
    assert t.current_official_label("nope") == "집행부"
    assert t.in_questioning_turn("nope") is False


def test_drop_channel():
    t = _tracker_with_roster()
    t.drop_channel(CH)
    assert CH not in t._states


def test_simulated_committee_meeting_flow():
    """실제 상임위 진행 흐름 모사: 위원장 진행 → 위원1 질의(집행부 답변) → 위원2 질의."""
    t = _tracker_with_roster()
    # 위원장 개의/진행 (위원 변경 없음)
    t.observe(CH, "성원이 되었으므로 제4차 보건복지위원회를 개회하겠습니다")
    assert t._states[CH].current_member_id is None
    assert t.current_known_councilor_ids(CH) == ["c0"]  # 위원장만

    # 위원장이 김민수 위원 호명
    t.observe(CH, "먼저 김민수 위원님 질의해 주시기 바랍니다")
    assert t._states[CH].current_member_id == "c1"
    assert t.in_questioning_turn(CH) is True
    assert set(t.current_known_councilor_ids(CH)) == {"c0", "c1"}

    # 집행부 답변 (국장)
    t.observe(CH, "네 보건복지국장 답변 드리겠습니다")
    assert t.current_official_label(CH) == "집행부 보건복지국장"

    # 다음 위원(이영희) 호명 → prev=c1
    t.observe(CH, "다음은 이영희 위원 질의하시기 바랍니다")
    assert t._states[CH].current_member_id == "c2"
    assert t._states[CH].prev_member_id == "c1"
    # known set: 위원장 + 현재(c2) + 직전(c1)
    assert t.current_known_councilor_ids(CH) == ["c0", "c2", "c1"]
