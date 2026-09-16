"""관리자 API - 외부 API 상태 대시보드

외부 서비스(OpenAI, Supabase, KMS, HLS 등)의
연결 상태와 호출 통계를 모니터링합니다.
"""

import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from app.core.auth_middleware import require_role
from app.core.config import settings
from app.core.database import get_supabase
from app.services import stt_batch_queue
from app.services.kms_bulk_matcher import (
    match_and_update as kms_match_and_update,
    regenerate_for_session as kms_regenerate_for_session,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# ApiCallTracker – in-memory singleton
# ---------------------------------------------------------------------------

class ApiCallTracker:
    """Tracks API call statistics with a 24-hour rolling window."""

    def __init__(self) -> None:
        self._calls: dict[str, list[dict]] = defaultdict(list)

    def record(self, api_name: str, latency_ms: float, success: bool) -> None:
        self._calls[api_name].append({
            "timestamp": datetime.now(timezone.utc),
            "latency_ms": latency_ms,
            "success": success,
        })
        # Prune entries older than 24h
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        self._calls[api_name] = [
            c for c in self._calls[api_name] if c["timestamp"] > cutoff
        ]

    def get_stats(self, api_name: str) -> dict:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        recent = [
            c for c in self._calls.get(api_name, []) if c["timestamp"] > cutoff
        ]
        if not recent:
            return {"calls_today": 0, "avg_latency_ms": 0, "error_rate": 0}
        total = len(recent)
        errors = sum(1 for c in recent if not c["success"])
        avg_lat = sum(c["latency_ms"] for c in recent) / total
        return {
            "calls_today": total,
            "avg_latency_ms": round(avg_lat, 1),
            "error_rate": round(errors / total * 100, 1),
        }


api_tracker = ApiCallTracker()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mask_key(key: str | None) -> str:
    """API 키를 마스킹하여 반환합니다."""
    if not key:
        return "미설정"
    if len(key) <= 10:
        return "****"
    return f"{key[:6]}...{key[-4:]}"


# ---------------------------------------------------------------------------
# GET /api/admin/api-status
# ---------------------------------------------------------------------------

@router.get("/api-status")
async def get_api_status() -> list[dict]:
    """외부 API 연결 상태 및 호출 통계를 반환합니다."""
    results: list[dict] = []

    # 1. OpenAI GPT
    openai_status = await _check_openai()
    results.append(openai_status)

    # 2. Supabase
    supabase_status = await _check_supabase()
    results.append(supabase_status)

    # 4. 경기도의회 KMS
    kms_status = await _check_kms()
    results.append(kms_status)

    # 5. 경기도의회 HLS
    hls_status = await _check_hls()
    results.append(hls_status)

    # 6. 경기도의회 의원정보 API
    councilor_status = _check_councilor_api()
    results.append(councilor_status)

    return results


async def _check_openai() -> dict:
    """OpenAI API 연결 상태를 확인합니다."""
    model_name = settings.openai_model
    masked_key = _mask_key(settings.openai_api_key)
    # 기능별 모델 — 공용(openai_model)만 보이면 AI 대화·요약이 무엇을 쓰는지 오해한다(2026-09-15 대화 모델 분리)
    per_feature = {
        "chat_model": settings.ai_chat_model,
        "summary_model": settings.summary_model,
        "summary_map_model": settings.summary_map_model,
        "agenda_model": settings.agenda_model,
    }

    if not settings.openai_api_key:
        return {
            "name": "OpenAI GPT",
            "description": "AI 문법 검사, 회의 요약, 자막 교정",
            "status": "not_configured",
            "details": {"model": model_name, "masked_key": masked_key, **per_feature},
            "stats": api_tracker.get_stats("openai"),
        }

    status = "unknown"
    details: dict = {"model": model_name, "masked_key": masked_key, **per_feature}

    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            )
        latency = (time.monotonic() - t0) * 1000
        if resp.status_code == 200:
            status = "connected"
            api_tracker.record("openai", latency, True)
        else:
            status = "disconnected"
            details["http_status"] = resp.status_code
            api_tracker.record("openai", latency, False)
    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        status = "disconnected"
        details["error"] = str(e)[:100]
        api_tracker.record("openai", latency, False)

    return {
        "name": "OpenAI GPT",
        "description": "AI 문법 검사, 회의 요약, 자막 교정",
        "status": status,
        "details": details,
        "stats": api_tracker.get_stats("openai"),
    }




async def _check_supabase() -> dict:
    """Supabase 연결 상태를 확인합니다."""
    supabase_url = settings.supabase_url

    if not supabase_url or not settings.supabase_key:
        return {
            "name": "Supabase",
            "description": "데이터베이스 (회의, 자막, 의안 등)",
            "status": "not_configured",
            "details": {"url": supabase_url or "미설정"},
            "stats": api_tracker.get_stats("supabase"),
        }

    status = "unknown"
    details: dict = {"url": supabase_url}

    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{supabase_url}/rest/v1/meetings?select=id&limit=1",
                headers={
                    "apikey": settings.supabase_key,
                    "Authorization": f"Bearer {settings.supabase_key}",
                },
            )
        latency = (time.monotonic() - t0) * 1000
        if resp.status_code in (200, 206):
            status = "connected"
            api_tracker.record("supabase", latency, True)
        else:
            status = "disconnected"
            details["http_status"] = resp.status_code
            api_tracker.record("supabase", latency, False)
    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        status = "disconnected"
        details["error"] = str(e)[:100]
        api_tracker.record("supabase", latency, False)

    return {
        "name": "Supabase",
        "description": "데이터베이스 (회의, 자막, 의안 등)",
        "status": status,
        "details": details,
        "stats": api_tracker.get_stats("supabase"),
    }


async def _check_kms() -> dict:
    """경기도의회 KMS 서버 상태를 확인합니다."""
    status = "unknown"
    details: dict = {"url": "https://kms.ggc.go.kr"}

    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.head("https://kms.ggc.go.kr")
        latency = (time.monotonic() - t0) * 1000
        if resp.status_code < 500:
            status = "connected"
            api_tracker.record("kms", latency, True)
        else:
            status = "disconnected"
            details["http_status"] = resp.status_code
            api_tracker.record("kms", latency, False)
    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        status = "disconnected"
        details["error"] = str(e)[:100]
        api_tracker.record("kms", latency, False)

    return {
        "name": "경기도의회 KMS",
        "description": "VOD 영상 저장소 (KMS → MP4 변환)",
        "status": status,
        "details": details,
        "stats": api_tracker.get_stats("kms"),
    }


async def _check_hls() -> dict:
    """경기도의회 HLS 스트리밍 채널 상태를 확인합니다."""
    from app.core.channels import CHANNELS

    active_channels = 0
    details: dict = {"total_channels": len(CHANNELS)}

    try:
        # 활성 라이브 STT 채널 수 확인 (OpenAI Realtime 엔진)
        from app.services.openai_realtime_stt import get_channel_stt_service
        svc = get_channel_stt_service()
        active_channels = len(svc.active_channels) if hasattr(svc, "active_channels") else 0
    except Exception:
        pass

    details["active_channels"] = active_channels

    return {
        "name": "경기도의회 HLS",
        "description": "실시간 방송 스트리밍 (18개 채널)",
        "status": "connected" if active_channels > 0 else "unknown",
        "details": details,
        "stats": api_tracker.get_stats("hls"),
    }


def _check_councilor_api() -> dict:
    """경기도의회 의원정보 API 상태를 확인합니다."""
    return {
        "name": "경기도의회 의원정보",
        "description": "의원 프로필 및 소속 정보 동기화",
        "status": "unknown",
        "details": {"note": "정적 데이터 기반 (자동 동기화 미구현)"},
        "stats": api_tracker.get_stats("councilor_api"),
    }


# ---------------------------------------------------------------------------
# 사용자 관리 (admin only)
# ---------------------------------------------------------------------------

VALID_ROLES = ["staff", "committee_staff", "meeting_manager", "stenographer", "admin"]


@router.get("/users")
async def list_users(
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("admin")),
) -> list[dict]:
    """전체 사용자 목록을 반환합니다."""
    result = supabase.table("users").select(
        "id,username,display_name,role,assigned_committee,is_active,last_login_at,created_at"
    ).order("created_at").execute()
    return result.data or []


@router.post("/users", status_code=201)
async def create_user(
    body: dict,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("admin")),
) -> dict:
    """새 사용자를 생성합니다."""
    # 비밀번호는 받지 않는다 — 아이디·비밀번호 로그인을 없앴으므로(2026-08-28)
    # 여기서 해시를 만들어 봐야 아무 데서도 쓰이지 않는 개인정보만 쌓인다.
    # 이 API 가 만드는 것은 자격증명이 아니라 **권한을 미리 얹은 자리**다 —
    # username 은 의정포털 usercode 와 같아야 QR 로그인이 이 행을 찾는다.
    username = body.get("username", "").strip()
    display_name = body.get("display_name", "").strip()
    role = body.get("role", "staff")
    assigned_committee = body.get("assigned_committee")

    if not username or not display_name:
        raise HTTPException(status_code=422, detail="username, display_name은 필수입니다.")
    if role not in VALID_ROLES:
        raise HTTPException(status_code=422, detail=f"유효하지 않은 역할입니다: {role}")

    existing = supabase.table("users").select("id").eq("username", username).execute()
    if existing.data:
        raise HTTPException(status_code=409, detail="이미 존재하는 사용자명입니다.")

    user_data = {
        "username": username,
        "display_name": display_name,
        "role": role,
        "assigned_committee": assigned_committee,
    }
    result = supabase.table("users").insert(user_data).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="사용자 생성에 실패했습니다.")

    created = result.data[0]
    created.pop("password_hash", None)
    return created


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    body: dict,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("admin")),
) -> dict:
    """사용자 정보를 수정합니다."""
    updates: dict = {}
    if "display_name" in body:
        updates["display_name"] = body["display_name"]
    if "role" in body:
        if body["role"] not in VALID_ROLES:
            raise HTTPException(status_code=422, detail=f"유효하지 않은 역할: {body['role']}")
        updates["role"] = body["role"]
    if "assigned_committee" in body:
        updates["assigned_committee"] = body["assigned_committee"]
    if "is_active" in body:
        updates["is_active"] = body["is_active"]
    if not updates:
        raise HTTPException(status_code=422, detail="수정할 항목이 없습니다.")

    result = supabase.table("users").update(updates).eq("id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    updated = result.data[0]
    updated.pop("password_hash", None)
    return updated


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    supabase: Client = Depends(get_supabase),
    current_user: dict = Depends(require_role("admin")),
) -> dict:
    """사용자를 삭제합니다."""
    if current_user["id"] == user_id:
        raise HTTPException(status_code=400, detail="자기 자신은 삭제할 수 없습니다.")

    result = supabase.table("users").delete().eq("id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    return {"message": "삭제되었습니다."}


# ---------------------------------------------------------------------------
# VOD 일괄 매칭 (admin 전용)
# ---------------------------------------------------------------------------


@router.post("/vod-bulk-match")
async def vod_bulk_match(
    regenerate: bool = False,
    regenerate_existing: bool = False,
    session: int | None = None,
    pages: int = 3,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("admin")),
) -> dict:
    """KMS 최근회의영상 크롤 → 미등록 회의 VOD URL 자동 매칭(등록).

    ★기본 동작은 '등록만'이다 (regenerate=False). 과거 기본값(True)은 버튼 1회
    클릭으로 다수 회의의 유료 STT+LLM 교정이 자동 실행되어 비용이 폭증했고,
    사용자도 '등록'과 'AI 자막 생성'이 섞여 혼란스러워했다.
    AI 자막 생성은 /vod 목록에서 회의를 체크해 명시적으로 실행한다
    (POST /api/meetings/{id}/stt).

    옵션 (명시적으로 켤 때만):
    - regenerate=True: 신규 매칭 건의 자막을 VOD STT로 재생성
    - regenerate_existing=True: 이미 vod_url 있는 session/오늘 회의도 강제 재생성
    - pages: KMS 목록 페이지 수(페이지당 15건, 기본 3 — 병행 회기 커버, 최대 6)

    반환: kms_entries, pending, matched_count, unmatched_count, errors,
         regeneration_started, existing_regenerated
    """
    try:
        result = await kms_match_and_update(
            supabase, regenerate_subtitles=regenerate, pages=max(1, min(pages, 6))
        )
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))

    if regenerate and regenerate_existing:
        try:
            regen = await kms_regenerate_for_session(
                supabase, session_number=session, include_today=True
            )
            result["existing_regenerated"] = regen.get("targets_count", 0)
            result["existing_targets"] = regen.get("targets", [])
            # 기존이든 신규든 하나라도 시작되면 True로 보정
            if regen.get("regeneration_started"):
                result["regeneration_started"] = True
        except Exception as e:
            logger.exception("vod-bulk-match: regenerate_existing failed: %s", e)
            result["existing_regenerated"] = 0
            result.setdefault("errors", []).append(
                {"error": f"regenerate_existing_failed: {e}"}
            )
    else:
        result["existing_regenerated"] = 0

    return result


@router.post("/vod-auto-stt/run")
async def vod_auto_stt_run(
    dry_run: bool = False,
    _user: dict = Depends(require_role("admin")),
) -> dict:
    """VOD 자동 등록 → AI 자막 자동 생성을 지금 1회 실행한다.

    다음 등록 주기(30분)까지 기다리지 않고 검증할 때 쓴다. 하루 상한·오늘 시도한 회의 제외는
    자동 실행과 같다. dry_run=true 면 등록·생성 없이 **대상 목록만** 돌려준다(비용 0).
    실제 실행은 백그라운드로 돌고, 결과는 GET /api/admin/vod-auto-stt/status 와
    알림(type=vod_auto_stt, 생성했을 때만)으로 남는다.
    """
    import asyncio as _asyncio

    from app.core.database import get_supabase_client
    from app.services.vod_auto_stt import run_once

    if dry_run:
        return await run_once(get_supabase_client, dry_run=True)
    if stt_batch_queue.is_running():
        raise HTTPException(status_code=409, detail="이미 일괄 생성이 진행 중입니다.")
    _asyncio.create_task(run_once(get_supabase_client), name="vod-auto-stt-manual")
    return {"status": "started"}


@router.get("/vod-auto-stt/status")
async def vod_auto_stt_status(_user: dict = Depends(require_role("admin"))) -> dict:
    """AI 자막 자동 생성 설정 + 오늘 장부 + 마지막 실행 요약 + 현재 배치 큐 상태."""
    from app.services.vod_auto_stt import ledger_status

    return {
        "enabled": settings.vod_auto_stt_enabled,
        "trigger": "VOD 자동 등록 직후",
        "interval_minutes": settings.kms_auto_register_interval_minutes,
        "daily_limit": settings.vod_auto_stt_daily_limit,
        "max_age_days": settings.vod_auto_stt_max_age_days,
        "today": ledger_status(),
        "queue": stt_batch_queue.status(),
    }


@router.post("/vod-regenerate-session")
async def vod_regenerate_session(
    session: int | None = 389,
    include_today: bool = True,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("admin")),
) -> dict:
    """이미 vod_url이 있는 현재 세션/오늘 회의들의 자막을 **강제 재생성**.

    실시간 STT로 드리프트된 자막을 VOD 타임라인 기준으로 재생성 + AI 교정.
    백그라운드 순차 처리 (회의당 약 10분).

    쿼리: session (기본 389), include_today (기본 true)
    반환: targets_count, targets[], regeneration_started
    """
    result = await kms_regenerate_for_session(
        supabase, session_number=session, include_today=include_today
    )
    return result


# ---------------------------------------------------------------------------
# API 사용량·비용 추정 대시보드
# ---------------------------------------------------------------------------

# 단가(시간당 USD) — 실측 기반 추정치 (정확한 과금은 OpenAI 대시보드 참조):
#   생중계: gpt-4o-transcribe 윈도우 전사(~$0.36) + 글로서리 프롬프트 + 교정 미니모델 ≈ $0.6/h
#   AI 자막(VOD): gpt-4o-transcribe-diarize 배치(600초 청크) ≈ $0.4/h
_LIVE_COST_PER_HOUR_USD = 0.6
_VOD_COST_PER_HOUR_USD = 0.4
_DEFAULT_USD_KRW = 1450

_COMMITTEE_RE = None  # lazy compile


def _committee_of(meeting: dict) -> str:
    """meeting의 위원회명 — committee 컬럼 우선, 없으면 제목에서 추출."""
    global _COMMITTEE_RE
    if meeting.get("committee"):
        return str(meeting["committee"])
    if _COMMITTEE_RE is None:
        import re
        _COMMITTEE_RE = re.compile(r"([가-힣A-Za-z·]+위원회|본회의)")
    m = _COMMITTEE_RE.search(meeting.get("title") or "")
    return m.group(1) if m else "기타"


@router.get("/usage-costs")
async def get_usage_costs(
    days: int = 30,
    usd_krw: int = _DEFAULT_USD_KRW,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("admin")),
) -> dict:
    """위원회별 STT 사용량·비용 추정 (원화).

    ★실측 과금이 아니라 '오디오 시간 × 단가' 추정치다.
      생중계 판정: channel_id 보유 (AutoSTT가 생성한 회의)
      AI 자막 판정: subtitle_stage ∈ (ai, reviewing, final) — VOD 재전사 실행됨
      오디오 시간: duration_seconds, 없으면 자막 최대 end_time
    한 회의가 생중계 후 AI 자막까지 생성되면 두 비용이 모두 잡힌다 (실제로 2회 전사).
    """
    days = max(1, min(days, 120))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    res = (
        supabase.table("meetings")
        .select("id,title,committee,channel_id,duration_seconds,subtitle_stage,meeting_date,status")
        .gte("meeting_date", since)
        .order("meeting_date", desc=True)
        .limit(400)
        .execute()
    )
    meetings = res.data or []

    def minutes_of(m: dict) -> float:
        dur = m.get("duration_seconds")
        if dur and dur > 0:
            return float(dur) / 60.0
        # 폴백: 자막 마지막 end_time (생중계 회의는 duration이 비어 있음)
        try:
            r = (
                supabase.table("subtitles")
                .select("end_time")
                .eq("meeting_id", m["id"])
                .order("end_time", desc=True)
                .limit(1)
                .execute()
            )
            if r.data:
                return float(r.data[0]["end_time"]) / 60.0
        except Exception:
            pass
        return 0.0

    AI_STAGES = {"ai", "reviewing", "final"}
    by_committee: dict[str, dict] = {}
    totals = {
        "live_minutes": 0.0, "vod_minutes": 0.0,
        "live_cost_usd": 0.0, "vod_cost_usd": 0.0,
        "live_api_calls_est": 0, "vod_api_calls_est": 0,
        "meetings": 0,
    }

    for m in meetings:
        is_live = bool(m.get("channel_id"))
        is_vod_ai = (m.get("subtitle_stage") or "") in AI_STAGES
        if not is_live and not is_vod_ai:
            continue
        mins = minutes_of(m)
        if mins <= 0:
            continue
        comm = _committee_of(m)
        row = by_committee.setdefault(comm, {
            "committee": comm,
            "live_minutes": 0.0, "vod_minutes": 0.0,
            "live_cost_usd": 0.0, "vod_cost_usd": 0.0,
            "live_api_calls_est": 0, "vod_api_calls_est": 0,
            "meetings": 0,
        })
        row["meetings"] += 1
        totals["meetings"] += 1
        if is_live:
            cost = mins / 60.0 * _LIVE_COST_PER_HOUR_USD
            calls = int(mins * 6)  # 평균 ~10초 윈도우 → 분당 ~6회 전사 호출
            row["live_minutes"] += mins
            row["live_cost_usd"] += cost
            row["live_api_calls_est"] += calls
            totals["live_minutes"] += mins
            totals["live_cost_usd"] += cost
            totals["live_api_calls_est"] += calls
        if is_vod_ai:
            cost = mins / 60.0 * _VOD_COST_PER_HOUR_USD
            calls = max(1, int(mins / 10))  # 600초(10분) 청크당 1회 전사 호출
            row["vod_minutes"] += mins
            row["vod_cost_usd"] += cost
            row["vod_api_calls_est"] += calls
            totals["vod_minutes"] += mins
            totals["vod_cost_usd"] += cost
            totals["vod_api_calls_est"] += calls

    def finalize(row: dict) -> dict:
        out = dict(row)
        out["live_minutes"] = round(row["live_minutes"], 1)
        out["vod_minutes"] = round(row["vod_minutes"], 1)
        out["live_cost_krw"] = int(row["live_cost_usd"] * usd_krw)
        out["vod_cost_krw"] = int(row["vod_cost_usd"] * usd_krw)
        out["total_cost_krw"] = out["live_cost_krw"] + out["vod_cost_krw"]
        out["live_cost_usd"] = round(row["live_cost_usd"], 2)
        out["vod_cost_usd"] = round(row["vod_cost_usd"], 2)
        return out

    rows = sorted(
        (finalize(r) for r in by_committee.values()),
        key=lambda r: r["total_cost_krw"],
        reverse=True,
    )
    return {
        "period_days": days,
        "since": since,
        "usd_krw": usd_krw,
        "rates": {
            "live_per_hour_usd": _LIVE_COST_PER_HOUR_USD,
            "vod_per_hour_usd": _VOD_COST_PER_HOUR_USD,
        },
        "committees": rows,
        "totals": finalize(totals),
        "note": "오디오 시간 × 단가 추정치입니다. 정확한 청구액은 OpenAI 대시보드를 확인하세요.",
    }
