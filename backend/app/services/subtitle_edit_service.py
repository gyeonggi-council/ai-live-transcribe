"""자막 편집 서비스 — 단건/배치 수정, 분할, 병합, 교정단어 수집

api/subtitles.py 인라인 알고리즘 이관. 오류 관례:
- LookupError → 라우터에서 404 매핑
- ValueError  → 라우터에서 400 매핑 (메시지는 기존 detail과 바이트 동일)
"""

import logging

from supabase import Client

from app.repositories.dictionary_repository import DictionaryRepository
from app.repositories.subtitle_repository import SubtitleRepository
from app.services.history_tracker import record_changes_for_update
from app.services.subtitle_select import prefer_ai_subtitles
from app.services.vod_stt_service import VodSttService

logger = logging.getLogger(__name__)


def collect_correction(supabase: Client, original_text: str, corrected_text: str) -> None:
    """원본과 교정 텍스트를 비교하여 변경된 단어를 사전에 자동 수집합니다.

    단어 단위 diff를 수행하고, 변경된 단어 쌍을 dictionary 테이블에 기록합니다.
    """
    original_words = original_text.split()
    corrected_words = corrected_text.split()

    # 단순 단어 비교 (같은 위치의 단어가 다르면 교정으로 간주)
    pairs: list[tuple[str, str]] = []
    for i in range(min(len(original_words), len(corrected_words))):
        if original_words[i] != corrected_words[i]:
            pairs.append((original_words[i], corrected_words[i]))

    dictionary_repo = DictionaryRepository(supabase)
    for wrong, correct in pairs:
        if len(wrong) < 2 or len(correct) < 2:
            continue
        try:
            dictionary_repo.upsert_user_correction(wrong, correct)
        except Exception as e:
            logger.debug("교정 수집 실패 (%s→%s): %s", wrong, correct, e)


def update_subtitle(
    supabase: Client,
    meeting_id: str,
    subtitle_id: str,
    update_data: dict,
) -> dict | None:
    """자막 단건을 수정합니다. 대상이 없으면 None (라우터에서 404)."""
    repo = SubtitleRepository(supabase)

    # 원본 조회 (이력 기록용)
    original = repo.get(subtitle_id, meeting_id)

    updated = repo.update(subtitle_id, update_data, meeting_id)
    if not updated:
        return None

    # 변경 이력 기록
    if original:
        record_changes_for_update(supabase, subtitle_id, original, update_data)

    # 교정 단어 자동 수집 (텍스트 변경 시)
    if original and "text" in update_data and original.get("text") != update_data["text"]:
        collect_correction(supabase, original["text"], update_data["text"])

    logger.info(
        "자막 수정 완료: meeting_id=%s, subtitle_id=%s, fields=%s",
        meeting_id,
        subtitle_id,
        list(update_data.keys()),
    )
    return updated[0]


def update_subtitles_batch(supabase: Client, meeting_id: str, items) -> dict:
    """여러 자막을 한번에 수정합니다. 존재하지 않는 자막은 건너뜁니다."""
    repo = SubtitleRepository(supabase)
    updated_items: list[dict] = []

    for item in items:
        update_data = {}
        if item.text is not None:
            update_data["text"] = item.text
        if item.speaker is not None:
            update_data["speaker"] = item.speaker
        if item.start_time is not None:
            update_data["start_time"] = item.start_time
        if item.end_time is not None:
            update_data["end_time"] = item.end_time

        # 변경할 필드가 없으면 건너뜀
        if not update_data:
            continue

        # 원본 조회 (이력 기록용)
        original = repo.get(item.id, meeting_id)

        updated = repo.update(item.id, update_data, meeting_id)
        if updated:
            updated_items.append(updated[0])
            # 변경 이력 기록
            if original:
                record_changes_for_update(supabase, item.id, original, update_data)

    logger.info(
        "자막 배치 수정 완료: meeting_id=%s, 요청=%d건, 수정=%d건",
        meeting_id,
        len(items),
        len(updated_items),
    )
    return {
        "updated": len(updated_items),
        "items": updated_items,
    }


def split_subtitle(
    supabase: Client,
    meeting_id: str,
    subtitle_id: str,
    position: int,
    split_time_req: float | None = None,
) -> dict:
    """자막을 지정된 위치에서 2개로 분할합니다.

    텍스트를 position 위치에서 나누고, 시간도 비례 분할합니다.
    """
    repo = SubtitleRepository(supabase)

    # 원본 조회
    original = repo.get(subtitle_id, meeting_id)
    if original is None:
        raise LookupError("자막을 찾을 수 없습니다.")

    text = original["text"]

    # 분할 위치 검증
    if position <= 0 or position >= len(text):
        raise ValueError(f"분할 위치가 유효하지 않습니다. (0 < position < {len(text)})")

    # 텍스트 분할
    text_first = text[:position].rstrip()
    text_second = text[position:].lstrip()

    if not text_first or not text_second:
        raise ValueError("분할 결과 빈 자막이 생성됩니다.")

    # 시간 분할
    start = original["start_time"]
    end = original["end_time"]
    if split_time_req is not None:
        split_time = split_time_req
        if split_time <= start or split_time >= end:
            raise ValueError(f"분할 시점이 유효하지 않습니다. ({start} < split_time < {end})")
    else:
        # 텍스트 비율로 자동 계산
        ratio = position / len(text)
        split_time = round(start + (end - start) * ratio, 2)

    # 원본 업데이트 (앞부분)
    repo.update(subtitle_id, {"text": text_first, "end_time": split_time})

    # 새 자막 생성 (뒷부분)
    new_subtitle_data = {
        "meeting_id": meeting_id,
        "text": text_second,
        "start_time": split_time,
        "end_time": end,
        "speaker": original.get("speaker"),
        "confidence": original.get("confidence"),
    }
    new_rows = repo.insert(new_subtitle_data)

    # 이력 기록
    record_changes_for_update(
        supabase, subtitle_id, original,
        {"text": text_first, "end_time": split_time},
        "user:split",
    )

    logger.info(
        "자막 분할 완료: meeting_id=%s, subtitle_id=%s, position=%d",
        meeting_id, subtitle_id, position,
    )

    # 업데이트된 원본 조회
    updated_original = repo.get_by_id(subtitle_id)

    return {
        "original": updated_original,
        "new": new_rows[0] if new_rows else None,
    }


def merge_selected(supabase: Client, meeting_id: str, subtitle_ids: list[str]) -> dict:
    """선택한 자막들을 하나로 병합합니다.

    첫 번째 자막의 start_time과 마지막 자막의 end_time을 사용하고,
    텍스트는 공백으로 합산합니다.
    """
    repo = SubtitleRepository(supabase)

    # 선택된 자막 조회 (시간순)
    subtitles = []
    for sid in subtitle_ids:
        row = repo.get(sid, meeting_id)
        if row is None:
            raise LookupError(f"자막을 찾을 수 없습니다: {sid}")
        subtitles.append(row)

    # 시간순 정렬
    subtitles.sort(key=lambda s: s["start_time"])

    # 병합 데이터
    first = subtitles[0]
    last = subtitles[-1]
    merged_text = " ".join(s["text"] for s in subtitles)
    merged_start = first["start_time"]
    merged_end = last["end_time"]

    # 첫 번째 자막 업데이트
    repo.update(first["id"], {
        "text": merged_text,
        "start_time": merged_start,
        "end_time": merged_end,
    })

    # 이력 기록
    record_changes_for_update(
        supabase, first["id"], first,
        {"text": merged_text, "end_time": merged_end},
        "user:merge",
    )

    # 나머지 자막 삭제
    deleted_count = 0
    for sub in subtitles[1:]:
        repo.delete(sub["id"])
        deleted_count += 1

    logger.info(
        "자막 선택 병합 완료: meeting_id=%s, %d개 → 1개",
        meeting_id, len(subtitles),
    )

    return {
        "merged": repo.get_by_id(first["id"]),
        "deleted_count": deleted_count,
    }


def merge_short(
    supabase: Client,
    meeting_id: str,
    gap_threshold: float,
    min_length: int,
) -> dict:
    """기존 자막을 문장 단위로 자동 병합합니다.

    같은 화자의 연속 자막 중 시간 간격이 짧거나 텍스트가 짧은 것을 합칩니다.
    원본은 삭제되고 병합된 자막으로 대체됩니다.
    """
    repo = SubtitleRepository(supabase)

    # 기존 자막 조회 — 한 종류만 병합한다.
    # ★실시간 초안(kind='live')과 AI 완성본(kind='ai')을 섞어 병합하면 두 자막이
    #   한 덩어리로 뭉개져 '실시간 자막(초안)' 탭이 못 쓰게 된다. 화면이 기본으로
    #   보여주는 종류(AI 있으면 AI)만 대상으로 삼는다.
    all_rows = repo.list_all_ordered(meeting_id)
    rows = prefer_ai_subtitles(all_rows)
    if not rows:
        return {"original_count": 0, "merged_count": 0, "reduced": 0}

    # 병합 대상 종류 — 삭제·재삽입 모두 이 종류로만 한다.
    # 종류가 하나로 확정될 때만 좁힌다. kind 가 비어 있는 레거시 데이터는 종류로
    # 거를 수 없으므로 예전처럼 전체를 갈아끼운다(좁혔다가는 삭제가 빗나가 중복된다).
    kinds = {r.get("kind") for r in rows}
    merge_kind = kinds.pop() if len(kinds) == 1 else None
    original_count = len(rows)

    # 병합 로직 적용
    subs_for_merge = [
        {
            "meeting_id": meeting_id,
            "text": s["text"],
            "start_time": s["start_time"],
            "end_time": s["end_time"],
            "confidence": s.get("confidence", 0),
            "speaker": s.get("speaker"),
        }
        for s in rows
    ]

    merged = VodSttService._merge_short_utterances(
        subs_for_merge,
        gap_threshold=gap_threshold,
        min_length=min_length,
    )

    if len(merged) >= original_count:
        return {"original_count": original_count, "merged_count": original_count, "reduced": 0}

    # 기존 자막 삭제 + 병합 자막 삽입 — 둘 다 같은 종류에만 적용한다
    if merge_kind:
        for m in merged:
            m["kind"] = merge_kind
    repo.delete_by_meeting(meeting_id, kind=merge_kind)
    repo.insert_many(merged)

    reduced = original_count - len(merged)
    logger.info(
        "자막 병합 완료: meeting_id=%s, %d → %d (-%d)",
        meeting_id, original_count, len(merged), reduced,
    )

    return {
        "original_count": original_count,
        "merged_count": len(merged),
        "reduced": reduced,
    }
