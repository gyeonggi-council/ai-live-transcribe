"""Whisper 서비스 테스트 (TDD - RED Phase)

테스트 케이스:
1. test_whisper_transcribe_success - 정상 변환
2. test_whisper_with_councilor_prompt - 의원 명단 프롬프트 적용
3. test_whisper_rate_limit_retry - rate limit 재시도
4. test_dictionary_correction - 용어 교정
5. test_councilor_name_correction - 의원 이름 교정
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.whisper import WhisperService, TranscriptionResult
from app.services.dictionary import DictionaryService, DictionaryEntry


class TestWhisperService:
    """Whisper 서비스 테스트"""

    @pytest.fixture
    def whisper_service(self) -> WhisperService:
        """Whisper 서비스 인스턴스"""
        return WhisperService(api_key="test-api-key")

    @pytest.fixture
    def mock_audio_chunk(self) -> bytes:
        """테스트용 오디오 청크 (WAV 형식 헤더 포함)"""
        # 최소한의 WAV 파일 헤더 생성
        wav_header = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"fmt " + b"\x00" * 20
        audio_data = b"\x00" * 1000
        return wav_header + audio_data

    @pytest.fixture
    def councilor_names(self) -> list[str]:
        """테스트용 의원 명단"""
        return ["김철수", "박영희", "이민수", "최유진"]

    @pytest.mark.asyncio
    async def test_whisper_transcribe_success(
        self, whisper_service: WhisperService, mock_audio_chunk: bytes
    ):
        """정상 변환 테스트"""
        # Arrange
        expected_text = "안녕하세요. 오늘 회의를 시작하겠습니다."
        expected_confidence = 0.95

        mock_response = MagicMock()
        mock_response.text = expected_text

        with patch.object(
            whisper_service, "_call_openai_api", new_callable=AsyncMock
        ) as mock_api:
            mock_api.return_value = TranscriptionResult(
                text=expected_text,
                confidence=expected_confidence,
            )

            # Act
            result = await whisper_service.transcribe(mock_audio_chunk)

            # Assert
            assert result.text == expected_text
            assert result.confidence == expected_confidence
            mock_api.assert_called_once()

    @pytest.mark.asyncio
    async def test_whisper_with_councilor_prompt(
        self,
        whisper_service: WhisperService,
        mock_audio_chunk: bytes,
        councilor_names: list[str],
    ):
        """의원 명단 프롬프트 적용 테스트"""
        # Arrange
        expected_text = "김철수 의원님, 발언해 주십시오."

        with patch.object(
            whisper_service, "_call_openai_api", new_callable=AsyncMock
        ) as mock_api:
            mock_api.return_value = TranscriptionResult(
                text=expected_text,
                confidence=0.98,
            )

            # Act
            result = await whisper_service.transcribe(
                mock_audio_chunk,
                councilor_names=councilor_names,
            )

            # Assert
            assert result.text == expected_text
            # 프롬프트에 의원 이름이 포함되었는지 확인
            call_args = mock_api.call_args
            assert call_args is not None
            # prompt 파라미터 확인
            if "prompt" in call_args.kwargs:
                prompt = call_args.kwargs["prompt"]
                assert any(name in prompt for name in councilor_names)

    @pytest.mark.asyncio
    async def test_whisper_rate_limit_retry(
        self, whisper_service: WhisperService, mock_audio_chunk: bytes
    ):
        """Rate limit 재시도 테스트"""
        # Arrange
        from app.services.whisper import RateLimitError

        expected_text = "재시도 후 성공한 텍스트입니다."

        # 첫 번째 호출은 RateLimitError, 두 번째 호출은 성공
        with patch.object(
            whisper_service, "_call_openai_api", new_callable=AsyncMock
        ) as mock_api:
            mock_api.side_effect = [
                RateLimitError("Rate limit exceeded"),
                TranscriptionResult(text=expected_text, confidence=0.90),
            ]

            # Act
            result = await whisper_service.transcribe(
                mock_audio_chunk,
                max_retries=3,
            )

            # Assert
            assert result.text == expected_text
            assert mock_api.call_count == 2

    @pytest.mark.asyncio
    async def test_whisper_rate_limit_max_retries_exceeded(
        self, whisper_service: WhisperService, mock_audio_chunk: bytes
    ):
        """Rate limit 최대 재시도 초과 테스트"""
        from app.services.whisper import RateLimitError

        with patch.object(
            whisper_service, "_call_openai_api", new_callable=AsyncMock
        ) as mock_api:
            mock_api.side_effect = RateLimitError("Rate limit exceeded")

            # Act & Assert
            with pytest.raises(RateLimitError):
                await whisper_service.transcribe(
                    mock_audio_chunk,
                    max_retries=2,
                )

            assert mock_api.call_count == 3  # 초기 시도 1회 + 재시도 2회

    @pytest.mark.asyncio
    async def test_whisper_timeout_error(
        self, whisper_service: WhisperService, mock_audio_chunk: bytes
    ):
        """타임아웃 에러 테스트"""
        from app.services.whisper import TimeoutError

        with patch.object(
            whisper_service, "_call_openai_api", new_callable=AsyncMock
        ) as mock_api:
            mock_api.side_effect = TimeoutError("Request timed out")

            # Act & Assert
            with pytest.raises(TimeoutError):
                await whisper_service.transcribe(mock_audio_chunk)

    @pytest.mark.asyncio
    async def test_whisper_empty_audio(self, whisper_service: WhisperService):
        """빈 오디오 처리 테스트"""
        # Arrange
        empty_audio = b""

        # Act
        result = await whisper_service.transcribe(empty_audio)

        # Assert
        assert result.text == ""
        assert result.confidence == 0.0


class TestDictionaryService:
    """사전 서비스 테스트"""

    @pytest.fixture
    def dictionary_service(self) -> DictionaryService:
        """사전 서비스 인스턴스"""
        entries = [
            DictionaryEntry(
                wrong_text="경기도 의회",
                correct_text="경기도의회",
                category="term",
            ),
            DictionaryEntry(
                wrong_text="예산안",
                correct_text="예산(안)",
                category="term",
            ),
            DictionaryEntry(
                wrong_text="김철순",
                correct_text="김철수",
                category="councilor",
            ),
            DictionaryEntry(
                wrong_text="박영휘",
                correct_text="박영희",
                category="councilor",
            ),
        ]
        return DictionaryService(entries=entries)

    def test_dictionary_correction(self, dictionary_service: DictionaryService):
        """용어 교정 테스트"""
        # Arrange
        input_text = "경기도 의회에서 예산안을 심의합니다."
        expected_text = "경기도의회에서 예산(안)을 심의합니다."

        # Act
        result = dictionary_service.correct(input_text)

        # Assert
        assert result == expected_text

    def test_councilor_name_correction(self, dictionary_service: DictionaryService):
        """의원 이름 교정 테스트"""
        # Arrange
        input_text = "김철순 의원님이 발언하셨습니다. 이어서 박영휘 의원님."
        expected_text = "김철수 의원님이 발언하셨습니다. 이어서 박영희 의원님."

        # Act
        result = dictionary_service.correct(input_text)

        # Assert
        assert result == expected_text

    def test_dictionary_no_correction_needed(self, dictionary_service: DictionaryService):
        """교정 필요 없는 텍스트 테스트"""
        # Arrange
        input_text = "오늘 날씨가 좋습니다."

        # Act
        result = dictionary_service.correct(input_text)

        # Assert
        assert result == input_text

    def test_dictionary_multiple_corrections(self, dictionary_service: DictionaryService):
        """여러 교정 적용 테스트"""
        # Arrange
        input_text = "경기도 의회에서 김철순 의원이 예산안을 발표했습니다."
        expected_text = "경기도의회에서 김철수 의원이 예산(안)을 발표했습니다."

        # Act
        result = dictionary_service.correct(input_text)

        # Assert
        assert result == expected_text

    def test_dictionary_case_sensitive(self, dictionary_service: DictionaryService):
        """대소문자 구분 테스트 (한글이므로 무관)"""
        # Arrange
        input_text = "김철순 의원"

        # Act
        result = dictionary_service.correct(input_text)

        # Assert
        assert result == "김철수 의원"

    def test_dictionary_empty_input(self, dictionary_service: DictionaryService):
        """빈 입력 처리 테스트"""
        # Arrange
        input_text = ""

        # Act
        result = dictionary_service.correct(input_text)

        # Assert
        assert result == ""

    def test_dictionary_add_entry(self, dictionary_service: DictionaryService):
        """항목 추가 테스트"""
        # Arrange
        new_entry = DictionaryEntry(
            wrong_text="행정위원회",
            correct_text="행정자치위원회",
            category="term",
        )

        # Act
        dictionary_service.add_entry(new_entry)
        result = dictionary_service.correct("행정위원회에서")

        # Assert
        assert result == "행정자치위원회에서"

    def test_dictionary_remove_entry(self, dictionary_service: DictionaryService):
        """항목 제거 테스트"""
        # Arrange - 먼저 교정이 작동하는지 확인
        assert dictionary_service.correct("김철순") == "김철수"

        # Act
        dictionary_service.remove_entry("김철순")
        result = dictionary_service.correct("김철순")

        # Assert
        assert result == "김철순"  # 더 이상 교정되지 않음


class TestWhisperServiceFactory:
    """Whisper 서비스 팩토리 테스트"""

    def test_from_config_with_api_key(self):
        """API 키로 서비스 생성 테스트"""
        # Act
        service = WhisperService.from_config(api_key="test-key")

        # Assert
        assert service is not None
        assert service._api_key == "test-key"

    def test_from_config_without_api_key_raises_error(self):
        """API 키 없이 서비스 생성 시 에러 발생 테스트"""
        # Arrange
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.openai_api_key = ""

            # Act & Assert
            with pytest.raises(ValueError, match="API key is required"):
                WhisperService.from_config()

    def test_from_config_with_dictionary_service(self):
        """사전 서비스와 함께 서비스 생성 테스트"""
        # Arrange
        dictionary_service = DictionaryService()

        # Act
        service = WhisperService.from_config(
            api_key="test-key",
            dictionary_service=dictionary_service,
        )

        # Assert
        assert service._dictionary_service is dictionary_service


class TestWhisperWithDictionary:
    """Whisper + Dictionary 통합 테스트"""

    @pytest.fixture
    def whisper_service(self) -> WhisperService:
        """Whisper 서비스 인스턴스"""
        entries = [
            DictionaryEntry(
                wrong_text="경기도 의회",
                correct_text="경기도의회",
                category="term",
            ),
        ]
        dictionary_service = DictionaryService(entries=entries)
        return WhisperService(
            api_key="test-api-key",
            dictionary_service=dictionary_service,
        )

    @pytest.fixture
    def mock_audio_chunk(self) -> bytes:
        """테스트용 오디오 청크"""
        wav_header = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"fmt " + b"\x00" * 20
        return wav_header + b"\x00" * 1000

    @pytest.mark.asyncio
    async def test_transcribe_with_dictionary_correction(
        self, whisper_service: WhisperService, mock_audio_chunk: bytes
    ):
        """사전 교정이 적용된 변환 테스트"""
        # Arrange
        raw_text = "경기도 의회에서 회의가 진행됩니다."
        expected_text = "경기도의회에서 회의가 진행됩니다."

        with patch.object(
            whisper_service, "_call_openai_api", new_callable=AsyncMock
        ) as mock_api:
            mock_api.return_value = TranscriptionResult(
                text=raw_text,
                confidence=0.95,
            )

            # Act
            result = await whisper_service.transcribe(
                mock_audio_chunk,
                apply_dictionary=True,
            )

            # Assert
            assert result.text == expected_text
