"""Tests for speaker_utils.group_words_by_speaker.

# @TASK P5-T1.2 - 화자 그룹핑 유틸리티 테스트
# @TEST tests/services/test_speaker_utils.py
"""

import pytest

from app.services.speaker_utils import group_words_by_speaker


class TestGroupWordsBySpeaker:
    """group_words_by_speaker 함수 테스트."""

    def test_empty_words_returns_empty_list(self):
        """빈 words 배열은 빈 리스트를 반환해야 합니다."""
        result = group_words_by_speaker([])
        assert result == []

    def test_single_word(self):
        """단일 단어는 하나의 그룹을 반환해야 합니다."""
        words = [
            {"speaker": 0, "punctuated_word": "안녕하세요", "confidence": 0.95, "start": 0.0, "end": 1.0}
        ]
        result = group_words_by_speaker(words)
        assert len(result) == 1
        assert result[0]["speaker"] == 0
        assert result[0]["text"] == "안녕하세요"
        assert result[0]["confidence"] == pytest.approx(0.95)
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 1.0

    def test_same_speaker_multiple_words(self):
        """같은 화자의 연속 단어는 하나의 그룹으로 묶여야 합니다."""
        words = [
            {"speaker": 0, "punctuated_word": "오늘", "confidence": 0.9, "start": 0.0, "end": 0.5},
            {"speaker": 0, "punctuated_word": "회의를", "confidence": 0.8, "start": 0.5, "end": 1.0},
            {"speaker": 0, "punctuated_word": "시작합니다.", "confidence": 0.85, "start": 1.0, "end": 1.5},
        ]
        result = group_words_by_speaker(words)
        assert len(result) == 1
        assert result[0]["speaker"] == 0
        assert result[0]["text"] == "오늘 회의를 시작합니다."
        assert result[0]["confidence"] == pytest.approx((0.9 + 0.8 + 0.85) / 3)
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 1.5

    def test_speaker_change_creates_new_group(self):
        """화자가 바뀌면 새 그룹이 생성되어야 합니다."""
        words = [
            {"speaker": 0, "punctuated_word": "의견을", "confidence": 0.9, "start": 0.0, "end": 0.5},
            {"speaker": 0, "punctuated_word": "말씀해주세요.", "confidence": 0.85, "start": 0.5, "end": 1.0},
            {"speaker": 1, "punctuated_word": "네,", "confidence": 0.92, "start": 1.0, "end": 1.3},
            {"speaker": 1, "punctuated_word": "찬성합니다.", "confidence": 0.88, "start": 1.3, "end": 2.0},
        ]
        result = group_words_by_speaker(words)
        assert len(result) == 2

        assert result[0]["speaker"] == 0
        assert result[0]["text"] == "의견을 말씀해주세요."
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 1.0

        assert result[1]["speaker"] == 1
        assert result[1]["text"] == "네, 찬성합니다."
        assert result[1]["start"] == 1.0
        assert result[1]["end"] == 2.0

    def test_multiple_speaker_changes(self):
        """여러 번 화자가 바뀌는 경우 올바르게 그룹핑해야 합니다."""
        words = [
            {"speaker": 0, "word": "A", "confidence": 0.9, "start": 0.0, "end": 0.5},
            {"speaker": 1, "word": "B", "confidence": 0.8, "start": 0.5, "end": 1.0},
            {"speaker": 0, "word": "C", "confidence": 0.85, "start": 1.0, "end": 1.5},
        ]
        result = group_words_by_speaker(words)
        assert len(result) == 3
        assert result[0]["speaker"] == 0
        assert result[0]["text"] == "A"
        assert result[1]["speaker"] == 1
        assert result[1]["text"] == "B"
        assert result[2]["speaker"] == 0
        assert result[2]["text"] == "C"

    def test_word_fallback_when_no_punctuated_word(self):
        """punctuated_word가 없으면 word 키를 사용해야 합니다."""
        words = [
            {"speaker": 0, "word": "테스트", "confidence": 0.9, "start": 0.0, "end": 0.5},
        ]
        result = group_words_by_speaker(words)
        assert result[0]["text"] == "테스트"

    def test_punctuated_word_takes_priority(self):
        """punctuated_word가 word보다 우선해야 합니다."""
        words = [
            {"speaker": 0, "punctuated_word": "테스트.", "word": "테스트", "confidence": 0.9, "start": 0.0, "end": 0.5},
        ]
        result = group_words_by_speaker(words)
        assert result[0]["text"] == "테스트."

    def test_none_speaker(self):
        """speaker가 None인 경우도 올바르게 처리해야 합니다."""
        words = [
            {"speaker": None, "punctuated_word": "안녕", "confidence": 0.9, "start": 0.0, "end": 0.5},
            {"speaker": None, "punctuated_word": "하세요", "confidence": 0.85, "start": 0.5, "end": 1.0},
        ]
        result = group_words_by_speaker(words)
        assert len(result) == 1
        assert result[0]["speaker"] is None
        assert result[0]["text"] == "안녕 하세요"

    def test_missing_speaker_key(self):
        """speaker 키가 없는 경우 None으로 처리해야 합니다."""
        words = [
            {"punctuated_word": "첫번째", "confidence": 0.9, "start": 0.0, "end": 0.5},
            {"punctuated_word": "두번째", "confidence": 0.85, "start": 0.5, "end": 1.0},
        ]
        result = group_words_by_speaker(words)
        assert len(result) == 1
        assert result[0]["speaker"] is None
        assert result[0]["text"] == "첫번째 두번째"

    def test_missing_time_keys_default_to_zero(self):
        """start/end 키가 없으면 0.0으로 기본값 처리해야 합니다."""
        words = [
            {"speaker": 0, "punctuated_word": "테스트", "confidence": 0.9},
        ]
        result = group_words_by_speaker(words)
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 0.0

    def test_confidence_average_calculation(self):
        """신뢰도가 정확한 평균으로 계산되어야 합니다."""
        words = [
            {"speaker": 0, "punctuated_word": "A", "confidence": 1.0, "start": 0.0, "end": 0.5},
            {"speaker": 0, "punctuated_word": "B", "confidence": 0.5, "start": 0.5, "end": 1.0},
        ]
        result = group_words_by_speaker(words)
        assert result[0]["confidence"] == pytest.approx(0.75)
