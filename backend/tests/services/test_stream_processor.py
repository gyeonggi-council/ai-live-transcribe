"""StreamProcessor 서비스 테스트 (TDD - RED -> GREEN)

HLS 스트림에서 오디오를 추출하고 Deepgram으로 자막을 생성하는 파이프라인 테스트.

테스트 케이스:
1. test_download_segment_success - 세그먼트 다운로드
2. test_extract_audio_with_ffmpeg - ffmpeg 오디오 추출
3. test_process_segment_pipeline - 전체 파이프라인
4. test_stream_processor_error_recovery - 에러 복구
5. test_segment_to_subtitle_save - DB 저장
6. test_broadcast_subtitle_via_websocket - WebSocket 브로드캐스트
"""

from __future__ import annotations

import asyncio
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.stream_processor import (
    AudioExtractionError,
    SegmentDownloadError,
    StreamProcessor,
    StreamProcessorConfig,
    StreamProcessorError,
)


# ============================================================================
# Test 1: Segment Download
# ============================================================================


class TestDownloadSegment:
    """세그먼트 다운로드 테스트"""

    @pytest.mark.asyncio
    async def test_download_segment_success(self) -> None:
        """세그먼트 다운로드 성공 테스트"""
        # Arrange
        segment_url = "https://example.com/segment1.ts"
        expected_data = b"mock_ts_segment_data"

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=expected_data)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_response)
            mock_context.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = MagicMock(return_value=mock_context)

            mock_session_class.return_value = mock_session

            # Act
            processor = StreamProcessor(
                stt_service=MagicMock(),
                connection_manager=MagicMock(),
            )
            result = await processor.download_segment(segment_url)

        # Assert
        assert result == expected_data

    @pytest.mark.asyncio
    async def test_download_segment_failure_raises_error(self) -> None:
        """세그먼트 다운로드 실패 시 SegmentDownloadError 발생"""
        # Arrange
        segment_url = "https://example.com/segment1.ts"

        mock_response = AsyncMock()
        mock_response.status = 404

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_response)
            mock_context.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = MagicMock(return_value=mock_context)

            mock_session_class.return_value = mock_session

            # Act & Assert
            processor = StreamProcessor(
                stt_service=MagicMock(),
                connection_manager=MagicMock(),
            )
            with pytest.raises(SegmentDownloadError):
                await processor.download_segment(segment_url)

    @pytest.mark.asyncio
    async def test_download_segment_with_retry(self) -> None:
        """세그먼트 다운로드 재시도 테스트"""
        # Arrange
        segment_url = "https://example.com/segment1.ts"
        expected_data = b"mock_ts_segment_data"

        # 첫 번째 호출 실패, 두 번째 호출 성공
        mock_response_fail = AsyncMock()
        mock_response_fail.status = 500

        mock_response_success = AsyncMock()
        mock_response_success.status = 200
        mock_response_success.read = AsyncMock(return_value=expected_data)

        call_count = 0

        async def mock_get_response():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_response_fail
            return mock_response_success

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(side_effect=mock_get_response)
            mock_context.__aexit__ = AsyncMock(return_value=None)
            mock_session.get = MagicMock(return_value=mock_context)

            mock_session_class.return_value = mock_session

            # Act
            processor = StreamProcessor(
                stt_service=MagicMock(),
                connection_manager=MagicMock(),
                config=StreamProcessorConfig(max_retries=3, retry_delay=0.01),
            )
            result = await processor.download_segment(segment_url)

        # Assert
        assert result == expected_data
        assert call_count == 2


# ============================================================================
# Test 2: Audio Extraction with FFmpeg
# ============================================================================


class TestExtractAudio:
    """ffmpeg 오디오 추출 테스트"""

    @pytest.mark.asyncio
    async def test_extract_audio_with_ffmpeg_success(self) -> None:
        """ffmpeg 오디오 추출 성공 테스트"""
        # Arrange
        ts_data = b"mock_ts_segment_data"
        expected_audio = b"mock_wav_audio_data"

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(expected_audio, b""))
        mock_process.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            # Act
            processor = StreamProcessor(
                stt_service=MagicMock(),
                connection_manager=MagicMock(),
            )
            result = await processor.extract_audio(ts_data)

        # Assert
        assert result == expected_audio

    @pytest.mark.asyncio
    async def test_extract_audio_ffmpeg_failure(self) -> None:
        """ffmpeg 오디오 추출 실패 시 AudioExtractionError 발생"""
        # Arrange
        ts_data = b"mock_ts_segment_data"

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"", b"FFmpeg error"))
        mock_process.returncode = 1

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            # Act & Assert
            processor = StreamProcessor(
                stt_service=MagicMock(),
                connection_manager=MagicMock(),
            )
            with pytest.raises(AudioExtractionError):
                await processor.extract_audio(ts_data)

    @pytest.mark.asyncio
    async def test_extract_audio_with_custom_options(self) -> None:
        """사용자 정의 옵션으로 오디오 추출 테스트"""
        # Arrange
        ts_data = b"mock_ts_segment_data"
        expected_audio = b"mock_wav_audio_data"

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(expected_audio, b""))
        mock_process.returncode = 0

        with patch(
            "asyncio.create_subprocess_exec", return_value=mock_process
        ) as mock_exec:
            # Act
            config = StreamProcessorConfig(
                audio_sample_rate=22050,
                audio_channels=2,
            )
            processor = StreamProcessor(
                stt_service=MagicMock(),
                connection_manager=MagicMock(),
                config=config,
            )
            result = await processor.extract_audio(ts_data)

        # Assert
        assert result == expected_audio
        # ffmpeg가 올바른 옵션으로 호출되었는지 확인
        call_args = mock_exec.call_args
        assert "-ar" in call_args[0]
        assert "22050" in call_args[0]
        assert "-ac" in call_args[0]
        assert "2" in call_args[0]


# ============================================================================
# Test 3: Process Segment Pipeline
# ============================================================================


class TestProcessSegmentPipeline:
    """전체 파이프라인 테스트"""

    @pytest.mark.asyncio
    async def test_process_segment_pipeline_success(self) -> None:
        """전체 파이프라인 성공 테스트"""
        # Arrange
        meeting_id = uuid.uuid4()
        segment_url = "https://example.com/segment1.ts"
        segment_data = b"mock_ts_data"
        audio_data = b"mock_wav_audio_data"
        transcription_text = "테스트 자막입니다"

        # Mock DeepgramService
        mock_stt = AsyncMock()
        mock_stt.transcribe = AsyncMock(
            return_value=MagicMock(text=transcription_text, confidence=0.95)
        )

        # Mock ConnectionManager
        mock_connection_manager = AsyncMock()
        mock_connection_manager.broadcast_subtitle = AsyncMock()

        # Mock DB session
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        processor = StreamProcessor(
            stt_service=mock_stt,
            connection_manager=mock_connection_manager,
        )

        # Mock internal methods
        processor.download_segment = AsyncMock(return_value=segment_data)
        processor.extract_audio = AsyncMock(return_value=audio_data)

        # Act
        result = await processor.process_segment(
            meeting_id=meeting_id,
            segment_url=segment_url,
            segment_index=0,
            segment_duration=10.0,
            db=mock_db,
        )

        # Assert
        assert result is not None
        assert result.text == transcription_text
        processor.download_segment.assert_called_once_with(segment_url)
        processor.extract_audio.assert_called_once_with(segment_data)
        mock_stt.transcribe.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_segment_pipeline_empty_transcription(self) -> None:
        """빈 텍스트 변환 시 자막 생성 안 함"""
        # Arrange
        meeting_id = uuid.uuid4()
        segment_url = "https://example.com/segment1.ts"
        segment_data = b"mock_ts_data"
        audio_data = b"mock_wav_audio_data"

        # Mock DeepgramService - 빈 텍스트 반환
        mock_stt = AsyncMock()
        mock_stt.transcribe = AsyncMock(
            return_value=MagicMock(text="", confidence=0.0)
        )

        # Mock ConnectionManager
        mock_connection_manager = AsyncMock()

        # Mock DB session
        mock_db = AsyncMock()

        processor = StreamProcessor(
            stt_service=mock_stt,
            connection_manager=mock_connection_manager,
        )

        processor.download_segment = AsyncMock(return_value=segment_data)
        processor.extract_audio = AsyncMock(return_value=audio_data)

        # Act
        result = await processor.process_segment(
            meeting_id=meeting_id,
            segment_url=segment_url,
            segment_index=0,
            segment_duration=10.0,
            db=mock_db,
        )

        # Assert
        assert result is None
        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_segment_with_dictionary_correction(self) -> None:
        """사전 교정 적용 테스트"""
        # Arrange
        meeting_id = uuid.uuid4()
        segment_url = "https://example.com/segment1.ts"
        segment_data = b"mock_ts_data"
        audio_data = b"mock_wav_audio_data"

        # Mock DeepgramService
        mock_stt = AsyncMock()
        mock_stt.transcribe = AsyncMock(
            return_value=MagicMock(text="교정된 자막입니다", confidence=0.95)
        )

        mock_connection_manager = AsyncMock()
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        processor = StreamProcessor(
            stt_service=mock_stt,
            connection_manager=mock_connection_manager,
        )

        processor.download_segment = AsyncMock(return_value=segment_data)
        processor.extract_audio = AsyncMock(return_value=audio_data)

        # Act
        result = await processor.process_segment(
            meeting_id=meeting_id,
            segment_url=segment_url,
            segment_index=0,
            segment_duration=10.0,
            db=mock_db,
            apply_dictionary=True,
        )

        # Assert
        # Deepgram이 apply_dictionary=True로 호출되었는지 확인
        call_kwargs = mock_stt.transcribe.call_args[1]
        assert call_kwargs.get("apply_dictionary") is True


# ============================================================================
# Test 4: Error Recovery
# ============================================================================


class TestErrorRecovery:
    """에러 복구 테스트"""

    @pytest.mark.asyncio
    async def test_stream_processor_error_recovery_download(self) -> None:
        """다운로드 에러 복구 테스트"""
        # Arrange
        segment_url = "https://example.com/segment1.ts"
        expected_data = b"mock_ts_segment_data"

        # 두 번 실패 후 성공
        call_count = 0

        async def mock_download(url):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise SegmentDownloadError("Network error")
            return expected_data

        processor = StreamProcessor(
            stt_service=MagicMock(),
            connection_manager=MagicMock(),
            config=StreamProcessorConfig(max_retries=3, retry_delay=0.01),
        )

        # _download_segment_internal을 모킹
        processor._download_segment_internal = mock_download

        # Act
        result = await processor.download_segment(segment_url)

        # Assert
        assert result == expected_data
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_stream_processor_max_retries_exceeded(self) -> None:
        """최대 재시도 횟수 초과 테스트"""
        # Arrange
        segment_url = "https://example.com/segment1.ts"

        async def mock_download(url):
            raise SegmentDownloadError("Network error")

        processor = StreamProcessor(
            stt_service=MagicMock(),
            connection_manager=MagicMock(),
            config=StreamProcessorConfig(max_retries=2, retry_delay=0.01),
        )

        processor._download_segment_internal = mock_download

        # Act & Assert
        with pytest.raises(SegmentDownloadError):
            await processor.download_segment(segment_url)

    @pytest.mark.asyncio
    async def test_process_segment_continues_on_transient_error(self) -> None:
        """일시적 오류 시 파이프라인 계속 진행"""
        # Arrange
        meeting_id = uuid.uuid4()
        segment_url = "https://example.com/segment1.ts"

        mock_stt = AsyncMock()
        mock_stt.transcribe = AsyncMock(
            return_value=MagicMock(text="자막", confidence=0.95)
        )

        mock_connection_manager = AsyncMock()
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        processor = StreamProcessor(
            stt_service=mock_stt,
            connection_manager=mock_connection_manager,
            config=StreamProcessorConfig(max_retries=2, retry_delay=0.01),
        )

        # 첫 번째 다운로드 실패, 두 번째 성공
        download_calls = 0

        async def mock_download(url):
            nonlocal download_calls
            download_calls += 1
            if download_calls == 1:
                raise SegmentDownloadError("Temporary error")
            return b"mock_data"

        processor._download_segment_internal = mock_download
        processor.extract_audio = AsyncMock(return_value=b"audio_data")

        # Act
        result = await processor.process_segment(
            meeting_id=meeting_id,
            segment_url=segment_url,
            segment_index=0,
            segment_duration=10.0,
            db=mock_db,
        )

        # Assert
        assert result is not None
        assert download_calls == 2


# ============================================================================
# Test 5: Subtitle Save to DB
# ============================================================================


class TestSubtitleSave:
    """DB 저장 테스트"""

    @pytest.mark.asyncio
    async def test_segment_to_subtitle_save(self) -> None:
        """자막 DB 저장 테스트"""
        # Arrange
        meeting_id = uuid.uuid4()
        text = "테스트 자막입니다"
        start_time = 0.0
        end_time = 10.0
        confidence = 0.95

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        processor = StreamProcessor(
            stt_service=MagicMock(),
            connection_manager=MagicMock(),
        )

        # Act
        subtitle = await processor.save_subtitle(
            meeting_id=meeting_id,
            text=text,
            start_time=start_time,
            end_time=end_time,
            confidence=confidence,
            db=mock_db,
        )

        # Assert
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        mock_db.refresh.assert_called_once()

        # 저장된 subtitle 확인
        added_subtitle = mock_db.add.call_args[0][0]
        assert added_subtitle.meeting_id == meeting_id
        assert added_subtitle.text == text
        assert added_subtitle.start_time == start_time
        assert added_subtitle.end_time == end_time
        assert added_subtitle.confidence == confidence

    @pytest.mark.asyncio
    async def test_save_subtitle_with_speaker(self) -> None:
        """화자 정보가 있는 자막 저장 테스트"""
        # Arrange
        meeting_id = uuid.uuid4()
        text = "발언 내용입니다"
        speaker = "김의원"

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        processor = StreamProcessor(
            stt_service=MagicMock(),
            connection_manager=MagicMock(),
        )

        # Act
        subtitle = await processor.save_subtitle(
            meeting_id=meeting_id,
            text=text,
            start_time=0.0,
            end_time=5.0,
            confidence=0.95,
            speaker=speaker,
            db=mock_db,
        )

        # Assert
        added_subtitle = mock_db.add.call_args[0][0]
        assert added_subtitle.speaker == speaker


# ============================================================================
# Test 6: WebSocket Broadcast
# ============================================================================


class TestWebSocketBroadcast:
    """WebSocket 브로드캐스트 테스트"""

    @pytest.mark.asyncio
    async def test_broadcast_subtitle_via_websocket(self) -> None:
        """WebSocket으로 자막 브로드캐스트 테스트"""
        # Arrange
        meeting_id = uuid.uuid4()
        subtitle_data = {
            "id": str(uuid.uuid4()),
            "meeting_id": str(meeting_id),
            "text": "테스트 자막입니다",
            "start_time": 0.0,
            "end_time": 5.0,
            "confidence": 0.95,
            "speaker": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        mock_connection_manager = AsyncMock()
        mock_connection_manager.broadcast_subtitle = AsyncMock()

        processor = StreamProcessor(
            stt_service=MagicMock(),
            connection_manager=mock_connection_manager,
        )

        # Act
        await processor.broadcast_subtitle(meeting_id, subtitle_data)

        # Assert
        mock_connection_manager.broadcast_subtitle.assert_called_once_with(
            meeting_id, subtitle_data
        )

    @pytest.mark.asyncio
    async def test_broadcast_after_save(self) -> None:
        """자막 저장 후 자동 브로드캐스트 테스트"""
        # Arrange
        meeting_id = uuid.uuid4()
        segment_url = "https://example.com/segment1.ts"

        mock_stt = AsyncMock()
        mock_stt.transcribe = AsyncMock(
            return_value=MagicMock(text="테스트 자막", confidence=0.95)
        )

        mock_connection_manager = AsyncMock()
        mock_connection_manager.broadcast_subtitle = AsyncMock()

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        # refresh가 subtitle의 id, created_at을 설정하도록 모킹
        async def mock_refresh(obj):
            obj.id = uuid.uuid4()
            obj.created_at = datetime.now(timezone.utc)

        mock_db.refresh = mock_refresh

        processor = StreamProcessor(
            stt_service=mock_stt,
            connection_manager=mock_connection_manager,
        )

        processor.download_segment = AsyncMock(return_value=b"ts_data")
        processor.extract_audio = AsyncMock(return_value=b"audio_data")

        # Act
        result = await processor.process_segment(
            meeting_id=meeting_id,
            segment_url=segment_url,
            segment_index=0,
            segment_duration=10.0,
            db=mock_db,
        )

        # Assert
        assert result is not None
        mock_connection_manager.broadcast_subtitle.assert_called_once()

        # broadcast 호출 인자 확인
        call_args = mock_connection_manager.broadcast_subtitle.call_args
        assert call_args[0][0] == meeting_id
        broadcast_data = call_args[0][1]
        assert broadcast_data["text"] == "테스트 자막"

    @pytest.mark.asyncio
    async def test_no_broadcast_on_empty_subtitle(self) -> None:
        """빈 자막일 때 브로드캐스트 안 함"""
        # Arrange
        meeting_id = uuid.uuid4()
        segment_url = "https://example.com/segment1.ts"

        mock_stt = AsyncMock()
        mock_stt.transcribe = AsyncMock(
            return_value=MagicMock(text="", confidence=0.0)
        )

        mock_connection_manager = AsyncMock()
        mock_db = AsyncMock()

        processor = StreamProcessor(
            stt_service=mock_stt,
            connection_manager=mock_connection_manager,
        )

        processor.download_segment = AsyncMock(return_value=b"ts_data")
        processor.extract_audio = AsyncMock(return_value=b"audio_data")

        # Act
        result = await processor.process_segment(
            meeting_id=meeting_id,
            segment_url=segment_url,
            segment_index=0,
            segment_duration=10.0,
            db=mock_db,
        )

        # Assert
        assert result is None
        mock_connection_manager.broadcast_subtitle.assert_not_called()


# ============================================================================
# Test: Configuration
# ============================================================================


class TestStreamProcessorConfig:
    """StreamProcessor 설정 테스트"""

    def test_default_config(self) -> None:
        """기본 설정 테스트"""
        config = StreamProcessorConfig()

        assert config.max_retries == 3
        assert config.retry_delay == 1.0
        assert config.audio_sample_rate == 16000
        assert config.audio_channels == 1
        assert config.segment_duration == 10.0

    def test_custom_config(self) -> None:
        """사용자 정의 설정 테스트"""
        config = StreamProcessorConfig(
            max_retries=5,
            retry_delay=2.0,
            audio_sample_rate=22050,
            audio_channels=2,
            segment_duration=15.0,
        )

        assert config.max_retries == 5
        assert config.retry_delay == 2.0
        assert config.audio_sample_rate == 22050
        assert config.audio_channels == 2
        assert config.segment_duration == 15.0
