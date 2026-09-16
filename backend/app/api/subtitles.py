"""Subtitles API 라우터 (Supabase REST)

# @TASK P5-T2.1 - 자막 조회/검색/수정 API
# @SPEC docs/planning/02-trd.md#자막-API
"""

import logging
import re
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from supabase import Client

from app.core.auth_middleware import optional_auth, require_role
from app.core.database import get_supabase
from app.schemas.subtitle import (
    SubtitleBatchUpdate,
    SubtitleMergeSelectedRequest,
    SubtitleSplitRequest,
    SubtitleUpdate,
)
from app.services.grammar_checker import check_grammar_batch
from app.services.history_tracker import get_subtitle_history, record_changes_for_update
from app.services.pii_masking import mask_pii, mask_pii_batch
from app.services.terminology_checker import apply_terminology_fix, check_terminology
from app.services.verification_service import (
    batch_verify,
    get_review_queue,
    get_verification_stats,
    update_verification_status,
)
from app.services.vod_stt_service import VodSttService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meetings", tags=["subtitles"])

# subtitles.meeting_id 는 uuid 컬럼 — 채널 ID(ch1 등) 유입 판별용
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


@router.get(
    "/{meeting_id}/subtitles",
    summary="회의별 자막 목록 조회",
)
async def get_subtitles(
    meeting_id: str,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    kind: Annotated[str | None, Query()] = None,
    supabase: Client = Depends(get_supabase),
) -> dict:
    """회의별 자막 목록을 조회합니다.

    kind: 'live'(실시간) / 'ai'(VOD 화자구분) 중 한 종류만 조회. 미지정 시
    AI 자막이 있으면 AI 우선, 없으면 실시간 자막을 반환한다. kind_counts로
    두 종류의 보유 건수를 함께 내려 프런트가 비교 토글을 표시할 수 있게 한다.

    meeting_id 가 채널 ID(ch1 등)면 해당 채널의 라이브/최근 회의로 해석한다 —
    subtitles.meeting_id 는 uuid 라 채널 ID 를 그대로 넣으면 22P02(500)가 났다
    (2026-08-18, 운영에도 있던 결함). 해석 불가면 빈 목록(200).
    """
    if not _UUID_RE.fullmatch(meeting_id):
        from app.api.meetings import get_live_meeting_service

        resolved = get_live_meeting_service(supabase, channel=meeting_id)
        rid = (resolved or {}).get("id") or ""
        if _UUID_RE.fullmatch(rid):
            meeting_id = rid
        else:
            empty_counts = {"live": 0, "ai": 0}
            return {
                "items": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
                "kind": kind if kind in ("live", "ai") else "live",
                "kind_counts": empty_counts,
            }

    # 종류별 건수 (비교 토글 노출 판단용)
    kind_counts: dict[str, int] = {}
    for k in ("live", "ai"):
        c = (
            supabase.table("subtitles")
            .select("id", count="exact")
            .eq("meeting_id", meeting_id)
            .eq("kind", k)
            .execute()
        )
        kind_counts[k] = c.count or 0

    # 조회할 종류 결정 — 미지정 시 ai 우선(있으면), 없으면 live
    effective_kind = kind
    if effective_kind not in ("live", "ai"):
        effective_kind = "ai" if kind_counts["ai"] > 0 else "live"

    query = (
        supabase.table("subtitles")
        .select("*")
        .eq("meeting_id", meeting_id)
        .eq("kind", effective_kind)
    )
    result = query.order("start_time").range(offset, offset + limit - 1).execute()
    total = kind_counts.get(effective_kind, 0)

    return {
        "items": result.data,
        "total": total,
        "limit": limit,
        "offset": offset,
        "kind": effective_kind,
        "kind_counts": kind_counts,
    }


@router.delete(
    "/{meeting_id}/subtitles",
    summary="회의 자막 전체 삭제",
)
async def delete_all_subtitles(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("stenographer", "admin")),
) -> dict:
    """회의의 모든 자막을 삭제합니다. 자막 재생성을 위해 사용합니다."""
    count_result = (
        supabase.table("subtitles")
        .select("id", count="exact")
        .eq("meeting_id", meeting_id)
        .execute()
    )
    total = count_result.count or 0

    if total > 0:
        supabase.table("subtitles").delete().eq("meeting_id", meeting_id).execute()
        logger.info("자막 전체 삭제: meeting_id=%s, %d건", meeting_id, total)

    return {"deleted": total}


# @TASK P5-T2.1 - 자막 단건 수정 엔드포인트
@router.patch(
    "/{meeting_id}/subtitles/{subtitle_id}",
    summary="자막 단건 수정",
)
async def update_subtitle(
    meeting_id: str,
    subtitle_id: str,
    body: SubtitleUpdate,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("stenographer", "admin")),
) -> dict:
    """자막을 수정합니다. text 또는 speaker 필드를 변경할 수 있습니다."""
    # Layer 2: 도메인 검증 - 변경할 필드가 하나도 없으면 400
    update_data = body.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="수정할 필드가 없습니다. text 또는 speaker를 지정해주세요.",
        )

    # 원본 조회 (이력 기록용)
    original_result = (
        supabase.table("subtitles")
        .select("*")
        .eq("id", subtitle_id)
        .eq("meeting_id", meeting_id)
        .limit(1)
        .execute()
    )
    original = original_result.data[0] if original_result.data else None

    # Supabase UPDATE + 필터링
    result = (
        supabase.table("subtitles")
        .update(update_data)
        .eq("id", subtitle_id)
        .eq("meeting_id", meeting_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"자막을 찾을 수 없습니다 (meeting_id={meeting_id}, subtitle_id={subtitle_id})",
        )

    # 변경 이력 기록
    if original:
        record_changes_for_update(supabase, subtitle_id, original, update_data)

    # 교정 단어 자동 수집 (텍스트 변경 시)
    if original and "text" in update_data and original.get("text") != update_data["text"]:
        _collect_correction(supabase, original["text"], update_data["text"])

    logger.info(
        "자막 수정 완료: meeting_id=%s, subtitle_id=%s, fields=%s",
        meeting_id,
        subtitle_id,
        list(update_data.keys()),
    )
    return result.data[0]


# @TASK P5-T2.1 - 자막 배치 수정 엔드포인트
@router.patch(
    "/{meeting_id}/subtitles",
    summary="자막 배치 수정",
)
async def update_subtitles_batch(
    meeting_id: str,
    body: SubtitleBatchUpdate,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("stenographer", "admin")),
) -> dict:
    """여러 자막을 한번에 수정합니다.

    각 항목의 id로 자막을 찾아 text/speaker를 업데이트합니다.
    존재하지 않는 자막은 건너뛰고 나머지만 수정합니다.
    """
    updated_items: list[dict] = []

    for item in body.items:
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
        original_result = (
            supabase.table("subtitles")
            .select("*")
            .eq("id", item.id)
            .eq("meeting_id", meeting_id)
            .limit(1)
            .execute()
        )
        original = original_result.data[0] if original_result.data else None

        result = (
            supabase.table("subtitles")
            .update(update_data)
            .eq("id", item.id)
            .eq("meeting_id", meeting_id)
            .execute()
        )

        if result.data:
            updated_items.append(result.data[0])
            # 변경 이력 기록
            if original:
                record_changes_for_update(supabase, item.id, original, update_data)

    logger.info(
        "자막 배치 수정 완료: meeting_id=%s, 요청=%d건, 수정=%d건",
        meeting_id,
        len(body.items),
        len(updated_items),
    )
    return {
        "updated": len(updated_items),
        "items": updated_items,
    }


# =============================================================================
# Subtitle Split / Merge-Selected (Vrew 스타일 편집)
# =============================================================================


@router.post(
    "/{meeting_id}/subtitles/{subtitle_id}/split",
    summary="자막 분할",
)
async def split_subtitle(
    meeting_id: str,
    subtitle_id: str,
    body: SubtitleSplitRequest,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("stenographer", "admin")),
) -> dict:
    """자막을 지정된 위치에서 2개로 분할합니다.

    텍스트를 position 위치에서 나누고, 시간도 비례 분할합니다.
    """
    # 원본 조회
    result = (
        supabase.table("subtitles")
        .select("*")
        .eq("id", subtitle_id)
        .eq("meeting_id", meeting_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="자막을 찾을 수 없습니다.",
        )

    original = result.data[0]
    text = original["text"]

    # 분할 위치 검증
    if body.position <= 0 or body.position >= len(text):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"분할 위치가 유효하지 않습니다. (0 < position < {len(text)})",
        )

    # 텍스트 분할
    text_first = text[:body.position].rstrip()
    text_second = text[body.position:].lstrip()

    if not text_first or not text_second:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="분할 결과 빈 자막이 생성됩니다.",
        )

    # 시간 분할
    start = original["start_time"]
    end = original["end_time"]
    if body.split_time is not None:
        split_time = body.split_time
        if split_time <= start or split_time >= end:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"분할 시점이 유효하지 않습니다. ({start} < split_time < {end})",
            )
    else:
        # 텍스트 비율로 자동 계산
        ratio = body.position / len(text)
        split_time = round(start + (end - start) * ratio, 2)

    # 원본 업데이트 (앞부분)
    supabase.table("subtitles").update({
        "text": text_first,
        "end_time": split_time,
    }).eq("id", subtitle_id).execute()

    # 새 자막 생성 (뒷부분)
    new_subtitle_data = {
        "meeting_id": meeting_id,
        "text": text_second,
        "start_time": split_time,
        "end_time": end,
        "speaker": original.get("speaker"),
        "confidence": original.get("confidence"),
    }
    new_result = supabase.table("subtitles").insert(new_subtitle_data).execute()

    # 이력 기록
    record_changes_for_update(
        supabase, subtitle_id, original,
        {"text": text_first, "end_time": split_time},
        "user:split",
    )

    logger.info(
        "자막 분할 완료: meeting_id=%s, subtitle_id=%s, position=%d",
        meeting_id, subtitle_id, body.position,
    )

    # 업데이트된 원본 조회
    updated_original = (
        supabase.table("subtitles")
        .select("*")
        .eq("id", subtitle_id)
        .limit(1)
        .execute()
    )

    return {
        "original": updated_original.data[0] if updated_original.data else None,
        "new": new_result.data[0] if new_result.data else None,
    }


@router.post(
    "/{meeting_id}/subtitles/merge-selected",
    summary="선택한 자막 병합",
)
async def merge_selected_subtitles(
    meeting_id: str,
    body: SubtitleMergeSelectedRequest,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("stenographer", "admin")),
) -> dict:
    """선택한 자막들을 하나로 병합합니다.

    첫 번째 자막의 start_time과 마지막 자막의 end_time을 사용하고,
    텍스트는 공백으로 합산합니다.
    """
    # 선택된 자막 조회 (시간순)
    subtitles = []
    for sid in body.subtitle_ids:
        result = (
            supabase.table("subtitles")
            .select("*")
            .eq("id", sid)
            .eq("meeting_id", meeting_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"자막을 찾을 수 없습니다: {sid}",
            )
        subtitles.append(result.data[0])

    # 시간순 정렬
    subtitles.sort(key=lambda s: s["start_time"])

    # 병합 데이터
    first = subtitles[0]
    last = subtitles[-1]
    merged_text = " ".join(s["text"] for s in subtitles)
    merged_start = first["start_time"]
    merged_end = last["end_time"]
    merged_speaker = first.get("speaker")

    # 첫 번째 자막 업데이트
    supabase.table("subtitles").update({
        "text": merged_text,
        "start_time": merged_start,
        "end_time": merged_end,
    }).eq("id", first["id"]).execute()

    # 이력 기록
    record_changes_for_update(
        supabase, first["id"], first,
        {"text": merged_text, "end_time": merged_end},
        "user:merge",
    )

    # 나머지 자막 삭제
    deleted_count = 0
    for sub in subtitles[1:]:
        supabase.table("subtitles").delete().eq("id", sub["id"]).execute()
        deleted_count += 1

    logger.info(
        "자막 선택 병합 완료: meeting_id=%s, %d개 → 1개",
        meeting_id, len(subtitles),
    )

    # 업데이트된 자막 조회
    merged_result = (
        supabase.table("subtitles")
        .select("*")
        .eq("id", first["id"])
        .limit(1)
        .execute()
    )

    return {
        "merged": merged_result.data[0] if merged_result.data else None,
        "deleted_count": deleted_count,
    }


# =============================================================================
# Subtitle Merge (짧은 자막 병합) - Auto
# =============================================================================


@router.post(
    "/{meeting_id}/subtitles/merge",
    summary="기존 자막 문장 병합",
)
async def merge_subtitles(
    meeting_id: str,
    gap_threshold: float = Query(1.0, ge=0.1, le=5.0, description="병합 기준 시간 간격 (초)"),
    min_length: int = Query(15, ge=5, le=50, description="병합 기준 최소 텍스트 길이"),
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("stenographer", "admin")),
) -> dict:
    """기존 자막을 문장 단위로 병합합니다.

    같은 화자의 연속 자막 중 시간 간격이 짧거나 텍스트가 짧은 것을 합칩니다.
    원본은 삭제되고 병합된 자막으로 대체됩니다.
    """
    # 기존 자막 조회
    result = (
        supabase.table("subtitles")
        .select("*")
        .eq("meeting_id", meeting_id)
        .order("start_time")
        .execute()
    )

    if not result.data:
        return {"original_count": 0, "merged_count": 0, "reduced": 0}

    original_count = len(result.data)

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
        for s in result.data
    ]

    merged = VodSttService._merge_short_utterances(
        subs_for_merge,
        gap_threshold=gap_threshold,
        min_length=min_length,
    )

    if len(merged) >= original_count:
        return {"original_count": original_count, "merged_count": original_count, "reduced": 0}

    # 기존 자막 삭제 + 병합 자막 삽입
    supabase.table("subtitles").delete().eq("meeting_id", meeting_id).execute()
    supabase.table("subtitles").insert(merged).execute()

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


# =============================================================================
# Subtitle History (P6-2: T7)
# =============================================================================


@router.get(
    "/{meeting_id}/subtitles/{subtitle_id}/history",
    summary="자막 변경 이력 조회",
)
async def get_history(
    meeting_id: str,
    subtitle_id: str,
    supabase: Client = Depends(get_supabase),
) -> list[dict]:
    """자막의 변경 이력을 조회합니다."""
    return get_subtitle_history(supabase, subtitle_id)


# =============================================================================
# PII Masking (P6-2: T6)
# =============================================================================


@router.post(
    "/{meeting_id}/subtitles/detect-pii",
    summary="자막 PII 감지",
)
async def detect_pii_in_subtitles(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
) -> dict:
    """회의의 모든 자막에서 개인정보(PII)를 감지합니다."""
    result = (
        supabase.table("subtitles")
        .select("id, text")
        .eq("meeting_id", meeting_id)
        .order("start_time")
        .execute()
    )

    if not result.data:
        return {"items": [], "total_pii_count": 0}

    masked_results = mask_pii_batch(result.data)
    pii_items = [r for r in masked_results if r["pii_found"]]
    total_pii = sum(len(r["pii_found"]) for r in masked_results)

    return {"items": pii_items, "total_pii_count": total_pii}


@router.post(
    "/{meeting_id}/subtitles/apply-pii-mask",
    summary="자막 PII 마스킹 적용",
)
async def apply_pii_mask(
    meeting_id: str,
    subtitle_ids: list[str] = Body(default=None, description="마스킹할 자막 ID 목록 (없으면 전체)"),
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("stenographer", "admin")),
) -> dict:
    """자막의 PII를 마스킹하여 실제로 업데이트합니다."""
    query = supabase.table("subtitles").select("id, text").eq("meeting_id", meeting_id)
    if subtitle_ids:
        query = query.in_("id", subtitle_ids)
    result = query.order("start_time").execute()

    if not result.data:
        return {"updated": 0, "items": []}

    updated_items = []
    for item in result.data:
        masked_text, pii_list = mask_pii(item["text"])
        if not pii_list:
            continue

        # 원본 기록 후 업데이트
        record_changes_for_update(
            supabase, item["id"], {"text": item["text"]}, {"text": masked_text}, "system:pii_mask"
        )

        supabase.table("subtitles").update({"text": masked_text}).eq("id", item["id"]).execute()
        updated_items.append({
            "id": item["id"],
            "original_text": item["text"],
            "masked_text": masked_text,
            "pii_count": len(pii_list),
        })

    return {"updated": len(updated_items), "items": updated_items}


# =============================================================================
# Terminology Check (Phase 6B)
# =============================================================================


@router.post(
    "/{meeting_id}/subtitles/check-terminology",
    summary="용어 표기 점검",
)
async def check_terminology_endpoint(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
    _user: dict | None = Depends(optional_auth),
) -> dict:
    """자막의 용어 표기 일관성을 점검합니다.

    비로그인 포함 누구나 호출 가능. 클라이언트에서 '최초 1회' UX 제약으로 남용 방지.
    결과를 즉시 적용하지는 않으므로(POST check-*는 조회), 안전.
    """
    result = (
        supabase.table("subtitles")
        .select("id, text")
        .eq("meeting_id", meeting_id)
        .order("start_time")
        .execute()
    )

    if not result.data:
        return {"issues": [], "total_issues": 0}

    issues = check_terminology(result.data)
    return {
        "issues": [
            {
                "subtitle_id": i.subtitle_id,
                "wrong_term": i.wrong_term,
                "correct_term": i.correct_term,
                "category": i.category,
            }
            for i in issues
        ],
        "total_issues": len(issues),
    }


@router.post(
    "/{meeting_id}/subtitles/apply-terminology",
    summary="용어 표기 일괄 교정",
)
async def apply_terminology_endpoint(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("admin")),
) -> dict:
    """자막의 용어를 사전 기반으로 일괄 교정합니다. (admin 전용)"""
    result = (
        supabase.table("subtitles")
        .select("id, text")
        .eq("meeting_id", meeting_id)
        .order("start_time")
        .execute()
    )

    if not result.data:
        return {"updated": 0, "items": []}

    fixes = apply_terminology_fix(result.data)

    # 실제 업데이트 적용
    for fix in fixes:
        record_changes_for_update(
            supabase, fix["id"],
            {"text": fix["original_text"]},
            {"text": fix["corrected_text"]},
            "system:terminology",
        )
        supabase.table("subtitles").update({"text": fix["corrected_text"]}).eq("id", fix["id"]).execute()

    return {"updated": len(fixes), "items": fixes}


# =============================================================================
# Grammar Check (Phase 6B)
# =============================================================================


@router.post(
    "/{meeting_id}/subtitles/check-grammar",
    summary="AI 문장 검사",
)
async def check_grammar_endpoint(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
    _user: dict | None = Depends(optional_auth),
) -> dict:
    """AI를 사용하여 자막의 맞춤법/문법을 검사합니다.

    비로그인 포함 누구나 호출 가능 — 조회만 하고 DB는 변경하지 않음.
    실제 적용(apply-*)은 여전히 admin 전용.
    클라이언트에서 '최초 1회' UX 제약을 두어 OpenAI 비용 남용을 억제.
    """
    result = (
        supabase.table("subtitles")
        .select("id, text")
        .eq("meeting_id", meeting_id)
        .order("start_time")
        .execute()
    )

    if not result.data:
        return {"issues": [], "total_issues": 0}

    try:
        issues = await check_grammar_batch(result.data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    return {
        "issues": [
            {
                "subtitle_id": i.subtitle_id,
                "original_text": i.original_text,
                "corrected_text": i.corrected_text,
                "changes": i.changes,
            }
            for i in issues
        ],
        "total_issues": len(issues),
    }


@router.post(
    "/{meeting_id}/subtitles/apply-grammar",
    summary="AI 문장 교정 적용",
)
async def apply_grammar_endpoint(
    meeting_id: str,
    corrections: list[dict] = Body(..., description="적용할 교정 목록 [{subtitle_id, corrected_text}]"),
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("admin")),
) -> dict:
    """AI 문장 검사 결과를 선택적으로 적용합니다. (admin 전용)"""
    updated = 0

    for correction in corrections:
        subtitle_id = correction.get("subtitle_id")
        corrected_text = correction.get("corrected_text")
        if not subtitle_id or not corrected_text:
            continue

        # 원본 조회
        original_result = (
            supabase.table("subtitles")
            .select("text")
            .eq("id", subtitle_id)
            .eq("meeting_id", meeting_id)
            .limit(1)
            .execute()
        )
        if not original_result.data:
            continue

        original_text = original_result.data[0]["text"]
        if original_text == corrected_text:
            continue

        # 이력 기록 + 업데이트
        record_changes_for_update(
            supabase, subtitle_id,
            {"text": original_text},
            {"text": corrected_text},
            "system:grammar",
        )
        supabase.table("subtitles").update({"text": corrected_text}).eq("id", subtitle_id).execute()
        updated += 1

    return {"updated": updated}


# =============================================================================
# Verification (대조관리) Endpoints (P7-T1.3)
# =============================================================================


# @TASK P7-T1.3 - 회의별 자막 검증 통계
# @SPEC docs/planning/08-feature-tasks.md
@router.get(
    "/{meeting_id}/subtitles/verification-stats",
    summary="회의별 자막 검증 통계",
)
async def get_subtitle_verification_stats(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
) -> dict:
    """회의별 자막 검증 통계를 조회합니다.

    verified / unverified / flagged 비율과 진행률을 반환합니다.
    """
    return get_verification_stats(supabase, meeting_id)


# @TASK P7-T1.3 - 미검증/저신뢰 자막 큐 조회
@router.get(
    "/{meeting_id}/subtitles/review-queue",
    summary="미검증/저신뢰 자막 큐 조회",
)
async def get_subtitle_review_queue(
    meeting_id: str,
    confidence_threshold: float = Query(0.7, ge=0.0, le=1.0),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    supabase: Client = Depends(get_supabase),
) -> dict:
    """미검증/저신뢰 자막 큐를 조회합니다.

    verification_status가 'verified'가 아닌 자막을 신뢰도 오름차순으로 반환합니다.
    """
    return get_review_queue(supabase, meeting_id, confidence_threshold, limit, offset)


# @TASK P7-T1.3 - 개별 자막 검증 상태 변경
@router.patch(
    "/{meeting_id}/subtitles/{subtitle_id}/verify",
    summary="개별 자막 검증 상태 변경",
)
async def verify_subtitle(
    meeting_id: str,
    subtitle_id: str,
    body: dict,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("stenographer", "admin")),
) -> dict:
    """개별 자막의 검증 상태를 변경합니다.

    body: { "status": "verified" | "flagged" | "unverified" }
    """
    status_val = body.get("status")
    if status_val not in ("verified", "flagged", "unverified"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="status must be 'verified', 'flagged', or 'unverified'",
        )
    result = update_verification_status(supabase, meeting_id, subtitle_id, status_val)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subtitle not found",
        )
    return result


# @TASK P7-T1.3 - 일괄 자막 검증
@router.post(
    "/{meeting_id}/subtitles/batch-verify",
    summary="일괄 자막 검증",
)
async def batch_verify_subtitles(
    meeting_id: str,
    body: dict,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("stenographer", "admin")),
) -> dict:
    """여러 자막의 검증 상태를 일괄 변경합니다.

    body: { "subtitle_ids": [...], "status": "verified" | "flagged" | "unverified" }
    """
    subtitle_ids = body.get("subtitle_ids", [])
    status_val = body.get("status", "verified")
    if not subtitle_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="subtitle_ids is required",
        )
    if status_val not in ("verified", "flagged", "unverified"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid status",
        )
    return batch_verify(supabase, meeting_id, subtitle_ids, status_val)


@router.get(
    "/{meeting_id}/subtitles/search",
    summary="자막 내 키워드 검색",
)
async def search_subtitles(
    meeting_id: str,
    q: Annotated[str, Query(min_length=1, description="검색어")],
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    supabase: Client = Depends(get_supabase),
) -> dict:
    """자막 내 키워드를 검색합니다."""
    search_term = q.strip()
    if not search_term:
        raise HTTPException(status_code=422, detail="검색어는 비어있을 수 없습니다")

    # 전체 개수
    count_result = (
        supabase.table("subtitles")
        .select("id", count="exact")
        .eq("meeting_id", meeting_id)
        .ilike("text", f"%{search_term}%")
        .execute()
    )
    total = count_result.count or 0

    # 검색 결과
    result = (
        supabase.table("subtitles")
        .select("*")
        .eq("meeting_id", meeting_id)
        .ilike("text", f"%{search_term}%")
        .order("start_time")
        .range(offset, offset + limit - 1)
        .execute()
    )

    return {
        "items": result.data,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# =============================================================================
# 교정 단어 자동 수집 유틸
# =============================================================================


def _collect_correction(supabase: Client, original_text: str, corrected_text: str) -> None:
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

    for wrong, correct in pairs:
        if len(wrong) < 2 or len(correct) < 2:
            continue
        try:
            supabase.table("dictionary").upsert(
                {
                    "wrong_text": wrong,
                    "correct_text": correct,
                    "category": "user_correction",
                },
                on_conflict="wrong_text",
            ).execute()
        except Exception as e:
            logger.debug("교정 수집 실패 (%s→%s): %s", wrong, correct, e)
