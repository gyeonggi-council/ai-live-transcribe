"""리포지토리 계층 — Supabase 테이블 접근 전담

규칙 (docs/architecture/backend-layering.md 참조):
- `.table()` 호출은 이 패키지에만 둔다 (레거시 모듈은 점진 이관).
- 예외를 삼키지 않는다 — 폴백/HTTPException/로깅은 서비스·라우터 소관.
- `.single()` 사용 금지, select 컬럼 문자열·체인 순서는 기존 쿼리를 그대로 유지.
- 반환은 raw dict(list) — Pydantic 변환 금지.
"""

from app.repositories.dictionary_repository import DictionaryRepository
from app.repositories.meeting_repository import MeetingRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.subtitle_repository import SubtitleRepository

__all__ = [
    "DictionaryRepository",
    "MeetingRepository",
    "NotificationRepository",
    "SubtitleRepository",
]
