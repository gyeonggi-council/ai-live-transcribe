"""자막 변경 이력 추적 서비스

자막 수정 시 old/new 값을 subtitle_history 테이블에 기록합니다.
"""

import logging

from supabase import Client

logger = logging.getLogger(__name__)


def record_subtitle_change(
    supabase: Client,
    subtitle_id: str,
    field_name: str,
    old_value: str | None,
    new_value: str | None,
    changed_by: str | None = None,
) -> dict | None:
    """자막 변경 이력을 기록합니다."""
    if old_value == new_value:
        return None

    data = {
        "subtitle_id": subtitle_id,
        "field_name": field_name,
        "old_value": old_value,
        "new_value": new_value,
        "changed_by": changed_by,
    }

    try:
        result = supabase.table("subtitle_history").insert(data).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.warning("이력 기록 실패 (subtitle_id=%s): %s", subtitle_id, e)
        return None


def record_changes_for_update(
    supabase: Client,
    subtitle_id: str,
    original: dict,
    update_data: dict,
    changed_by: str | None = None,
) -> list[dict]:
    """업데이트 데이터와 원본을 비교하여 변경된 필드의 이력을 기록합니다."""
    records = []
    for field_name, new_value in update_data.items():
        old_value = original.get(field_name)
        if str(old_value) != str(new_value) if old_value is not None else new_value is not None:
            record = record_subtitle_change(
                supabase, subtitle_id, field_name, str(old_value) if old_value is not None else None, str(new_value), changed_by
            )
            if record:
                records.append(record)
    return records


def get_subtitle_history(
    supabase: Client,
    subtitle_id: str,
) -> list[dict]:
    """자막의 변경 이력을 조회합니다."""
    try:
        result = (
            supabase.table("subtitle_history")
            .select("*")
            .eq("subtitle_id", subtitle_id)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data
    except Exception as e:
        logger.warning("이력 조회 실패 (subtitle_id=%s): %s", subtitle_id, e)
        return []
