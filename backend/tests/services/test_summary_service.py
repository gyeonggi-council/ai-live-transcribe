# @TASK P7-T2.1 - AI 요약 서비스 테스트
# @TEST tests/services/test_summary_service.py

"""summary_service 모듈 테스트

_format_subtitles_for_prompt, generate_meeting_summary,
get_summary, delete_summary 를 테스트합니다.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.summary_service import (
    MAX_TRANSCRIPT_CHARS,
    MeetingSummary,
    _call_openai_summary,
    _format_subtitles_for_prompt,
    _format_time_hms,
    delete_summary,
    generate_meeting_summary,
    get_summary,
)
from tests.conftest import MockSupabaseClient


# ──────────────────────────────────────────────
# _format_time_hms 헬퍼 테스트
# ──────────────────────────────────────────────


class TestFormatTimeHms:
    def test_zero(self):
        assert _format_time_hms(0) == "00:00:00"

    def test_seconds_only(self):
        assert _format_time_hms(45) == "00:00:45"

    def test_minutes_and_seconds(self):
        assert _format_time_hms(125) == "00:02:05"

    def test_hours_minutes_seconds(self):
        assert _format_time_hms(3661) == "01:01:01"

    def test_float_input(self):
        assert _format_time_hms(90.7) == "00:01:30"


# ──────────────────────────────────────────────
# _format_subtitles_for_prompt 테스트
# ──────────────────────────────────────────────

SAMPLE_SUBTITLES = [
    {
        "id": "s1",
        "meeting_id": "test-123",
        "start_time": 30.0,
        "end_time": 35.0,
        "text": "회의를 시작하겠습니다.",
        "speaker": "의장",
        "confidence": 0.95,
    },
    {
        "id": "s2",
        "meeting_id": "test-123",
        "start_time": 75.0,
        "end_time": 82.0,
        "text": "첫 번째 안건을 논의하겠습니다.",
        "speaker": "김위원",
        "confidence": 0.90,
    },
    {
        "id": "s3",
        "meeting_id": "test-123",
        "start_time": 150.0,
        "end_time": 160.0,
        "text": "찬성합니다.",
        "speaker": None,
        "confidence": 0.88,
    },
]

SAMPLE_AGENDAS = [
    {"order_num": 1, "title": "2026년 예산안 심의"},
    {"order_num": 2, "title": "조례 개정안 논의"},
]


class TestFormatSubtitlesForPrompt:
    def test_basic_formatting(self):
        result = _format_subtitles_for_prompt(SAMPLE_SUBTITLES)
        assert "[00:00:30] 의장: 회의를 시작하겠습니다." in result
        assert "[00:01:15] 김위원: 첫 번째 안건을 논의하겠습니다." in result

    def test_null_speaker_fallback(self):
        """화자가 None이면 '발언자 미확인'으로 표시."""
        result = _format_subtitles_for_prompt(SAMPLE_SUBTITLES)
        assert "[00:02:30] 발언자 미확인: 찬성합니다." in result

    def test_empty_subtitles(self):
        result = _format_subtitles_for_prompt([])
        assert result == ""

    def test_with_agendas(self):
        """안건 목록이 있으면 상단에 포함."""
        result = _format_subtitles_for_prompt(SAMPLE_SUBTITLES, SAMPLE_AGENDAS)
        assert "=== 안건 목록 ===" in result
        assert "1. 2026년 예산안 심의" in result
        assert "2. 조례 개정안 논의" in result
        assert "=== 회의 자막 ===" in result

    def test_without_agendas(self):
        """안건이 없으면 안건 섹션 미포함."""
        result = _format_subtitles_for_prompt(SAMPLE_SUBTITLES, None)
        assert "=== 안건 목록 ===" not in result

    def test_truncation_on_long_text(self):
        """매우 긴 자막은 MAX_TRANSCRIPT_CHARS로 잘림."""
        long_subtitles = []
        for i in range(500):
            long_subtitles.append({
                "start_time": float(i * 10),
                "end_time": float(i * 10 + 5),
                "text": f"이것은 매우 긴 자막 텍스트입니다. 번호: {i}. " * 5,
                "speaker": f"화자{i % 3}",
            })
        result = _format_subtitles_for_prompt(long_subtitles)
        # 잘린 텍스트 끝에 생략 안내 포함
        assert "이하 생략" in result
        # MAX_TRANSCRIPT_CHARS보다 약간 길 수 있음 (생략 메시지 포함)
        assert len(result) < MAX_TRANSCRIPT_CHARS + 100

    def test_missing_start_time_defaults_zero(self):
        """start_time이 없으면 0으로 기본값."""
        subs = [{"text": "테스트", "speaker": "화자"}]
        result = _format_subtitles_for_prompt(subs)
        assert "[00:00:00]" in result


# ──────────────────────────────────────────────
# _call_openai_summary 테스트 (mocked HTTP)
# ──────────────────────────────────────────────


MOCK_OPENAI_RESPONSE = {
    "choices": [
        {
            "message": {
                "content": json.dumps(
                    {
                        "summary_text": "경기도의회 본회의에서 예산안을 심의하고 조례 개정안을 논의했습니다.",
                        "agenda_summaries": [
                            {
                                "order_num": 1,
                                "title": "예산안 심의",
                                "summary": "2026년 예산안이 원안대로 가결되었습니다.",
                            }
                        ],
                        "key_decisions": ["2026년 예산안 가결"],
                        "action_items": ["세부 집행계획 수립"],
                    },
                    ensure_ascii=False,
                )
            }
        }
    ]
}


class TestCallOpenaiSummary:
    @pytest.mark.asyncio
    async def test_successful_call(self):
        """OpenAI API 정상 호출 시 MeetingSummary 반환."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = MOCK_OPENAI_RESPONSE

        with patch("app.services.summary_service.settings") as mock_settings:
            mock_settings.openai_api_key = "test-key"
            mock_settings.summary_model = "gpt-5-mini"
            with patch("app.services.summary_service.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post.return_value = mock_response
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                result = await _call_openai_summary("테스트 자막 텍스트")

        assert isinstance(result, MeetingSummary)
        assert "예산안" in result.summary_text
        assert len(result.agenda_summaries) == 1
        assert result.key_decisions == ["2026년 예산안 가결"]
        assert result.action_items == ["세부 집행계획 수립"]
        assert result.model_used == "gpt-5-mini"

    @pytest.mark.asyncio
    async def test_missing_api_key_raises(self):
        """API 키가 없으면 ValueError."""
        with patch("app.services.summary_service.settings") as mock_settings:
            mock_settings.openai_api_key = ""
            with pytest.raises(ValueError, match="OPENAI_API_KEY"):
                await _call_openai_summary("테스트")

    @pytest.mark.asyncio
    async def test_json_with_code_block(self):
        """코드블록으로 감싸진 JSON도 파싱."""
        code_block_content = '```json\n{"summary_text": "요약입니다.", "agenda_summaries": [], "key_decisions": [], "action_items": []}\n```'
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": code_block_content}}]
        }

        with patch("app.services.summary_service.settings") as mock_settings:
            mock_settings.openai_api_key = "test-key"
            with patch("app.services.summary_service.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post.return_value = mock_response
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                result = await _call_openai_summary("테스트")

        assert result.summary_text == "요약입니다."

    @pytest.mark.asyncio
    async def test_invalid_json_raises(self):
        """JSON 파싱 실패는 오류다 — 예전엔 원문 500자를 요약으로 저장해 깨진 결과가 캐시에 갇혔다(2026-09-14)."""
        from app.services.summary_service import SummaryGenerationError

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "이것은 유효하지 않은 JSON입니다."}}]
        }

        with patch("app.services.summary_service.settings") as mock_settings:
            mock_settings.openai_api_key = "test-key"
            mock_settings.summary_model = "gpt-5.4-mini"
            with patch("app.services.summary_service.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post.return_value = mock_response
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                with pytest.raises(SummaryGenerationError):
                    await _call_openai_summary("테스트")


# ──────────────────────────────────────────────
# generate_meeting_summary 통합 테스트
# ──────────────────────────────────────────────


def _router_client(subtitles=None, existing=None, upsert_error=None):
    """table() 이름별 MagicMock 체인 — subtitles(range 페이지 포함)·meeting_agendas·meeting_summaries."""
    client = MagicMock()
    sq = MagicMock()
    for m in ("select", "eq", "order", "range", "limit"):
        getattr(sq, m).return_value = sq
    sq.execute.return_value = MagicMock(data=list(subtitles if subtitles is not None else SAMPLE_SUBTITLES))
    aq = MagicMock()
    for m in ("select", "eq", "order"):
        getattr(aq, m).return_value = aq
    aq.execute.return_value = MagicMock(data=[])
    mq = MagicMock()
    for m in ("select", "eq", "order", "limit", "delete"):
        getattr(mq, m).return_value = mq
    mq.execute.return_value = MagicMock(data=list(existing or []))
    if upsert_error is not None:
        mq.upsert.side_effect = upsert_error
    else:
        mq.upsert.return_value = mq
    client.summary_query = mq

    def route(name):
        return {"subtitles": sq, "meeting_agendas": aq, "meeting_summaries": mq}.get(name, MagicMock())

    client.table.side_effect = route
    return client


class TestGenerateMeetingSummary:
    @pytest.mark.asyncio
    async def test_generates_summary_with_subtitles(self):
        """자막이 있는 회의의 요약 생성."""
        mock_supabase = MockSupabaseClient(
            table_data={
                "subtitles": SAMPLE_SUBTITLES,
                "meeting_summaries": [],
            }
        )

        expected_summary = MeetingSummary(
            summary_text="테스트 요약입니다.",
            agenda_summaries=[],
            key_decisions=["결정1"],
            action_items=["조치1"],
        )

        with patch(
            "app.services.summary_service._call_openai_summary",
            new_callable=AsyncMock,
            return_value=expected_summary,
        ) as mock_call:
            result = await generate_meeting_summary(mock_supabase, "test-123")

        assert isinstance(result, MeetingSummary)
        assert result.summary_text == "테스트 요약입니다."
        assert result.key_decisions == ["결정1"]
        mock_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_when_no_subtitles(self):
        """자막이 없으면 ValueError."""
        mock_supabase = MockSupabaseClient(
            table_data={"subtitles": []}
        )

        with pytest.raises(ValueError, match="자막이 없습니다"):
            await generate_meeting_summary(mock_supabase, "test-123")

    @pytest.mark.asyncio
    async def test_continues_when_agenda_table_missing(self):
        """meeting_agendas 테이블이 없어도 정상 동작."""
        # MockSupabaseClient는 없는 테이블에 빈 배열 반환
        mock_supabase = MockSupabaseClient(
            table_data={"subtitles": SAMPLE_SUBTITLES}
        )

        expected_summary = MeetingSummary(
            summary_text="요약",
            agenda_summaries=[],
            key_decisions=[],
            action_items=[],
        )

        with patch(
            "app.services.summary_service._call_openai_summary",
            new_callable=AsyncMock,
            return_value=expected_summary,
        ):
            result = await generate_meeting_summary(mock_supabase, "test-123")

        assert result.summary_text == "요약"

    @pytest.mark.asyncio
    async def test_db_save_failure_raises(self):
        """저장 실패는 오류다 — 정상처럼 돌려주면 다음 요청이 다시 생성해 비용이 두 번 든다(2026-09-14)."""
        from app.services.summary_service import SummaryGenerationError

        mock_supabase = _router_client(upsert_error=Exception("DB Error"))
        expected_summary = MeetingSummary(summary_text="요약 결과")
        with patch(
            "app.services.summary_service._call_openai_summary",
            new_callable=AsyncMock,
            return_value=expected_summary,
        ):
            with pytest.raises(SummaryGenerationError):
                await generate_meeting_summary(mock_supabase, "test-123")

    @pytest.mark.asyncio
    async def test_upsert_uses_meeting_id_conflict_and_new_columns(self):
        """upsert 는 on_conflict=meeting_id(UNIQUE) 이고 034 컬럼(complete·segments…)을 함께 쓴다."""
        mock_supabase = _router_client()
        with patch(
            "app.services.summary_service._call_openai_summary",
            new_callable=AsyncMock,
            return_value=MeetingSummary(summary_text="요약 결과"),
        ):
            result = await generate_meeting_summary(mock_supabase, "test-123")
        assert result.complete is True
        assert result.source_chars > 0
        call = mock_supabase.summary_query.upsert.call_args
        assert call.kwargs.get("on_conflict") == "meeting_id"
        payload = call.args[0]
        assert payload["complete"] is True and "segments" in payload and payload["generated_from"] == "ai"

    @pytest.mark.asyncio
    async def test_long_transcript_uses_map_reduce(self):
        """단일 호출 상한을 넘으면 청크 요약 → 병합. 청크 하나가 끝내 실패하면 저장하지 않는다."""
        from app.services import summary_service as svc

        long_subs = [
            {"id": str(i), "start_time": i * 10.0, "end_time": i * 10.0 + 9, "speaker": f"화자 {i % 3}", "text": "가" * 90, "kind": "ai"}
            for i in range(400)
        ]  # ≈ 400 × 110자 = 44,000자 > 12,000
        mock_supabase = _router_client(subtitles=long_subs)
        seen: list[int] = []

        async def fake_chunk(chunk, agendas):
            seen.append(chunk["idx"])
            return {**{k: chunk[k] for k in ("idx", "order_num", "title", "start_time", "end_time")},
                    "summary": f"구간 {chunk['idx']}", "topics": [], "decisions": [f"결정{chunk['idx']}"],
                    "action_items": [], "numbers": [], "speakers": [{"name": "화자 0", "points": ["p"]}]}

        async def fake_reduce(system, user, **kw):
            assert "구간별 요약" in user
            return {"summary_text": "병합 요약", "agenda_summaries": [], "key_decisions": ["결정0"], "action_items": []}

        with patch.object(svc, "_summarize_chunk", side_effect=fake_chunk), patch.object(
            svc, "_call_openai_json", side_effect=fake_reduce
        ), patch.object(svc, "_call_openai_summary", new_callable=AsyncMock) as single:
            result = await generate_meeting_summary(mock_supabase, "long-1")
        single.assert_not_called()
        assert result.summary_text == "병합 요약"
        assert len(seen) >= 4 and len(result.segments) == len(seen)
        assert result.speakers[0]["name"] == "화자 0"
        assert "map" in result.model_used

        # 일부 실패 → 저장 없이 오류
        mock_supabase2 = _router_client(subtitles=long_subs)

        async def flaky(chunk, agendas):
            if chunk["idx"] == 1:
                raise svc.SummaryGenerationError("x")
            return await fake_chunk(chunk, agendas)

        with patch.object(svc, "_summarize_chunk", side_effect=flaky), patch.object(svc, "_call_openai_json", side_effect=fake_reduce):
            with pytest.raises(svc.SummaryGenerationError):
                await generate_meeting_summary(mock_supabase2, "long-2")
        mock_supabase2.summary_query.upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_concurrent_requests_generate_once(self):
        """같은 회의 요청이 겹치면 한 번만 만든다(회의별 락) — 두 번째는 락을 기다린 뒤 캐시를 읽는다."""
        mock_supabase = _router_client()
        calls = 0

        async def slow(*a, **k):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.05)
            # 첫 생성이 저장되면 이후 get_summary 가 캐시를 돌려주도록 흉내
            mock_supabase.summary_query.execute.return_value.data = [{"summary_text": "캐시", "complete": True}]
            return MeetingSummary(summary_text="캐시")

        with patch("app.services.summary_service._call_openai_summary", side_effect=slow):
            r1, r2 = await asyncio.gather(
                generate_meeting_summary(mock_supabase, "conc-1"), generate_meeting_summary(mock_supabase, "conc-1")
            )
        assert calls == 1
        assert r1.summary_text == r2.summary_text == "캐시"

    @pytest.mark.asyncio
    async def test_daily_limit_and_cache_hit_not_counted(self):
        from app.services import summary_service as svc

        svc._daily.clear()
        with patch.object(svc.settings, "ai_summary_daily_limit", 1):
            mock_supabase = _router_client()
            with patch("app.services.summary_service._call_openai_summary", new_callable=AsyncMock, return_value=MeetingSummary(summary_text="a")):
                await generate_meeting_summary(mock_supabase, "lim-1")
            # 캐시 적중은 차감 없음
            cached = _router_client(existing=[{"summary_text": "있음", "complete": True}])
            assert (await generate_meeting_summary(cached, "lim-2")).summary_text == "있음"
            # 두 번째 실제 생성은 상한
            with pytest.raises(svc.SummaryLimitError):
                await generate_meeting_summary(_router_client(), "lim-3")
        svc._daily.clear()

    @pytest.mark.asyncio
    async def test_agendas_override_skips_db_lookup(self):
        """안건 초안이 방금 추출한(아직 저장 전) 목록을 넘기면 그것으로 요약한다."""
        mock_supabase = _router_client()
        extracted = [{"order_num": 1, "title": "경기도 청년 조례안"}]
        with patch("app.services.summary_service._call_openai_summary", new_callable=AsyncMock, return_value=MeetingSummary(summary_text="a")) as call:
            await generate_meeting_summary(mock_supabase, "ov-1", agendas_override=extracted)
        assert call.call_args.args[1] == extracted
        assert "=== 안건 목록 ===" in call.call_args.args[0]

    @pytest.mark.asyncio
    async def test_refresh_partial_regenerates_only_incomplete(self):
        old_row = {"summary_text": "옛 요약", "complete": False}
        with patch("app.services.summary_service._call_openai_summary", new_callable=AsyncMock, return_value=MeetingSummary(summary_text="새 요약")) as call:
            assert (await generate_meeting_summary(_router_client(existing=[old_row]), "p-1")).summary_text == "옛 요약"
            call.assert_not_called()
            assert (await generate_meeting_summary(_router_client(existing=[old_row]), "p-1", refresh_partial=True)).summary_text == "새 요약"
            # 완전한 요약은 refresh 를 무시
            full = {"summary_text": "완전", "complete": True}
            assert (await generate_meeting_summary(_router_client(existing=[full]), "p-2", refresh_partial=True)).summary_text == "완전"


class TestPregenFlagsAndReasoning:
    """2026-09-15 — 요약 미리 만들기 인자(count_daily·replace_live) · 추론 수준 전달."""

    @pytest.mark.asyncio
    async def test_count_daily_false_does_not_consume_user_limit(self):
        from app.services import summary_service as svc

        svc._daily.clear()
        with patch.object(svc.settings, "ai_summary_daily_limit", 1), patch(
            "app.services.summary_service._call_openai_summary", new_callable=AsyncMock, return_value=MeetingSummary(summary_text="a")
        ):
            await generate_meeting_summary(_router_client(), "pg-1", count_daily=False)
            await generate_meeting_summary(_router_client(), "pg-2", count_daily=False)
            # 미리 만들기가 두 건 만들어도 담당자의 1건은 남아 있다
            await generate_meeting_summary(_router_client(), "pg-3")
            with pytest.raises(svc.SummaryLimitError):
                await generate_meeting_summary(_router_client(), "pg-4")
        svc._daily.clear()

    @pytest.mark.asyncio
    async def test_replace_live_regenerates_only_live_based(self):
        live_row = {"summary_text": "실시간 자막 요약", "complete": True, "generated_from": "live"}
        ai_row = {"summary_text": "AI 자막 요약", "complete": True, "generated_from": "ai"}
        with patch("app.services.summary_service._call_openai_summary", new_callable=AsyncMock, return_value=MeetingSummary(summary_text="새 요약")) as call:
            assert (await generate_meeting_summary(_router_client(existing=[live_row]), "rl-1")).summary_text == "실시간 자막 요약"
            call.assert_not_called()
            assert (await generate_meeting_summary(_router_client(existing=[live_row]), "rl-1", replace_live=True)).summary_text == "새 요약"
            assert (await generate_meeting_summary(_router_client(existing=[ai_row]), "rl-2", replace_live=True)).summary_text == "AI 자막 요약"

    @pytest.mark.asyncio
    async def test_reasoning_effort_in_request_body(self):
        from app.services import summary_service as svc

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch.object(svc.settings, "openai_api_key", "k"), patch(
            "app.services.summary_service.httpx.AsyncClient", return_value=mock_client
        ):
            await svc._call_openai_json("s", "u", model="m", max_tokens=10, timeout=1, reasoning_effort="low")
            assert mock_client.post.call_args.kwargs["json"]["reasoning_effort"] == "low"
            await svc._call_openai_json("s", "u", model="m", max_tokens=10, timeout=1)
            assert "reasoning_effort" not in mock_client.post.call_args.kwargs["json"]


class TestRenderSegments:
    def test_every_chunk_survives_budget(self):
        """병합 입력은 청크를 하나도 버리지 않는다 — 예산이 모자라면 본문을 줄인다(Codex P1)."""
        from app.services.summary_service import _render_segments

        segs = [
            {"idx": i, "order_num": None, "title": None, "start_time": i * 600.0, "end_time": i * 600.0 + 599,
             "summary": "요" * 900, "decisions": ["결정" * 40], "action_items": ["조치" * 40], "numbers": ["수치" * 40], "speakers": []}
            for i in range(20)
        ]
        text = _render_segments(segs, None, 12000)
        assert len(text) <= 12000
        for i in range(20):
            assert f"[구간 {i + 1} ·" in text


class TestBuildSummaryChunks:
    def test_chunks_cover_every_subtitle_without_cutting(self):
        from app.services.summary_service import build_summary_chunks

        subs = [
            {"id": str(i), "start_time": i * 10.0, "end_time": i * 10.0 + 9, "speaker": "위원장" if i % 4 == 0 else f"화자 {i % 2}", "text": "나" * 100, "kind": "ai"}
            for i in range(120)
        ]
        chunks = build_summary_chunks(subs, agendas=None, target_chars=2000)
        flat = [s["id"] for c in chunks for s in c["subtitles"]]
        assert flat == [s["id"] for s in subs]  # 순서 보존·누락 없음·중복 없음
        assert len(chunks) >= 5
        for c in chunks:
            assert c["start_time"] <= c["end_time"]
            assert sum(len(s["text"]) + 24 for s in c["subtitles"]) <= 2000 * 1.5 + 130

    def test_agenda_anchor_starts_new_chunk(self):
        from app.services.summary_service import build_summary_chunks

        subs = [{"id": str(i), "start_time": i * 10.0, "end_time": i * 10.0 + 9, "speaker": "위원장", "text": "일반 발언입니다", "kind": "ai"} for i in range(40)]
        subs[20]["text"] = "의사일정 제1항 경기도 청년 주거 지원 조례안을 상정합니다"
        agendas = [{"order_num": 1, "title": "경기도 청년 주거 지원 조례안"}]
        chunks = build_summary_chunks(subs, agendas=agendas, target_chars=100000)
        assert len(chunks) == 2
        assert chunks[1]["subtitles"][0]["id"] == "20"
        assert chunks[1]["order_num"] == 1 and chunks[0]["order_num"] is None


# ──────────────────────────────────────────────
# get_summary 테스트
# ──────────────────────────────────────────────


class TestGetSummary:
    @pytest.mark.asyncio
    async def test_returns_summary_when_exists(self):
        """저장된 요약이 있으면 반환."""
        stored_summary = {
            "meeting_id": "test-123",
            "summary_text": "저장된 요약",
            "agenda_summaries": [],
            "key_decisions": [],
            "action_items": [],
            "model_used": "gpt-5-mini",
        }
        mock_supabase = MockSupabaseClient(
            table_data={"meeting_summaries": [stored_summary]}
        )

        result = await get_summary(mock_supabase, "test-123")
        assert result is not None
        assert result["summary_text"] == "저장된 요약"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_exists(self):
        """저장된 요약이 없으면 None."""
        mock_supabase = MockSupabaseClient(
            table_data={"meeting_summaries": []}
        )

        result = await get_summary(mock_supabase, "nonexistent-id")
        assert result is None


# ──────────────────────────────────────────────
# delete_summary 테스트
# ──────────────────────────────────────────────


class TestDeleteSummary:
    @pytest.mark.asyncio
    async def test_delete_returns_true(self):
        """삭제 성공 시 True 반환."""
        mock_supabase = MockSupabaseClient(
            table_data={"meeting_summaries": [{"meeting_id": "test-123"}]}
        )

        result = await delete_summary(mock_supabase, "test-123")
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_returns_false_on_error(self):
        """삭제 실패 시 False 반환."""
        mock_supabase = MagicMock()
        mock_query = MagicMock()
        mock_query.delete.return_value = mock_query
        mock_query.eq.side_effect = Exception("DB Error")
        mock_supabase.table.return_value = mock_query

        result = await delete_summary(mock_supabase, "test-123")
        assert result is False


# ──────────────────────────────────────────────
# MeetingSummary 데이터클래스 테스트
# ──────────────────────────────────────────────


class TestMeetingSummaryDataclass:
    def test_default_values(self):
        """기본값이 올바르게 설정되는지 확인."""
        summary = MeetingSummary(summary_text="테스트")
        assert summary.summary_text == "테스트"
        assert summary.agenda_summaries == []
        assert summary.key_decisions == []
        assert summary.action_items == []
        assert summary.model_used == "gpt-5-mini"

    def test_full_initialization(self):
        """모든 필드를 지정하여 초기화."""
        summary = MeetingSummary(
            summary_text="전체 요약",
            agenda_summaries=[{"order_num": 1, "title": "안건1", "summary": "요약1"}],
            key_decisions=["결정1", "결정2"],
            action_items=["조치1"],
            model_used="gpt-4o",
        )
        assert summary.summary_text == "전체 요약"
        assert len(summary.agenda_summaries) == 1
        assert len(summary.key_decisions) == 2
        assert summary.model_used == "gpt-4o"
