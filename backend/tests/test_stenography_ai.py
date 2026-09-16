"""속기록 AI 보조 서비스 테스트

# @TASK P11C-T7.2 - AI 보조 서비스 테스트
# @TEST backend/tests/test_stenography_ai.py
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.stenography_ai import (
    auto_detect_speakers,
    auto_proofread,
    auto_paragraphs,
)


@pytest.fixture
def mock_supabase():
    """Supabase REST 클라이언트 mock"""
    client = MagicMock()
    return client


@pytest.fixture
def sample_lines():
    """테스트용 속기록 라인"""
    return [
        {"id": str(uuid.uuid4()), "sequence_no": 1, "text": "의장 그럼 회의를 시작하겠습니다.", "speaker": None},
        {"id": str(uuid.uuid4()), "sequence_no": 2, "text": "네, 김철수 의원 발언하시기 바랍니다.", "speaker": None},
        {"id": str(uuid.uuid4()), "sequence_no": 3, "text": "감사합니다 의장님. 저는 이번 안건에 대해...", "speaker": None},
        {"id": str(uuid.uuid4()), "sequence_no": 4, "text": "좋습니다. 다음 안건으로 넘어가겠습니다.", "speaker": None},
    ]


class TestAutoDetectSpeakers:
    """화자 자동 구분 테스트"""

    @pytest.mark.asyncio
    async def test_auto_detect_speakers_returns_suggestions(self, mock_supabase, sample_lines):
        """화자 자동 구분이 제안 목록을 반환"""
        record_id = str(uuid.uuid4())
        meeting_id = str(uuid.uuid4())

        # 라인 조회 mock
        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
            data=sample_lines
        )

        # councilors 조회 mock (빈 결과)
        mock_councilors = MagicMock()
        mock_councilors.data = []

        openai_response = {
            "choices": [{
                "message": {
                    "content": json.dumps([
                        {"line_id": sample_lines[0]["id"], "suggested_speaker": "의장"},
                        {"line_id": sample_lines[1]["id"], "suggested_speaker": "의장"},
                        {"line_id": sample_lines[2]["id"], "suggested_speaker": "김철수 의원"},
                        {"line_id": sample_lines[3]["id"], "suggested_speaker": "의장"},
                    ])
                }
            }]
        }

        with patch("app.services.stenography_ai._call_openai_json", new_callable=AsyncMock) as mock_openai:
            mock_openai.return_value = json.loads(openai_response["choices"][0]["message"]["content"])

            # table side effect
            call_count = {"n": 0}
            original_table = mock_supabase.table

            def table_side_effect(name):
                call_count["n"] += 1
                mock_table = MagicMock()
                if name == "stenography_lines":
                    mock_table.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(data=sample_lines)
                elif name == "councilors":
                    mock_table.select.return_value.eq.return_value.execute.return_value = mock_councilors
                return mock_table

            mock_supabase.table.side_effect = table_side_effect

            result = await auto_detect_speakers(mock_supabase, record_id, meeting_id)

            assert len(result) == 4
            assert result[0]["suggested_speaker"] == "의장"

    @pytest.mark.asyncio
    async def test_auto_detect_speakers_empty_lines(self, mock_supabase):
        """라인이 없으면 빈 목록 반환"""
        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
            data=[]
        )

        result = await auto_detect_speakers(mock_supabase, str(uuid.uuid4()), str(uuid.uuid4()))
        assert result == []


class TestAutoProofread:
    """맞춤법/용어 교정 테스트"""

    @pytest.mark.asyncio
    async def test_auto_proofread_returns_corrections(self, mock_supabase, sample_lines):
        """교정 결과를 반환"""
        record_id = str(uuid.uuid4())

        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
            data=sample_lines
        )
        # dictionary mock
        mock_supabase.table.return_value.select.return_value.execute.return_value = MagicMock(data=[])

        corrections = [
            {
                "line_id": sample_lines[0]["id"],
                "original_text": "의장 그럼 회의를 시작하겠습니다.",
                "corrected_text": "의장, 그럼 회의를 시작하겠습니다.",
                "changes": ["쉼표 추가"],
            }
        ]

        with patch("app.services.stenography_ai._call_openai_json", new_callable=AsyncMock) as mock_openai:
            mock_openai.return_value = corrections

            def table_side_effect(name):
                mock_table = MagicMock()
                if name == "stenography_lines":
                    mock_table.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(data=sample_lines)
                elif name == "dictionary":
                    mock_table.select.return_value.execute.return_value = MagicMock(data=[])
                return mock_table

            mock_supabase.table.side_effect = table_side_effect

            result = await auto_proofread(mock_supabase, record_id)

            assert len(result) == 1
            assert "쉼표 추가" in result[0]["changes"]


class TestAutoParagraphs:
    """문단 자동 구분 테스트"""

    @pytest.mark.asyncio
    async def test_auto_paragraphs_returns_paragraph_breaks(self, mock_supabase, sample_lines):
        """문단 구분 결과를 반환"""
        record_id = str(uuid.uuid4())

        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
            data=sample_lines
        )

        paragraph_result = [
            {"line_id": sample_lines[2]["id"], "starts_new_paragraph": True},
        ]

        with patch("app.services.stenography_ai._call_openai_json", new_callable=AsyncMock) as mock_openai:
            mock_openai.return_value = paragraph_result

            result = await auto_paragraphs(mock_supabase, record_id)

            assert len(result) == 1
            assert result[0]["starts_new_paragraph"] is True

    @pytest.mark.asyncio
    async def test_auto_paragraphs_empty_lines(self, mock_supabase):
        """라인이 없으면 빈 목록 반환"""
        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
            data=[]
        )

        result = await auto_paragraphs(mock_supabase, str(uuid.uuid4()))
        assert result == []
