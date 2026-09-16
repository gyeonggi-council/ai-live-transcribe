"""Bills API 라우터 (Supabase REST)

의안(Bill) CRUD 및 의안-회의 연결(mention) 관리 API

@TASK P5-T4.2 - 의안 CRUD API
@SPEC docs/planning/
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from supabase import Client

from app.core.database import get_supabase
from app.schemas.bill import BillCreate, BillMentionCreate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bills", tags=["bills"])


# =============================================================================
# GET /api/bills - 의안 목록 조회
# =============================================================================


@router.get(
    "",
    summary="의안 목록 조회",
)
async def get_bills(
    committee: str | None = Query(None, description="위원회 필터"),
    bill_status: str | None = Query(None, alias="status", description="상태 필터"),
    q: str | None = Query(None, description="검색어 (의안명)"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    supabase: Client = Depends(get_supabase),
) -> dict:
    """의안 목록을 조회합니다.

    - committee: 소관 위원회로 필터링
    - status: 상태(received/reviewing/decided/promulgated)로 필터링
    - q: 의안명 ILIKE 검색
    - limit/offset: 페이지네이션
    """
    # 전체 개수 쿼리
    count_query = supabase.table("bills").select("id", count="exact")
    if committee:
        count_query = count_query.eq("committee", committee)
    if bill_status:
        count_query = count_query.eq("status", bill_status)
    if q:
        count_query = count_query.ilike("title", f"%{q}%")
    count_result = count_query.execute()
    total = count_result.count or 0

    # 데이터 쿼리
    data_query = supabase.table("bills").select("*")
    if committee:
        data_query = data_query.eq("committee", committee)
    if bill_status:
        data_query = data_query.eq("status", bill_status)
    if q:
        data_query = data_query.ilike("title", f"%{q}%")
    data_query = data_query.order("proposed_date", desc=True)
    data_query = data_query.range(offset, offset + limit - 1)
    result = data_query.execute()

    return {
        "items": result.data,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# =============================================================================
# GET /api/bills/{bill_id} - 의안 상세 조회 (관련 회의 포함)
# =============================================================================


@router.get(
    "/{bill_id}",
    summary="의안 상세 조회",
)
async def get_bill(
    bill_id: str,
    supabase: Client = Depends(get_supabase),
) -> dict:
    """의안 상세 정보를 조회합니다. 관련 회의(mentions) 정보를 포함합니다.

    1. bills 테이블에서 bill_id로 조회
    2. bill_mentions 테이블에서 해당 bill_id의 모든 mentions 조회
    3. mentions에 포함된 meeting_id들로 meetings 조회
    4. mentions에 meeting_title, meeting_date 추가
    """
    # 1. 의안 조회
    bill_result = (
        supabase.table("bills")
        .select("*")
        .eq("id", bill_id)
        .limit(1)
        .execute()
    )
    if not bill_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"의안을 찾을 수 없습니다 (id={bill_id})",
        )
    bill = bill_result.data[0]

    # 2. mentions 조회
    mentions_result = (
        supabase.table("bill_mentions")
        .select("*")
        .eq("bill_id", bill_id)
        .order("created_at", desc=True)
        .execute()
    )
    mentions = mentions_result.data

    # 3. meetings 정보 조회 및 매핑
    if mentions:
        meeting_ids = list({m["meeting_id"] for m in mentions})
        meetings_map: dict[str, dict] = {}
        for mid in meeting_ids:
            meeting_result = (
                supabase.table("meetings")
                .select("id,title,meeting_date")
                .eq("id", mid)
                .limit(1)
                .execute()
            )
            if meeting_result.data:
                meetings_map[mid] = meeting_result.data[0]

        # 4. mentions에 meeting 정보 추가
        for mention in mentions:
            meeting_info = meetings_map.get(mention["meeting_id"], {})
            mention["meeting_title"] = meeting_info.get("title")
            mention["meeting_date"] = meeting_info.get("meeting_date")

    bill["mentions"] = mentions
    return bill


# =============================================================================
# POST /api/bills - 의안 등록
# =============================================================================


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="의안 등록",
)
async def create_bill(
    data: BillCreate,
    supabase: Client = Depends(get_supabase),
) -> dict:
    """새 의안을 등록합니다.

    - bill_number 중복 체크
    - 생성된 의안 정보 반환
    """
    # bill_number 중복 체크
    existing = (
        supabase.table("bills")
        .select("id")
        .eq("bill_number", data.bill_number)
        .limit(1)
        .execute()
    )
    if existing.data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"이미 존재하는 의안번호입니다: {data.bill_number}",
        )

    # 데이터 준비
    insert_data: dict = {
        "bill_number": data.bill_number,
        "title": data.title,
        "status": data.status,
    }
    if data.proposer is not None:
        insert_data["proposer"] = data.proposer
    if data.committee is not None:
        insert_data["committee"] = data.committee
    if data.proposed_date is not None:
        insert_data["proposed_date"] = data.proposed_date.isoformat()

    # 생성
    result = supabase.table("bills").insert(insert_data).execute()

    logger.info("의안 등록 완료: bill_number=%s, title=%s", data.bill_number, data.title)
    return result.data[0]


# =============================================================================
# POST /api/bills/{bill_id}/mentions - 의안-회의 연결 등록
# =============================================================================


@router.post(
    "/{bill_id}/mentions",
    status_code=status.HTTP_201_CREATED,
    summary="의안-회의 연결 등록",
)
async def create_bill_mention(
    bill_id: str,
    data: BillMentionCreate,
    supabase: Client = Depends(get_supabase),
) -> dict:
    """의안과 회의를 연결합니다.

    - bill_id 존재 확인
    - meeting_id 존재 확인
    - 연결 정보 생성
    """
    # bill_id 존재 확인
    bill_result = (
        supabase.table("bills")
        .select("id")
        .eq("id", bill_id)
        .limit(1)
        .execute()
    )
    if not bill_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"의안을 찾을 수 없습니다 (id={bill_id})",
        )

    # meeting_id 존재 확인
    meeting_result = (
        supabase.table("meetings")
        .select("id")
        .eq("id", str(data.meeting_id))
        .limit(1)
        .execute()
    )
    if not meeting_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"회의를 찾을 수 없습니다 (id={data.meeting_id})",
        )

    # 데이터 준비
    insert_data: dict = {
        "bill_id": bill_id,
        "meeting_id": str(data.meeting_id),
    }
    if data.subtitle_id is not None:
        insert_data["subtitle_id"] = str(data.subtitle_id)
    if data.start_time is not None:
        insert_data["start_time"] = data.start_time
    if data.end_time is not None:
        insert_data["end_time"] = data.end_time
    if data.note is not None:
        insert_data["note"] = data.note

    # 생성
    result = supabase.table("bill_mentions").insert(insert_data).execute()

    logger.info(
        "의안-회의 연결 등록: bill_id=%s, meeting_id=%s",
        bill_id,
        data.meeting_id,
    )
    return result.data[0]


# =============================================================================
# GET /api/bills/{bill_id}/mentions - 의안-회의 연결 목록 조회
# =============================================================================


@router.get(
    "/{bill_id}/mentions",
    summary="의안-회의 연결 목록 조회",
)
async def get_bill_mentions(
    bill_id: str,
    supabase: Client = Depends(get_supabase),
) -> dict:
    """의안에 연결된 회의 목록을 조회합니다.

    - bill_id 존재 확인
    - bill_mentions 조회 + meeting 정보 포함
    """
    # bill_id 존재 확인
    bill_result = (
        supabase.table("bills")
        .select("id")
        .eq("id", bill_id)
        .limit(1)
        .execute()
    )
    if not bill_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"의안을 찾을 수 없습니다 (id={bill_id})",
        )

    # mentions 조회
    mentions_result = (
        supabase.table("bill_mentions")
        .select("*")
        .eq("bill_id", bill_id)
        .order("created_at", desc=True)
        .execute()
    )
    mentions = mentions_result.data

    # meeting 정보 추가
    if mentions:
        meeting_ids = list({m["meeting_id"] for m in mentions})
        meetings_map: dict[str, dict] = {}
        for mid in meeting_ids:
            meeting_result = (
                supabase.table("meetings")
                .select("id,title,meeting_date")
                .eq("id", mid)
                .limit(1)
                .execute()
            )
            if meeting_result.data:
                meetings_map[mid] = meeting_result.data[0]

        for mention in mentions:
            meeting_info = meetings_map.get(mention["meeting_id"], {})
            mention["meeting_title"] = meeting_info.get("title")
            mention["meeting_date"] = meeting_info.get("meeting_date")

    return {"items": mentions}
