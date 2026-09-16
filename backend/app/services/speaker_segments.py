# -*- coding: utf-8 -*-
"""화자별 연속 발언구간 빌더 — 발언영상 추출 기능의 데이터 원천.

자막을 AI 자막 우선(prefer_ai_subtitles)으로 선택한 뒤, 연속된 같은 화자의
발언을 강제 분할 없이(_group_by_speaker(max_group_duration=None)) 병합하여
화자별 발언구간 목록을 만든다.
"""

from __future__ import annotations

from supabase import Client

from app.services.subtitle_fetch import fetch_all_subtitles
from app.services.subtitle_select import prefer_ai_subtitles
from app.services.transcript_export import _group_by_speaker

PAGE_SIZE = 1000  # Supabase 1회 조회 한도 대비 페이지 크기
PREVIEW_LENGTH = 80  # 구간 미리보기 글자 수
UNKNOWN_SPEAKER = "(미지정)"


# 자막 전량 조회는 subtitle_fetch 로 옮겼다(2026-09-14). 이름은 남긴다 — clip_job_service·clip_draft_index 와
# 그 테스트들이 이 이름으로 import·monkeypatch 한다.
_fetch_all_subtitles = fetch_all_subtitles


def build_speaker_segments(supabase: Client, meeting: dict) -> dict:
    """회의 자막을 화자별 연속 발언구간으로 병합합니다.

    반환 형태:
    {
        meeting_id, kms_midx(없으면 None), title, total_duration,
        speakers: [  # total_time 내림차순
            {
                speaker, total_time, segment_count,
                segments: [
                    {start_time, end_time, duration, subtitle_count, text_preview}
                ],
            }
        ],
    }
    """
    meeting_id = meeting.get("id")
    all_subs = _fetch_all_subtitles(supabase, meeting_id)
    subtitles = prefer_ai_subtitles(all_subs)

    # 화자 미지정은 "(미지정)"으로 정규화 (그룹핑 전 통일)
    normalized = [
        {**sub, "speaker": sub.get("speaker") or UNKNOWN_SPEAKER}
        for sub in subtitles
    ]

    # 강제 분할 없이 연속 발언 전체를 하나의 구간으로 유지
    grouped = _group_by_speaker(normalized, max_group_duration=None)

    speakers_map: dict[str, dict] = {}
    for entry in grouped:
        speaker = entry["speaker"]
        if speaker not in speakers_map:
            speakers_map[speaker] = {
                "speaker": speaker,
                "total_time": 0.0,
                "segment_count": 0,
                "segments": [],
            }

        start = entry.get("start_time") or 0
        end = entry.get("end_time") or 0
        duration = max(0, end - start)
        text = " ".join(entry["texts"])

        info = speakers_map[speaker]
        info["total_time"] += duration
        info["segment_count"] += 1
        info["segments"].append({
            "start_time": start,
            "end_time": end,
            "duration": duration,
            "subtitle_count": len(entry["texts"]),
            "text_preview": text[:PREVIEW_LENGTH],
        })

    # 총 발언 시간 순으로 정렬 (많이 발언한 화자가 위)
    speakers_list = sorted(
        speakers_map.values(),
        key=lambda s: s["total_time"],
        reverse=True,
    )

    total_duration = max(
        (sub.get("end_time") or 0 for sub in subtitles), default=0
    )

    return {
        "meeting_id": meeting_id,
        "kms_midx": meeting.get("kms_midx"),
        "title": meeting.get("title"),
        "total_duration": total_duration,
        "speakers": speakers_list,
    }
