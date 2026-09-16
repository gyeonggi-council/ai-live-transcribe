"""화자(speaker) 관련 유틸리티 함수 모음.

# @TASK P5-T1.2 - 화자 그룹핑 유틸리티 추출
# @SPEC channel_stt.py에서 분리된 화자 그룹핑 로직

Deepgram STT 결과의 words 배열을 화자 단위로 그룹핑하는 등
화자 관련 공통 로직을 제공합니다.
"""

from __future__ import annotations


def group_words_by_speaker(words: list[dict]) -> list[dict]:
    """words 배열을 화자 경계에서 분할하여 그룹별로 반환합니다.

    Deepgram STT 결과의 words 배열에서 연속된 같은 화자의 단어를
    하나의 그룹으로 묶고, 화자가 바뀌는 지점에서 새 그룹을 시작합니다.

    Args:
        words: Deepgram words 배열. 각 dict는 다음 키를 포함:
            - speaker (int | None): 화자 ID
            - punctuated_word 또는 word (str): 단어 텍스트
            - confidence (float): 인식 신뢰도
            - start (float): 시작 시간(초)
            - end (float): 종료 시간(초)

    Returns:
        화자별로 그룹핑된 dict 리스트. 각 dict 키:
            - speaker (int | None): 화자 ID
            - text (str): 해당 화자의 연속 단어를 공백으로 결합한 텍스트
            - confidence (float): 그룹 내 단어들의 평균 신뢰도
            - start (float): 그룹 첫 단어의 시작 시간
            - end (float): 그룹 마지막 단어의 종료 시간
    """
    if not words:
        return []

    groups: list[dict] = []
    current_speaker = words[0].get("speaker")
    current_words: list[str] = []
    conf_sum = 0.0
    conf_count = 0
    start = words[0].get("start", 0.0)
    end = words[0].get("end", 0.0)

    for w in words:
        sp = w.get("speaker")
        word_text = w.get("punctuated_word", w.get("word", ""))

        if sp != current_speaker and current_words:
            # 화자가 바뀌면 현재 그룹을 확정하고 새 그룹 시작
            groups.append({
                "speaker": current_speaker,
                "text": " ".join(current_words),
                "confidence": conf_sum / conf_count if conf_count else 0.0,
                "start": start,
                "end": end,
            })
            current_words = []
            conf_sum = 0.0
            conf_count = 0
            current_speaker = sp
            start = w.get("start", 0.0)

        current_words.append(word_text)
        conf_sum += w.get("confidence", 0.0)
        conf_count += 1
        end = w.get("end", 0.0)

    # 마지막 그룹
    if current_words:
        groups.append({
            "speaker": current_speaker,
            "text": " ".join(current_words),
            "confidence": conf_sum / conf_count if conf_count else 0.0,
            "start": start,
            "end": end,
        })

    return groups


def detect_speaker_overlap(
    groups: list[dict],
    prev_speaker: int | None,
    prev_end_time: float,
    overlap_threshold: float = 0.5,
) -> tuple[list[dict], list[dict]]:
    """화자 그룹에서 이전 화자의 잔여 단어를 분리합니다.

    Deepgram의 is_final 응답에서 이전 화자(A)의 마지막 단어가
    다음 화자(B)의 첫 응답에 포함되는 경우를 감지하여 분리합니다.

    Args:
        groups: group_words_by_speaker() 결과
        prev_speaker: 이전 버퍼의 화자 ID
        prev_end_time: 이전 버퍼의 종료 시간
        overlap_threshold: 시간 겹침 임계값 (초)

    Returns:
        (carry_over, new_groups) 튜플:
        - carry_over: 이전 화자에 합쳐야 할 그룹 (0 또는 1개)
        - new_groups: 새 화자 그룹들
    """
    if not groups or prev_speaker is None:
        return [], groups

    first = groups[0]

    # 첫 그룹이 이전 화자와 같고, 시간이 겹치면 carry_over로 분리
    if (
        first["speaker"] == prev_speaker
        and first["start"] <= prev_end_time + overlap_threshold
    ):
        return [first], groups[1:]

    return [], groups
