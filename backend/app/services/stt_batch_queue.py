"""AI 자막 일괄 생성 큐 — 서버 측 순차 처리, 프로세스당 배치 1개.

원래 `api/meetings.py` 안에 있던 `_stt_batch` 상태와 `_run_stt_batch` 를 서비스로
옮겼다(2026-09-03). 이유: VOD 등록 직후 자동 생성(`vod_auto_stt`)과 관리자 버튼
(`POST /api/meetings/stt-batch`)이 **같은 "동시에 배치 1개" 가드**를 써야 한다 —
둘이 따로 큐를 들고 있으면 같은 회의가 두 번 전사돼 자막이 2벌 들어가고 비용도 2배다
(인메모리 가드만 있던 시절 재시작 직후 실제로 났던 사고와 같은 모양).

상태는 인메모리(재시작 시 소멸 — 잔여분은 다시 요청). 브라우저가 큐를 돌리면 페이지를
닫는 순간 다음 회의가 시작되지 않으므로 서버 백그라운드 태스크가 돈다.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_state: dict[str, Any] = {
    "running": False,
    "queue": [],        # 대기 중 meeting_id
    "current": None,    # 처리 중 meeting_id
    "done": [],         # 성공 meeting_id
    "failed": [],       # {meeting_id, reason}
    "source": None,     # "manual" | "auto"
    "started_at": None,
    "finished_at": None,
}

# 자동 실행의 마지막 요약 (vod_auto_stt.run_once 가 기록) — 관리자 조회용
_last_auto_run: Optional[dict[str, Any]] = None


def is_running() -> bool:
    return bool(_state["running"])


def status() -> dict[str, Any]:
    """진행 상태 스냅샷 (API 응답용). current_progress 는 라우터가 붙인다."""
    return {
        "running": _state["running"],
        "current": _state["current"],
        "pending": list(_state["queue"]),
        "done": list(_state["done"]),
        "failed": list(_state["failed"]),
        "source": _state["source"],
        "started_at": _state["started_at"],
        "finished_at": _state["finished_at"],
        "last_auto_run": _last_auto_run,
    }


def record_auto_run(summary: dict[str, Any]) -> None:
    global _last_auto_run
    _last_auto_run = dict(summary)


def last_auto_run() -> Optional[dict[str, Any]]:
    return _last_auto_run


def _claim(meeting_ids: list[str], source: str) -> bool:
    """배치 슬롯을 잡는다. 이미 돌고 있으면 False (호출자가 409/건너뜀 처리)."""
    if _state["running"]:
        return False
    _state.update({
        "running": True,
        "queue": list(meeting_ids),
        "current": None,
        "done": [],
        "failed": [],
        "source": source,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "finished_at": None,
    })
    return True


async def _process_queue(supabase_factory: Callable[[], Any]) -> None:
    """큐의 회의를 한 번에 1건씩 순차 처리한다 (비용·부하 통제)."""
    from app.services.meeting_service import get_meeting_by_id_service
    from app.services.vod_stt_service import VodSttService, get_task_by_meeting, is_processing

    try:
        while _state["queue"]:
            meeting_id = _state["queue"].pop(0)
            _state["current"] = meeting_id
            supabase = supabase_factory()
            meeting = get_meeting_by_id_service(supabase, meeting_id)
            vod_url = (meeting or {}).get("vod_url")
            if not meeting or not vod_url:
                _state["failed"].append({"meeting_id": meeting_id, "reason": "VOD 미등록"})
                continue
            if meeting.get("status") in ("live", "processing") or is_processing(meeting_id):
                _state["failed"].append({"meeting_id": meeting_id, "reason": "이미 처리 중이거나 생중계"})
                continue
            try:
                await VodSttService().process(meeting_id, vod_url, supabase)
            except Exception as e:
                _state["failed"].append({"meeting_id": meeting_id, "reason": str(e)[:120]})
                continue
            task = get_task_by_meeting(meeting_id)
            if task and task.status == "completed":
                _state["done"].append(meeting_id)
            else:
                _state["failed"].append(
                    {"meeting_id": meeting_id, "reason": (task.error if task else None) or "실패"}
                )
    finally:
        _state["current"] = None
        _state["running"] = False
        _state["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")


async def run_batch(
    meeting_ids: list[str], supabase_factory: Callable[[], Any], *, source: str = "manual"
) -> Optional[dict[str, Any]]:
    """배치를 잡아 **끝날 때까지** 처리하고 요약을 돌려준다. 이미 돌고 있으면 None."""
    ids = list(dict.fromkeys(meeting_ids))
    if not ids or not _claim(ids, source):
        return None
    await _process_queue(supabase_factory)
    return {"done": list(_state["done"]), "failed": list(_state["failed"]), "source": source}


def start_batch(
    meeting_ids: list[str], supabase_factory: Callable[[], Any], *, source: str = "manual"
) -> bool:
    """배치를 잡아 백그라운드로 돌린다(즉시 반환). 이미 돌고 있으면 False."""
    ids = list(dict.fromkeys(meeting_ids))
    if not ids or not _claim(ids, source):
        return False
    asyncio.create_task(_process_queue(supabase_factory), name=f"stt-batch-{source}")
    return True


def _reset_for_tests() -> None:
    global _last_auto_run
    _state.update({
        "running": False, "queue": [], "current": None, "done": [], "failed": [],
        "source": None, "started_at": None, "finished_at": None,
    })
    _last_auto_run = None
