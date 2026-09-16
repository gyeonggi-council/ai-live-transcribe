"""안건별 자막 분류 서비스

# @TASK P10-T2.1 - 안건별 자막 분류 비즈니스 로직
# @SPEC docs/planning/02-trd.md#회의록-작성

회의의 안건(meeting_agendas)별로 자막을 시간대에 따라 분류합니다.
"""

from typing import Any

MAX_GROUP_DURATION = 150  # 2.5분 — 긴 발언을 가독성 있게 분할


def group_by_speaker(subtitles: list[dict]) -> list[dict]:
    """연속 동일 화자의 발언을 하나의 그룹으로 병합합니다.

    같은 화자라도 그룹 시작으로부터 2.5분 이상 경과하면 새 그룹으로 분할합니다.

    Args:
        subtitles: 시간순 정렬된 자막 목록

    Returns:
        화자별 그룹 목록. 각 그룹은 speaker, texts, start_time, end_time 포함.
    """
    if not subtitles:
        return []

    groups: list[dict] = []
    current_group: dict[str, Any] | None = None

    for sub in subtitles:
        speaker = sub.get("speaker") or "unknown"
        should_split = (
            current_group is not None
            and current_group["speaker"] == speaker
            and (sub["start_time"] - current_group["start_time"]) >= MAX_GROUP_DURATION
        )

        if current_group is None or current_group["speaker"] != speaker or should_split:
            # 새 그룹 시작
            if current_group is not None:
                groups.append(current_group)
            current_group = {
                "speaker": speaker,
                "texts": [sub["text"]],
                "start_time": sub["start_time"],
                "end_time": sub["end_time"],
            }
        else:
            # 기존 그룹에 추가
            current_group["texts"].append(sub["text"])
            current_group["end_time"] = sub["end_time"]

    if current_group is not None:
        groups.append(current_group)

    return groups


def _has_start_time(agendas: list[dict]) -> bool:
    """안건 목록에 start_time 필드가 존재하는지 확인합니다."""
    return any("start_time" in a and a["start_time"] is not None for a in agendas)


def _classify_by_time(agendas: list[dict], subtitles: list[dict]) -> dict:
    """안건의 start_time 기반으로 자막을 시간 구간별로 분류합니다.

    - 첫 안건 start_time 이전 자막 -> unassigned
    - 각 안건: 해당 안건 start_time ~ 다음 안건 start_time 전까지
    - 마지막 안건: 마지막 안건 start_time ~ 끝
    """
    # 안건을 start_time으로 정렬 (이미 order_num으로 정렬됐을 수 있지만 안전하게)
    sorted_agendas = sorted(agendas, key=lambda a: a.get("start_time", 0))

    unassigned: list[dict] = []
    agenda_results: list[dict] = []

    for i, agenda in enumerate(sorted_agendas):
        agenda_start = agenda.get("start_time", 0)
        if i + 1 < len(sorted_agendas):
            agenda_end = sorted_agendas[i + 1].get("start_time", float("inf"))
        else:
            agenda_end = float("inf")

        agenda_subtitles = [
            s for s in subtitles
            if agenda_start <= s["start_time"] < agenda_end
        ]

        agenda_results.append({
            "order_num": agenda["order_num"],
            "title": agenda["title"],
            "description": agenda.get("description"),
            "subtitles": agenda_subtitles,
            "speaker_groups": group_by_speaker(agenda_subtitles),
        })

    # 첫 안건 시작 전 자막은 unassigned
    first_start = sorted_agendas[0].get("start_time", 0) if sorted_agendas else 0
    unassigned = [s for s in subtitles if s["start_time"] < first_start]

    return {
        "agendas": agenda_results,
        "unassigned_subtitles": unassigned,
        "total_subtitles": len(subtitles),
    }


def _classify_by_equal_distribution(agendas: list[dict], subtitles: list[dict]) -> dict:
    """안건에 start_time이 없을 때 자막을 균등 분배합니다.

    order_num 순으로 정렬된 안건에 자막을 N/M개씩 분배합니다.
    """
    sorted_agendas = sorted(agendas, key=lambda a: a["order_num"])
    n_agendas = len(sorted_agendas)
    n_subtitles = len(subtitles)

    agenda_results: list[dict] = []
    chunk_size = n_subtitles // n_agendas if n_agendas > 0 else n_subtitles
    remainder = n_subtitles % n_agendas if n_agendas > 0 else 0

    offset = 0
    for i, agenda in enumerate(sorted_agendas):
        # 나머지를 앞 안건에 1개씩 추가
        size = chunk_size + (1 if i < remainder else 0)
        agenda_subtitles = subtitles[offset:offset + size]
        offset += size

        agenda_results.append({
            "order_num": agenda["order_num"],
            "title": agenda["title"],
            "description": agenda.get("description"),
            "subtitles": agenda_subtitles,
            "speaker_groups": group_by_speaker(agenda_subtitles),
        })

    return {
        "agendas": agenda_results,
        "unassigned_subtitles": [],
        "total_subtitles": n_subtitles,
    }


def classify_subtitles_by_agenda(
    agendas: list[dict],
    subtitles: list[dict],
) -> dict:
    """안건별로 자막을 분류합니다.

    Args:
        agendas: 안건 목록 (order_num 순 정렬 기대)
        subtitles: 자막 목록 (start_time 순 정렬 기대)

    Returns:
        안건별 자막 분류 결과. agendas, unassigned_subtitles, total_subtitles 포함.

    분류 전략:
        1. 안건이 없는 경우: 전체 자막을 "전체" 그룹으로 반환
        2. 안건에 start_time이 있는 경우: 시간 구간으로 분류
        3. 안건에 start_time이 없는 경우: order_num 기반 균등 분배
    """
    # 안건이 없으면 전체를 하나의 그룹으로
    if not agendas:
        return {
            "agendas": [
                {
                    "order_num": 0,
                    "title": "전체",
                    "description": None,
                    "subtitles": subtitles,
                    "speaker_groups": group_by_speaker(subtitles),
                }
            ],
            "unassigned_subtitles": [],
            "total_subtitles": len(subtitles),
        }

    # 안건에 start_time이 있으면 시간 기반 분류
    if _has_start_time(agendas):
        return _classify_by_time(agendas, subtitles)

    # start_time이 없으면 균등 분배
    return _classify_by_equal_distribution(agendas, subtitles)
