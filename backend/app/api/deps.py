"""라우터 공용 의존성 팩토리 — 리포지토리 주입

리포지토리는 get_supabase 의존성을 경유해 Client를 받으므로,
tests/conftest.py 의 `app.dependency_overrides[get_supabase]` 가
리포지토리 내부까지 그대로 관통한다 (테스트 픽스처 무변경 보증).
"""

from typing import Generator

from fastapi import Depends
from sqlalchemy.orm import Session
from supabase import Client

from app.core.database import get_supabase
from app.core.postgres import get_postgres_session, is_postgres_backend
from app.repositories.clip_job_repository import ClipJobRepository
from app.repositories.dictionary_repository import DictionaryRepository
from app.repositories.meeting_repository import MeetingRepository
from app.repositories.notification_repository import NotificationRepository, PgNotificationRepository
from app.repositories.subtitle_repository import SubtitleRepository


def get_postgres_session_for_backend() -> Generator[Session | None, None, None]:
    """PostgreSQL 모드에서만 request-scoped session을 제공합니다."""
    if not is_postgres_backend():
        yield None
        return
    yield from get_postgres_session()


def get_supabase_for_backend(
    supabase: Client | None = Depends(get_supabase),
) -> Client | None:
    """기존 FastAPI Supabase override를 보존하는 선택적 client dependency."""
    return supabase


def get_meeting_repository(
    supabase: Client = Depends(get_supabase),
) -> MeetingRepository:
    return MeetingRepository(supabase)


def get_subtitle_repository(
    supabase: Client = Depends(get_supabase),
) -> SubtitleRepository:
    return SubtitleRepository(supabase)


def get_notification_repository(
    session: Session | None = Depends(get_postgres_session_for_backend),
    supabase: Client | None = Depends(get_supabase_for_backend),
) -> NotificationRepository | PgNotificationRepository:
    """현재 DB backend에 맞는 notifications 리포지토리를 선택합니다."""
    if session is not None:
        return PgNotificationRepository(session)
    if supabase is not None:
        return NotificationRepository(supabase)
    raise RuntimeError("선택된 DB backend의 notifications resource를 가져올 수 없습니다.")


def get_dictionary_repository(
    supabase: Client = Depends(get_supabase),
) -> DictionaryRepository:
    return DictionaryRepository(supabase)


def get_clip_job_repository(
    supabase: Client = Depends(get_supabase),
) -> ClipJobRepository:
    """발언영상 클립 잡(clip_jobs) 리포지토리."""
    return ClipJobRepository(supabase)
