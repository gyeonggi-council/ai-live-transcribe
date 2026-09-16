"""자막 교정 적용 서비스 — PII 마스킹 / 용어 교정 / AI 문법 교정 적용

api/subtitles.py의 apply-* 루프 이관. check-*(조회 전용)는 라우터에 남는다.
"""

import logging

from supabase import Client

from app.repositories.subtitle_repository import SubtitleRepository
from app.services.history_tracker import record_changes_for_update
from app.services.pii_masking import mask_pii
from app.services.terminology_checker import apply_terminology_fix

logger = logging.getLogger(__name__)


def apply_pii_mask(
    supabase: Client,
    meeting_id: str,
    subtitle_ids: list[str] | None = None,
) -> dict:
    """자막의 PII를 마스킹하여 실제로 업데이트합니다."""
    repo = SubtitleRepository(supabase)
    rows = repo.list_id_text(meeting_id, subtitle_ids)

    if not rows:
        return {"updated": 0, "items": []}

    updated_items = []
    for item in rows:
        masked_text, pii_list = mask_pii(item["text"])
        if not pii_list:
            continue

        # 원본 기록 후 업데이트
        record_changes_for_update(
            supabase, item["id"], {"text": item["text"]}, {"text": masked_text}, "system:pii_mask"
        )

        repo.update(item["id"], {"text": masked_text})
        updated_items.append({
            "id": item["id"],
            "original_text": item["text"],
            "masked_text": masked_text,
            "pii_count": len(pii_list),
        })

    return {"updated": len(updated_items), "items": updated_items}


def apply_terminology(supabase: Client, meeting_id: str) -> dict:
    """자막의 용어를 사전 기반으로 일괄 교정합니다."""
    repo = SubtitleRepository(supabase)
    rows = repo.list_id_text(meeting_id)

    if not rows:
        return {"updated": 0, "items": []}

    fixes = apply_terminology_fix(rows)

    # 실제 업데이트 적용
    for fix in fixes:
        record_changes_for_update(
            supabase, fix["id"],
            {"text": fix["original_text"]},
            {"text": fix["corrected_text"]},
            "system:terminology",
        )
        repo.update(fix["id"], {"text": fix["corrected_text"]})

    return {"updated": len(fixes), "items": fixes}


def apply_grammar_corrections(
    supabase: Client,
    meeting_id: str,
    corrections: list[dict],
) -> dict:
    """AI 문장 검사 결과를 선택적으로 적용합니다."""
    repo = SubtitleRepository(supabase)
    updated = 0

    for correction in corrections:
        subtitle_id = correction.get("subtitle_id")
        corrected_text = correction.get("corrected_text")
        if not subtitle_id or not corrected_text:
            continue

        # 원본 조회
        original_row = repo.get_text(subtitle_id, meeting_id)
        if not original_row:
            continue

        original_text = original_row["text"]
        if original_text == corrected_text:
            continue

        # 이력 기록 + 업데이트
        record_changes_for_update(
            supabase, subtitle_id,
            {"text": original_text},
            {"text": corrected_text},
            "system:grammar",
        )
        repo.update(subtitle_id, {"text": corrected_text})
        updated += 1

    return {"updated": updated}
