"""Subtitle SQLAlchemy 모델"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class Subtitle(Base):
    """자막 모델

    Attributes:
        id: 자막 고유 식별자 (UUID)
        meeting_id: 회의 FK (UUID)
        start_time: 시작 시간 (초)
        end_time: 종료 시간 (초)
        text: 자막 텍스트
        speaker: 화자 (선택)
        confidence: 인식 신뢰도 (0~1)
        created_at: 생성 시각
    """

    __tablename__ = "subtitles"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    meeting_id = Column(
        UUID(as_uuid=True),
        ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    text = Column(Text, nullable=False)
    speaker = Column(String(100), nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Subtitle(id={self.id}, meeting_id={self.meeting_id}, text={self.text[:20]}...)>"
