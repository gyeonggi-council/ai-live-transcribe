"""HLS 스트림 프로세서 서비스

HLS 스트림에서 오디오를 추출하고 Deepgram API를 통해 자막을 생성하는 파이프라인입니다.

파이프라인 흐름:
HLS URL -> 세그먼트 다운로드 -> 오디오 추출 (ffmpeg)
    -> Deepgram 변환 -> 사전 교정 -> DB 저장 -> WebSocket 브로드캐스트
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import aiohttp

from app.models.subtitle import Subtitle

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.api.websocket import ConnectionManager


# ============================================================================
# Exceptions
# ============================================================================


class StreamProcessorError(Exception):
    """StreamProcessor 기본 예외"""

    pass


class SegmentDownloadError(StreamProcessorError):
    """세그먼트 다운로드 실패 예외"""

    pass


class AudioExtractionError(StreamProcessorError):
    """오디오 추출 실패 예외"""

    pass


# ============================================================================
# Configuration
# ============================================================================


@dataclass
class StreamProcessorConfig:
    """StreamProcessor 설정

    Attributes:
        max_retries: 최대 재시도 횟수 (다운로드 실패 시)
        retry_delay: 재시도 간 대기 시간 (초)
        audio_sample_rate: 오디오 샘플레이트 (Hz)
        audio_channels: 오디오 채널 수
        segment_duration: 기본 세그먼트 길이 (초)
        download_timeout: 다운로드 타임아웃 (초)
    """

    max_retries: int = 3
    retry_delay: float = 1.0
    audio_sample_rate: int = 16000
    audio_channels: int = 1
    segment_duration: float = 10.0
    download_timeout: float = 30.0


# ============================================================================
# StreamProcessor
# ============================================================================


class StreamProcessor:
    """HLS 스트림 프로세서

    HLS 스트림에서 세그먼트를 다운로드하고, 오디오를 추출하여
    STT 엔진으로 자막을 생성합니다 (레거시 경로 — 현행 라이브는 openai_realtime_stt 사용).

    Pipeline:
    1. HLS 세그먼트 다운로드 (aiohttp)
    2. 오디오 추출 (ffmpeg subprocess)
    3. STT 변환 (stt_service)
    4. 사전 교정 (DictionaryService - optional)
    5. DB 저장 (Subtitle model)
    6. WebSocket 브로드캐스트 (ConnectionManager)
    """

    def __init__(
        self,
        stt_service: object,
        connection_manager: ConnectionManager,
        config: StreamProcessorConfig | None = None,
    ):
        """StreamProcessor 초기화

        Args:
            stt_service: Deepgram STT API 서비스
            connection_manager: WebSocket 연결 관리자
            config: 프로세서 설정 (기본값 사용 시 None)
        """
        self._stt_service = stt_service
        self._connection_manager = connection_manager
        self._config = config or StreamProcessorConfig()

    @property
    def config(self) -> StreamProcessorConfig:
        """현재 설정 반환"""
        return self._config

    # ========================================================================
    # 1. Segment Download
    # ========================================================================

    async def download_segment(self, segment_url: str) -> bytes:
        """HLS 세그먼트 다운로드

        재시도 로직이 포함되어 있어 일시적 네트워크 오류에 대응합니다.

        Args:
            segment_url: 세그먼트 URL

        Returns:
            다운로드된 세그먼트 데이터 (bytes)

        Raises:
            SegmentDownloadError: 다운로드 실패 시 (모든 재시도 소진)
        """
        last_error: Exception | None = None
        retries = 0

        while retries <= self._config.max_retries:
            try:
                return await self._download_segment_internal(segment_url)
            except SegmentDownloadError as e:
                last_error = e
                retries += 1
                if retries <= self._config.max_retries:
                    await asyncio.sleep(self._config.retry_delay)
                continue

        raise last_error or SegmentDownloadError("Download failed after all retries")

    async def _download_segment_internal(self, segment_url: str) -> bytes:
        """실제 세그먼트 다운로드 구현

        Args:
            segment_url: 세그먼트 URL

        Returns:
            다운로드된 세그먼트 데이터 (bytes)

        Raises:
            SegmentDownloadError: 다운로드 실패 시
        """
        timeout = aiohttp.ClientTimeout(total=self._config.download_timeout)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(segment_url) as response:
                if response.status != 200:
                    raise SegmentDownloadError(
                        f"Failed to download segment: HTTP {response.status}"
                    )
                return await response.read()

    # ========================================================================
    # 2. Audio Extraction (FFmpeg)
    # ========================================================================

    async def extract_audio(self, ts_data: bytes) -> bytes:
        """TS 세그먼트에서 오디오 추출 (ffmpeg 사용)

        ffmpeg를 subprocess로 실행하여 TS 데이터에서 WAV 오디오를 추출합니다.

        Args:
            ts_data: TS 세그먼트 데이터

        Returns:
            추출된 오디오 데이터 (WAV 형식)

        Raises:
            AudioExtractionError: 오디오 추출 실패 시
        """
        # ffmpeg 명령어 구성
        # stdin으로 TS 데이터를 받고, stdout으로 WAV 오디오 출력
        ffmpeg_cmd = [
            "ffmpeg",
            "-i",
            "pipe:0",  # stdin에서 입력
            "-vn",  # 비디오 스트림 제외
            "-acodec",
            "pcm_s16le",  # PCM 16-bit little-endian
            "-ar",
            str(self._config.audio_sample_rate),  # 샘플레이트
            "-ac",
            str(self._config.audio_channels),  # 채널 수
            "-f",
            "wav",  # WAV 형식
            "pipe:1",  # stdout으로 출력
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *ffmpeg_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate(input=ts_data)

            if process.returncode != 0:
                raise AudioExtractionError(
                    f"FFmpeg failed with code {process.returncode}: {stderr.decode()}"
                )

            return stdout

        except FileNotFoundError:
            raise AudioExtractionError(
                "FFmpeg not found. Please install FFmpeg and add it to PATH."
            )
        except Exception as e:
            if isinstance(e, AudioExtractionError):
                raise
            raise AudioExtractionError(f"Audio extraction failed: {str(e)}")

    # ========================================================================
    # 3. Process Segment (Full Pipeline)
    # ========================================================================

    async def process_segment(
        self,
        meeting_id: uuid.UUID,
        segment_url: str,
        segment_index: int,
        segment_duration: float,
        db: AsyncSession,
        *,
        apply_dictionary: bool = False,
        councilor_names: list[str] | None = None,
    ) -> Subtitle | None:
        """세그먼트 처리 파이프라인

        전체 파이프라인을 실행합니다:
        1. 세그먼트 다운로드
        2. 오디오 추출
        3. Whisper 변환
        4. DB 저장
        5. WebSocket 브로드캐스트

        Args:
            meeting_id: 회의 ID
            segment_url: 세그먼트 URL
            segment_index: 세그먼트 인덱스 (시간 계산용)
            segment_duration: 세그먼트 길이 (초)
            db: 데이터베이스 세션
            apply_dictionary: 사전 교정 적용 여부
            councilor_names: 의원 이름 목록 (Whisper 프롬프트용)

        Returns:
            생성된 Subtitle 객체 또는 None (빈 텍스트인 경우)
        """
        # 1. 세그먼트 다운로드
        segment_data = await self.download_segment(segment_url)

        # 2. 오디오 추출
        audio_data = await self.extract_audio(segment_data)

        # 3. Deepgram 변환
        result = await self._stt_service.transcribe(
            audio_chunk=audio_data,
            councilor_names=councilor_names,
            apply_dictionary=apply_dictionary,
        )

        # 빈 텍스트인 경우 저장하지 않음
        if not result.text or not result.text.strip():
            return None

        # 4. 시간 계산
        start_time = segment_index * segment_duration
        end_time = start_time + segment_duration

        # 5. DB 저장
        subtitle = await self.save_subtitle(
            meeting_id=meeting_id,
            text=result.text,
            start_time=start_time,
            end_time=end_time,
            confidence=result.confidence,
            db=db,
        )

        # 6. WebSocket 브로드캐스트
        subtitle_data = self._subtitle_to_dict(subtitle)
        await self.broadcast_subtitle(meeting_id, subtitle_data)

        return subtitle

    # ========================================================================
    # 4. Save Subtitle to DB
    # ========================================================================

    async def save_subtitle(
        self,
        meeting_id: uuid.UUID,
        text: str,
        start_time: float,
        end_time: float,
        confidence: float,
        db: AsyncSession,
        speaker: str | None = None,
    ) -> Subtitle:
        """자막을 데이터베이스에 저장

        Args:
            meeting_id: 회의 ID
            text: 자막 텍스트
            start_time: 시작 시간 (초)
            end_time: 종료 시간 (초)
            confidence: 인식 신뢰도 (0~1)
            db: 데이터베이스 세션
            speaker: 화자 (선택)

        Returns:
            저장된 Subtitle 객체
        """
        subtitle = Subtitle(
            meeting_id=meeting_id,
            text=text,
            start_time=start_time,
            end_time=end_time,
            confidence=confidence,
            speaker=speaker,
        )

        db.add(subtitle)
        await db.commit()
        await db.refresh(subtitle)

        return subtitle

    # ========================================================================
    # 5. WebSocket Broadcast
    # ========================================================================

    async def broadcast_subtitle(
        self, meeting_id: uuid.UUID, subtitle_data: dict[str, Any]
    ) -> None:
        """WebSocket을 통해 자막 브로드캐스트

        Args:
            meeting_id: 회의 ID
            subtitle_data: 자막 데이터 (SubtitleResponse 형식)
        """
        await self._connection_manager.broadcast_subtitle(meeting_id, subtitle_data)

    # ========================================================================
    # Helper Methods
    # ========================================================================

    def _subtitle_to_dict(self, subtitle: Subtitle) -> dict[str, Any]:
        """Subtitle 객체를 딕셔너리로 변환

        Args:
            subtitle: Subtitle 모델 객체

        Returns:
            자막 데이터 딕셔너리
        """
        return {
            "id": str(subtitle.id),
            "meeting_id": str(subtitle.meeting_id),
            "text": subtitle.text,
            "start_time": subtitle.start_time,
            "end_time": subtitle.end_time,
            "confidence": subtitle.confidence,
            "speaker": subtitle.speaker,
            "created_at": (
                subtitle.created_at.isoformat()
                if subtitle.created_at
                else datetime.now(timezone.utc).isoformat()
            ),
        }
