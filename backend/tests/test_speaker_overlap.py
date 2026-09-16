"""화자 전환 겹침 감지 테스트"""

import pytest

from app.services.speaker_utils import detect_speaker_overlap, group_words_by_speaker


class TestDetectSpeakerOverlap:
    """detect_speaker_overlap 함수 테스트"""

    def test_no_overlap_different_speakers(self):
        """이전 화자와 다른 화자만 있으면 carry_over 없음"""
        groups = [
            {"speaker": 1, "text": "안녕하세요", "confidence": 0.9, "start": 10.0, "end": 12.0},
        ]
        carry, new = detect_speaker_overlap(groups, prev_speaker=0, prev_end_time=9.5)
        assert carry == []
        assert new == groups

    def test_overlap_same_speaker_first_group(self):
        """첫 그룹이 이전 화자와 같고 시간이 겹치면 carry_over에 분리"""
        groups = [
            {"speaker": 0, "text": "마지막 말", "confidence": 0.8, "start": 9.0, "end": 10.0},
            {"speaker": 1, "text": "새 발언", "confidence": 0.9, "start": 10.0, "end": 12.0},
        ]
        carry, new = detect_speaker_overlap(groups, prev_speaker=0, prev_end_time=9.5)
        assert len(carry) == 1
        assert carry[0]["text"] == "마지막 말"
        assert len(new) == 1
        assert new[0]["text"] == "새 발언"

    def test_no_overlap_time_gap(self):
        """시간 겹침이 없으면 carry_over 없음"""
        groups = [
            {"speaker": 0, "text": "별도 발언", "confidence": 0.8, "start": 20.0, "end": 22.0},
        ]
        carry, new = detect_speaker_overlap(groups, prev_speaker=0, prev_end_time=9.5)
        assert carry == []
        assert new == groups

    def test_no_prev_speaker(self):
        """이전 화자가 없으면 carry_over 없음"""
        groups = [
            {"speaker": 0, "text": "첫 발언", "confidence": 0.9, "start": 0.0, "end": 2.0},
        ]
        carry, new = detect_speaker_overlap(groups, prev_speaker=None, prev_end_time=0.0)
        assert carry == []
        assert new == groups

    def test_empty_groups(self):
        carry, new = detect_speaker_overlap([], prev_speaker=0, prev_end_time=5.0)
        assert carry == []
        assert new == []

    def test_all_same_speaker_overlap(self):
        """모든 그룹이 이전 화자와 같으면 첫 그룹만 carry_over"""
        groups = [
            {"speaker": 0, "text": "추가 말", "confidence": 0.8, "start": 9.0, "end": 10.0},
            {"speaker": 0, "text": "또 다른 말", "confidence": 0.9, "start": 10.0, "end": 12.0},
        ]
        carry, new = detect_speaker_overlap(groups, prev_speaker=0, prev_end_time=9.5)
        assert len(carry) == 1
        assert len(new) == 1


class TestGroupWordsIntegration:
    """group_words_by_speaker + detect_speaker_overlap 통합 테스트"""

    def test_speaker_transition_scenario(self):
        """A가 말하다가 B로 전환되는 시나리오"""
        words = [
            {"speaker": 0, "word": "감사합니다", "confidence": 0.9, "start": 8.0, "end": 9.0},
            {"speaker": 1, "word": "네", "confidence": 0.95, "start": 9.5, "end": 10.0},
            {"speaker": 1, "word": "알겠습니다", "confidence": 0.92, "start": 10.0, "end": 11.0},
        ]
        groups = group_words_by_speaker(words)
        assert len(groups) == 2

        # 이전 버퍼가 화자 0이고 end_time=8.5인 상황
        carry, new = detect_speaker_overlap(groups, prev_speaker=0, prev_end_time=8.5)

        # "감사합니다"는 화자 0이고 이전 버퍼 범위와 겹침 → carry_over
        assert len(carry) == 1
        assert carry[0]["text"] == "감사합니다"
        # 나머지는 화자 1
        assert len(new) == 1
        assert new[0]["speaker"] == 1
