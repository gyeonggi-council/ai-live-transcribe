"""WebSocket 실시간 자막 스트리밍

경로: /ws/meetings/{meeting_id}/subtitles
  - meeting_id: UUID meeting ID 또는 channel ID (예: ch8)
"""

import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.database import get_supabase_client

router = APIRouter(tags=["websocket"])
logger = logging.getLogger(__name__)


class ConnectionManager:
    """WebSocket 연결 관리자

    방(room_id)별로 WebSocket 연결을 관리하고
    자막 브로드캐스트 기능을 제공합니다.
    room_id는 meeting UUID 또는 channel ID(str) 모두 가능합니다.

    자막 히스토리:
    - 채널별로 최근 HISTORY_SIZE개의 자막을 메모리에 보관
    - 새 클라이언트 접속 시 히스토리를 일괄 전송 (늦게 들어와도 이전 자막 확인 가능)
    """

    HISTORY_SIZE = 200  # 채널당 보관할 최대 자막 수

    def __init__(self) -> None:
        """ConnectionManager 초기화"""
        self.active_connections: dict[str, list[WebSocket]] = {}
        self.subtitle_history: dict[str, list[dict[str, Any]]] = {}

    async def connect(self, websocket: WebSocket, room_id: str) -> None:
        """WebSocket 연결을 방에 추가하고, 기존 자막 히스토리를 전송"""
        if hasattr(websocket, "accept") and callable(websocket.accept):
            try:
                await websocket.accept()
            except Exception:
                pass

        if room_id not in self.active_connections:
            self.active_connections[room_id] = []

        self.active_connections[room_id].append(websocket)
        count = len(self.active_connections[room_id])
        logger.info("connection open: room=%s, total=%d", room_id, count)

        # 늦게 접속한 사용자에게 자막 히스토리 전송
        # 1. DB에서 전체 히스토리 로드 시도 (생중계 회의가 있는 경우)
        # 2. 폴백: 인메모리 버퍼 사용
        history_subtitles = await self._load_history_for_room(room_id)

        if history_subtitles:
            try:
                await websocket.send_json({
                    "type": "subtitle_history",
                    "payload": {
                        "subtitles": history_subtitles,
                    },
                })
                logger.info(
                    "sent %d history subtitles to new client: room=%s",
                    len(history_subtitles), room_id,
                )
            except Exception:
                logger.warning("failed to send history to client: room=%s", room_id)

    def disconnect(self, websocket: WebSocket, room_id: str) -> None:
        """WebSocket 연결을 방에서 제거"""
        if room_id in self.active_connections:
            if websocket in self.active_connections[room_id]:
                self.active_connections[room_id].remove(websocket)

            if not self.active_connections[room_id]:
                del self.active_connections[room_id]

    async def broadcast_subtitle(
        self, room_id: str, subtitle_data: dict[str, Any]
    ) -> None:
        """자막을 히스토리에 저장하고 해당 방의 모든 클라이언트에 브로드캐스트"""
        # 히스토리에 저장
        if room_id not in self.subtitle_history:
            self.subtitle_history[room_id] = []
        self.subtitle_history[room_id].append(subtitle_data)
        # 크기 제한
        if len(self.subtitle_history[room_id]) > self.HISTORY_SIZE:
            self.subtitle_history[room_id] = self.subtitle_history[room_id][-self.HISTORY_SIZE:]

        # 실시간 브로드캐스트
        message = {
            "type": "subtitle_created",
            "payload": subtitle_data,
        }

        if room_id in self.active_connections:
            disconnected = []

            for websocket in self.active_connections[room_id]:
                try:
                    await websocket.send_json(message)
                except Exception:
                    disconnected.append(websocket)

            for websocket in disconnected:
                self.disconnect(websocket, room_id)

    async def broadcast_interim_subtitle(
        self, room_id: str, interim_data: dict[str, Any]
    ) -> None:
        """인터림 자막 브로드캐스트 (히스토리 저장 안함)

        확정 전 미리보기 자막을 클라이언트에 전송합니다.
        히스토리에는 저장하지 않으며, 확정 자막(subtitle_created)이
        도착하면 프론트엔드에서 교체합니다.
        """
        message = {
            "type": "subtitle_interim",
            "payload": interim_data,
        }

        if room_id in self.active_connections:
            disconnected = []
            for websocket in self.active_connections[room_id]:
                try:
                    await websocket.send_json(message)
                except Exception:
                    disconnected.append(websocket)
            for websocket in disconnected:
                self.disconnect(websocket, room_id)

    async def broadcast_corrected_subtitle(
        self, room_id: str, correction_data: dict[str, Any]
    ) -> None:
        """교정된 자막을 브로드캐스트합니다.

        기존 자막의 텍스트를 교정된 텍스트로 업데이트합니다.
        히스토리에서도 해당 자막을 찾아 교정합니다.
        """
        # 히스토리에서 해당 자막 업데이트
        # corrected_text는 텍스트 교정 경로에서만, speaker는 화자 구분(diarize) 경로에서 온다.
        # diarize는 speaker만 보내므로 둘 중 하나만 와도 안전하게 반영한다.
        sub_id = correction_data.get("id", "")
        corrected_text = correction_data.get("corrected_text")
        has_speaker = "speaker" in correction_data
        if room_id in self.subtitle_history and sub_id and (corrected_text or has_speaker):
            for item in self.subtitle_history[room_id]:
                subtitle = item.get("subtitle", {})
                if subtitle.get("id") == sub_id:
                    if corrected_text:
                        subtitle["original_text"] = subtitle.get("text", "")
                        subtitle["text"] = corrected_text
                        subtitle["is_corrected"] = True
                    if has_speaker:
                        subtitle["speaker"] = correction_data["speaker"]
                    break

        message = {
            "type": "subtitle_corrected",
            "payload": correction_data,
        }

        if room_id in self.active_connections:
            disconnected = []
            for websocket in self.active_connections[room_id]:
                try:
                    await websocket.send_json(message)
                except Exception:
                    disconnected.append(websocket)
            for websocket in disconnected:
                self.disconnect(websocket, room_id)

    async def broadcast_material_request(
        self, room_id: str, request_data: dict[str, Any]
    ) -> None:
        """감지된 요구자료를 브로드캐스트합니다 (모니터링 직원 실시간 알림).

        히스토리에는 저장하지 않는다 — 클라이언트는 REST(material-requests)로
        초기 목록을 로드하고, 이 이벤트로 증분만 반영한다.
        """
        message = {"type": "material_request_detected", "payload": request_data}
        if room_id in self.active_connections:
            disconnected = []
            for websocket in self.active_connections[room_id]:
                try:
                    await websocket.send_json(message)
                except Exception:
                    disconnected.append(websocket)
            for websocket in disconnected:
                self.disconnect(websocket, room_id)

    async def broadcast_stt_status(self, room_id: str, status: dict[str, Any]) -> None:
        """자막 생성 상태를 브로드캐스트합니다 (서버가 단일 진실 — 모든 시청자 동일).

        프런트 상태 바('자막 생성 중/음성 대기/정회')가 각 브라우저의 수신 시점이
        아니라 백엔드의 실제 STT 상태를 표시하도록 한다. 히스토리에는 저장 안 함.
        """
        message = {"type": "stt_status", "payload": status}
        if room_id in self.active_connections:
            disconnected = []
            for websocket in self.active_connections[room_id]:
                try:
                    await websocket.send_json(message)
                except Exception:
                    disconnected.append(websocket)
            for websocket in disconnected:
                self.disconnect(websocket, room_id)

    async def broadcast_correction_failed(
        self, room_id: str, subtitle_id: str, reason: str
    ) -> None:
        """교정 실패 이벤트를 브로드캐스트합니다.

        프론트엔드에서 pending 상태를 해제하기 위해 사용합니다.
        히스토리에는 저장하지 않습니다.
        """
        message = {
            "type": "subtitle_correction_failed",
            "payload": {
                "subtitle_id": subtitle_id,
                "reason": reason,
            },
        }

        if room_id in self.active_connections:
            disconnected = []
            for websocket in self.active_connections[room_id]:
                try:
                    await websocket.send_json(message)
                except Exception:
                    disconnected.append(websocket)
            for websocket in disconnected:
                self.disconnect(websocket, room_id)

    async def _load_history_for_room(self, room_id: str) -> list[dict]:
        """방의 자막 히스토리를 로드합니다.

        생중계 채널인 경우 DB에서 전체 자막을 로드하고,
        실패하거나 데이터가 없으면 인메모리 버퍼를 사용합니다.
        """
        # DB에서 로드 시도 (채널 ID인 경우 LiveMeetingManager로 회의 UUID 조회)
        try:
            from app.services.live_meeting import get_live_meeting_manager

            meeting_id = get_live_meeting_manager().get_meeting_id(room_id)
            if meeting_id:
                supabase = get_supabase_client()
                result = (
                    supabase.table("subtitles")
                    .select("id, meeting_id, text, start_time, end_time, confidence, speaker, created_at")
                    .eq("meeting_id", meeting_id)
                    .order("start_time")
                    .execute()
                )
                if result.data:
                    logger.info(
                        "loaded %d subtitles from DB for room=%s (meeting=%s)",
                        len(result.data), room_id, meeting_id,
                    )
                    return result.data
        except Exception as e:
            logger.warning("failed to load DB history for room=%s: %s", room_id, e)

        # 폴백: 인메모리 히스토리
        history = self.subtitle_history.get(room_id, [])
        return [item["subtitle"] for item in history if "subtitle" in item]

    def clear_history(self, room_id: str) -> None:
        """특정 방의 자막 히스토리를 초기화합니다."""
        if room_id in self.subtitle_history:
            del self.subtitle_history[room_id]
            logger.info("cleared subtitle history: room=%s", room_id)


# 전역 ConnectionManager 인스턴스
manager = ConnectionManager()


async def _handle_ws(websocket: WebSocket, room_id: str) -> None:
    """WebSocket 연결을 처리하는 공통 로직."""
    await manager.connect(websocket, room_id)
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, room_id)


@router.websocket("/ws/meetings/{meeting_id}/subtitles")
async def websocket_subtitle_endpoint(
    websocket: WebSocket, meeting_id: str
) -> None:
    """실시간 자막 WebSocket 엔드포인트 (meeting UUID 또는 channel ID)"""
    await _handle_ws(websocket, meeting_id)
