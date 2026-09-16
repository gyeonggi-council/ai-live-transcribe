# -*- coding: utf-8 -*-
"""AI 자막 의원 슬롯 — 호명 단서 뼈대 + 라벨 보조 (2026-09-08, 공식 인덱스 채점 57% → 66%).

실측(392회 1차 안전행정위, midx 138268): 위원장이 "다음은 윤충식 의원님 질의해 주시기 바랍니다" 라고
정확히 불렀는데 그 뒤 발언이 통째로 박영선 위원으로 붙어(음성 융합 오귀속) 라벨만 쓰면 윤충식 슬롯이
3분에서 끊겼다. 호명 줄과 "수고하셨습니다" 는 STT 본문에 그대로 있다.
"""
from __future__ import annotations

from app.services import clip_draft_index as draft

ROSTER = [{"id": "1", "name": "윤충식"}, {"id": "2", "name": "박영선"}, {"id": "3", "name": "김회철"},
          {"id": "4", "name": "장민수"}, {"id": "5", "name": "양경석"}, {"id": "6", "name": "이성한"}]


def _sub(start, text, speaker, end=None):
    return {"start_time": start, "end_time": end if end is not None else start + 5,
            "text": text, "speaker": speaker, "kind": "ai"}


def _seg(turns):
    speakers: dict[str, dict] = {}
    for sp, start, end in turns:
        speakers.setdefault(sp, {"speaker": sp, "segments": []})["segments"].append(
            {"start_time": start, "end_time": end, "text_preview": sp})
    return {"speakers": list(speakers.values())}


# 01:53:32 위원장 호명 → 윤충식 42초 → (라벨이 박영선으로 틀린) 8분 → 02:04:57 "윤충식 의원님 수고하셨습니다. 다음은 김회철"
SUBS = [
    _sub(6812, "이성한 의원님 수고하셨습니다. 다음은 윤충식 의원님 질의해 주시기 바랍니다.", "양경석 위원장"),
    _sub(6821, "김규식 안전관리실장님을 비롯한 업무 보고해 주신 분들께 감사의 말씀 드리겠고요.", "윤충식 위원"),
    _sub(6863, "존경하는 우리 윤충식 부위원장이 말씀하셨던 것처럼 저희가 검토하겠습니다.", "김규식 안전관리실장"),
    _sub(7005, "우리 조성 비율에는 모자라지 않게 매년 적립이 잘 되고 있는 거죠?", "박영선 위원"),
    _sub(7497, "윤충식 의원님 수고하셨습니다. 다음은 김회철 의원님 질의하시기 바랍니다.", "양경석 위원장"),
    _sub(7504, "화성 출신 김회철 의원입니다. 안전관리실장님 업무보고 22페이지에 질의드리겠습니다.", "김회철 위원"),
    _sub(7900, "김회철 의원님 수고 많으셨습니다. 더 이상 질의하실 의원님 안 계시므로 마치겠습니다.", "양경석 위원장"),
]
TURNS = [("양경석 위원장", 6812, 6821), ("윤충식 위원", 6821, 6863), ("김규식 안전관리실장", 6863, 7005),
         ("박영선 위원", 7005, 7493), ("양경석 위원장", 7497, 7504), ("김회철 위원", 7504, 7900)]


def _by_name(groups):
    return {g["name"]: [(s["start"], s["end"]) for s in g["segments"]] for g in groups}


class TestHybridSlots:
    def test_cue_defines_slot_even_when_labels_are_wrong(self):
        out = _by_name(draft.build_draft_from_ai(_seg(TURNS), ROSTER, SUBS, duration=8000))
        # 윤충식: 호명 줄(6812)부터 "수고하셨습니다"(7497) 까지 — 라벨이 박영선으로 틀린 8분이 그대로 들어 있다
        assert out["윤충식"] == [(6812, 7497)]
        # 김회철: 호명(7497) 부터 "수고 많으셨습니다"(7900)
        assert out["김회철"] == [(7497, 7900)]
        # 박영선 라벨 슬롯은 윤충식 호명 슬롯과 절반 넘게 겹치므로 버린다
        assert "박영선" not in out

    def test_executive_mention_is_not_a_call(self):
        """집행부의 "OO 의원님 말씀하신…" 은 호명이 아니다 — 슬롯을 쪼개지 않는다."""
        out = _by_name(draft.build_draft_from_ai(_seg(TURNS), ROSTER, SUBS, duration=8000))
        assert len(out["윤충식"]) == 1

    def test_labels_only_when_no_cues(self):
        subs = [_sub(6821, "질의드리겠습니다.", "윤충식 위원")]
        out = _by_name(draft.build_draft_from_ai(_seg(TURNS), ROSTER, subs, duration=8000))
        assert "윤충식" in out and "박영선" in out          # 단서가 없으면 예전 라벨 규칙 그대로

    def test_label_slot_is_cut_at_chair_transition(self):
        """호명이 없는 의원의 라벨 슬롯도 "수고하셨습니다" 에서 끊긴다."""
        subs = [_sub(7497, "장민수 의원님 수고하셨습니다.", "양경석 위원장"),
                _sub(7600, "화성 출신 김회철 의원입니다.", "김회철 위원")]
        turns = [("장민수 위원", 7000, 7100), ("김규식 안전관리실장", 7100, 7495), ("김규식 안전관리실장", 7500, 7590),
                 ("김회철 위원", 7600, 7900)]
        out = _by_name(draft.build_draft_from_ai(_seg(turns), ROSTER, subs, duration=8000))
        assert out["장민수"] == [(7000, 7497)]
        assert out["김회철"] == [(7600, 8000)]

    def test_adjacent_different_names_are_different_people(self):
        """인사 순서: 30초마다 다른 의원 — 예전 90초 병합이 12명을 한 단서로 뭉쳤다."""
        subs = [_sub(100, "화성 출신 김회철 위원입니다.", "김회철 위원"),
                _sub(130, "안산 출신 박영선 위원입니다.", "박영선 위원"),
                _sub(160, "다음은 장민수 의원님 말씀 부탁드리겠습니다.", "양경석 위원장"),
                _sub(200, "네, 장민수입니다. 잘 부탁드립니다.", "장민수 위원")]
        cues = draft.find_cues(subs, ROSTER)
        assert [(c["start"], c["name"]) for c in cues] == [(100, "김회철"), (130, "박영선"), (160, "장민수")]

    def test_stt_dropped_syllable_self_intro_needs_exact_roster_match(self):
        subs = [_sub(10, "장민수원입니다. 먼저 업무보고 준비하시느라 수고 많으셨습니다.", "장민수 위원"),
                _sub(20, "경기도 수원입니다.", "(미지정)")]
        assert [c["name"] for c in draft.find_cues(subs, ROSTER)] == ["장민수"]

    def test_second_call_within_seconds_is_a_correction(self):
        """"박상현 의원님 부탁드리겠습니다 / 아, 양보하셨네요 / 윤도희 의원님 질의해 주시기 바랍니다" → 윤도희."""
        roster = ROSTER + [{"id": "7", "name": "윤도희"}]
        subs = [_sub(100, "예, 박영선 의원님 부탁드리겠습니다.", "양경석 위원장"),
                _sub(103, "아, 박영선 의원님이 양보하셨네요.", "양경석 위원장"),
                _sub(104, "윤도희 의원님 질의해 주시기 바랍니다.", "양경석 위원장"),
                _sub(109, "안양 윤도희 의원입니다.", "윤도희 위원")]
        assert [c["name"] for c in draft.find_cues(subs, roster)] == ["윤도희"]

    def test_topic_marker_after_name_is_not_a_call(self):
        """"지영일 의원님은 본질의를 하셨기 때문에 …" 는 호명이 아니다 — 6초 뒤 "김태희 의원님 질의해" 가 호명."""
        roster = ROSTER + [{"id": "8", "name": "지영일"}]
        subs = [_sub(100, "지영일 의원님은 본질의 해소했기 때문에 조금 있다가 하시면 될 것 같고요.", "양경석 위원장"),
                _sub(106, "김회철 의원님 질의해 주시기 바랍니다.", "양경석 위원장")]
        assert [c["name"] for c in draft.find_cues(subs, roster)] == ["김회철"]

    def test_stt_vowel_error_resolves_by_jamo(self):
        """'강송상 의원님' → 강성삼 (글자 단위로는 명부 밖, 자모 단위로는 모음 둘 차이)."""
        roster = ROSTER + [{"id": "9", "name": "강성삼"}]
        subs = [_sub(100, "수고하셨습니다 다음은 강송상 의원님 질의해 주시기 바랍니다", "양경석 위원장")]
        assert [c["name"] for c in draft.find_cues(subs, roster)] == ["강성삼"]

    def test_missed_call_split_by_closing(self):
        """조명자 호명 뒤 김지호 호명이 STT 에서 빠짐 → "김지호 의원님 수고하셨습니다" 와 김지호 라벨로 가른다."""
        roster = ROSTER + [{"id": "10", "name": "조명자"}, {"id": "11", "name": "김지호"}]
        subs = [_sub(100, "다음은 조명자 의원님 질의해 주시기 바랍니다.", "양경석 위원장"),
                _sub(1200, "김지호 의원님 수고하셨습니다. 다음은 장민수 의원님 질의해 주시기 바랍니다.", "양경석 위원장")]
        turns = [("조명자 위원", 105, 500), ("김규식 안전관리실장", 500, 580), ("김지호 위원", 600, 1195),
                 ("장민수 위원", 1205, 1500)]
        out = _by_name(draft.build_draft_from_ai(_seg(turns), roster, subs, duration=1600))
        assert out["조명자"] == [(100, 600)] and out["김지호"] == [(600, 1200)]

    def test_garbled_closing_name_still_closes_own_slot(self):
        """"유효종 의원님 수고하셨습니다" 는 명부에서 안 풀리지만 방금 발언한 유호준의 마무리다 — 자모 절반이면 인정."""
        assert draft.closing_matches("유효종", "유호준")
        assert draft.closing_matches("장성용", "장송회")
        assert not draft.closing_matches("김태희", "유호준")
        roster = ROSTER + [{"id": "12", "name": "유호준"}]
        subs = [_sub(100, "다음은 유호준 의원님 질의해 주시기 바랍니다.", "양경석 위원장"),
                _sub(700, "네, 유효종 의원님 수고하셨습니다.", "양경석 위원장"),
                _sub(702, "제가 잠깐 사실관계 확인을 해서 말씀을 드리면", "양경석 위원장")]
        assert draft._closing_times(subs, roster) == [(700, "유효종")]

    def test_member_thanking_official_is_not_a_boundary_and_closing_phrase_keeps_last_answer(self):
        """의원의 "네, 수고하셨고요" 와 "이상으로 질의 마치겠습니다" 뒤에도 집행부 답변이 이어진다 —
        슬롯은 위원장의 "OO 의원님 수고하셨습니다" 에서 끝난다."""
        subs = [_sub(100, "다음은 윤충식 의원님 질의해 주시기 바랍니다.", "양경석 위원장"),
                _sub(300, "네, 소통해 주시기 바란다는 마음으로 제언을 드립니다. 네, 수고하셨고요.", "윤충식 위원"),
                _sub(400, "이상으로 질의를 마치겠습니다.", "윤충식 위원"),
                _sub(410, "말씀하신 자료는 정리해서 보고드리겠습니다.", "김규식 안전관리실장"),
                _sub(500, "윤충식 의원님 수고하셨습니다. 다음은 김회철 의원님 질의해 주시기 바랍니다.", "양경석 위원장")]
        turns = [("윤충식 위원", 105, 300), ("김규식 안전관리실장", 300, 400), ("김회철 위원", 505, 900)]
        out = _by_name(draft.build_draft_from_ai(_seg(turns), ROSTER, subs, duration=1000))
        assert out["윤충식"] == [(100, 500)]

    def test_recalling_same_member_is_not_a_boundary_and_call_wins_over_earlier_self(self):
        """가짜 자기소개(02:33:02) 뒤 90초 안에 위원장 호명(02:34:09 "네, 김태현님.")이 오면 호명이 시작이고,
        그 호명 줄("더 이상 질의하실 의원님 안 계십니까?")은 같은 사람을 부르는 줄이라 전환이 아니다."""
        roster = ROSTER + [{"id": "13", "name": "김태희"}]
        subs = [_sub(100, "담당 부서과장 김태희입니다.", "박호순 국장"),
                _sub(160, "더 이상 질의하실 의원님 안 계십니까? 네, 김태현님.", "양경석 위원장"),
                _sub(400, "김태희 의원님 수고하셨습니다.", "양경석 위원장")]
        turns = [("김태희 위원", 165, 395)]
        out = _by_name(draft.build_draft_from_ai(_seg(turns), roster, subs, duration=600))
        assert out["김태희"] == [(160, 400)]

    def test_greeting_round_short_slots(self):
        """인사 순서: "OO 의원님 인사해 주시기 바랍니다" 뒤 10~16초 — 호명 슬롯은 8초부터 실제다."""
        subs = [_sub(104, "먼저 김회철 의원님 인사해 주시기 바랍니다.", "양경석 위원장"),
                _sub(109, "안녕하세요. 화성 출신 김회철 의원입니다. 잘 부탁드립니다.", "김회철 위원"),
                _sub(120, "김회철 의원님 수고하셨습니다.", "양경석 위원장"),
                _sub(121, "다음은 박영선 의원님 인사해 주시기 바랍니다.", "양경석 위원장"),
                _sub(126, "반갑습니다. 가평 출신 박영선 의원입니다.", "박영선 위원"),
                _sub(137, "박영선 의원님 수고하셨습니다.", "양경석 위원장")]
        turns = [("김회철 위원", 109, 119), ("박영선 위원", 126, 136)]
        out = _by_name(draft.build_draft_from_ai(_seg(turns), ROSTER, subs, duration=300))
        assert out["김회철"] == [(104, 121)] and out["박영선"][0][0] == 121

    def test_unresolved_call_takes_similar_single_label(self):
        """'장장 의원님 자료 요청해 주시기' — 명부에서 못 풀지만 60초 안 라벨이 장민수 하나이고 성이 같으면 그 사람."""
        subs = [_sub(100, "장장 의원님 자료 요청해 주시기 바랍니다.", "양경석 위원장"),
                _sub(105, "경기기후보험 지원 내용 자료를 요청합니다.", "장민수 위원"),
                _sub(200, "곽상윤 부위원장님 부탁드리겠습니다.", "양경석 위원장"),
                _sub(205, "네, 질의하겠습니다.", "박영선 위원")]
        cues = draft.find_cues(subs, ROSTER)
        assert [(c["start"], c["name"]) for c in cues] == [(100, "장민수")]   # 곽상윤→박영선 은 안 닮아 버린다

    def test_chair_line_short_call_at_end(self):
        subs = [_sub(10, "다음 질의하실 의원님 계십니까? 없으신가요? 박영선 의원님?", "양경석 위원장"),
                _sub(12, "다음 질의하실 의원님 계십니까? 없으신가요? 김회철 의원님?", "김규식 안전관리실장")]
        cues = draft.find_cues(subs, ROSTER, chair_line=lambda s: "위원장" in str(s.get("speaker")))
        assert [c["name"] for c in cues] == ["박영선"]
