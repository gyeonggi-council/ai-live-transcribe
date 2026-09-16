"""속기록 수정 이력 서비스

# @TASK P11C-T3 - 수정이력 서비스
# @SPEC docs/planning/02-trd.md#속기록

속기록 라인 수정 시 변경 이력을 기록하고 조회하는 서비스입니다.
stenography_edit_history 테이블 사용 (Supabase REST).
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from supabase import Client

logger = logging.getLogger(__name__)


# 타입 alias
EditHistoryEntry = dict


def record_edit(
    supabase: Client,
    line_id: str,
    editor_id: Optional[str],
    editor_name: str,
    field_changed: str,
    old_value: Optional[str],
    new_value: str,
) -> Optional[dict]:
    """수정 이력을 기록합니다.

    old_value와 new_value가 동일하면 이력을 생성하지 않습니다.

    Args:
        supabase: Supabase 클라이언트
        line_id: 수정된 라인 ID
        editor_id: 편집자 사용자 ID (nullable)
        editor_name: 편집자 이름
        field_changed: 변경된 필드 (text, speaker, start_ms, end_ms, paragraph)
        old_value: 이전 값
        new_value: 새 값

    Returns:
        생성된 이력 dict 또는 None (변경 없음)
    """
    # 동일 값이면 스킵
    if old_value is not None and str(old_value) == str(new_value):
        return None

    entry_data = {
        "id": str(uuid.uuid4()),
        "line_id": line_id,
        "editor_id": editor_id,
        "editor_name": editor_name,
        "field_changed": field_changed,
        "old_value": old_value,
        "new_value": str(new_value),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        result = supabase.table("stenography_edit_history").insert(entry_data).execute()
        return result.data[0] if result.data else entry_data
    except Exception as e:
        logger.error("수정 이력 기록 실패: %s", e)
        return entry_data


def get_history(
    supabase: Client,
    record_id: str,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """특정 속기록의 수정 이력을 조회합니다.

    record_id에 속한 모든 라인의 이력을 최신순으로 반환합니다.

    Args:
        supabase: Supabase 클라이언트
        record_id: 속기록 레코드 ID
        limit: 조회 제한
        offset: 오프셋

    Returns:
        (이력 목록, 전체 수) 튜플
    """
    # 해당 레코드의 모든 라인 ID 조회
    lines_result = (
        supabase.table("stenography_lines")
        .select("id")
        .eq("record_id", record_id)
        .execute()
    )
    lines = lines_result.data or []

    if not lines:
        return [], 0

    line_ids = [line["id"] for line in lines]

    # 이력 조회
    try:
        history_result = (
            supabase.table("stenography_edit_history")
            .select("*")
            .in_("line_id", line_ids)
            .order("created_at", desc=True)
            .limit(limit)
            .offset(offset)
            .execute()
        )
        items = history_result.data or []
        return items, len(items)
    except Exception as e:
        logger.error("수정 이력 조회 실패: %s", e)
        return [], 0
