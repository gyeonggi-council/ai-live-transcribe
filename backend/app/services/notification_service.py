"""알림 서비스 — 알림 생성 정책 (실패 무시)

meetings.py 등 다른 도메인이 상태 변경 시 호출한다.
api/meetings.py → api/notifications.py 크로스 라우터 import를 해소하기 위해
api/notifications.py의 create_notification_record를 이 모듈로 이관했다.
"""

import logging
from typing import Optional

from supabase import Client

from app.repositories.notification_repository import NotificationRepository

logger = logging.getLogger(__name__)


def create_notification_record(
    supabase: Client,
    notification_type: str,
    title: str,
    message: str,
    related_meeting_id: Optional[str] = None,
) -> Optional[dict]:
    """알림 레코드를 생성합니다.

    정책: 알림 생성 실패가 본 작업(회의 상태 변경 등)을 막지 않도록
    예외를 삼키고 None을 반환한다.
    """
    data = {
        "type": notification_type,
        "title": title,
        "message": message,
        "related_meeting_id": related_meeting_id,
        "is_read": False,
    }
    try:
        result = NotificationRepository(supabase).insert(data)
        return result[0] if result else data
    except Exception as e:
        logger.warning("알림 생성 실패 (무시됨): %s", e)
        return None
