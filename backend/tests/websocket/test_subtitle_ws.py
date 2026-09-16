"""WebSocket 자막 실시간 스트리밍 테스트 - TDD"""

import uuid
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.websocket import ConnectionManager, manager


class TestConnectionManager:
    """ConnectionManager 클래스 테스트"""

    def test_connection_manager_exists(self) -> None:
        """ConnectionManager 클래스가 존재한다"""
        from app.api.websocket import ConnectionManager
        assert ConnectionManager is not None

    def test_connection_manager_has_connect_method(self) -> None:
        """ConnectionManager에 connect 메서드가 있다"""
        cm = ConnectionManager()
        assert hasattr(cm, "connect")
        assert callable(cm.connect)

    def test_connection_manager_has_disconnect_method(self) -> None:
        """ConnectionManager에 disconnect 메서드가 있다"""
        cm = ConnectionManager()
        assert hasattr(cm, "disconnect")
        assert callable(cm.disconnect)

    def test_connection_manager_has_broadcast_subtitle_method(self) -> None:
        """ConnectionManager에 broadcast_subtitle 메서드가 있다"""
        cm = ConnectionManager()
        assert hasattr(cm, "broadcast_subtitle")
        assert callable(cm.broadcast_subtitle)

    def test_connection_manager_initializes_empty_connections(self) -> None:
        """ConnectionManager 초기화 시 빈 연결 딕셔너리를 가진다"""
        cm = ConnectionManager()
        assert hasattr(cm, "active_connections")
        assert isinstance(cm.active_connections, dict)
        assert len(cm.active_connections) == 0


class TestWebSocketEndpoint:
    """WebSocket 엔드포인트 테스트"""

    @pytest.fixture
    def client(self) -> TestClient:
        """테스트 클라이언트"""
        return TestClient(app)

    @pytest.fixture
    def meeting_id(self) -> uuid.UUID:
        """테스트용 회의 ID"""
        return uuid.uuid4()

    def test_websocket_endpoint_exists(
        self, client: TestClient, meeting_id: uuid.UUID
    ) -> None:
        """WebSocket 엔드포인트가 존재한다"""
        # WebSocket 연결 테스트 - 정상적으로 연결되어야 함
        with client.websocket_connect(f"/ws/meetings/{meeting_id}/subtitles") as ws:
            # 연결이 성공하면 테스트 통과
            pass

    def test_websocket_accepts_valid_meeting_id(
        self, client: TestClient, meeting_id: uuid.UUID
    ) -> None:
        """유효한 meeting_id로 WebSocket 연결이 가능하다"""
        with client.websocket_connect(f"/ws/meetings/{meeting_id}/subtitles") as ws:
            # 연결 성공
            assert ws is not None

    def test_websocket_multiple_connections_same_meeting(
        self, client: TestClient, meeting_id: uuid.UUID
    ) -> None:
        """같은 회의에 여러 클라이언트가 연결할 수 있다"""
        with client.websocket_connect(f"/ws/meetings/{meeting_id}/subtitles") as ws1:
            with client.websocket_connect(f"/ws/meetings/{meeting_id}/subtitles") as ws2:
                assert ws1 is not None
                assert ws2 is not None


class TestSubtitleBroadcast:
    """자막 브로드캐스트 테스트"""

    @pytest.fixture
    def client(self) -> TestClient:
        """테스트 클라이언트"""
        return TestClient(app)

    @pytest.fixture
    def meeting_id(self) -> uuid.UUID:
        """테스트용 회의 ID"""
        return uuid.uuid4()

    @pytest.fixture
    def sample_subtitle_payload(self, meeting_id: uuid.UUID) -> dict:
        """샘플 자막 페이로드"""
        return {
            "id": str(uuid.uuid4()),
            "meeting_id": str(meeting_id),
            "start_time": 123.45,
            "end_time": 126.78,
            "text": "테스트 자막 텍스트입니다",
            "speaker": "홍길동",
            "confidence": 0.95,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    @pytest.mark.asyncio
    async def test_broadcast_subtitle_sends_to_all_clients(
        self, meeting_id: uuid.UUID, sample_subtitle_payload: dict
    ) -> None:
        """broadcast_subtitle이 해당 방의 모든 클라이언트에 메시지를 전송한다"""
        cm = ConnectionManager()

        # Mock WebSocket 생성
        mock_ws1 = MagicMock()
        mock_ws1.send_json = MagicMock()
        mock_ws2 = MagicMock()
        mock_ws2.send_json = MagicMock()

        # 연결 추가
        await cm.connect(mock_ws1, meeting_id)
        await cm.connect(mock_ws2, meeting_id)

        # 브로드캐스트
        await cm.broadcast_subtitle(meeting_id, sample_subtitle_payload)

        # 두 클라이언트 모두에게 메시지가 전송되었는지 확인
        expected_message = {
            "type": "subtitle_created",
            "payload": sample_subtitle_payload,
        }
        mock_ws1.send_json.assert_called_once_with(expected_message)
        mock_ws2.send_json.assert_called_once_with(expected_message)

    @pytest.mark.asyncio
    async def test_broadcast_subtitle_only_to_same_meeting(
        self, sample_subtitle_payload: dict
    ) -> None:
        """broadcast_subtitle은 같은 meeting_id의 클라이언트에만 전송한다"""
        cm = ConnectionManager()

        meeting_id_1 = uuid.uuid4()
        meeting_id_2 = uuid.uuid4()

        # Mock WebSocket 생성
        mock_ws1 = MagicMock()
        mock_ws1.send_json = MagicMock()
        mock_ws2 = MagicMock()
        mock_ws2.send_json = MagicMock()

        # 다른 회의에 각각 연결
        await cm.connect(mock_ws1, meeting_id_1)
        await cm.connect(mock_ws2, meeting_id_2)

        # meeting_id_1에만 브로드캐스트
        sample_subtitle_payload["meeting_id"] = str(meeting_id_1)
        await cm.broadcast_subtitle(meeting_id_1, sample_subtitle_payload)

        # meeting_id_1의 클라이언트만 메시지를 받아야 함
        mock_ws1.send_json.assert_called_once()
        mock_ws2.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_disconnect_removes_connection(
        self, meeting_id: uuid.UUID
    ) -> None:
        """disconnect가 연결을 제거한다"""
        cm = ConnectionManager()

        mock_ws = MagicMock()
        mock_ws.send_json = MagicMock()

        # 연결 후 연결 해제
        await cm.connect(mock_ws, meeting_id)
        assert meeting_id in cm.active_connections
        assert mock_ws in cm.active_connections[meeting_id]

        cm.disconnect(mock_ws, meeting_id)

        # 연결이 제거되었는지 확인
        if meeting_id in cm.active_connections:
            assert mock_ws not in cm.active_connections[meeting_id]

    @pytest.mark.asyncio
    async def test_disconnect_cleans_up_empty_room(
        self, meeting_id: uuid.UUID
    ) -> None:
        """마지막 연결 해제 시 빈 방을 정리한다"""
        cm = ConnectionManager()

        mock_ws = MagicMock()

        # 연결 후 연결 해제
        await cm.connect(mock_ws, meeting_id)
        cm.disconnect(mock_ws, meeting_id)

        # 빈 방은 딕셔너리에서 제거되어야 함
        assert meeting_id not in cm.active_connections


class TestWebSocketMessageFormat:
    """WebSocket 메시지 형식 테스트"""

    @pytest.fixture
    def meeting_id(self) -> uuid.UUID:
        """테스트용 회의 ID"""
        return uuid.uuid4()

    @pytest.fixture
    def sample_subtitle_payload(self, meeting_id: uuid.UUID) -> dict:
        """샘플 자막 페이로드"""
        return {
            "id": str(uuid.uuid4()),
            "meeting_id": str(meeting_id),
            "start_time": 123.45,
            "end_time": 126.78,
            "text": "테스트 자막",
            "speaker": "홍길동",
            "confidence": 0.95,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    @pytest.mark.asyncio
    async def test_message_has_correct_type(
        self, meeting_id: uuid.UUID, sample_subtitle_payload: dict
    ) -> None:
        """메시지에 올바른 type 필드가 있다"""
        cm = ConnectionManager()

        mock_ws = MagicMock()
        sent_message = None

        def capture_message(msg):
            nonlocal sent_message
            sent_message = msg

        mock_ws.send_json = MagicMock(side_effect=capture_message)

        await cm.connect(mock_ws, meeting_id)
        await cm.broadcast_subtitle(meeting_id, sample_subtitle_payload)

        assert sent_message is not None
        assert "type" in sent_message
        assert sent_message["type"] == "subtitle_created"

    @pytest.mark.asyncio
    async def test_message_has_correct_payload(
        self, meeting_id: uuid.UUID, sample_subtitle_payload: dict
    ) -> None:
        """메시지에 올바른 payload 필드가 있다"""
        cm = ConnectionManager()

        mock_ws = MagicMock()
        sent_message = None

        def capture_message(msg):
            nonlocal sent_message
            sent_message = msg

        mock_ws.send_json = MagicMock(side_effect=capture_message)

        await cm.connect(mock_ws, meeting_id)
        await cm.broadcast_subtitle(meeting_id, sample_subtitle_payload)

        assert sent_message is not None
        assert "payload" in sent_message
        assert sent_message["payload"] == sample_subtitle_payload

    @pytest.mark.asyncio
    async def test_payload_contains_required_fields(
        self, meeting_id: uuid.UUID, sample_subtitle_payload: dict
    ) -> None:
        """payload에 필수 필드가 모두 포함되어 있다"""
        required_fields = [
            "id", "meeting_id", "start_time", "end_time",
            "text", "speaker", "confidence", "created_at"
        ]

        for field in required_fields:
            assert field in sample_subtitle_payload, f"Missing field: {field}"


class TestGlobalManager:
    """전역 ConnectionManager 인스턴스 테스트"""

    def test_global_manager_exists(self) -> None:
        """전역 manager 인스턴스가 존재한다"""
        from app.api.websocket import manager
        assert manager is not None
        assert isinstance(manager, ConnectionManager)
