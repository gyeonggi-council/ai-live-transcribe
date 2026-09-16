"""VOD 프로세서 서비스

VOD(MP4) 파일에서 자막을 생성하는 서비스입니다.

파이프라인 흐름:
MP4 URL -> 다운로드 -> 오디오 추출 (ffmpeg)
    -> 청크 분할 -> Deepgram 배치 처리
    -> 타임스탬프 계산 -> DB 저장
    -> 회의 상태 업데이트 (ended)
"""

from __future__ import annotations

import asyncio
import io
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import aiohttp
from sqlalchemy import update

from app.models.subtitle import Subtitle
from app.models.meeting import Meeting

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ============================================================================
# Exceptions
# ============================================================================


class VodProcessorError(Exception):
    """VodProcessor 기본 예외"""

    pass


class VodDownloadError(VodProcessorError):
    """VOD 다운로드 실패 예외"""

    pass


class AudioExtractionError(VodProcessorError):
    """오디오 추출 실패 예외"""

    pass


# ============================================================================
# Data Classes
# ============================================================================


@dataclass
class AudioChunk:
    """오디오 청크 데이터

    Attributes:
        index: 청크 인덱스
        start_time: 시작 시간 (초)
        end_time: 종료 시간 (초)
        audio_data: 오디오 데이터 (bytes)
    """

    index: int
    start_time: float
    end_time: float
    audio_data: bytes


@dataclass
class SubtitleData:
    """자막 데이터

    Attributes:
        text: 자막 텍스트
        start_time: 시작 시간 (초)
        end_time: 종료 시간 (초)
        confidence: 인식 신뢰도 (0~1)
        speaker: 화자 (선택)
    """

    text: str
    start_time: float
    end_time: float
    confidence: float
    speaker: str | None = None


# ============================================================================
# Configuration
# ============================================================================


@dataclass
class VodProcessorConfig:
    """VodProcessor 설정

    Attributes:
        chunk_duration_seconds: 청크 길이 (초)
        max_retries: 최대 재시도 횟수
        retry_delay: 재시도 간 대기 시간 (초)
        audio_sample_rate: 오디오 샘플레이트 (Hz)
        audio_channels: 오디오 채널 수
        download_timeout: 다운로드 타임아웃 (초)
    """

    chunk_duration_seconds: int = 30
    max_retries: int = 3
    retry_delay: float = 1.0
    audio_sample_rate: int = 16000
    audio_channels: int = 1
    download_timeout: float = 300.0  # 5분


# ============================================================================
# VodProcessor
# ============================================================================


class VodProcessor:
    """VOD 프로세서

    VOD(MP4) 파일을 다운로드하고, 오디오를 추출하여
    Deepgram API로 자막을 생성합니다.

    Pipeline:
    1. VOD 다운로드 (aiohttp)
    2. 오디오 추출 (ffmpeg subprocess)
    3. 청크 분할 (30초 단위)
    4. STT 배치 변환 (stt_service — 현행은 vod_stt_service의 OpenAI 배치)
    5. DB 저장 (Subtitle model)
    6. 회의 상태 업데이트 (Meeting model)
    """

    def __init__(
        self,
        stt_service: object,
        config: VodProcessorConfig | None = None,
    ):
        """VodProcessor 초기화

        Args:
            stt_service: Deepgram STT API 서비스
            config: 프로세서 설정 (기본값 사용 시 None)
        """
        self._stt_service = stt_service
        self._config = config or VodProcessorConfig()
        self._progress_callback: Callable[[float, str], None] | None = None

    @property
    def config(self) -> VodProcessorConfig:
        """현재 설정 반환"""
        return self._config

    # ========================================================================
    # Progress Tracking
    # ========================================================================

    def set_progress_callback(
        self, callback: Callable[[float, str], None]
    ) -> None:
        """진행률 콜백 설정

        Args:
            callback: 진행률 콜백 함수 (progress: 0.0~1.0, message: str)
        """
        self._progress_callback = callback

    def _notify_progress(self, progress: float, message: str) -> None:
        """진행률 알림

        Args:
            progress: 진행률 (0.0~1.0)
            message: 상태 메시지
        """
        if self._progress_callback:
            self._progress_callback(progress, message)

    # ========================================================================
    # 1. VOD Download
    # ========================================================================

    async def download_vod(self, vod_url: str) -> bytes:
        """VOD 다운로드

        Args:
            vod_url: VOD URL

        Returns:
            다운로드된 VOD 데이터 (bytes)

        Raises:
            VodDownloadError: 다운로드 실패 시
        """
        timeout = aiohttp.ClientTimeout(total=self._config.download_timeout)
        # KMS 보안정책(2026-07-21): 비브라우저 UA 차단 → 브라우저형 헤더 필수
        from app.services.kms_vod_resolver import KMS_BROWSER_HEADERS

        headers = dict(KMS_BROWSER_HEADERS)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(vod_url, headers=headers) as response:
                    if response.status != 200:
                        raise VodDownloadError(
                            f"Failed to download VOD: HTTP {response.status}"
                        )
                    return await response.read()
        except aiohttp.ClientError as e:
            raise VodDownloadError(f"Download failed: {str(e)}")

    async def download_vod_to_file(
        self, vod_url: str, output_path: Path
    ) -> Path:
        """VOD를 파일로 다운로드

        Args:
            vod_url: VOD URL
            output_path: 출력 파일 경로

        Returns:
            저장된 파일 경로
        """
        content = await self.download_vod(vod_url)
        output_path.write_bytes(content)
        return output_path

    # ========================================================================
    # 2. Audio Extraction (FFmpeg)
    # ========================================================================

    async def extract_audio_from_file(self, mp4_path: Path) -> bytes:
        """MP4 파일에서 오디오 추출

        ffmpeg를 subprocess로 실행하여 MP4에서 WAV 오디오를 추출합니다.

        Args:
            mp4_path: MP4 파일 경로

        Returns:
            추출된 오디오 데이터 (WAV 형식)

        Raises:
            VodProcessorError: 오디오 추출 실패 시
        """
        # ffmpeg 명령어 구성
        ffmpeg_cmd = [
            "ffmpeg",
            "-i",
            str(mp4_path),
            "-vn",  # 비디오 스트림 제외
            "-acodec",
            "pcm_s16le",  # PCM 16-bit little-endian
            "-ar",
            str(self._config.audio_sample_rate),
            "-ac",
            str(self._config.audio_channels),
            "-f",
            "wav",
            "pipe:1",  # stdout으로 출력
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *ffmpeg_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                raise VodProcessorError(
                    f"FFmpeg failed with code {process.returncode}: {stderr.decode()}"
                )

            return stdout

        except FileNotFoundError:
            raise VodProcessorError(
                "FFmpeg not found. Please install FFmpeg and add it to PATH."
            )
        except Exception as e:
            if isinstance(e, VodProcessorError):
                raise
            raise VodProcessorError(f"Audio extraction failed: {str(e)}")

    async def extract_audio_from_bytes(self, mp4_data: bytes) -> bytes:
        """MP4 바이트에서 오디오 추출

        Args:
            mp4_data: MP4 데이터 (bytes)

        Returns:
            추출된 오디오 데이터 (WAV 형식)
        """
        # 임시 파일에 저장 후 처리
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp.write(mp4_data)
            tmp_path = Path(tmp.name)

        try:
            return await self.extract_audio_from_file(tmp_path)
        finally:
            # 임시 파일 삭제
            tmp_path.unlink(missing_ok=True)

    # ========================================================================
    # 3. Audio Chunking
    # ========================================================================

    def _get_audio_duration(self, audio_data: bytes) -> float:
        """오디오 데이터의 길이를 초 단위로 반환

        WAV 헤더에서 샘플레이트와 데이터 크기를 읽어 계산합니다.

        Args:
            audio_data: WAV 오디오 데이터

        Returns:
            오디오 길이 (초)
        """
        # WAV 헤더 파싱 (간단한 버전)
        # 실제로는 wave 모듈이나 ffprobe를 사용하는 것이 더 정확함
        if len(audio_data) < 44:
            return 0.0

        # WAV 헤더에서 샘플레이트 읽기 (offset 24-27)
        sample_rate = int.from_bytes(audio_data[24:28], "little")
        # 바이트레이트 (offset 28-31)
        byte_rate = int.from_bytes(audio_data[28:32], "little")

        if byte_rate == 0:
            return 0.0

        # 데이터 크기 (헤더 제외)
        data_size = len(audio_data) - 44
        duration = data_size / byte_rate

        return duration

    async def _extract_audio_chunk(
        self, audio_data: bytes, start_time: float, end_time: float
    ) -> bytes:
        """오디오 데이터에서 특정 시간 범위의 청크 추출

        ffmpeg를 사용하여 시간 범위를 자릅니다.

        Args:
            audio_data: 전체 오디오 데이터
            start_time: 시작 시간 (초)
            end_time: 종료 시간 (초)

        Returns:
            추출된 청크 데이터 (WAV 형식)
        """
        duration = end_time - start_time

        ffmpeg_cmd = [
            "ffmpeg",
            "-i",
            "pipe:0",
            "-ss",
            str(start_time),
            "-t",
            str(duration),
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(self._config.audio_sample_rate),
            "-ac",
            str(self._config.audio_channels),
            "-f",
            "wav",
            "pipe:1",
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *ffmpeg_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate(input=audio_data)

            if process.returncode != 0:
                raise VodProcessorError(
                    f"FFmpeg chunk extraction failed: {stderr.decode()}"
                )

            return stdout

        except FileNotFoundError:
            raise VodProcessorError("FFmpeg not found")
        except Exception as e:
            if isinstance(e, VodProcessorError):
                raise
            raise VodProcessorError(f"Chunk extraction failed: {str(e)}")

    async def split_audio_into_chunks(
        self, audio_data: bytes, total_duration: float
    ) -> list[AudioChunk]:
        """오디오를 청크로 분할

        Args:
            audio_data: 전체 오디오 데이터
            total_duration: 전체 오디오 길이 (초)

        Returns:
            AudioChunk 리스트
        """
        chunks: list[AudioChunk] = []
        chunk_duration = self._config.chunk_duration_seconds
        current_time = 0.0
        index = 0

        while current_time < total_duration:
            end_time = min(current_time + chunk_duration, total_duration)
            chunk_audio = await self._extract_audio_chunk(
                audio_data, current_time, end_time
            )

            chunks.append(
                AudioChunk(
                    index=index,
                    start_time=current_time,
                    end_time=end_time,
                    audio_data=chunk_audio,
                )
            )

            current_time = end_time
            index += 1

        return chunks

    # ========================================================================
    # 4. Batch Transcription
    # ========================================================================

    async def batch_transcribe_chunks(
        self,
        chunks: list[AudioChunk],
        *,
        councilor_names: list[str] | None = None,
        apply_dictionary: bool = False,
    ) -> list[SubtitleData]:
        """청크들을 배치로 변환

        Args:
            chunks: AudioChunk 리스트
            councilor_names: 의원 이름 목록 (정확도 향상용)
            apply_dictionary: 사전 후처리 적용 여부

        Returns:
            SubtitleData 리스트 (빈 결과는 제외)
        """
        subtitles: list[SubtitleData] = []

        for chunk in chunks:
            result = await self._stt_service.transcribe(
                audio_chunk=chunk.audio_data,
                councilor_names=councilor_names,
                apply_dictionary=apply_dictionary,
            )

            # 빈 결과 필터링
            if result.text and result.text.strip():
                subtitles.append(
                    SubtitleData(
                        text=result.text,
                        start_time=chunk.start_time,
                        end_time=chunk.end_time,
                        confidence=result.confidence,
                    )
                )

        return subtitles

    # ========================================================================
    # 5. Timestamp Calculation
    # ========================================================================

    def calculate_timestamps(
        self,
        chunk_index: int,
        chunk_duration: float,
        *,
        actual_duration: float | None = None,
    ) -> tuple[float, float]:
        """타임스탬프 계산

        Args:
            chunk_index: 청크 인덱스
            chunk_duration: 청크 기본 길이 (초)
            actual_duration: 실제 청크 길이 (마지막 청크용, 선택)

        Returns:
            (start_time, end_time) 튜플
        """
        start_time = chunk_index * chunk_duration
        end_time = start_time + (actual_duration or chunk_duration)
        return start_time, end_time

    # ========================================================================
    # 6. Database Operations
    # ========================================================================

    async def save_subtitles_to_db(
        self,
        meeting_id: uuid.UUID,
        subtitles: list[SubtitleData],
        db: AsyncSession,
    ) -> int:
        """자막들을 DB에 저장

        Args:
            meeting_id: 회의 ID
            subtitles: SubtitleData 리스트
            db: 데이터베이스 세션

        Returns:
            저장된 자막 수
        """
        for subtitle_data in subtitles:
            subtitle = Subtitle(
                meeting_id=meeting_id,
                text=subtitle_data.text,
                start_time=subtitle_data.start_time,
                end_time=subtitle_data.end_time,
                confidence=subtitle_data.confidence,
                speaker=subtitle_data.speaker,
            )
            db.add(subtitle)

        await db.commit()
        return len(subtitles)

    async def update_meeting_status(
        self,
        meeting_id: uuid.UUID,
        status: str,
        db: AsyncSession,
        *,
        duration_seconds: int | None = None,
    ) -> None:
        """회의 상태 업데이트

        Args:
            meeting_id: 회의 ID
            status: 새 상태 (processing, ended, etc.)
            db: 데이터베이스 세션
            duration_seconds: 회의 길이 (초, 선택)
        """
        values = {"status": status, "updated_at": datetime.now(timezone.utc)}
        if duration_seconds is not None:
            values["duration_seconds"] = duration_seconds

        stmt = update(Meeting).where(Meeting.id == meeting_id).values(**values)
        await db.execute(stmt)
        await db.commit()

    # ========================================================================
    # 7. Full Pipeline
    # ========================================================================

    async def process_vod(
        self,
        vod_url: str,
        meeting_id: uuid.UUID,
        db: AsyncSession,
        *,
        councilor_names: list[str] | None = None,
        apply_dictionary: bool = False,
    ) -> dict[str, Any]:
        """전체 VOD 처리 파이프라인

        Args:
            vod_url: VOD URL
            meeting_id: 회의 ID
            db: 데이터베이스 세션
            councilor_names: 의원 이름 목록 (정확도 향상용)
            apply_dictionary: 사전 후처리 적용 여부

        Returns:
            처리 결과 딕셔너리:
            - status: "completed" | "error"
            - subtitles_count: 생성된 자막 수
            - duration_seconds: VOD 길이 (초)
            - error: 에러 메시지 (실패 시)
        """
        try:
            # 1. 상태를 processing으로 업데이트
            self._notify_progress(0.0, "처리 시작")
            await self.update_meeting_status(meeting_id, "processing", db)

            # 2. VOD 다운로드
            self._notify_progress(0.1, "VOD 다운로드 중")
            mp4_data = await self.download_vod(vod_url)

            # 3. 임시 파일에 저장
            with tempfile.NamedTemporaryFile(
                suffix=".mp4", delete=False
            ) as tmp:
                tmp.write(mp4_data)
                tmp_path = Path(tmp.name)

            try:
                # 4. 오디오 추출
                self._notify_progress(0.2, "오디오 추출 중")
                audio_data = await self.extract_audio_from_file(tmp_path)

                # 5. 오디오 길이 계산
                total_duration = self._get_audio_duration(audio_data)

                # 6. 청크 분할
                self._notify_progress(0.3, "오디오 청크 분할 중")
                chunks = await self.split_audio_into_chunks(
                    audio_data, total_duration
                )

                # 7. 배치 변환
                total_chunks = len(chunks)
                subtitles: list[SubtitleData] = []

                for i, chunk in enumerate(chunks):
                    progress = 0.3 + (0.6 * (i + 1) / total_chunks)
                    self._notify_progress(
                        progress, f"청크 {i + 1}/{total_chunks} 처리 중"
                    )

                    result = await self._stt_service.transcribe(
                        audio_chunk=chunk.audio_data,
                        councilor_names=councilor_names,
                        apply_dictionary=apply_dictionary,
                    )

                    if result.text and result.text.strip():
                        subtitles.append(
                            SubtitleData(
                                text=result.text,
                                start_time=chunk.start_time,
                                end_time=chunk.end_time,
                                confidence=result.confidence,
                            )
                        )

                # 8. DB 저장
                self._notify_progress(0.95, "자막 저장 중")
                saved_count = await self.save_subtitles_to_db(
                    meeting_id, subtitles, db
                )

                # 9. 상태를 ended로 업데이트
                await self.update_meeting_status(
                    meeting_id,
                    "ended",
                    db,
                    duration_seconds=int(total_duration),
                )

                self._notify_progress(1.0, "처리 완료")

                return {
                    "status": "completed",
                    "subtitles_count": saved_count,
                    "duration_seconds": total_duration,
                }

            finally:
                # 임시 파일 삭제
                tmp_path.unlink(missing_ok=True)

        except Exception as e:
            # 에러 발생 시 상태 업데이트
            try:
                await self.update_meeting_status(meeting_id, "error", db)
            except Exception:
                pass  # 상태 업데이트 실패 무시

            return {
                "status": "error",
                "error": str(e),
            }
