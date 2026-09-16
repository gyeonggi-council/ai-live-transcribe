"""회의 서비스 — 조회/생성 정책 (채널 정적 폴백 포함)

api/meetings.py 에서 이관. "meetings 테이블이 없으면 channels 정적 데이터로
서비스를 유지한다"는 폴백은 도메인 정책이므로 이 계층이 소유한다.
리포지토리는 쿼리만 하고 예외를 전파한다.

※ api/meetings.py 가 이 함수들을 bare-name 으로 re-export 한다 —
   테스트가 app.api.meetings.* 를 patch 하므로 시그니처·이름 변경 금지.
"""

import logging
from datetime import date
from typing import Optional

from supabase import Client

from app.core.channels import get_all_channels, get_channel
from app.repositories.meeting_repository import MeetingRepository
from app.schemas.meeting import MeetingCreate, MeetingStatus

logger = logging.getLogger(__name__)


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


def get_meetings_service(
    supabase: Client,
    statuses: Optional[list[MeetingStatus]] = None,
    limit: int = 10,
    offset: int = 0,
) -> list[dict]:
    """회의 목록을 조회합니다. meetings 테이블 없으면 채널 데이터 반환."""
    repo = MeetingRepository(supabase)
    try:
        status_values = [s.value for s in statuses] if statuses else None
        return repo.list(status_values, limit=limit, offset=offset)
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
    repo = MeetingRepository(supabase)

    if channel:
        # 1) 현재 방송 중 meeting
        try:
            row = repo.find_live_by_channel(channel)
            if row:
                return row
        except Exception as e:
            logger.warning("get_live_meeting: DB(live) 조회 실패 (%s)", e)

        # 2) 가장 최근 ended meeting (오늘 방송 종료된 회의 자막 열람)
        try:
            row = repo.find_recent_finished_by_channel(channel)
            if row:
                return row
        except Exception as e:
            logger.warning("get_live_meeting: DB(ended) 조회 실패 (%s)", e)

        # 3) 폴백: 채널 정적 정보 기반 meeting 스텁
        ch = get_channel(channel)
        if ch:
            return _channel_to_meeting(ch)
        return None

    try:
        return repo.find_any_live()
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
        return MeetingRepository(supabase).get_by_id(meeting_id)
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
    return MeetingRepository(supabase).insert(data)


def find_duplicate_vod(supabase: Client, vod_url: str) -> Optional[dict]:
    """vod_url 기준 기존 회의를 조회합니다. 쿼리 실패 시 경고만 남기고 None.

    (409 발생 여부는 라우터의 _check_duplicate_vod 가 판단한다.)
    """
    try:
        return MeetingRepository(supabase).find_by_vod_url(vod_url)
    except Exception as e:
        logger.warning("중복 체크 스킵 (meetings 테이블 조회 실패): %s", e)
        return None
