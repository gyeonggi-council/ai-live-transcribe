"""자막 생성 백그라운드 태스크

VOD 자막 생성을 백그라운드에서 처리하는 태스크입니다.

특징:
- asyncio 기반 비동기 처리
- 회의 상태 자동 업데이트 (processing -> ended/error)
- 진행률 추적 (선택)
- 에러 핸들링 및 재시도
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.vod_processor import VodProcessor


# ============================================================================
# Task Status
# ============================================================================


@dataclass
class TaskStatus:
    """태스크 상태

    Attributes:
        task_id: 태스크 ID
        meeting_id: 회의 ID
        status: 상태 (pending, running, completed, failed)
        progress: 진행률 (0.0~1.0)
        message: 상태 메시지
        error: 에러 메시지 (실패 시)
        started_at: 시작 시각
        completed_at: 완료 시각
        result: 처리 결과 (완료 시)
    """

    task_id: str
    meeting_id: uuid.UUID
    status: str = "pending"
    progress: float = 0.0
    message: str = ""
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None


# ============================================================================
# Subtitle Generation Task
# ============================================================================


class SubtitleGenerationTask:
    """자막 생성 태스크

    VOD 자막 생성을 백그라운드에서 처리합니다.

    사용 예:
    ```python
    task = SubtitleGenerationTask(vod_processor, db_factory)
    task_id = await task.submit(meeting_id, vod_url)
    status = task.get_status(task_id)
    ```
    """

    def __init__(
        self,
        vod_processor: VodProcessor,
        db_session_factory: Callable[[], AsyncSession],
    ):
        """태스크 초기화

        Args:
            vod_processor: VOD 프로세서 서비스
            db_session_factory: DB 세션 팩토리 함수
        """
        self._vod_processor = vod_processor
        self._db_session_factory = db_session_factory
        self._tasks: dict[str, TaskStatus] = {}
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._max_retries = 3
        self._retry_delay = 5.0  # seconds

    @property
    def max_retries(self) -> int:
        """최대 재시도 횟수"""
        return self._max_retries

    def set_max_retries(self, value: int) -> None:
        """최대 재시도 횟수 설정"""
        self._max_retries = value

    # ========================================================================
    # Task Management
    # ========================================================================

    async def submit(
        self,
        meeting_id: uuid.UUID,
        vod_url: str,
        *,
        councilor_names: list[str] | None = None,
        apply_dictionary: bool = False,
    ) -> str:
        """태스크 제출

        Args:
            meeting_id: 회의 ID
            vod_url: VOD URL
            councilor_names: 의원 이름 목록
            apply_dictionary: 사전 후처리 적용 여부

        Returns:
            태스크 ID
        """
        task_id = str(uuid.uuid4())

        # 태스크 상태 초기화
        self._tasks[task_id] = TaskStatus(
            task_id=task_id,
            meeting_id=meeting_id,
            status="pending",
            message="대기 중",
        )

        # 백그라운드 태스크 생성
        asyncio_task = asyncio.create_task(
            self._run_task(
                task_id=task_id,
                meeting_id=meeting_id,
                vod_url=vod_url,
                councilor_names=councilor_names,
                apply_dictionary=apply_dictionary,
            )
        )
        self._running_tasks[task_id] = asyncio_task

        return task_id

    def get_status(self, task_id: str) -> TaskStatus | None:
        """태스크 상태 조회

        Args:
            task_id: 태스크 ID

        Returns:
            TaskStatus 또는 None (태스크가 없는 경우)
        """
        return self._tasks.get(task_id)

    def get_all_statuses(self) -> list[TaskStatus]:
        """모든 태스크 상태 조회

        Returns:
            TaskStatus 리스트
        """
        return list(self._tasks.values())

    async def cancel(self, task_id: str) -> bool:
        """태스크 취소

        Args:
            task_id: 태스크 ID

        Returns:
            취소 성공 여부
        """
        if task_id not in self._running_tasks:
            return False

        asyncio_task = self._running_tasks[task_id]
        if asyncio_task.done():
            return False

        asyncio_task.cancel()

        # 상태 업데이트
        if task_id in self._tasks:
            self._tasks[task_id].status = "cancelled"
            self._tasks[task_id].message = "취소됨"
            self._tasks[task_id].completed_at = datetime.now(timezone.utc)

        return True

    # ========================================================================
    # Task Execution
    # ========================================================================

    async def _run_task(
        self,
        task_id: str,
        meeting_id: uuid.UUID,
        vod_url: str,
        *,
        councilor_names: list[str] | None = None,
        apply_dictionary: bool = False,
    ) -> None:
        """태스크 실행 (내부 메서드)

        재시도 로직이 포함되어 있습니다.

        Args:
            task_id: 태스크 ID
            meeting_id: 회의 ID
            vod_url: VOD URL
            councilor_names: 의원 이름 목록
            apply_dictionary: 사전 후처리 적용 여부
        """
        status = self._tasks[task_id]
        status.status = "running"
        status.started_at = datetime.now(timezone.utc)
        status.message = "처리 시작"

        retries = 0
        last_error: Exception | None = None

        while retries <= self._max_retries:
            try:
                # 진행률 콜백 설정
                def progress_callback(progress: float, message: str) -> None:
                    status.progress = progress
                    status.message = message

                self._vod_processor.set_progress_callback(progress_callback)

                # DB 세션 생성
                db = self._db_session_factory()

                try:
                    # VOD 처리
                    result = await self._vod_processor.process_vod(
                        vod_url=vod_url,
                        meeting_id=meeting_id,
                        db=db,
                        councilor_names=councilor_names,
                        apply_dictionary=apply_dictionary,
                    )

                    if result["status"] == "completed":
                        status.status = "completed"
                        status.progress = 1.0
                        status.message = "처리 완료"
                        status.result = result
                        status.completed_at = datetime.now(timezone.utc)
                        return
                    else:
                        raise Exception(result.get("error", "Unknown error"))

                finally:
                    await db.close()

            except asyncio.CancelledError:
                status.status = "cancelled"
                status.message = "취소됨"
                status.completed_at = datetime.now(timezone.utc)
                raise

            except Exception as e:
                last_error = e
                retries += 1

                if retries <= self._max_retries:
                    status.message = f"재시도 {retries}/{self._max_retries}"
                    await asyncio.sleep(self._retry_delay)
                continue

        # 모든 재시도 실패
        status.status = "failed"
        status.error = str(last_error) if last_error else "Unknown error"
        status.message = f"실패: {status.error}"
        status.completed_at = datetime.now(timezone.utc)

    # ========================================================================
    # Cleanup
    # ========================================================================

    def cleanup_completed(self, max_age_hours: int = 24) -> int:
        """완료된 태스크 정리

        Args:
            max_age_hours: 정리할 최대 시간 (시간)

        Returns:
            정리된 태스크 수
        """
        now = datetime.now(timezone.utc)
        removed = 0

        task_ids_to_remove = []
        for task_id, status in self._tasks.items():
            if status.status in ("completed", "failed", "cancelled"):
                if status.completed_at:
                    age_hours = (
                        now - status.completed_at
                    ).total_seconds() / 3600
                    if age_hours > max_age_hours:
                        task_ids_to_remove.append(task_id)

        for task_id in task_ids_to_remove:
            del self._tasks[task_id]
            if task_id in self._running_tasks:
                del self._running_tasks[task_id]
            removed += 1

        return removed
