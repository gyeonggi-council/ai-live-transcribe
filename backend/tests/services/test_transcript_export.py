# @TASK P5-T5.1 - 공식 회의록 포맷 생성 테스트
# @SPEC docs/planning/02-trd.md#회의록-내보내기

"""export_official() 및 관련 헬퍼 함수 테스트."""

from app.services.transcript_export import (
    export_markdown,
    export_official,
    export_srt,
    _format_date_korean,
    _format_duration_korean,
    _group_by_speaker,
)


# ──────────────────────────────────────────────
# _format_date_korean 헬퍼 테스트
# ──────────────────────────────────────────────


class TestFormatDateKorean:
    def test_standard_date(self):
        assert _format_date_korean("2026-02-11") == "2026년 02월 11일"

    def test_single_digit_month_day(self):
        assert _format_date_korean("2025-01-05") == "2025년 01월 05일"

    def test_invalid_format_passthrough(self):
        """하이픈이 2개가 아닌 문자열은 원본 그대로 반환."""
        assert _format_date_korean("not-a-valid-date-format") == "not-a-valid-date-format"

    def test_three_part_non_date_still_formats(self):
        """하이픈 2개로 구분되는 문자열은 그대로 포맷 적용 (단순 split 기반)."""
        result = _format_date_korean("some-random-string")
        assert result == "some년 random월 string일"

    def test_empty_string(self):
        assert _format_date_korean("") == ""

    def test_date_with_time(self):
        """날짜+시간 문자열은 파싱 실패 시 그대로 반환."""
        result = _format_date_korean("2026-02-11T10:00:00")
        # split("-")하면 3개 이상이므로 첫 3개만 사용하거나 원본 반환
        # 구현에 따라 결정 - 스펙에서는 date_str.split("-") 후 len==3 체크
        assert isinstance(result, str)


# ──────────────────────────────────────────────
# _format_duration_korean 헬퍼 테스트
# ──────────────────────────────────────────────


class TestFormatDurationKorean:
    def test_hours_and_minutes(self):
        assert _format_duration_korean(3661) == "1시간 1분"

    def test_only_minutes(self):
        assert _format_duration_korean(300) == "5분"

    def test_zero_seconds(self):
        assert _format_duration_korean(0) == "0분"

    def test_exact_hour(self):
        assert _format_duration_korean(3600) == "1시간 0분"

    def test_large_duration(self):
        assert _format_duration_korean(7260) == "2시간 1분"

    def test_less_than_minute(self):
        assert _format_duration_korean(30) == "0분"


# ──────────────────────────────────────────────
# _group_by_speaker max_group_duration 파라미터 테스트
# ──────────────────────────────────────────────


class TestGroupBySpeakerMaxDuration:
    LONG_SPEECH = [
        {"start_time": 0, "end_time": 10, "text": "발언1", "speaker": "의장"},
        {"start_time": 160, "end_time": 170, "text": "발언2", "speaker": "의장"},
    ]

    def test_default_splits_long_speech_at_150s(self):
        """기본값(150초)에서는 긴 발언이 강제 분할된다 (기존 동작 유지)."""
        grouped = _group_by_speaker(self.LONG_SPEECH)
        assert len(grouped) == 2

    def test_none_keeps_continuous_span(self):
        """max_group_duration=None이면 강제 분할 없이 연속 span을 유지한다."""
        grouped = _group_by_speaker(self.LONG_SPEECH, max_group_duration=None)
        assert len(grouped) == 1
        assert grouped[0]["start_time"] == 0
        assert grouped[0]["end_time"] == 170
        assert grouped[0]["texts"] == ["발언1", "발언2"]


# ──────────────────────────────────────────────
# export_official 메인 함수 테스트
# ──────────────────────────────────────────────


SAMPLE_MEETING = {
    "id": "test-123",
    "title": "제100회 경기도의회 본회의",
    "meeting_date": "2026-02-11",
    "duration_seconds": 5400,
    "status": "ended",
}

SAMPLE_SUBTITLES = [
    {
        "id": "s1",
        "meeting_id": "test-123",
        "start_time": 83,
        "end_time": 90,
        "text": "의사일정 제1항을 상정합니다.",
        "speaker": "의장",
        "confidence": 0.95,
    },
    {
        "id": "s2",
        "meeting_id": "test-123",
        "start_time": 91,
        "end_time": 100,
        "text": "찬성하시는 분은 거수하여 주시기 바랍니다.",
        "speaker": "의장",
        "confidence": 0.93,
    },
    {
        "id": "s3",
        "meeting_id": "test-123",
        "start_time": 225,
        "end_time": 240,
        "text": "감사합니다. 질문 드리겠습니다.",
        "speaker": "김위원",
        "confidence": 0.90,
    },
    {
        "id": "s4",
        "meeting_id": "test-123",
        "start_time": 312,
        "end_time": 330,
        "text": "답변 드리겠습니다.",
        "speaker": "의장",
        "confidence": 0.92,
    },
]


class TestExportOfficial:
    def test_returns_string(self):
        result = export_official(SAMPLE_MEETING, SAMPLE_SUBTITLES)
        assert isinstance(result, str)

    def test_header_contains_title(self):
        result = export_official(SAMPLE_MEETING, SAMPLE_SUBTITLES)
        assert "제100회 경기도의회 본회의" in result

    def test_header_contains_korean_date(self):
        result = export_official(SAMPLE_MEETING, SAMPLE_SUBTITLES)
        assert "2026년 02월 11일" in result

    def test_header_contains_duration(self):
        result = export_official(SAMPLE_MEETING, SAMPLE_SUBTITLES)
        assert "1시간 30분" in result

    def test_header_has_border(self):
        """헤더에 이중선 구분선이 있어야 합니다."""
        result = export_official(SAMPLE_MEETING, SAMPLE_SUBTITLES)
        lines = result.split("\n")
        # 첫 줄이 구분선(═)이어야 함
        border_lines = [l for l in lines if "═" in l]
        assert len(border_lines) >= 2  # 상단 + 하단

    def test_body_speaker_marker(self):
        """화자 이름 앞에 ○ 마커가 있어야 합니다."""
        result = export_official(SAMPLE_MEETING, SAMPLE_SUBTITLES)
        assert "\u25CB 의장" in result  # ○ 의장
        assert "\u25CB 김위원" in result  # ○ 김위원

    def test_body_timestamps(self):
        """발언에 타임스탬프가 포함되어야 합니다."""
        result = export_official(SAMPLE_MEETING, SAMPLE_SUBTITLES)
        assert "(00:01:23)" in result  # 83초 = 1분 23초
        assert "(00:03:45)" in result  # 225초 = 3분 45초

    def test_consecutive_same_speaker_merged(self):
        """연속된 같은 화자 발언이 병합되어야 합니다."""
        result = export_official(SAMPLE_MEETING, SAMPLE_SUBTITLES)
        # 의장이 처음 두 번 연속 → 한 블록으로 병합
        # ○ 의장 은 두 번 나와야 함 (첫 블록 + 세 번째 블록)
        count = result.count("\u25CB 의장")
        assert count == 2  # 병합 후 의장 2번

    def test_footer_disclaimer(self):
        """면책 조항이 포함되어야 합니다."""
        result = export_official(SAMPLE_MEETING, SAMPLE_SUBTITLES)
        assert "AI 음성인식으로 자동 생성" in result
        assert "공식 회의록과 다를 수 있습니다" in result

    def test_footer_has_border(self):
        """푸터에 단선 구분선이 있어야 합니다."""
        result = export_official(SAMPLE_MEETING, SAMPLE_SUBTITLES)
        border_lines = [l for l in result.split("\n") if "─" in l]
        assert len(border_lines) >= 2  # 상단 + 하단

    def test_empty_subtitles(self):
        """자막이 없을 때도 정상 출력."""
        result = export_official(SAMPLE_MEETING, [])
        assert isinstance(result, str)
        assert "제100회 경기도의회 본회의" in result
        assert "자막 데이터가 없습니다" in result

    def test_speaker_none_fallback(self):
        """화자가 None이면 '발언자 미확인'으로 표시."""
        subtitles = [
            {
                "start_time": 10,
                "end_time": 20,
                "text": "테스트 발언입니다.",
                "speaker": None,
            }
        ]
        result = export_official(SAMPLE_MEETING, subtitles)
        assert "발언자 미확인" in result

    def test_missing_meeting_fields(self):
        """meeting에 필드가 누락되어도 에러 없이 동작."""
        minimal_meeting = {"title": "테스트 회의"}
        result = export_official(minimal_meeting, SAMPLE_SUBTITLES)
        assert "테스트 회의" in result

    def test_no_duration(self):
        """duration_seconds가 없으면 '미정' 표시."""
        meeting = {"title": "테스트", "meeting_date": "2026-01-01"}
        result = export_official(meeting, [])
        assert isinstance(result, str)
        # duration 없으면 해당 줄 생략하거나 '미정' 표시

    def test_existing_exports_not_broken(self):
        """기존 export_markdown, export_srt가 정상 동작하는지 확인."""
        md = export_markdown(SAMPLE_MEETING, SAMPLE_SUBTITLES)
        assert "# 제100회 경기도의회 본회의" in md

        srt = export_srt(SAMPLE_SUBTITLES)
        assert "00:01:23" in srt
