"""OpenAI Whisper API 클라이언트 서비스

오디오 청크를 텍스트로 변환하는 서비스입니다.
"""

from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING, Self

import httpx

if TYPE_CHECKING:
    from app.services.dictionary import DictionaryService


class WhisperError(Exception):
    """Whisper 서비스 기본 예외"""

    pass


class RateLimitError(WhisperError):
    """Rate limit 초과 예외"""

    pass


class TimeoutError(WhisperError):
    """타임아웃 예외"""

    pass


class APIError(WhisperError):
    """API 호출 실패 예외"""

    pass


@dataclass
class TranscriptionResult:
    """변환 결과

    Attributes:
        text: 변환된 텍스트
        confidence: 신뢰도 (0~1)
    """

    text: str
    confidence: float


class WhisperService:
    """OpenAI Whisper API 클라이언트

    오디오 청크를 텍스트로 변환합니다.
    - 의원 명단 프롬프트로 정확도 향상
    - Rate limit, timeout 등 에러 핸들링
    - 사전 기반 후처리 지원
    """

    OPENAI_API_URL = "https://api.openai.com/v1/audio/transcriptions"
    DEFAULT_MODEL = "whisper-1"
    DEFAULT_LANGUAGE = "ko"
    DEFAULT_TIMEOUT = 30.0
    DEFAULT_RETRY_DELAY = 1.0

    def __init__(
        self,
        api_key: str,
        dictionary_service: "DictionaryService | None" = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        """Whisper 서비스 초기화

        Args:
            api_key: OpenAI API 키
            dictionary_service: 사전 서비스 (후처리용)
            timeout: API 호출 타임아웃 (초)
        """
        self._api_key = api_key
        self._dictionary_service = dictionary_service
        self._timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)

    async def transcribe(
        self,
        audio_chunk: bytes,
        *,
        councilor_names: list[str] | None = None,
        max_retries: int = 0,
        apply_dictionary: bool = False,
    ) -> TranscriptionResult:
        """오디오 청크를 텍스트로 변환

        Args:
            audio_chunk: 오디오 데이터 (WAV, MP3 등)
            councilor_names: 의원 이름 목록 (프롬프트에 포함)
            max_retries: 최대 재시도 횟수 (rate limit 시)
            apply_dictionary: 사전 후처리 적용 여부

        Returns:
            TranscriptionResult: 변환 결과

        Raises:
            RateLimitError: Rate limit 초과 시 (max_retries 초과 시)
            TimeoutError: 타임아웃 발생 시
            APIError: 기타 API 오류 시
        """
        # 빈 오디오 처리
        if not audio_chunk:
            return TranscriptionResult(text="", confidence=0.0)

        # 프롬프트 생성
        prompt = self._build_prompt(councilor_names)

        # 재시도 로직
        retries = 0
        last_error = None

        while retries <= max_retries:
            try:
                result = await self._call_openai_api(
                    audio_chunk=audio_chunk,
                    prompt=prompt,
                )

                # 사전 후처리
                if apply_dictionary and self._dictionary_service:
                    result = TranscriptionResult(
                        text=self._dictionary_service.correct(result.text),
                        confidence=result.confidence,
                    )

                return result

            except RateLimitError as e:
                last_error = e
                retries += 1
                if retries <= max_retries:
                    # 지수 백오프
                    delay = self.DEFAULT_RETRY_DELAY * (2 ** (retries - 1))
                    await asyncio.sleep(delay)
                continue

        # 모든 재시도 실패
        raise last_error or RateLimitError("Rate limit exceeded")

    def _build_prompt(self, councilor_names: list[str] | None) -> str | None:
        """Whisper 프롬프트 생성

        의원 이름을 포함한 프롬프트를 생성하여 정확도를 향상시킵니다.

        Args:
            councilor_names: 의원 이름 목록

        Returns:
            프롬프트 문자열 또는 None
        """
        if not councilor_names:
            return None

        # 의원 이름을 프롬프트에 포함
        names_str = ", ".join(councilor_names)
        return f"회의 참석 의원: {names_str}. 한국어 회의 녹음입니다."

    async def _call_openai_api(
        self,
        audio_chunk: bytes,
        prompt: str | None = None,
    ) -> TranscriptionResult:
        """OpenAI Whisper API 호출

        Args:
            audio_chunk: 오디오 데이터
            prompt: 프롬프트 (선택)

        Returns:
            TranscriptionResult: 변환 결과

        Raises:
            RateLimitError: Rate limit 초과 시
            TimeoutError: 타임아웃 발생 시
            APIError: 기타 API 오류 시
        """
        # 요청 데이터 준비
        files = {
            "file": ("audio.wav", io.BytesIO(audio_chunk), "audio/wav"),
        }
        data = {
            "model": self.DEFAULT_MODEL,
            "language": self.DEFAULT_LANGUAGE,
            "response_format": "json",
        }
        if prompt:
            data["prompt"] = prompt

        headers = {
            "Authorization": f"Bearer {self._api_key}",
        }

        try:
            response = await self._client.post(
                self.OPENAI_API_URL,
                files=files,
                data=data,
                headers=headers,
            )

            if response.status_code == 429:
                raise RateLimitError("Rate limit exceeded")

            if response.status_code != 200:
                raise APIError(f"API error: {response.status_code} - {response.text}")

            result = response.json()
            return TranscriptionResult(
                text=result.get("text", ""),
                # Whisper API는 신뢰도를 직접 제공하지 않음
                # 향후 segments의 avg_logprob 등을 활용할 수 있음
                confidence=0.95,
            )

        except httpx.TimeoutException:
            raise TimeoutError("Request timed out")
        except httpx.RequestError as e:
            raise APIError(f"Request failed: {str(e)}")

    @classmethod
    def from_config(
        cls,
        api_key: str | None = None,
        dictionary_service: DictionaryService | None = None,
    ) -> WhisperService:
        """설정으로부터 서비스 인스턴스 생성

        Args:
            api_key: OpenAI API 키 (None이면 환경변수에서 읽음)
            dictionary_service: 사전 서비스 (후처리용)

        Returns:
            WhisperService 인스턴스

        Raises:
            ValueError: API 키가 설정되지 않은 경우
        """
        if api_key is None:
            from app.core.config import settings

            api_key = settings.openai_api_key

        if not api_key:
            raise ValueError("OpenAI API key is required")

        return cls(api_key=api_key, dictionary_service=dictionary_service)

    async def close(self) -> None:
        """HTTP 클라이언트 종료"""
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        """Async context manager 진입"""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager 종료"""
        await self.close()
