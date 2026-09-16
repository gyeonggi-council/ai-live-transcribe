"""Meetings API 라우터 (Supabase REST)

meetings 테이블이 없으면 channels 정적 데이터로 폴백합니다.
"""

import asyncio
import json
import logging
import re
import tempfile
import uuid as _uuid_mod
from datetime import date, datetime, timezone
from pathlib import Path as _Path
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, status
from supabase import Client

from app.core.config import settings as app_settings

from app.core.auth_middleware import AI_ROLES, optional_auth, require_role, require_role_or_council

# 2026-09-12 — 로그인 없이 바꿀 수 있던 쓰기 API 를 역할로 막는다.
# 회의록 상태·확정 이력: 회의록을 실제로 확정하는 사람만("final" 은 잠금이다)
_TRANSCRIPT_ROLES = ("meeting_manager", "stenographer", "admin")
# 참석자·안건 편집: 회의록 화면을 쓰는 직원
_MEETING_EDIT_ROLES = ("committee_staff", "meeting_manager", "stenographer", "admin")
from app.core.channels import get_all_channels, get_channel, get_committee_for_channel
from app.core.database import get_supabase
from app.schemas.meeting import (
    AgendaCreate,
    AgendaUpdate,
    MeetingCreate,
    MeetingFromUrl,
    MeetingStatus,
    MeetingUpdate,
    ParticipantCreate,
    PublicationCreate,
    TranscriptStatusUpdate,
)
from app.api.notifications import create_notification_record
from app.services.kms_vod_resolver import (
    is_allowed_vod_source,
    is_kms_vod_url,
    resolve_kms_vod_url,
    resolve_kms_vod_metadata,
)
from app.services import meeting_clock
from app.services.summary_service import (
    SummaryGenerationError,
    SummaryLimitError,
    delete_summary,
    generate_meeting_summary,
    get_summary,
)
from app.services.vod_stt_service import (
    VodSttService,
    get_task_by_meeting,
    is_processing,
)
from app.services.kms_bulk_matcher import (
    _match_meeting_to_entry,
    _regenerate_pipeline,
    fetch_recent_vod_list,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


# ─── AI 자막 일괄 생성 큐 (서버 측 순차 처리) ────────────────────────────────
# 브라우저가 큐를 돌리면 페이지를 닫는 순간 다음 회의가 시작되지 않는다.
# 큐를 서버 백그라운드 태스크로 옮겨 '한 번 요청하면 떠나도 끝까지 처리'를 보장.
# 상태는 인메모리(재시작 시 소멸 — 잔여분은 다시 요청).
# ★큐 본체는 services/stt_batch_queue 로 옮겼다(2026-09-03) — VOD 등록 직후 자동 생성
#   (services/vod_auto_stt)과 이 버튼이 같은 "배치 1개" 가드를 쓰기 위해서다.

from pydantic import BaseModel as _BaseModel

from app.services import stt_batch_queue as _batch_queue


class SttBatchRequest(_BaseModel):
    meeting_ids: list[str]


@router.post("/stt-batch")
async def start_stt_batch(
    body: SttBatchRequest,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("admin", "meeting_manager")),
) -> dict:
    """선택한 회의들의 AI 자막을 서버에서 순차 생성한다 (페이지를 닫아도 계속).

    동시에 1개 배치만 허용 — 진행 중이면 409 (자동 생성 배치가 도는 중이어도 같다).
    """
    ids = list(dict.fromkeys(body.meeting_ids))  # 중복 제거, 순서 유지
    if not ids:
        raise HTTPException(status_code=400, detail="대상 회의가 없습니다.")
    from app.core.database import get_supabase_client
    if not _batch_queue.start_batch(ids, get_supabase_client, source="manual"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 일괄 생성이 진행 중입니다. 완료 후 다시 시도해주세요.",
        )
    return {"status": "started", "total": len(ids)}


@router.get("/stt-batch/status")
async def get_stt_batch_status() -> dict:
    """일괄 생성 진행 상태 (모든 시청 페이지가 동일하게 조회 가능).

    current_progress: 처리 중인 회의의 세부 진행률(0~1)과 단계 메시지
    ("VOD 다운로드", "OpenAI 전사 3/8 청크", "자막 저장 중" 등) —
    VodSttService 인메모리 태스크에서 그대로 노출한다.
    source: manual(버튼) | auto(VOD 등록 직후 자동). last_auto_run: 마지막 자동 실행 요약.
    """
    st = _batch_queue.status()
    progress = None
    current = st["current"]
    if current:
        t = get_task_by_meeting(current)
        if t:
            progress = {
                "progress": round(t.progress, 3),
                "message": t.message,
                "status": t.status,
            }
    st["current_progress"] = progress
    return st


def _channel_to_meeting(ch: dict, meeting_status: str = "live") -> dict:
    """채널 정보를 meeting 형식으로 변환합니다."""
    return {
        "id": ch["id"],
        "title": ch["name"],
        "meeting_date": date.today().isoformat(),
        "stream_url": ch["stream_url"],
        "vod_url": None,
        "status": meeting_status,
        "duration_seconds": None,
        "committee": ch.get("committee"),
        "created_at": None,
        "updated_at": None,
    }


# =============================================================================
# Service Functions (Supabase REST + 채널 폴백)
# =============================================================================


def get_meetings_service(
    supabase: Client,
    statuses: Optional[list[MeetingStatus]] = None,
    limit: int = 10,
    offset: int = 0,
) -> list[dict]:
    """회의 목록을 조회합니다. meetings 테이블 없으면 채널 데이터 반환."""
    try:
        query = supabase.table("meetings").select("*")
        if statuses:
            status_values = [s.value for s in statuses]
            query = query.in_("status", status_values)
        query = query.order("meeting_date", desc=True)
        query = query.range(offset, offset + limit - 1)
        result = query.execute()
        return result.data
    except Exception:
        # meetings 테이블이 없으면 채널 데이터로 폴백
        channels = get_all_channels()
        meetings = [_channel_to_meeting(ch) for ch in channels]
        if statuses:
            status_values = [s.value for s in statuses]
            meetings = [m for m in meetings if m["status"] in status_values]
        return meetings[offset:offset + limit]


def get_live_meeting_service(
    supabase: Client,
    channel: Optional[str] = None,
) -> Optional[dict]:
    """실시간 회의를 조회합니다.

    channel이 지정된 경우 우선순위:
    1. DB에 해당 channel_id + status='live'인 meeting 레코드 (실제 방송 중)
    2. DB에 해당 channel_id + status='ended' 중 가장 최근 회의 (오늘 방송 종료 후 자막 조회용)
    3. 채널 정적 정보 스텁 (DB에 아무 레코드도 없을 때만)

    프론트 `/live?channel=chX` 페이지는 방송 종료 후에도 쌓인 자막을 열람하도록 이 폴백을 활용.
    """
    if channel:
        # 1) 현재 방송 중 meeting
        try:
            result = (
                supabase.table("meetings")
                .select("*")
                .eq("channel_id", channel)
                .eq("status", "live")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if result.data:
                return result.data[0]
        except Exception as e:
            logger.warning("get_live_meeting: DB(live) 조회 실패 (%s)", e)

        # 2) 가장 최근 ended meeting (오늘 방송 종료된 회의 자막 열람)
        try:
            result = (
                supabase.table("meetings")
                .select("*")
                .eq("channel_id", channel)
                .in_("status", ["ended", "processing"])
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if result.data:
                return result.data[0]
        except Exception as e:
            logger.warning("get_live_meeting: DB(ended) 조회 실패 (%s)", e)

        # 3) 폴백: 채널 정적 정보 기반 meeting 스텁
        ch = get_channel(channel)
        if ch:
            return _channel_to_meeting(ch)
        return None

    try:
        result = (
            supabase.table("meetings")
            .select("*")
            .eq("status", "live")
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception:
        return None


def get_meeting_by_id_service(
    supabase: Client,
    meeting_id: str,
) -> Optional[dict]:
    """회의 ID로 회의를 조회합니다."""
    # 먼저 채널 ID인지 확인
    ch = get_channel(meeting_id)
    if ch:
        return _channel_to_meeting(ch)

    try:
        result = (
            supabase.table("meetings")
            .select("*")
            .eq("id", meeting_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception:
        return None


def create_meeting_service(supabase: Client, meeting_data: MeetingCreate) -> dict:
    """새 회의를 생성합니다."""
    data = {
        "title": meeting_data.title,
        "meeting_date": meeting_data.meeting_date.isoformat(),
        "stream_url": meeting_data.stream_url,
        "vod_url": meeting_data.vod_url,
        "status": meeting_data.status.value,
        "duration_seconds": meeting_data.duration_seconds,
    }
    result = supabase.table("meetings").insert(data).execute()
    return result.data[0]


# =============================================================================
# API Endpoints
# =============================================================================


@router.get("")
async def get_meetings(
    status: Optional[str] = Query(None, description="회의 상태 필터 (콤마구분 가능: processing,ended)"),
    limit: int = Query(10, ge=1, le=100, description="조회할 개수"),
    offset: int = Query(0, ge=0, description="시작 위치"),
    supabase: Client = Depends(get_supabase),
) -> list[dict]:
    """회의 목록을 조회합니다."""
    statuses = None
    if status:
        try:
            status_list = []
            for s in status.split(","):
                status_list.append(MeetingStatus(s.strip()))
            statuses = status_list
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="Invalid status value",
            )
    return get_meetings_service(supabase, statuses=statuses, limit=limit, offset=offset)


@router.get("/live")
async def get_live_meeting(
    channel: Optional[str] = Query(None, description="채널 ID (예: ch14)"),
    supabase: Client = Depends(get_supabase),
) -> Optional[dict]:
    """현재 실시간 회의를 조회합니다. 채널로 필터 가능."""
    return get_live_meeting_service(supabase, channel=channel)


@router.get("/{meeting_id}")
async def get_meeting_by_id(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
) -> dict:
    """회의 ID로 회의를 조회합니다."""
    meeting = get_meeting_by_id_service(supabase, meeting_id)

    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting with id {meeting_id} not found",
        )

    # 채널 ID 기반으로 committee 자동 설정 (비어있는 경우)
    if not meeting.get("committee"):
        ch_id = meeting.get("id") if get_channel(meeting.get("id", "")) else None
        if ch_id:
            meeting["committee"] = get_committee_for_channel(ch_id)

    return meeting


def _check_duplicate_vod(supabase: Client, vod_url: str) -> None:
    """vod_url 기준으로 중복 회의를 검사하고, 존재 시 409를 발생시킵니다.

    Supabase 쿼리 자체가 실패하면(테이블 부재 등) 경고만 남기고 통과합니다.
    """
    if not vod_url:
        return
    try:
        result = (
            supabase.table("meetings")
            .select("id,title,meeting_date")
            .eq("vod_url", vod_url)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.warning("중복 체크 스킵 (meetings 테이블 조회 실패): %s", e)
        return

    if result.data:
        existing = result.data[0]
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "이미 등록된 VOD입니다.",
                "existing_meeting_id": existing.get("id"),
                "existing_title": existing.get("title"),
                "existing_meeting_date": existing.get("meeting_date"),
            },
        )


def _assert_allowed_vod_source(url: str) -> None:
    """허용되지 않은 VOD 소스 URL이면 422를 발생시킵니다."""
    if not is_allowed_vod_source(url):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="경기도의회 공식 VOD(https://kms.ggc.go.kr) 주소만 등록할 수 있습니다.",
        )


@router.post("/from-url", status_code=status.HTTP_201_CREATED)
async def create_meeting_from_url(
    data: MeetingFromUrl,
    supabase: Client = Depends(get_supabase),
    user: dict | None = Depends(optional_auth),
) -> dict:
    """URL만으로 VOD를 등록합니다. 비로그인 허용(공식 도메인만), admin은 모든 도메인 허용.

    KMS URL이면 메타데이터를 자동 추출합니다.
    """
    # 0. 도메인 화이트리스트 — 관리자는 외부 VOD URL 매칭을 위해 우회 허용
    if not (user and user.get("role") == "admin"):
        _assert_allowed_vod_source(data.url)

    # 1. 메타데이터 추출
    try:
        metadata = await resolve_kms_vod_metadata(data.url)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"URL 변환 실패: {e}",
        )
    except Exception as e:
        logger.exception("KMS 메타데이터 추출 중 예기치 못한 오류: %s", data.url)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"KMS 페이지를 가져오지 못했습니다: {e}",
        )

    # 2. 중복 체크 (vod_url 기준)
    _check_duplicate_vod(supabase, metadata["vod_url"])

    # 3. meeting 생성
    meeting_data = MeetingCreate(
        title=metadata["title"],
        meeting_date=date.fromisoformat(metadata["meeting_date"]),
        vod_url=metadata["vod_url"],
        status=MeetingStatus.ENDED,
        duration_seconds=metadata["duration_seconds"],
    )
    return create_meeting_service(supabase, meeting_data)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_meeting(
    meeting_data: MeetingCreate,
    supabase: Client = Depends(get_supabase),
    user: dict | None = Depends(optional_auth),
) -> dict:
    """새 회의(VOD)를 등록합니다. 비로그인 허용(공식 도메인만), admin은 모든 도메인 허용.

    KMS VOD URL은 자동으로 MP4 URL로 변환됩니다.
    """
    # 0. vod_url이 있는 경우 화이트리스트 검증 — 관리자는 우회 허용
    is_admin = bool(user and user.get("role") == "admin")
    if meeting_data.vod_url and not is_admin:
        _assert_allowed_vod_source(meeting_data.vod_url)

    if meeting_data.vod_url and is_kms_vod_url(meeting_data.vod_url):
        try:
            meeting_data.vod_url = await resolve_kms_vod_url(meeting_data.vod_url)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"KMS VOD URL 변환 실패: {e}",
            )
        except Exception as e:
            logger.exception("KMS URL 변환 중 예기치 못한 오류")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"KMS 페이지를 가져오지 못했습니다: {e}",
            )

    # 중복 체크 (vod_url 기준, resolve 이후)
    if meeting_data.vod_url:
        _check_duplicate_vod(supabase, meeting_data.vod_url)

    return create_meeting_service(supabase, meeting_data)


# =============================================================================
# VOD STT Endpoints
# =============================================================================


@router.post("/{meeting_id}/stt")
async def start_stt_processing(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("admin", "meeting_manager")),
) -> dict:
    """VOD STT(AI 자막 생성) 처리를 시작합니다 (백그라운드).

    - 유료 OpenAI 호출을 트리거하므로 관리자/회의담당만 실행 가능 (비용 보호)
    - meeting이 존재하고 vod_url이 있어야 함
    - 이미 처리 중이면 409 Conflict
    - 즉시 task_id와 status를 반환
    """
    # 1. meeting 존재 확인
    meeting = get_meeting_by_id_service(supabase, meeting_id)
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting {meeting_id}을(를) 찾을 수 없습니다.",
        )

    # 2. vod_url 필수 체크
    vod_url = meeting.get("vod_url")
    if not vod_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="VOD URL이 없는 회의입니다. 먼저 VOD URL을 등록해주세요.",
        )

    # 3. 중복 처리 방지 — 최대 1회 처리 보장 (이중 가드)
    #    (a) 인메모리 태스크: 같은 프로세스 내 동시 클릭 차단
    #    (b) DB status='processing': 서버 재시작에도 살아남는 가드.
    #        과거 인메모리 가드만 있을 때 재시작 직후 같은 회의가 2번 전사되어
    #        자막이 통째로 2벌 들어가고 비용도 2배 발생한 사고가 있었다.
    #        (고아 'processing'은 서버 기동 시 reset_orphaned_processing이 정리)
    if is_processing(meeting_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 STT 처리가 진행 중입니다.",
        )
    if meeting.get("status") == "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 AI 자막 생성이 진행 중입니다 (다른 요청에서 시작됨).",
        )
    # 생중계 중에는 라이브 STT와 충돌(자막 이중 기록)하므로 차단
    if meeting.get("status") == "live":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="생중계 진행 중에는 AI 자막을 생성할 수 없습니다. 방송 종료 후 실행해주세요.",
        )

    # 4. 백그라운드 태스크 실행
    service = VodSttService()
    asyncio.create_task(service.process(meeting_id, vod_url, supabase))

    # 5. 즉시 응답 (태스크가 아직 등록 안됐을 수 있으므로 짧은 대기)
    await asyncio.sleep(0.05)
    task = get_task_by_meeting(meeting_id)
    return {
        "task_id": task.task_id if task else None,
        "meeting_id": meeting_id,
        "status": task.status if task else "pending",
        "message": "STT 처리가 시작되었습니다.",
    }


@router.post("/{meeting_id}/regenerate")
async def regenerate_single_meeting(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("admin")),
) -> dict:
    """단일 회의에 대한 'VOD 연결 + 자막 재생성' 원클릭 파이프라인 (admin 전용).

    동작:
    1. vod_url 없으면 → KMS 최근목록에서 자동 매칭 + MP4 링크 업데이트
    2. 기존 자막 삭제 → VOD STT 재실행 → AI 문법 교정 (백그라운드)

    반환: status(started|queued|no_vod_match), vod_url, matched_from_kms
    """
    from datetime import datetime as _dt, timezone as _tz

    meeting = get_meeting_by_id_service(supabase, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="회의를 찾을 수 없습니다.")

    vod_url = meeting.get("vod_url")
    matched_from_kms = False

    # 1) vod_url 없으면 KMS 매칭 시도
    if not vod_url:
        try:
            entries = await fetch_recent_vod_list()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"KMS 목록 조회 실패: {e}")

        candidate = _match_meeting_to_entry(meeting, entries)
        if not candidate:
            return {
                "meeting_id": meeting_id,
                "status": "no_vod_match",
                "message": "KMS에서 매칭되는 VOD를 찾지 못했습니다. 방송 종료 후 30분~1시간 뒤 다시 시도해주세요.",
            }

        try:
            vod_url = await resolve_kms_vod_url(candidate["page_url"])
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"KMS 링크 변환 실패: {e}")

        new_title = meeting.get("title") or candidate["title"]
        if "생중계" in new_title or "제" not in new_title:
            new_title = f"{candidate['title']} [{candidate['meeting_date']}]"

        try:
            supabase.table("meetings").update(
                {
                    "vod_url": vod_url,
                    "duration_seconds": candidate["duration_seconds"],
                    "status": "ended",
                    "title": new_title,
                    "updated_at": _dt.now(_tz.utc).isoformat(),
                }
            ).eq("id", meeting_id).execute()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"DB 업데이트 실패: {e}")

        matched_from_kms = True

    # 2) 이미 처리 중이면 409
    if is_processing(meeting_id):
        raise HTTPException(
            status_code=409, detail="이미 STT 처리가 진행 중입니다."
        )

    # 3) 재생성 파이프라인 백그라운드 실행
    asyncio.create_task(_regenerate_pipeline(meeting_id, vod_url, supabase))

    return {
        "meeting_id": meeting_id,
        "status": "started",
        "vod_url": vod_url,
        "matched_from_kms": matched_from_kms,
        "message": "자막 재생성이 시작되었습니다.",
    }


@router.post("/{meeting_id}/upload-stt")
async def upload_mp4_and_stt(
    meeting_id: str,
    file: UploadFile,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("admin")),
) -> dict:
    """사용자 브라우저가 직접 업로드한 MP4 파일로 VOD STT 실행.

    흐름:
    1. 브라우저가 KMS에서 MP4를 로컬 다운로드
    2. 이 엔드포인트로 multipart/form-data 업로드 (streaming, 메모리 안전)
    3. 임시 파일 저장 → Deepgram → 자막 DB (기존 자막 삭제 + 새 자막 삽입)
    4. AI 문법 교정 백그라운드 실행

    Railway → KMS 대역폭 병목을 완전히 우회합니다.
    응답은 STT 완료 후 즉시 반환 (파이프라인 전체 동기 실행).
    """
    from app.services.vod_stt_service import (
        VodSttService,
        SttTaskStatus,
        _tasks,
    )
    from app.services.kms_bulk_matcher import _regenerate_pipeline  # noqa

    meeting = get_meeting_by_id_service(supabase, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="회의를 찾을 수 없습니다.")
    if is_processing(meeting_id):
        raise HTTPException(status_code=409, detail="이미 STT 처리 중입니다.")

    # 스트리밍 저장 (1 GB+ 대응, 메모리에 올리지 않음)
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp_path = _Path(tmp.name)
    total_bytes = 0
    try:
        while True:
            chunk = await file.read(1024 * 1024)  # 1 MB
            if not chunk:
                break
            tmp.write(chunk)
            total_bytes += len(chunk)
        tmp.close()

        if total_bytes < 1_000_000:
            raise HTTPException(
                status_code=400,
                detail=f"파일이 너무 작습니다 ({total_bytes} bytes). MP4 파일을 확인해주세요.",
            )

        # 태스크 등록
        task_id = str(_uuid_mod.uuid4())
        task = SttTaskStatus(
            task_id=task_id,
            meeting_id=meeting_id,
            status="running",
            progress=0.2,
            message=f"업로드 완료 ({total_bytes / (1024*1024):.0f} MB) — Deepgram 전송 중",
        )
        _tasks[meeting_id] = task

        # Deepgram 전송 (파일 직접 업로드 경로 재사용)
        service = VodSttService()
        dg_result = await VodSttService._send_to_deepgram(tmp_path, task)

        task.progress = 0.92
        task.message = "자막 데이터 변환 중"
        from app.services.dictionary import get_default_dictionary
        dictionary = get_default_dictionary()
        all_subtitles = VodSttService._parse_deepgram_response(
            meeting_id, dg_result, dictionary
        )

        # 기존 AI 자막만 삭제 (STT 성공 확인 후에만).
        # ★실시간 자막(kind='live')은 보존한다 — 회의 상세의 '실시간 자막(초안)' 탭이
        #   이 데이터를 읽는다. 전부 지우면 초안이 영구히 사라진다.
        if all_subtitles:
            supabase.table("subtitles").delete().eq("meeting_id", meeting_id).eq(
                "kind", "ai"
            ).execute()
            task.message = "기존 AI 자막 교체 중"
            await VodSttService._insert_subtitles(supabase, all_subtitles)
            task.progress = 0.95

        # meeting 상태 업데이트 — subtitle_stage='ai'로 승격
        duration = dg_result.get("metadata", {}).get("duration", 0)
        supabase.table("meetings").update({
            "status": "ended",
            "subtitle_stage": "ai",
            "duration_seconds": int(duration) if duration else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", meeting_id).execute()

        task.status = "completed"
        task.progress = 1.0
        task.message = f"완료 — {len(all_subtitles)}개 자막 생성"

        # AI 문법 교정은 백그라운드 (응답 지연 방지)
        async def _apply_grammar():
            try:
                from app.services.grammar_checker import check_grammar_batch
                subs = supabase.table("subtitles").select("id, text").eq(
                    "meeting_id", meeting_id
                ).execute().data or []
                issues = await check_grammar_batch(subs)
                for issue in issues:
                    try:
                        supabase.table("subtitles").update({
                            "text": issue.corrected_text,
                            "original_text": issue.original_text,
                            "is_corrected": True,
                            "correction_state": "corrected",
                        }).eq("id", issue.subtitle_id).execute()
                    except Exception:
                        pass
            except Exception as e:
                logger.exception("upload-stt grammar failed: %s", e)

        asyncio.create_task(_apply_grammar())

        return {
            "meeting_id": meeting_id,
            "status": "completed",
            "subtitles_count": len(all_subtitles),
            "uploaded_mb": round(total_bytes / (1024 * 1024), 1),
            "duration_seconds": int(duration) if duration else None,
            "message": f"자막 {len(all_subtitles)}개 생성 완료 (AI 교정 진행 중)",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("upload-stt failed: %s", e)
        task = _tasks.get(meeting_id)
        if task:
            task.status = "failed"
            task.error = str(e)
        raise HTTPException(status_code=500, detail=f"STT 처리 실패: {e}")
    finally:
        try:
            tmp.close()
        except Exception:
            pass
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


_AUDIO_CONTENT_TYPE_MAP = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".mp4": "video/mp4",  # 오디오만 있는 MP4 컨테이너도 허용
}


@router.post("/{meeting_id}/upload-audio-stt")
async def upload_audio_and_stt(
    meeting_id: str,
    file: UploadFile,
    force: bool = False,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("admin")),
) -> dict:
    """MP3/M4A/WAV/MP4 오디오 파일 업로드 → Deepgram AI 자막 생성.

    신 워크플로우 메인 경로. 사용자가 KMS 또는 녹음 장비에서 오디오를 직접 업로드.
    MP4보다 ~10배 작고 Railway→KMS 대역폭 병목 회피.

    동작:
    1. 확장자 화이트리스트 검증 + Content-Type 매핑
    2. reviewing/final 단계 보호 (force=true 없이는 409)
    3. 스트리밍 저장 → Deepgram → 자막 파싱 → safe-delete(성공 확인 후 삭제+삽입)
    4. meetings.subtitle_stage='ai' 업데이트
    5. AI 문법 교정 백그라운드
    """
    from app.services.vod_stt_service import (
        VodSttService,
        SttTaskStatus,
        _tasks,
    )

    # 확장자 → Content-Type
    ext = _Path(file.filename or "").suffix.lower()
    content_type = _AUDIO_CONTENT_TYPE_MAP.get(ext)
    if not content_type:
        raise HTTPException(
            status_code=415,
            detail=f"지원하지 않는 파일 형식: {ext}. MP3/M4A/WAV/MP4만 허용됩니다.",
        )

    meeting = get_meeting_by_id_service(supabase, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="회의를 찾을 수 없습니다.")

    # reviewing/final 단계 보호
    current_stage = meeting.get("subtitle_stage")
    if current_stage in ("reviewing", "final") and not force:
        raise HTTPException(
            status_code=409,
            detail=(
                f"현재 단계({current_stage})에서는 업로드가 차단됩니다. "
                "속기사 교정본이 덮어쓰여질 수 있습니다. "
                "강제 진행하려면 ?force=true 쿼리 파라미터를 추가하세요."
            ),
        )
    if is_processing(meeting_id):
        raise HTTPException(status_code=409, detail="이미 STT 처리 중입니다.")

    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    tmp_path = _Path(tmp.name)
    total_bytes = 0
    try:
        while True:
            chunk = await file.read(1024 * 1024)  # 1 MB
            if not chunk:
                break
            tmp.write(chunk)
            total_bytes += len(chunk)
        tmp.close()

        # 오디오는 작을 수 있음 (1분 MP3 ~1 MB)
        if total_bytes < 100_000:
            raise HTTPException(
                status_code=400,
                detail=f"파일이 너무 작습니다 ({total_bytes} bytes).",
            )

        task = SttTaskStatus(
            task_id=str(_uuid_mod.uuid4()),
            meeting_id=meeting_id,
            status="running",
            progress=0.2,
            message=f"업로드 완료 ({total_bytes / (1024*1024):.0f} MB, {content_type}) — Deepgram 전송 중",
        )
        _tasks[meeting_id] = task

        dg_result = await VodSttService._send_to_deepgram(
            tmp_path, task, content_type=content_type
        )

        task.progress = 0.92
        task.message = "자막 데이터 변환 중"
        from app.services.dictionary import get_default_dictionary
        dictionary = get_default_dictionary()
        all_subtitles = VodSttService._parse_deepgram_response(
            meeting_id, dg_result, dictionary
        )

        # safe-delete: STT 성공 확인 후에만 기존 AI 자막 삭제.
        # 실시간 자막(kind='live')은 초안으로 보존한다.
        if all_subtitles:
            supabase.table("subtitles").delete().eq("meeting_id", meeting_id).eq(
                "kind", "ai"
            ).execute()
            task.message = "기존 AI 자막 교체 중"
            await VodSttService._insert_subtitles(supabase, all_subtitles)
            task.progress = 0.95
        else:
            raise HTTPException(
                status_code=422,
                detail="Deepgram이 자막을 추출하지 못했습니다. 오디오 품질을 확인해주세요.",
            )

        duration = dg_result.get("metadata", {}).get("duration", 0)
        supabase.table("meetings").update({
            "status": "ended",
            "subtitle_stage": "ai",
            "duration_seconds": int(duration) if duration else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", meeting_id).execute()

        task.status = "completed"
        task.progress = 1.0
        task.message = f"완료 — {len(all_subtitles)}개 자막 생성"

        async def _apply_grammar():
            try:
                from app.services.grammar_checker import check_grammar_batch
                subs = supabase.table("subtitles").select("id, text").eq(
                    "meeting_id", meeting_id
                ).execute().data or []
                issues = await check_grammar_batch(subs)
                for issue in issues:
                    try:
                        supabase.table("subtitles").update({
                            "text": issue.corrected_text,
                            "original_text": issue.original_text,
                            "is_corrected": True,
                            "correction_state": "corrected",
                        }).eq("id", issue.subtitle_id).execute()
                    except Exception:
                        pass
            except Exception as e:
                logger.exception("upload-audio-stt grammar failed: %s", e)

        asyncio.create_task(_apply_grammar())

        return {
            "meeting_id": meeting_id,
            "status": "completed",
            "subtitle_stage": "ai",
            "subtitles_count": len(all_subtitles),
            "uploaded_mb": round(total_bytes / (1024 * 1024), 1),
            "content_type": content_type,
            "duration_seconds": int(duration) if duration else None,
            "message": f"자막 {len(all_subtitles)}개 생성 완료 (AI 교정 진행 중)",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("upload-audio-stt failed: %s", e)
        task = _tasks.get(meeting_id)
        if task:
            task.status = "failed"
            task.error = str(e)
        raise HTTPException(status_code=500, detail=f"STT 처리 실패: {e}")
    finally:
        try:
            tmp.close()
        except Exception:
            pass
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


@router.get("/{meeting_id}/stt/status")
async def get_stt_status(
    meeting_id: str,
) -> dict:
    """VOD STT 처리 상태를 조회합니다."""
    task = get_task_by_meeting(meeting_id)

    if task is None:
        return {
            "meeting_id": meeting_id,
            "status": "none",
            "progress": 0.0,
            "message": "STT 처리 기록이 없습니다.",
            "error": None,
        }

    return {
        "task_id": task.task_id,
        "meeting_id": task.meeting_id,
        "status": task.status,
        "progress": task.progress,
        "message": task.message,
        "error": task.error,
    }


@router.get("/{meeting_id}/clock-anchors")
async def get_meeting_clock_anchors(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
) -> dict:
    """회의 시각 기준점 — 영상/VOD 위에 "이 장면의 실제 시각"을 띄우는 근거.

    자막 시계(start_time)는 수신된 오디오 초라 정회 구간을 건너뛴다. 그래서 단순히
    시작 시각에 더할 수 없고, 구간별 기준점이 필요하다(services/meeting_clock 설명).

    source:
      recorded  — 라이브 STT 가 남긴 기준점 (초 단위 정확)
      estimated — 자막 기록 시각에서 추정 (±10초 내외, 기준점 도입 전 회의)
      none      — 근거 없음. 화면은 시각을 표시하지 않는다.
    """
    # 채널 ID(ch14 등)나 형식이 아닌 값이면 조회하지 않는다 — 기준점은 회의 단위다
    try:
        _uuid_mod.UUID(meeting_id)
    except ValueError:
        return {"meeting_id": meeting_id, "source": "none", "anchors": []}

    anchors, source = await asyncio.to_thread(
        meeting_clock.anchors_for_meeting, supabase, meeting_id
    )
    return {"meeting_id": meeting_id, "source": source, "anchors": anchors}


# =============================================================================
# Meeting Update (PATCH)
# =============================================================================


@router.patch("/{meeting_id}")
async def update_meeting(
    meeting_id: str,
    body: MeetingUpdate,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("admin")),
) -> dict:
    """회의 정보를 수정합니다 (vod_url, meeting_type, committee 등). admin 전용."""
    update_data = body.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="수정할 필드가 없습니다.",
        )

    # vod_url이 KMS 페이지(.do) URL이면 자동으로 MP4 직접링크로 변환 —
    # POST /from-url 및 POST /와 동일한 동작. 관리자가 KMS URL을 그대로
    # 붙여넣어도 플레이어가 바로 재생하도록 보장.
    if "vod_url" in update_data and update_data["vod_url"]:
        url = update_data["vod_url"]
        if is_kms_vod_url(url):
            try:
                update_data["vod_url"] = await resolve_kms_vod_url(url)
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"KMS VOD URL 변환 실패: {e}",
                )

    # date → isoformat 변환
    if "meeting_date" in update_data:
        update_data["meeting_date"] = update_data["meeting_date"].isoformat()
    if "status" in update_data:
        update_data["status"] = update_data["status"].value
    if "transcript_status" in update_data:
        update_data["transcript_status"] = update_data["transcript_status"].value

    # updated_at 명시적 갱신
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    result = (
        supabase.table("meetings")
        .update(update_data)
        .eq("id", meeting_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting {meeting_id}을(를) 찾을 수 없습니다.",
        )

    return result.data[0]


# =============================================================================
# Participants CRUD
# =============================================================================


@router.get("/{meeting_id}/participants")
async def get_participants(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
) -> list[dict]:
    """회의 참석자 목록을 조회합니다."""
    result = (
        supabase.table("meeting_participants")
        .select("*")
        .eq("meeting_id", meeting_id)
        .order("created_at")
        .execute()
    )
    return result.data


@router.post("/{meeting_id}/participants", status_code=status.HTTP_201_CREATED)
async def add_participant(
    meeting_id: str,
    body: ParticipantCreate,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role(*_MEETING_EDIT_ROLES)),
) -> dict:
    """회의 참석자를 추가합니다."""
    # 회의 존재 확인
    meeting = get_meeting_by_id_service(supabase, meeting_id)
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting {meeting_id}을(를) 찾을 수 없습니다.",
        )

    data = {
        "meeting_id": meeting_id,
        "councilor_id": body.councilor_id,
        "name": body.name,
        "role": body.role,
    }

    try:
        result = supabase.table("meeting_participants").insert(data).execute()
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="이미 등록된 참석자입니다.",
            )
        raise

    return result.data[0]


@router.delete("/{meeting_id}/participants/{participant_id}")
async def remove_participant(
    meeting_id: str,
    participant_id: str,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role(*_MEETING_EDIT_ROLES)),
) -> dict:
    """회의 참석자를 제거합니다."""
    result = (
        supabase.table("meeting_participants")
        .delete()
        .eq("id", participant_id)
        .eq("meeting_id", meeting_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="참석자를 찾을 수 없습니다.",
        )

    return {"deleted": True}


# =============================================================================
# Agendas CRUD
# =============================================================================


@router.get("/{meeting_id}/agendas")
async def get_agendas(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
) -> list[dict]:
    """회의 안건 목록을 조회합니다."""
    result = (
        supabase.table("meeting_agendas")
        .select("*")
        .eq("meeting_id", meeting_id)
        .order("order_num")
        .execute()
    )
    return result.data


@router.post("/{meeting_id}/agendas", status_code=status.HTTP_201_CREATED)
async def add_agenda(
    meeting_id: str,
    body: AgendaCreate,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role(*_MEETING_EDIT_ROLES)),
) -> dict:
    """안건을 추가합니다."""
    meeting = get_meeting_by_id_service(supabase, meeting_id)
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting {meeting_id}을(를) 찾을 수 없습니다.",
        )

    data = {
        "meeting_id": meeting_id,
        "order_num": body.order_num,
        "title": body.title,
        "description": body.description,
    }
    result = supabase.table("meeting_agendas").insert(data).execute()
    return result.data[0]


@router.patch("/{meeting_id}/agendas/{agenda_id}")
async def update_agenda(
    meeting_id: str,
    agenda_id: str,
    body: AgendaUpdate,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role(*_MEETING_EDIT_ROLES)),
) -> dict:
    """안건을 수정합니다."""
    update_data = body.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="수정할 필드가 없습니다.",
        )

    result = (
        supabase.table("meeting_agendas")
        .update(update_data)
        .eq("id", agenda_id)
        .eq("meeting_id", meeting_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="안건을 찾을 수 없습니다.",
        )

    return result.data[0]


@router.delete("/{meeting_id}/agendas/{agenda_id}")
async def delete_agenda(
    meeting_id: str,
    agenda_id: str,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role(*_MEETING_EDIT_ROLES)),
) -> dict:
    """안건을 삭제합니다."""
    result = (
        supabase.table("meeting_agendas")
        .delete()
        .eq("id", agenda_id)
        .eq("meeting_id", meeting_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="안건을 찾을 수 없습니다.",
        )

    return {"deleted": True}


@router.post("/{meeting_id}/agenda-draft")
async def create_agenda_draft(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
    _user: dict | None = Depends(optional_auth),
) -> dict:
    """AI 자막에서 안건 + 의사일정 내용 초안을 생성합니다 (수동 트리거).

    - 안건이 없으면 자막에서 추출해 meeting_agendas에 등록, 이미 있으면 보존.
    - summary_service의 안건별 요약으로 각 안건 description(의사일정 내용)이 빈 것만 채움.
    - 반환: agendas, agenda_summaries, summary_text, order_of_business_markdown 등.
    멱등(재호출 안전). ※운영 배포 시 require_role(편집권한 이상)로 가드 권장.
    """
    if not app_settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenAI API 키가 설정되지 않았습니다.",
        )

    # 최초 1회만 생성 (사용자 정책) — 시도 마커(agenda_draft_at, migration 026)가 1차 가드.
    # 추출 0개로 끝난 시도도 마커가 남아 재실행이 차단된다.
    try:
        meeting_row = (
            supabase.table("meetings")
            .select("agenda_draft_at")
            .eq("id", meeting_id)
            .limit(1)
            .execute()
            .data
        )
    except Exception:
        meeting_row = []
    if meeting_row and meeting_row[0].get("agenda_draft_at"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 안건 초안이 생성되어 있습니다 (회의당 1회만 생성됩니다).",
        )

    # 2차 가드(호환): 마커 도입 전 생성된 회의는 안건 존재 여부로 차단
    try:
        existing_agendas = (
            supabase.table("meeting_agendas")
            .select("id")
            .eq("meeting_id", meeting_id)
            .limit(1)
            .execute()
            .data
        )
    except Exception:
        existing_agendas = []
    if existing_agendas:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 안건 초안이 생성되어 있습니다 (회의당 1회만 생성됩니다).",
        )

    from app.services.agenda_draft_service import generate_agenda_draft

    try:
        result = await generate_agenda_draft(supabase, meeting_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except SummaryLimitError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except SummaryGenerationError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("안건 초안 생성 실패: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    # 시도 마커 기록 (0개 추출이어도) — 실패해도 응답은 유지(fail-soft, 2차 가드가 보완)
    try:
        supabase.table("meetings").update(
            {"agenda_draft_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", meeting_id).execute()
    except Exception as e:
        logger.warning("agenda_draft_at 마커 기록 실패: %s", e)

    return result


# =============================================================================
# Transcript Status + Publications (P6-3: T10)
# =============================================================================


@router.patch("/{meeting_id}/transcript-status")
async def update_transcript_status(
    meeting_id: str,
    body: TranscriptStatusUpdate,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role(*_TRANSCRIPT_ROLES)),
) -> dict:
    """회의록 상태를 변경합니다 (draft -> reviewing -> final).

    transcript_status와 subtitle_stage를 동기화합니다:
    - reviewing → subtitle_stage='reviewing' (속기사 교정 진행 중)
    - final     → subtitle_stage='final' (최종 확정)
    - draft는 자막 단계를 바꾸지 않음 (ai/draft 그대로 유지)
    """
    new_ts = body.transcript_status.value
    update_payload: dict = {"transcript_status": new_ts}
    if new_ts in ("reviewing", "final"):
        update_payload["subtitle_stage"] = new_ts

    result = (
        supabase.table("meetings")
        .update(update_payload)
        .eq("id", meeting_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting {meeting_id}을(를) 찾을 수 없습니다.",
        )

    # @TASK P11-T5.1 - transcript_status 변경 시 자동 알림 생성
    meeting_data = result.data[0]
    meeting_title = meeting_data.get("title", "회의")
    new_status = body.transcript_status.value
    create_notification_record(
        supabase,
        notification_type="status_change",
        title="회의록 상태 변경",
        message=f"{meeting_title} 회의록이 {new_status}(으)로 변경되었습니다",
        related_meeting_id=meeting_id,
    )

    return result.data[0]


@router.post("/{meeting_id}/publications", status_code=status.HTTP_201_CREATED)
async def create_publication(
    meeting_id: str,
    body: PublicationCreate,
    supabase: Client = Depends(get_supabase),
    user: dict = Depends(require_role(*_TRANSCRIPT_ROLES)),
) -> dict:
    """회의록 확정/공개 이력을 등록합니다."""
    meeting = get_meeting_by_id_service(supabase, meeting_id)
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting {meeting_id}을(를) 찾을 수 없습니다.",
        )

    data = {
        "meeting_id": meeting_id,
        "status": body.status.value,
        # 누가 확정했는지는 클라이언트가 보낸 이름이 아니라 로그인 세션에서 적는다(감사 기록)
        "published_by": user.get("display_name") or user.get("username") or body.published_by,
        "notes": body.notes,
    }
    result = supabase.table("transcript_publications").insert(data).execute()
    return result.data[0]


@router.get("/{meeting_id}/publications")
async def get_publications(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
) -> list[dict]:
    """회의록 확정/공개 이력을 조회합니다."""
    result = (
        supabase.table("transcript_publications")
        .select("*")
        .eq("meeting_id", meeting_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


# =============================================================================
# AI Summary (P7-T2.2)
# @TASK P7-T2.2 - AI 요약 API 엔드포인트
# @SPEC docs/planning/02-trd.md#AI-요약
# =============================================================================


@router.post("/{meeting_id}/summary")
async def create_meeting_summary(
    meeting_id: str,
    refresh: bool = Query(False, description="앞부분만 본 옛 요약(complete=false)이면 회의 전체로 다시 만든다"),
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role_or_council(*AI_ROLES)),
) -> dict:
    """AI 요약 생성 — 로그인 AI 역할(staff 포함) 또는 의회망 손님(2026-09-14 담당자 결정)

    회의당 1회만 생성(캐시가 있으면 OpenAI 재호출 없이 그대로). 긴 회의는 청크 요약 → 병합(summary_service).
    응답은 GET 과 같은 저장 행(id·created_at 포함).
    """
    try:
        summary = await generate_meeting_summary(supabase, meeting_id, refresh_partial=refresh)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except SummaryLimitError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except SummaryGenerationError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.error("요약 생성 실패: %s", e)
        raise HTTPException(status_code=500, detail="요약 생성 실패")
    row = await get_summary(supabase, meeting_id)
    if row:
        return row
    return {
        "meeting_id": meeting_id,
        "summary_text": summary.summary_text,
        "agenda_summaries": summary.agenda_summaries,
        "key_decisions": summary.key_decisions,
        "action_items": summary.action_items,
        "model_used": summary.model_used,
        "segments": summary.segments,
        "speakers": summary.speakers,
        "source_chars": summary.source_chars,
        "complete": summary.complete,
        "generated_from": summary.generated_from,
    }


@router.get("/{meeting_id}/summary")
async def get_meeting_summary(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
) -> dict:
    """저장된 요약 조회"""
    result = await get_summary(supabase, meeting_id)
    if result is None:
        raise HTTPException(
            status_code=404, detail="요약이 없습니다. POST로 생성하세요."
        )
    return result


@router.delete("/{meeting_id}/summary", status_code=204)
async def delete_meeting_summary(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("admin")),
) -> None:
    """요약 삭제 (재생성용)"""
    deleted = await delete_summary(supabase, meeting_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="삭제할 요약이 없습니다.")


# =============================================================================
# AI 회의정보 자동 추출
# =============================================================================

MEETING_INFO_PROMPT = """다음은 경기도의회 회의 자막입니다. 자막 내용을 분석하여 회의 정보를 추출하세요.

반드시 아래 JSON 형식으로만 응답하세요:
{
  "meeting_type": "본회의|상임위원회|특별위원회|예산결산특별위원회|기타 중 하나",
  "committee": "위원회 이름 (예: 기획재정위원회). 본회의면 null",
  "participants": [
    {"name": "이름", "role": "직책 (위원장/위원/도지사 등)"}
  ],
  "agendas": [
    {"order_num": 1, "title": "안건 제목"}
  ]
}

규칙:
- 자막에서 명시적으로 언급된 정보만 추출
- 참석자는 실제 발언하거나 호명된 사람만 포함
- 안건은 "제N호 의안", "상정", "안건" 등의 키워드에서 추출
- 확실하지 않으면 해당 필드를 null이나 빈 배열로"""


@router.post("/{meeting_id}/suggest-info")
async def suggest_meeting_info(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role("admin", "meeting_manager")),
) -> dict:
    """AI를 사용하여 자막에서 회의정보(유형, 위원회, 참석자, 안건)를 자동 추출합니다."""
    if not app_settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenAI API 키가 설정되지 않았습니다.",
        )

    # 자막 조회 (앞부분 100개 - 충분한 맥락)
    result = (
        supabase.table("subtitles")
        .select("text, speaker, start_time")
        .eq("meeting_id", meeting_id)
        .order("start_time")
        .limit(100)
        .execute()
    )

    if not result.data:
        return {"meeting_type": None, "committee": None, "participants": [], "agendas": []}

    # 자막 텍스트 구성
    lines = []
    for s in result.data:
        speaker = s.get("speaker") or "미지정"
        lines.append(f"[{speaker}] {s['text']}")
    transcript = "\n".join(lines)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {app_settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": app_settings.openai_model,
                    "messages": [
                        {"role": "system", "content": MEETING_INFO_PROMPT},
                        {"role": "user", "content": transcript},
                    ],
                    "max_completion_tokens": 1000,
                },
            )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"OpenAI API 오류 (HTTP {response.status_code})",
            )

        content = response.json()["choices"][0]["message"]["content"]
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        parsed = json.loads(content.strip())
        return parsed

    except json.JSONDecodeError:
        logger.warning("AI 회의정보 JSON 파싱 실패")
        return {"meeting_type": None, "committee": None, "participants": [], "agendas": [], "error": "파싱 실패"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("AI 회의정보 추출 실패: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ─── 회의 영상 썸네일 (목록·대시보드용) ──────────────────────────────────


@router.get("/{meeting_id}/thumbnail")
async def get_meeting_thumbnail(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
):
    """회의 영상의 대표 프레임(JPEG).

    브라우저가 `<video preload="metadata">` 로 직접 만들게 두면 안 된다 —
    KMS MP4 는 moov 가 파일 끝에 있어 회의 한 건마다 수 MB 를 받아야 하고,
    모바일에서 목록이 그대로 멈춘다. 서버가 ffmpeg 로 한 번 뽑아(약 1초·18KB)
    PVC 에 캐시하면 그 비용이 사라진다. 자세한 근거는 thumbnail_service 참조.
    """
    from fastapi.responses import FileResponse

    from app.services.thumbnail_service import ensure_thumbnail

    # 경로 조작 방지 — 캐시 파일명이 되므로 UUID 만 허용한다
    try:
        _uuid_mod.UUID(meeting_id)
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=404, detail="잘못된 회의 식별자입니다")

    meeting = get_meeting_by_id_service(supabase, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="회의를 찾을 수 없습니다")

    path = await ensure_thumbnail(meeting_id, meeting.get("vod_url"))
    if path is None:
        # 영상 미등록이거나 추출 실패 — 프런트는 자리표시로 떨어진다
        raise HTTPException(status_code=404, detail="썸네일이 없습니다")

    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ─── 라이브 오디오 녹음 다운로드 (자막 정확도 검증용) ─────────────────────


def _recording_size_or_404(meeting_id: str) -> tuple:
    """녹음 파일 경로·크기를 반환하거나 404를 던진다 (GET/HEAD 공용)."""
    from app.services.live_recorder import recording_path

    path = recording_path(meeting_id)
    if path is None:
        raise HTTPException(status_code=404, detail="잘못된 회의 식별자입니다")
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    if size == 0:
        raise HTTPException(
            status_code=404,
            detail="이 회의의 녹음 파일이 없습니다 (라이브 STT 중에만 녹음됩니다)",
        )
    return path, size


@router.head("/{meeting_id}/recording")
async def head_meeting_recording(meeting_id: str):
    """녹음 파일 존재 확인 (프런트 다운로드 버튼의 사전 점검용).

    FastAPI @router.get은 HEAD를 자동 지원하지 않아(405) 별도 라우트가 필요하다.
    """
    from fastapi.responses import Response

    _path, size = _recording_size_or_404(meeting_id)
    return Response(
        status_code=200,
        media_type="audio/mpeg",
        headers={
            "Content-Length": str(size),
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-store",
        },
    )


@router.get("/{meeting_id}/recording/meta")
async def get_meeting_recording_meta(meeting_id: str):
    """녹음 메타데이터 — 자막 타임스탬프 ↔ mp3 재생 위치 매핑용.

    mp3 위치(초) = 자막 start_time - start_offset_sec.
    바이트 위치 = mp3 위치 × bytes_per_sec (CBR).

    오프셋은 사이드카(.offset)가 정답이고, 사이드카가 없는 레거시 파일은
    'STT 진행 중'이면 현재 오디오 시계 - 파일 길이로 추정한다.
    """
    from app.services.live_recorder import (
        bytes_per_second,
        recording_offset,
        recording_path,
        recording_sessions,
    )
    from app.services.openai_realtime_stt import get_channel_stt_service

    path, size = _recording_size_or_404(meeting_id)
    bps = bytes_per_second()

    offset = recording_offset(meeting_id)
    sidecar = recording_path(meeting_id)
    has_sidecar = sidecar is not None and sidecar.with_suffix(".offset").exists()
    if not has_sidecar:
        svc = get_channel_stt_service()
        clock = None
        if hasattr(svc, "audio_clock_for_meeting"):
            clock = svc.audio_clock_for_meeting(meeting_id)
        if clock:
            offset = max(0.0, round(clock - size / bps, 2))

    return {
        "exists": True,
        "size_bytes": size,
        "bytes_per_sec": bps,
        "start_offset_sec": offset,
        # 재시작으로 오디오 시계가 되감긴 경우의 구간별 (clock, byte) 정밀 매핑.
        # 사이드카(.sessions)가 없으면 빈 목록 — 프론트는 start_offset_sec 만으로 동작.
        "sessions": recording_sessions(meeting_id),
    }


@router.get("/{meeting_id}/recording")
async def download_meeting_recording(meeting_id: str, request: Request, download: int = 0):
    """라이브 방송 중 저장된 오디오 MP3를 다운로드/스트리밍한다.

    live_recorder가 STT와 같은 PCM을 mp3로 저장한 파일 — 자막 타임스탬프와
    재생 위치가 대응하므로 전사 정확도를 귀로 검증할 수 있다.

    ★녹음 진행 중에는 파일이 계속 자란다 — FileResponse는 Content-Length를
    stat 시점 크기로 선언한 뒤 EOF까지 읽어, 선언량 초과로 서버가 연결을 끊는다.
    따라서 크기를 스냅샷하고 정확히 그 바이트 수만 보내는 bounded 스트리밍을 쓴다.

    Range 요청(bytes)을 지원한다 — 브라우저 <audio>의 구간 탐색(자막 ▶ 재생)이
    전체 파일을 받지 않고 해당 구간만 가져갈 수 있다 (48kbps CBR이라 선형 탐색).
    """
    from fastapi.responses import StreamingResponse

    path, size = _recording_size_or_404(meeting_id)

    start, end = 0, size - 1
    status_code = 200
    range_header = (request.headers.get("range") or "").strip()
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header) if range_header else None
    if m and (m.group(1) or m.group(2)):
        if m.group(1):
            start = int(m.group(1))
            if m.group(2):
                end = min(int(m.group(2)), size - 1)
        else:
            # suffix range: bytes=-N (마지막 N바이트)
            start = max(0, size - int(m.group(2)))
        if start >= size or start > end:
            raise HTTPException(
                status_code=416,
                detail="요청한 범위가 파일 크기를 벗어났습니다",
                headers={"Content-Range": f"bytes */{size}"},
            )
        status_code = 206

    length = end - start + 1

    def bounded_reader(p=path, offset=start, total=length, chunk=64 * 1024):
        remaining = total
        with open(p, "rb") as f:
            f.seek(offset)
            while remaining > 0:
                data = f.read(min(chunk, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    # 기본은 inline — 브라우저 <audio>/blob 재생용. ?download=1 일 때만 파일 저장 유도.
    disposition = "attachment" if download else "inline"
    headers = {
        "Content-Length": str(length),
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'{disposition}; filename="recording_{meeting_id}.mp3"',
        "Cache-Control": "no-store",
    }
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"

    return StreamingResponse(
        bounded_reader(),
        status_code=status_code,
        media_type="audio/mpeg",
        headers=headers,
    )
