"""백그라운드 태스크 모듈"""

from app.tasks.subtitle_generation import SubtitleGenerationTask

__all__ = ["SubtitleGenerationTask"]
