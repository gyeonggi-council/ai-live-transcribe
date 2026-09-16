# -*- coding: utf-8 -*-
"""초안 인덱스 — 실시간·AI 자막 본문 단서 / AI 자막 화자명 → 의원별 구간

실측 근거(2026-09-03, 09-02 본회의 실시간 자막): speaker 라벨은 "추미애 도지사"·
"집행부 국장" 같은 직책이고 의원 발언에도 그대로 붙어 있었다. 본문의
"…박은주 의원입니다"(자기소개)와 "김태희 의원님 질문하시고"(호명)는 살아남는다.

실측 2(2026-09-04, 393회 본회의 1·3차): AI 자막은 speaker 가 전부 None 이었고,
호명 "김해철"(오인식)→자기소개 "김회철" 이 50초 간격으로 붙어 나왔으며, 마지막 호명 뒤로
집행부 답변 3시간이 통째로 붙었다.
"""

import pytest

from app.services import clip_draft_index as draft

ROSTER = [
    {"id": "c1", "name": "김성태", "party": "더불어민주당", "district": "용인시"},
    {"id": "c2", "name": "박은주", "party": "더불어민주당", "district": "고양시"},
    {"id": "c3", "name": "김태희", "party": "더불어민주당", "district": "안산시"},
    {"id": "c4", "name": "윤종영", "party": "국민의힘", "district": "안양시"},
]


def _sub(start, text, speaker="추미애 도지사", kind="live", end=None):
    return {"start_time": start, "end_time": end if end is not None else start + 5,
            "text": text, "speaker": speaker, "kind": kind}


LIVE_SUBS = [
    _sub(1041.2, "농정해양위원회 소속 더불어민주당 용인 출신 김성태 의원입니다."),
    _sub(1100.0, "지사님께 묻겠습니다."),
    _sub(1452.6, "더불어민주당 박은주 의원입니다. 오늘 본 의원은 최근 계속되는 이상고온으로"),
    _sub(1500.0, "온열 환자가 급증하고 있습니다."),
    _sub(3413.8, "공직자와 언론인 여러분, 안산 지역 도시환경위원회 소속 김태희 도의원입니다."),
    _sub(4011.6, "김태희 의원님 질문하시고 지사님은 답변을 좀"),        # 같은 사람 호명 → 분할 안 함
    _sub(6011.7, "기획재정위원회 소속 윤종영 의원입니다. 오늘 저는", speaker="집행부 과장"),
    _sub(11603.2, "앞서 우리 존경하는 김태희 의원님, 우리 윤종영 의원님 질의 잘 들었습니다.",
         speaker="집행부 국장"),                                       # 답변 속 언급 → 단서 아님
    _sub(12000.0, "이상입니다.", end=12005.0),
]


class TestDetectKind:
    def test_kinds(self):
        assert draft.detect_subtitle_kind([]) == "none"
        assert draft.detect_subtitle_kind([{"kind": "live"}]) == "live"
        assert draft.detect_subtitle_kind([{"kind": "live"}, {"kind": "ai"}]) == "ai"
        assert draft.detect_subtitle_kind([{"kind": None}]) == "legacy"


class TestCuesFromLive:
    def test_live_subs_without_member_speaker_use_text_cues(self):
        groups = draft.build_draft_from_cues(LIVE_SUBS, ROSTER, duration=None)
        names = {g["name"] for g in groups}
        assert names == {"김성태", "박은주", "김태희", "윤종영"}
        by = {g["name"]: g for g in groups}
        # 김성태: 자기소개(1041.2) → 다음 사람 단서(1452.6)
        assert by["김성태"]["segments"][0]["start"] == pytest.approx(1041.2)
        assert by["김성태"]["segments"][0]["end"] == pytest.approx(1452.6)
        assert by["김성태"]["segments"][0]["end_estimated"] is False
        # 김태희: 자기소개 뒤 같은 사람 호명은 새 구간이 아니다 → 윤종영(6011.7)까지 한 구간
        assert len(by["김태희"]["segments"]) == 1
        assert by["김태희"]["segments"][0]["end"] == pytest.approx(6011.7)
        # 윤종영: 마지막 단서 → 마지막 자막 끝(12005)까지가 아니라 45분 상한에서 끊고 '추정' 표시
        assert by["윤종영"]["segments"][0]["end"] == pytest.approx(6011.7 + draft.MAX_SEGMENT_SECONDS)
        assert by["윤종영"]["segments"][0]["end_estimated"] is True

    def test_mention_inside_answer_is_not_a_cue(self):
        cues = draft.find_cues(LIVE_SUBS, ROSTER)
        assert all(abs(c["start"] - 11603.2) > 1 for c in cues)

    def test_unknown_name_dropped_when_roster_present(self):
        subs = [_sub(10.0, "국민의힘 소속 홍길동 의원입니다."), _sub(500.0, "끝", end=505)]
        assert draft.build_draft_from_cues(subs, ROSTER, duration=None) == []

    def test_roster_empty_trusts_regex(self):
        subs = [_sub(10.0, "국민의힘 소속 홍길동 의원입니다."), _sub(500.0, "끝", end=505)]
        groups = draft.build_draft_from_cues(subs, [], duration=None)
        assert [g["name"] for g in groups] == ["홍길동"]

    def test_adjacent_cues_are_one_person(self):
        """5초 간격의 자기소개 둘은 STT 잡음 — 한 사람(앞 단서 유지)으로 본다."""
        subs = [_sub(10.0, "김성태 의원입니다."), _sub(15.0, "박은주 의원입니다."), _sub(600.0, "끝", end=605)]
        groups = draft.build_draft_from_cues(subs, ROSTER, duration=None)
        assert [g["name"] for g in groups] == ["김성태"]
        assert groups[0]["segments"][0]["start"] == pytest.approx(10.0)

    def test_segments_are_raw_stt_clock(self):
        """오프셋은 프런트/SRT 단계에서 더한다 — 여기서는 자막 시각 그대로."""
        groups = draft.build_draft_from_cues(LIVE_SUBS, ROSTER, duration=None)
        starts = [s["start"] for g in groups for s in g["segments"]]
        assert min(starts) == pytest.approx(1041.2)


class TestCueMerge:
    """실측(1차 본회의 AI 자막): '김해철 의원님 나오셔서'(00:14:40, 오인식) → '김회철 의원입니다'(00:15:30)."""

    ROSTER = [{"id": "a", "name": "김회철"}, {"id": "b", "name": "김철환"},
              {"id": "c", "name": "오진택"}, {"id": "d", "name": "오지훈"}, {"id": "e", "name": "김선희"}]

    def test_ambiguous_call_takes_name_from_following_self_intro(self):
        subs = [
            _sub(880.0, "먼저 김해철 의원님 나오셔서 발언해 주시기 바랍니다.", kind="ai", speaker=None),
            _sub(930.0, "존경하는 선배 동료 의원 여러분, 더불어민주당 김회철 의원입니다.", kind="ai", speaker=None),
            _sub(1290.0, "다음은 김선희 의원님 나오셔서 발언해 주시기 바랍니다", kind="ai", speaker=None),
            _sub(1700.0, "끝", kind="ai", speaker=None, end=1705.0),
        ]
        groups = draft.build_draft_from_cues(subs, self.ROSTER, duration=None)
        by = {g["name"]: g for g in groups}
        assert set(by) == {"김회철", "김선희"}          # 김철환(동점 오매칭) 이 끼어들지 않는다
        assert by["김회철"]["segments"][0]["start"] == pytest.approx(880.0)   # 시작은 호명 시각
        assert by["김회철"]["segments"][0]["end"] == pytest.approx(1290.0)

    def test_exact_call_beats_fuzzy_self_intro(self):
        """'오진택 의원님 나오셔서'(정확) → '오지택 의원입니다'(오인식·동점) — 오진택 하나로."""
        subs = [
            _sub(157.0, "먼저 오진택 의원님 나오셔서 발언해 주시기 바랍니다."),
            _sub(206.0, "오지택 의원입니다. 민선 9기 추미애 도지사님께서"),
            _sub(539.0, "다음은 김선희 의원님 나오셔서 발언해 주시기 바랍니다."),
            _sub(900.0, "끝", end=905.0),
        ]
        groups = draft.build_draft_from_cues(subs, self.ROSTER, duration=None)
        assert [g["name"] for g in groups] == ["오진택", "김선희"]
        assert groups[0]["segments"][0]["start"] == pytest.approx(157.0)

    def test_char_tie_is_broken_by_jamo(self):
        """'김해철' 은 글자 단위로 김회철·김철환 동점이지만 자모 단위(ㅐ↔ㅚ 한 모음)로는 김회철이다(2026-09-08).
        예전엔 동점이라 버렸다 — 이제는 자모 점수가 가른다."""
        subs = [_sub(10.0, "먼저 김해철 의원님 나오셔서 발언해 주시기 바랍니다."), _sub(900.0, "끝", end=905.0)]
        assert [g["name"] for g in draft.build_draft_from_cues(subs, self.ROSTER, duration=None)] == ["김회철"]

    def test_true_tie_without_follow_up_is_dropped(self):
        roster = [{"id": "a", "name": "김회철"}, {"id": "b", "name": "김희철"}]   # 자모로도 동점
        subs = [_sub(10.0, "먼저 김해철 의원님 나오셔서 발언해 주시기 바랍니다."), _sub(900.0, "끝", end=905.0)]
        assert draft.build_draft_from_cues(subs, roster, duration=None) == []


class TestSegmentEnd:
    """실측(3차 본회의): 마지막 호명 김진명 02:36:43 뒤로 집행부 일괄 답변이 붙어 05:40 까지 갔다."""

    def test_end_at_chair_closing_phrase(self):
        subs = [
            _sub(100.0, "마지막으로 김성태 의원님 나오셔서 질문해 주시기 바랍니다."),
            _sub(1400.0, "그럼 금일 실시한 일곱 분의 의원님들의 일괄 질문에 대하여 집행부의 일괄 답변을 듣도록 하겠습니다."),
            _sub(9000.0, "산회를 선포합니다.", end=9005.0),
        ]
        seg = draft.build_draft_from_cues(subs, ROSTER, duration=None)[0]["segments"][0]
        assert seg["end"] == pytest.approx(1400.0)
        assert seg["end_estimated"] is False

    def test_closing_phrase_within_60s_of_cue_belongs_to_previous_speaker(self):
        subs = [
            _sub(100.0, "다음은 김성태 의원님 나오셔서 질문해 주시기 바랍니다."),
            _sub(130.0, "이상으로 5분 자유발언을 마치겠습니다."),   # 앞사람 마무리가 호명 뒤에 찍힌 경우
            _sub(1400.0, "의사일정 제3항 경기도 조례안을 상정합니다."),
            _sub(9000.0, "끝", end=9005.0),
        ]
        seg = draft.build_draft_from_cues(subs, ROSTER, duration=None)[0]["segments"][0]
        assert seg["end"] == pytest.approx(1400.0)

    def test_segment_capped_at_45_minutes_when_nothing_closes_it(self):
        subs = [_sub(100.0, "김성태 의원님 나오셔서 질문해 주시기 바랍니다."), _sub(4100.0, "끝", end=4105.0)]
        seg = draft.build_draft_from_cues(subs, ROSTER, duration=None)[0]["segments"][0]
        assert seg["end"] == pytest.approx(100.0 + 45 * 60)
        assert seg["end_estimated"] is True

    def test_member_mentioning_answers_mid_question_is_not_an_end(self):
        """실측(2차 김태희 일문일답): '저희가 질문하고 답변 듣고 궁금하잖아요' 는 끝이 아니다.
        의장의 '답변을 듣도록 하겠습니다' 만 끝이다."""
        subs = [
            _sub(100.0, "김성태 의원님 나오셔서 질문해 주시기 바랍니다."),
            _sub(1700.0, "저희가 질문하고 답변 듣고 궁금하잖아요. 이런 자리 없잖아요, 지사님."),
            _sub(2000.0, "도정질문으로 도지사님의 긍정적인 답변을 듣고 싶었습니다."),
            _sub(2300.0, "그럼 집행부의 답변을 듣도록 하겠습니다."),
            _sub(5000.0, "끝", end=5005.0),
        ]
        seg = draft.build_draft_from_cues(subs, ROSTER, duration=None)[0]["segments"][0]
        assert seg["end"] == pytest.approx(2300.0)


def _seg_result(turns):
    """[(speaker, start, end), …] 시간순 교대 목록 → build_speaker_segments 형태"""
    speakers: dict[str, dict] = {}
    for sp, start, end in turns:
        d = speakers.setdefault(sp, {"speaker": sp, "segments": []})
        d["segments"].append({"start_time": start, "end_time": end, "text_preview": f"{sp} {start}"})
    return {"speakers": list(speakers.values())}


COMMITTEE_ROSTER = [
    {"id": "c1", "name": "윤충식"}, {"id": "c2", "name": "이성한"}, {"id": "c3", "name": "양경석"},
    {"id": "c4", "name": "정종혁"}, {"id": "c5", "name": "최현정"},   # 집행부 최현정 인권담당관과 동명
]

# 실측(2026-09-08, 393회 1차 안전행정위 AI 자막) 윤충식 위원 질의 구간을 그대로 축약한 교대 목록
SAFETY_TURNS = [
    ("양경석 위원장", 772, 780),
    ("윤충식 위원", 780, 802), ("최현정 인권담당관", 802, 828),
    ("윤충식 위원", 828, 847), ("최현정 인권담당관", 847, 864),
    ("윤충식 위원", 864, 880), ("최현정 인권담당관", 880, 900),
    ("윤충식 위원", 900, 904), ("최현정 인권담당관", 904, 949),
    ("윤충식 위원", 949, 965), ("최현정 인권담당관", 965, 985),
    ("윤충식 위원", 985, 1005), ("최현정 인권담당관", 1005, 1027),
    ("윤충식 위원", 1027, 1034), ("최현정 인권담당관", 1034, 1044),
    ("윤충식 위원", 1044, 1059),
    ("양경석 위원장", 1060, 1070),                       # "수고하셨습니다. 다음 이성한 위원…"
    ("이성한 위원", 1080, 1118), ("최현정 인권담당관", 1118, 1176), ("이성한 위원", 1176, 1188),
]


class TestDraftFromAi:
    def test_keeps_only_roster_members_and_parses_role(self):
        seg_result = {"speakers": [
            {"speaker": "김태희 의원", "segments": [
                {"start_time": 10.0, "end_time": 100.0, "text_preview": "안녕하십니까"}]},
            {"speaker": "추미애 도지사", "segments": [{"start_time": 100.0, "end_time": 200.0}]},
            {"speaker": "(미지정)", "segments": [{"start_time": 200.0, "end_time": 300.0}]},
            {"speaker": "화자 2", "segments": [{"start_time": 300.0, "end_time": 400.0}]},
        ]}
        groups = draft.build_draft_from_ai(seg_result, ROSTER)
        assert [g["name"] for g in groups] == ["김태희"]
        assert groups[0]["role"] == "의원"
        # 경계(위원장·다른 의원)가 없으면 뒤따르는 답변까지 포함하고 끝을 추정으로 표시
        seg = groups[0]["segments"][0]
        assert seg["seconds"] == pytest.approx(390.0) and seg["end_estimated"] is True

    def test_member_and_executive_exchange_is_one_slot_until_chair_speaks(self):
        """의원↔집행부 8회 교대 = 한 구간. 끝은 위원장이 다음 의원을 부르는 순간(1060).
        실측에서는 이 구간이 8조각(22·19·16·4·16·20·7·15초)으로 나와 '자잘하다'는 신고를 받았다."""
        groups = {g["name"]: g for g in draft.build_draft_from_ai(_seg_result(SAFETY_TURNS), COMMITTEE_ROSTER)}
        assert set(groups) == {"윤충식", "이성한"}          # 위원장 진행 멘트(<60초)는 구간이 아니다
        (yun,) = groups["윤충식"]["segments"]
        assert (yun["start"], yun["end"]) == (780, 1060) and yun["end_estimated"] is False
        assert yun["title"].startswith("발언 8회·답변 포함")
        (lee,) = groups["이성한"]["segments"]
        assert (lee["start"], lee["end"]) == (1080, 1188)   # 경계 없음 → 마지막 본인 발언 끝

    def test_executive_with_member_like_name_is_not_a_member(self):
        """'최현정 인권담당관' 은 명부의 최현정 의원과 동명이어도 집행부다 — 슬롯을 열지 않는다."""
        groups = draft.build_draft_from_ai(_seg_result(SAFETY_TURNS), COMMITTEE_ROSTER)
        assert "최현정" not in {g["name"] for g in groups}

    def test_long_gap_splits_same_member_into_two_slots(self):
        """실측 정종혁 위원: 4347 에 끝났다가 4662 에 다시 나옴(315초 공백) → 두 구간."""
        turns = [
            ("정종혁 위원", 3968, 4002), ("집행부", 4002, 4015), ("정종혁 위원", 4015, 4065),
            ("집행부", 4065, 4100), ("양경석 위원장", 4100, 4110), ("집행부", 4110, 4300),
            ("정종혁 위원", 4662, 4802), ("양경석 위원장", 4802, 4810),
        ]
        (g,) = draft.build_draft_from_ai(_seg_result(turns), COMMITTEE_ROSTER)
        assert [(s["start"], s["end"]) for s in g["segments"]] == [(3968, 4100), (4662, 4802)]

    def test_chair_talking_over_a_minute_is_own_slot(self):
        """위원장도 60초 넘게 말하면(개의 인사·본인 질의) 구간이 된다. 10초짜리 진행 멘트는 아니다."""
        turns = [("양경석 위원장", 0, 241), ("집행부", 245, 300), ("윤충식 위원", 780, 802),
                 ("양경석 위원장", 1060, 1070)]
        groups = {g["name"]: g for g in draft.build_draft_from_ai(_seg_result(turns), COMMITTEE_ROSTER)}
        assert [(s["start"], s["end"]) for s in groups["양경석"]["segments"]] == [(0, 780)]
        assert [(s["start"], s["end"]) for s in groups["윤충식"]["segments"]] == [(780, 1060)]


AI_SUBS_NO_SPEAKER = [
    _sub(880.0, "먼저 김성태 의원님 나오셔서 발언해 주시기 바랍니다.", kind="ai", speaker=None),
    _sub(1290.0, "다음은 박은주 의원님 나오셔서 발언해 주시기 바랍니다", kind="ai", speaker=None),
    _sub(1700.0, "이상으로 5분 자유발언을 마치겠습니다.", kind="ai", speaker=None),
    _sub(5000.0, "끝", kind="ai", speaker=None, end=5005.0),
]


class TestBuildClipIndex:
    @pytest.mark.asyncio
    async def test_official_index_wins_when_kms_has_it(self, monkeypatch):
        from app.services import kms_angun_service as kms

        async def fake_angun(midx, **kw):
            return kms.parse_angun([
                {"m_pos": "100", "m_code": "1", "m_mbr": "M", "m_angun": "자료요구(김성태 위원)",
                 "m_hour": "00", "m_min": "01", "m_sec": "40"},
            ])

        monkeypatch.setattr(kms, "fetch_angun", fake_angun)
        monkeypatch.setattr(draft, "_load_roster", lambda sb, m: ROSTER)
        meeting = {"id": "m1", "kms_midx": "138270", "duration_seconds": 500, "clip_time_offset": None}
        out = await draft.build_clip_index(object(), meeting)
        assert out["source"] == "official"
        assert out["speakers"][0]["name"] == "김성태"
        assert out["speakers"][0]["party"] == "더불어민주당"
        assert out["speakers"][0]["segments"][0]["end"] == 500

    @pytest.mark.asyncio
    async def test_live_only_subtitles_give_none_with_ai_guidance(self, monkeypatch):
        """실시간 자막뿐이면(VOD 등록 직후, AI 자막 전) 의원 구간을 내지 않는다 — 시간축이 VOD 와 달라
        엉뚱한 의원이 잘렸다(2026-09-08 문화체육관광위). 수동 자르기용 duration 은 그대로 준다."""
        monkeypatch.setattr(draft, "_load_roster", lambda sb, m: ROSTER)
        monkeypatch.setattr(draft, "_fetch_all_subtitles", lambda sb, mid: LIVE_SUBS)
        meeting = {"id": "m1", "kms_midx": None, "duration_seconds": None, "clip_time_offset": -42.5}
        out = await draft.build_clip_index(object(), meeting)
        assert out["source"] == "none" and out["speakers"] == []
        assert out["duration"] == pytest.approx(12005.0)
        assert any("AI 자막이 아직" in w for w in out["warnings"])
        assert not any("시간 맞추기" in w for w in out["warnings"])

    @pytest.mark.asyncio
    async def test_ai_subs_without_speaker_labels_use_text_cues(self, monkeypatch):
        """실측(1차 본회의 080451fc): AI 자막 645건 speaker 전부 None → 화자구간은 '(미지정)' 하나뿐.
        본문 호명은 살아 있으니 거기서 초안을 세우고, 시간축은 VOD 라 source=ai(오프셋 없음)."""
        from app.services import kms_angun_service as kms

        async def fake_angun(midx, **kw):
            return kms.parse_angun([{"m_pos": "0", "m_code": " ", "m_mbr": "C",
                                     "m_angun": "제393회 임시회 제1차 본회의 개회식"}])

        monkeypatch.setattr(kms, "fetch_angun", fake_angun)
        monkeypatch.setattr(draft, "_load_roster", lambda sb, m: ROSTER)
        monkeypatch.setattr(draft, "_fetch_all_subtitles", lambda sb, mid: AI_SUBS_NO_SPEAKER)
        monkeypatch.setattr(draft, "build_speaker_segments", lambda sb, m: {
            "speakers": [{"speaker": "(미지정)", "segments": [{"start_time": 0, "end_time": 5000}]}]})
        meeting = {"id": "m1", "kms_midx": "138294", "duration_seconds": 5480, "clip_time_offset": None}
        out = await draft.build_clip_index(object(), meeting)
        assert out["source"] == "ai"
        assert [(s["name"], s["segments"][0]["start"], s["segments"][0]["end"]) for s in out["speakers"]] == [
            ("김성태", 880.0, 1290.0), ("박은주", 1290.0, 1700.0)]
        assert any("KMS 인덱스에 의원 발언 항목이 없습니다" in w for w in out["warnings"])
        assert any("AI 자막의 호명" in w for w in out["warnings"])
        assert not any("시간 맞추기" in w for w in out["warnings"])

    @pytest.mark.asyncio
    async def test_no_subtitles_gives_none_with_guidance(self, monkeypatch):
        monkeypatch.setattr(draft, "_load_roster", lambda sb, m: ROSTER)
        monkeypatch.setattr(draft, "_fetch_all_subtitles", lambda sb, mid: [])
        out = await draft.build_clip_index(object(), {"id": "m1", "kms_midx": None})
        assert out["source"] == "none" and out["speakers"] == []
        assert any("직접 잘라" in w for w in out["warnings"])


class TestStaffTitlesAreNotMembers:
    """실측(2026-09-10, 393회 도시환경위 3차 00:14:07): 김정희 **수석전문위원** 검토보고 5분이 김태희 의원 클립이 됐다.
    '수석전문위원 김정희입니다' 의 '위원' 이 의원 직함으로 걸리고, 자모 퍼지가 김정희→김태희 로 풀었다."""

    ROSTER = [{"id": "c3", "name": "김태희"}, {"id": "c9", "name": "이홍근"}]
    CHAIR = staticmethod(lambda s: "위원장" in str(s.get("speaker") or ""))

    def _cues(self, text, speaker="이홍근 위원장"):
        return draft.find_cues([_sub(848.0, text, speaker=speaker, kind="ai")], self.ROSTER, chair_line=self.CHAIR)

    def test_real_line_from_meeting_is_not_a_cue(self):
        assert self._cues("다음은 김정희 수석전문위원께서 검토보고 해주시기 바랍니다. 수석전문위원 김정희입니다.") == []

    @pytest.mark.parametrize("text,speaker", [
        ("수석전문위원 김정희입니다.", None),
        ("전문위원 김정희입니다.", None),
        ("수석전문위원 김정희입니다.", "김정희 수석전문위원"),
        ("김정희 전문위원님 말씀해 주시기 바랍니다.", "이홍근 위원장"),   # 이름·직함 사이 잡음 2글자가 '전문' 이면 안 된다
        ("건설국장 김정희입니다.", None),
    ])
    def test_staff_or_executive_name_is_not_a_member_cue(self, text, speaker):
        assert self._cues(text, speaker=speaker) == []

    def test_staff_closing_is_not_a_member_closing(self):
        subs = [_sub(10.0, "김정희 전문위원님 수고하셨습니다.", speaker="이홍근 위원장", kind="ai")]
        assert [n for _, n in draft._closing_times(subs, self.ROSTER) if n == "김태희"] == []

    @pytest.mark.parametrize("text", [
        "김태희 위원님 질의해 주시기 바랍니다.",
        "도의원 김태희입니다.",
        "안산 출신 김태희 의원입니다.",
    ])
    def test_real_member_cues_still_found(self, text):
        assert [c["name"] for c in self._cues(text)] == ["김태희"]

    def test_chair_self_intro_still_found(self):
        """'위원장' 은 '원장' 으로 끝나지만 의원이다 — 직함 가드에서 뺀다."""
        assert [c["name"] for c in self._cues("위원장 이홍근입니다.", speaker=None)] == ["이홍근"]

    def test_proportional_member_self_intro_still_found(self):
        """'비례대표' 는 의원의 자기소개 머리말이다 — 직함 가드에 '대표' 를 넣으면 안 된다
        (392회 경제노동위 1차 '비례대표 최예경입니다' → 최혜경, 넣었다가 2구간이 사라진 실측)."""
        roster = [{"id": "x", "name": "최혜경"}]
        subs = [_sub(4265.4, "네, 안녕하세요. 비례대표 최혜경입니다.", speaker="최혜경 위원", kind="ai")]
        assert [c["name"] for c in draft.find_cues(subs, roster)] == ["최혜경"]
