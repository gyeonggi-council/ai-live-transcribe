"""Statistics & Report API 라우터

# @TASK P11-T2.1 - 통계 API
# @TASK P11-T4.1 - 리포트 생성 API
# @SPEC docs/planning/02-trd.md#통계

통계 대시보드 및 리포트 생성을 위한 엔드포인트를 제공합니다.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from supabase import Client

from app.core.auth_middleware import optional_auth
from app.core.council_network import is_council, site_label_of
from app.core.database import get_supabase
from app.services import access_stats_service as access_stats

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stats", tags=["stats"])


# =============================================================================
# 접속자 수 (site_visits) - 오늘 / 누적
# 방문 1건당 1행(insert-only) → 경쟁 조건 없음.
# 프론트가 localStorage로 브라우저당 하루 1회만 POST 하므로 1행 = 방문자 1명.
# =============================================================================


# 한국 표준시(KST, UTC+9, DST 없음). 서버 OS 시간대(UTC 등)와 무관하게
# "오늘"을 항상 한국 날짜 기준으로 집계한다.
KST = timezone(timedelta(hours=9))


def seoul_today() -> str:
    """한국(KST) 기준 오늘 날짜 ISO 문자열(YYYY-MM-DD)."""
    return datetime.now(KST).date().isoformat()


def _read_visit_counts(supabase: Client) -> dict:
    """오늘/누적 접속자 수를 집계합니다. (테이블 미생성 시 0으로 우아하게 처리)"""
    today_str = seoul_today()
    try:
        today_res = (
            supabase.table("site_visits")
            .select("id", count="exact")
            .eq("visited_on", today_str)
            .execute()
        )
        today = today_res.count or 0
    except Exception:
        logger.warning("site_visits 오늘 집계 실패 (마이그레이션 021 미적용?)", exc_info=True)
        today = 0
    try:
        total_res = (
            supabase.table("site_visits").select("id", count="exact").execute()
        )
        total = total_res.count or 0
    except Exception:
        logger.warning("site_visits 누적 집계 실패 (마이그레이션 021 미적용?)", exc_info=True)
        total = 0
    return {"today": today, "total": total}


@router.get("/visits", summary="접속자 수 조회 (오늘/누적)")
async def get_visits(supabase: Client = Depends(get_supabase)) -> dict:
    """오늘/누적 접속자 수를 반환합니다. (집계만, 증가 없음)"""
    return _read_visit_counts(supabase)


@router.post("/visit", summary="접속 기록 (방문자 +1)")
async def record_visit(supabase: Client = Depends(get_supabase)) -> dict:
    """방문 1건을 기록하고 갱신된 접속자 수를 반환합니다.

    프론트엔드가 브라우저당 하루 1회만 호출합니다 (localStorage 중복 제거).
    개인정보(IP 등)는 저장하지 않습니다.
    """
    try:
        supabase.table("site_visits").insert(
            {"visited_on": seoul_today()}
        ).execute()
    except Exception:
        logger.warning("site_visits insert 실패 (마이그레이션 021 미적용?)", exc_info=True)
    return _read_visit_counts(supabase)


# =============================================================================
# 접속 통계 (access_events) — 접속처·화면·시청 시간  ★2026-09-16 담당자 요청
# IP 는 저장하지 않는다: 여기서 접속처 '이름' 으로 바꾼 뒤 서비스에 넘긴다.
# 화면(/visits)이 비로그인에게도 열려 있어야 해서(담당자 결정) 인증을 걸지 않는다 —
# 대신 개인을 가리키는 값을 애초에 저장하지 않고, 서비스가 중복·시간당 상한으로 막는다.
# =============================================================================


class AccessEventIn(BaseModel):
    """프런트가 보내는 접속 기록 한 건. 개인정보는 담기지 않는다."""

    kind: str
    meeting_id: Optional[str] = None
    visitor_key: Optional[str] = None
    path: Optional[str] = None


@router.post("/access", summary="접속 기록 (IP 미저장)")
async def record_access(
    payload: AccessEventIn,
    request: Request,
    user: Optional[dict] = Depends(optional_auth),
    supabase: Client = Depends(get_supabase),
) -> dict:
    """접속·시청 신호 1건을 기록합니다. 실패해도 화면이 죽지 않도록 항상 200 을 돌려줍니다."""
    detail: dict = {}
    if payload.path:
        detail["path"] = payload.path[:120]

    meeting_id = None
    if payload.meeting_id:
        try:
            meeting_id = str(uuid.UUID(payload.meeting_id))
        except (ValueError, AttributeError, TypeError):
            detail["channel"] = str(payload.meeting_id)[:20]  # ch60 같은 채널 ID

    role = (user or {}).get("role") or ("council_guest" if is_council(request) else "anonymous")
    saved = access_stats.record_event(
        supabase,
        kind=payload.kind,
        site_label=site_label_of(request),
        visitor_key=(payload.visitor_key or "")[:40] or None,
        device=access_stats.device_of(request.headers.get("user-agent", "")),
        role=role,
        meeting_id=meeting_id,
        detail=detail or None,
    )
    return {"recorded": saved}


@router.get("/access", summary="접속 통계 (접속처·시간대·회의·기능)")
async def get_access_stats(
    days: int = Query(30, ge=1, le=365, description="집계 기간(일)"),
    site: Optional[str] = Query(None, description="접속처 이름 — 주면 그 접속처만(드릴다운)"),
    supabase: Client = Depends(get_supabase),
) -> dict:
    return access_stats.build_stats(supabase, days, site)


# =============================================================================
# GET /api/stats/overview - 전체 현황 통계
# @TASK P11-T2.1 - 통계 개요
# =============================================================================


@router.get(
    "/overview",
    summary="전체 현황 통계",
)
async def get_overview(
    supabase: Client = Depends(get_supabase),
) -> dict:
    """전체 회의, 자막, 재생시간 통계를 반환합니다.

    - total_meetings: 등록된 회의 수
    - total_subtitles: 전체 자막 수
    - total_duration_seconds: 전체 회의 시간 합계 (초)
    - avg_confidence: 자막 평균 신뢰도
    """
    # 회의 통계
    try:
        meetings_result = (
            supabase.table("meetings")
            .select("id, duration_seconds", count="exact")
            .execute()
        )
        total_meetings = meetings_result.count or 0
        meetings_data = meetings_result.data or []
        total_duration = sum(
            m.get("duration_seconds") or 0 for m in meetings_data
        )
    except Exception:
        total_meetings = 0
        total_duration = 0

    # 자막 통계
    try:
        subtitles_result = (
            supabase.table("subtitles")
            .select("id, confidence", count="exact")
            .execute()
        )
        total_subtitles = subtitles_result.count or 0
        subtitles_data = subtitles_result.data or []
        confidences = [
            s["confidence"]
            for s in subtitles_data
            if s.get("confidence") is not None
        ]
        avg_confidence = (
            round(sum(confidences) / len(confidences), 4) if confidences else 0.0
        )
    except Exception:
        total_subtitles = 0
        avg_confidence = 0.0

    return {
        "total_meetings": total_meetings,
        "total_subtitles": total_subtitles,
        "total_duration_seconds": total_duration,
        "avg_confidence": avg_confidence,
    }


# =============================================================================
# GET /api/stats/speakers - 화자별 통계
# @TASK P11-T2.1 - 화자별 통계
# =============================================================================


@router.get(
    "/speakers",
    summary="화자별 발언 통계",
)
async def get_speaker_stats(
    supabase: Client = Depends(get_supabase),
) -> list[dict]:
    """화자별 총 발언 세그먼트 수, 발언 시간, 참여 회의 수를 반환합니다."""
    try:
        result = (
            supabase.table("subtitles")
            .select("speaker, start_time, end_time, meeting_id")
            .execute()
        )
        rows = result.data or []
    except Exception:
        return []

    if not rows:
        return []

    # 화자별 집계
    speakers_map: dict[str, dict] = {}
    for row in rows:
        speaker = row.get("speaker") or "(미지정)"
        if speaker not in speakers_map:
            speakers_map[speaker] = {
                "speaker": speaker,
                "total_segments": 0,
                "total_duration": 0.0,
                "meeting_ids": set(),
            }
        speakers_map[speaker]["total_segments"] += 1
        start = row.get("start_time") or 0.0
        end = row.get("end_time") or 0.0
        speakers_map[speaker]["total_duration"] += max(0, end - start)
        meeting_id = row.get("meeting_id")
        if meeting_id:
            speakers_map[speaker]["meeting_ids"].add(meeting_id)

    # set -> count 변환 후 정렬
    result_list = []
    for info in speakers_map.values():
        result_list.append({
            "speaker": info["speaker"],
            "total_segments": info["total_segments"],
            "total_duration": round(info["total_duration"], 2),
            "meeting_count": len(info["meeting_ids"]),
        })

    result_list.sort(key=lambda x: x["total_segments"], reverse=True)
    return result_list


# =============================================================================
# GET /api/stats/meetings - 월별 회의 통계
# @TASK P11-T2.1 - 월별 회의 통계
# =============================================================================


@router.get(
    "/meetings",
    summary="월별 회의 통계",
)
async def get_meeting_stats(
    supabase: Client = Depends(get_supabase),
) -> list[dict]:
    """월별 회의 수와 총 재생 시간을 반환합니다."""
    try:
        result = (
            supabase.table("meetings")
            .select("meeting_date, duration_seconds")
            .order("meeting_date")
            .execute()
        )
        rows = result.data or []
    except Exception:
        return []

    if not rows:
        return []

    # 월별 집계
    monthly: dict[str, dict] = {}
    for row in rows:
        meeting_date = row.get("meeting_date", "")
        if not meeting_date:
            continue
        # meeting_date format: "YYYY-MM-DD"
        month = meeting_date[:7]  # "YYYY-MM"
        if month not in monthly:
            monthly[month] = {"month": month, "count": 0, "total_duration": 0}
        monthly[month]["count"] += 1
        monthly[month]["total_duration"] += row.get("duration_seconds") or 0

    # 월 순서로 정렬
    return sorted(monthly.values(), key=lambda x: x["month"])


# =============================================================================
# GET /api/stats/report - 기간별 리포트
# @TASK P11-T4.1 - 리포트 생성 API
# =============================================================================


@router.get(
    "/report",
    summary="기간별 리포트 생성",
)
async def generate_report(
    date_from: str = Query(..., description="시작 날짜 (YYYY-MM-DD)"),
    date_to: str = Query(..., description="종료 날짜 (YYYY-MM-DD)"),
    format: str = Query("markdown", description="출력 형식 (markdown|json)"),
    supabase: Client = Depends(get_supabase),
):
    """기간 내 회의, 화자, 자막 통계를 리포트로 생성합니다.

    - format=markdown: Markdown 텍스트 반환 (text/markdown)
    - format=json: JSON 반환
    """
    # 1. 기간 내 회의 목록 조회
    try:
        meetings_result = (
            supabase.table("meetings")
            .select("*")
            .gte("meeting_date", date_from)
            .lte("meeting_date", date_to)
            .order("meeting_date")
            .execute()
        )
        meetings = meetings_result.data or []
    except Exception:
        meetings = []

    meeting_ids = [m["id"] for m in meetings if m.get("id")]

    # 2. 해당 회의의 자막 조회
    subtitles: list[dict] = []
    if meeting_ids:
        try:
            for mid in meeting_ids:
                sub_result = (
                    supabase.table("subtitles")
                    .select("speaker, start_time, end_time, confidence, meeting_id")
                    .eq("meeting_id", mid)
                    .execute()
                )
                subtitles.extend(sub_result.data or [])
        except Exception:
            pass

    # 3. 화자별 통계
    speaker_stats: dict[str, dict] = {}
    for sub in subtitles:
        speaker = sub.get("speaker") or "(미지정)"
        if speaker not in speaker_stats:
            speaker_stats[speaker] = {"segments": 0, "duration": 0.0}
        speaker_stats[speaker]["segments"] += 1
        start = sub.get("start_time") or 0.0
        end = sub.get("end_time") or 0.0
        speaker_stats[speaker]["duration"] += max(0, end - start)

    # 4. 자막 처리 현황
    total_subtitles = len(subtitles)
    confidences = [
        s["confidence"] for s in subtitles if s.get("confidence") is not None
    ]
    avg_confidence = (
        round(sum(confidences) / len(confidences), 4) if confidences else 0.0
    )

    # 5. 총 회의 시간
    total_duration = sum(m.get("duration_seconds") or 0 for m in meetings)

    report_data = {
        "period": {"from": date_from, "to": date_to},
        "meetings_count": len(meetings),
        "meetings": [
            {
                "title": m.get("title", ""),
                "date": m.get("meeting_date", ""),
                "status": m.get("status", ""),
                "duration_seconds": m.get("duration_seconds"),
            }
            for m in meetings
        ],
        "total_duration_seconds": total_duration,
        "total_subtitles": total_subtitles,
        "avg_confidence": avg_confidence,
        "speaker_stats": [
            {
                "speaker": speaker,
                "segments": info["segments"],
                "duration": round(info["duration"], 2),
            }
            for speaker, info in sorted(
                speaker_stats.items(), key=lambda x: x[1]["segments"], reverse=True
            )
        ],
    }

    if format == "json":
        return report_data

    # Markdown 리포트 생성
    md = _build_markdown_report(report_data)
    return PlainTextResponse(content=md, media_type="text/markdown")


def _build_markdown_report(data: dict) -> str:
    """리포트 데이터를 Markdown 형식으로 변환합니다."""
    lines = [
        f"# 회의 리포트 ({data['period']['from']} ~ {data['period']['to']})",
        "",
        "## 개요",
        "",
        f"- 총 회의 수: {data['meetings_count']}건",
        f"- 총 회의 시간: {data['total_duration_seconds']}초",
        f"- 총 자막 수: {data['total_subtitles']}건",
        f"- 평균 자막 신뢰도: {data['avg_confidence']}",
        "",
    ]

    if data["meetings"]:
        lines.append("## 회의 목록")
        lines.append("")
        lines.append("| 제목 | 날짜 | 상태 | 시간(초) |")
        lines.append("|------|------|------|----------|")
        for m in data["meetings"]:
            duration = m.get("duration_seconds") or "-"
            lines.append(f"| {m['title']} | {m['date']} | {m['status']} | {duration} |")
        lines.append("")

    if data["speaker_stats"]:
        lines.append("## 화자별 발언 통계")
        lines.append("")
        lines.append("| 화자 | 발언 수 | 발언 시간(초) |")
        lines.append("|------|---------|---------------|")
        for s in data["speaker_stats"]:
            lines.append(f"| {s['speaker']} | {s['segments']} | {s['duration']} |")
        lines.append("")

    return "\n".join(lines)
