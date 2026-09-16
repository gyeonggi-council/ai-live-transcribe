"""AutoSttManager 테스트

방송 상태 변경에 따른 STT 자동 시작/중지 로직을 검증합니다.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.auto_stt import AutoSttManager, LIVESTATUS_BROADCASTING


@pytest.fixture
def mock_status_service():
    """Mock ChannelStatusService."""
    service = MagicMock()
    service.fetch_status = AsyncMock(return_value={})
    service.subscribe = MagicMock(return_value=asyncio.Queue())
    service.unsubscribe = MagicMock()
    return service


@pytest.fixture
def mock_stt_service():
    """Mock ChannelSttService."""
    service = MagicMock()
    service.start = AsyncMock()
    service.stop = AsyncMock()
    service.stop_all = AsyncMock()
    service.is_running = MagicMock(return_value=False)
    return service


@pytest.fixture
def mock_live_meeting_mgr():
    """Mock LiveMeetingManager."""
    mgr = MagicMock()
    mgr.create_meeting_for_channel = AsyncMock(return_value="test-meeting-uuid")
    mgr.end_meeting_for_channel = AsyncMock()
    mgr.recover_active_meetings = AsyncMock()
    mgr.get_meeting_id = MagicMock(return_value=None)
    return mgr


@pytest.fixture
def manager(mock_status_service, mock_stt_service, mock_live_meeting_mgr):
    """AutoSttManager with mocked dependencies and enabled=True."""
    with patch("app.services.auto_stt.settings") as mock_settings:
        mock_settings.stt_auto_start = True
        # 라이브 STT 엔진이 OpenAI Realtime으로 교체됨 → 게이트는 openai_api_key
        mock_settings.openai_api_key = "test-key"
        mock_settings.deepgram_api_key = "test-key"
        mgr = AutoSttManager(
            status_service=mock_status_service,
            stt_service=mock_stt_service,
            live_meeting_mgr=mock_live_meeting_mgr,
        )
    return mgr


@pytest.fixture
def disabled_manager(mock_status_service, mock_stt_service, mock_live_meeting_mgr):
    """AutoSttManager with auto-start disabled."""
    with patch("app.services.auto_stt.settings") as mock_settings:
        mock_settings.stt_auto_start = False
        mock_settings.deepgram_api_key = "test-key"
        mgr = AutoSttManager(
            status_service=mock_status_service,
            stt_service=mock_stt_service,
            live_meeting_mgr=mock_live_meeting_mgr,
        )
    return mgr


class TestAutoSttManagerEnabled:
    """활성화된 AutoSttManager 테스트."""

    def test_enabled_when_api_key_and_auto_start(self, manager):
        """API 키와 auto_start가 모두 설정되면 enabled=True."""
        assert manager.enabled is True

    def test_disabled_when_no_api_key(self, mock_status_service, mock_stt_service, mock_live_meeting_mgr):
        """API 키가 없으면 disabled (라이브 엔진 = OpenAI Realtime → OPENAI_API_KEY 게이트)."""
        with patch("app.services.auto_stt.settings") as mock_settings:
            mock_settings.stt_auto_start = True
            mock_settings.openai_api_key = ""
            mgr = AutoSttManager(
                status_service=mock_status_service,
                stt_service=mock_stt_service,
                live_meeting_mgr=mock_live_meeting_mgr,
            )
        assert mgr.enabled is False

    def test_disabled_when_auto_start_false(self, disabled_manager):
        """stt_auto_start=False이면 disabled."""
        assert disabled_manager.enabled is False


class TestStartSttForLiveChannels:
    """서버 시작 시 방송중 채널 STT 자동 시작 테스트."""

    @pytest.mark.asyncio
    async def test_starts_stt_for_broadcasting_channel(
        self, manager, mock_status_service, mock_stt_service
    ):
        """방송중(livestatus=1)인 채널에 STT를 시작한다."""
        # ch14(본회의)의 code는 A011
        mock_status_service.fetch_status = AsyncMock(
            return_value={"A011": 1, "C001": 0}
        )
        mock_stt_service.is_running = MagicMock(return_value=False)

        await manager._start_stt_for_live_channels()

        # ch14에 대해 start가 호출되어야 함
        mock_stt_service.start.assert_called()
        call_args = [call.args for call in mock_stt_service.start.call_args_list]
        channel_ids = [args[0] for args in call_args]
        assert "ch14" in channel_ids

    @pytest.mark.asyncio
    async def test_skips_already_running_channel(
        self, manager, mock_status_service, mock_stt_service
    ):
        """이미 실행 중인 채널은 건너뛴다."""
        mock_status_service.fetch_status = AsyncMock(return_value={"A011": 1})
        mock_stt_service.is_running = MagicMock(return_value=True)

        await manager._start_stt_for_live_channels()

        mock_stt_service.start.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_broadcasting_channels(
        self, manager, mock_status_service, mock_stt_service
    ):
        """방송중인 채널이 없으면 아무것도 시작하지 않는다."""
        mock_status_service.fetch_status = AsyncMock(
            return_value={"A011": 0, "C001": 3}
        )

        await manager._start_stt_for_live_channels()

        mock_stt_service.start.assert_not_called()


class TestHandleStatusChanges:
    """상태 변경 이벤트 처리 테스트."""

    @pytest.mark.asyncio
    async def test_starts_stt_on_broadcast_start(
        self, manager, mock_stt_service
    ):
        """방송 시작(0->1) 시 STT를 시작한다."""
        changes = [
            {"code": "A011", "old_status": 0, "new_status": 1, "new_text": "방송중"}
        ]
        mock_stt_service.is_running = MagicMock(return_value=False)

        await manager._handle_status_changes(changes)

        mock_stt_service.start.assert_called_once()
        args = mock_stt_service.start.call_args.args
        assert args[0] == "ch14"  # A011 -> ch14

    @pytest.mark.asyncio
    async def test_stops_stt_on_broadcast_end(
        self, manager, mock_stt_service, mock_live_meeting_mgr
    ):
        """방송 종료(1->3) 시 STT를 중지하고 회의를 종료한다."""
        changes = [
            {"code": "A011", "old_status": 1, "new_status": 3, "new_text": "종료"}
        ]
        mock_stt_service.is_running = MagicMock(return_value=True)

        await manager._handle_status_changes(changes)

        mock_stt_service.stop.assert_called_once_with("ch14")
        mock_live_meeting_mgr.end_meeting_for_channel.assert_called_once_with("ch14")

    @pytest.mark.asyncio
    async def test_stops_stt_on_recess_but_keeps_meeting(
        self, manager, mock_stt_service, mock_live_meeting_mgr
    ):
        """정회(1->2) 시 STT를 중지하지만 회의는 유지한다."""
        changes = [
            {"code": "A011", "old_status": 1, "new_status": 2, "new_text": "정회중"}
        ]
        mock_stt_service.is_running = MagicMock(return_value=True)

        await manager._handle_status_changes(changes)

        mock_stt_service.stop.assert_called_once_with("ch14")
        # 정회 시에는 회의를 종료하지 않음
        mock_live_meeting_mgr.end_meeting_for_channel.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_non_broadcast_transitions(
        self, manager, mock_stt_service
    ):
        """방송중 관련 없는 전환(0->3)은 무시한다."""
        changes = [
            {"code": "A011", "old_status": 0, "new_status": 3, "new_text": "종료"}
        ]

        await manager._handle_status_changes(changes)

        mock_stt_service.start.assert_not_called()
        mock_stt_service.stop.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_unknown_channel_code(
        self, manager, mock_stt_service
    ):
        """알 수 없는 채널 코드는 무시한다."""
        changes = [
            {"code": "UNKNOWN", "old_status": 0, "new_status": 1, "new_text": "방송중"}
        ]

        await manager._handle_status_changes(changes)

        mock_stt_service.start.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_multiple_changes(
        self, manager, mock_stt_service
    ):
        """여러 채널의 동시 변경을 처리한다."""
        changes = [
            {"code": "A011", "old_status": 0, "new_status": 1, "new_text": "방송중"},
            {"code": "C001", "old_status": 1, "new_status": 3, "new_text": "종료"},
        ]
        # ch14(A011)은 실행 안 됨, ch1(C001)은 실행 중
        def is_running_side_effect(channel_id):
            return channel_id == "ch1"
        mock_stt_service.is_running = MagicMock(side_effect=is_running_side_effect)

        await manager._handle_status_changes(changes)

        # ch14 시작, ch1 중지
        assert mock_stt_service.start.call_count == 1
        assert mock_stt_service.stop.call_count == 1


class TestEnsureSttForLiveChannels:
    """폴링 보정 로직 테스트."""

    @pytest.mark.asyncio
    async def test_starts_missing_stt(
        self, manager, mock_status_service, mock_stt_service
    ):
        """방송중인데 STT가 안 돌고 있는 채널을 시작한다."""
        mock_status_service.fetch_status = AsyncMock(return_value={"A011": 1})
        mock_stt_service.is_running = MagicMock(return_value=False)

        started = await manager.ensure_stt_for_live_channels()

        assert "ch14" in started
        mock_stt_service.start.assert_called()

    @pytest.mark.asyncio
    async def test_returns_empty_when_disabled(
        self, disabled_manager
    ):
        """disabled 상태면 빈 리스트를 반환한다."""
        result = await disabled_manager.ensure_stt_for_live_channels()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_all_running(
        self, manager, mock_status_service, mock_stt_service
    ):
        """모든 방송 채널의 STT가 이미 실행 중이면 빈 리스트를 반환한다."""
        mock_status_service.fetch_status = AsyncMock(return_value={"A011": 1})
        mock_stt_service.is_running = MagicMock(return_value=True)

        started = await manager.ensure_stt_for_live_channels()

        assert started == []
        mock_stt_service.start.assert_not_called()


class TestManagerLifecycle:
    """매니저 시작/중지 수명주기 테스트."""

    @pytest.mark.asyncio
    async def test_start_creates_monitor_task(
        self, manager, mock_status_service
    ):
        """start()는 모니터 태스크를 생성한다."""
        mock_status_service.fetch_status = AsyncMock(return_value={})

        await manager.start()

        assert manager._monitor_task is not None
        assert not manager._monitor_task.done()

        # cleanup
        await manager.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_monitor_task(
        self, manager, mock_status_service
    ):
        """stop()은 모니터 태스크를 취소한다."""
        mock_status_service.fetch_status = AsyncMock(return_value={})

        await manager.start()
        task = manager._monitor_task
        await manager.stop()

        assert task.done()

    @pytest.mark.asyncio
    async def test_disabled_start_does_nothing(
        self, disabled_manager
    ):
        """disabled 상태에서 start()는 아무것도 하지 않는다."""
        await disabled_manager.start()

        assert disabled_manager._monitor_task is None
