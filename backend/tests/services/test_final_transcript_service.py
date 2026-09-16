import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.final_transcript_service import correct_segments_with_llm


@pytest.mark.asyncio
async def test_correct_segments_with_llm_applies_corrections():
    segments = [
        {"speaker": "화자 1", "start_time": 0.0, "end_time": 5.0, "text": "사내를 선포합니다"},
    ]
    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock()]
    fake_resp.choices[0].message.content = json.dumps(
        {"segments": [{"index": 0, "text": "산회를 선포합니다."}]}
    )
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=fake_resp)

    result = await correct_segments_with_llm(
        client=client,
        segments=segments,
        glossary_prompt="표기 일치: 산회",
        hint_texts=["산회를 선포합니다"],
        model="gpt-5-mini",
    )
    assert result[0]["text"] == "산회를 선포합니다."
    assert result[0]["start_time"] == 0.0
    assert result[0]["speaker"] == "화자 1"


@pytest.mark.asyncio
async def test_correct_segments_with_llm_falls_back_on_parse_error():
    segments = [{"speaker": "화자 1", "start_time": 0.0, "end_time": 5.0, "text": "원본"}]
    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock()]
    fake_resp.choices[0].message.content = "엉뚱한 비JSON 응답"
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=fake_resp)

    result = await correct_segments_with_llm(
        client=client, segments=segments, glossary_prompt="", hint_texts=[], model="gpt-5-mini"
    )
    assert result[0]["text"] == "원본"


from app.services.final_transcript_service import persist_final_lines


def test_persist_final_lines_creates_record_and_lines():
    inserted = {"records": [], "lines": []}
    supabase = MagicMock()

    def table(name):
        m = MagicMock()
        if name == "stenography_records":
            m.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

            def insert(payload):
                inserted["records"].append(payload)
                r = MagicMock()
                r.execute.return_value.data = [{"id": "rec-1", **payload}]
                return r

            m.insert.side_effect = insert
        elif name == "stenography_lines":
            def insert(payload):
                inserted["lines"].extend(payload if isinstance(payload, list) else [payload])
                r = MagicMock()
                r.execute.return_value.data = payload
                return r

            m.insert.side_effect = insert
            m.delete.return_value.eq.return_value.execute.return_value.data = []
        return m

    supabase.table.side_effect = table

    segments = [
        {"speaker": "화자 1", "start_time": 0.0, "end_time": 5.0, "text": "안녕하세요."},
        {"speaker": "화자 1", "start_time": 5.0, "end_time": 9.0, "text": "회의를 시작합니다."},
    ]
    record_id = persist_final_lines(supabase, "meeting-uuid", segments, source_meta={"model": "gpt-5-mini"})

    assert record_id == "rec-1"
    assert inserted["records"][0]["kind"] == "ai_final"
    assert len(inserted["lines"]) == 2
    assert inserted["lines"][0]["text"] == "안녕하세요."
    assert inserted["lines"][0]["start_ms"] == 0
    assert inserted["lines"][1]["start_ms"] == 5000


# ── Step A: task-status store ─────────────────────────────────────────────────

from app.services.final_transcript_service import (
    FinalTaskStatus, get_final_task, set_final_task,
)


def test_final_task_store_roundtrip():
    task = FinalTaskStatus(meeting_id="m-1", status="running", progress=0.5, message="교정 중")
    set_final_task("m-1", task)
    got = get_final_task("m-1")
    assert got is not None
    assert got.status == "running"
    assert got.progress == 0.5


# ── Step B: orchestrator happy path ──────────────────────────────────────────


def test_generate_final_transcript_happy_path(monkeypatch):
    import asyncio as _aio
    from app.services.final_transcript_service import generate_final_transcript

    supabase = MagicMock()
    supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"id": "m-1", "vod_url": "https://kms/x.mp4"}
    ]
    # subtitles(hint) 조회도 같은 chain을 타므로 order까지 mock
    supabase.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = []

    async def fake_retranscribe(meeting_id, vod_url, task):
        return [{"speaker": "화자 1", "start_time": 0.0, "end_time": 4.0, "text": "사내를 선포"}]

    monkeypatch.setattr("app.services.final_transcript_service._retranscribe_vod", fake_retranscribe)
    monkeypatch.setattr("app.services.final_transcript_service.load_meeting_glossary", lambda sb, mid: ["산회"])

    async def fake_correct(**kwargs):
        return [{"speaker": "화자 1", "start_time": 0.0, "end_time": 4.0, "text": "산회를 선포합니다."}]

    monkeypatch.setattr("app.services.final_transcript_service.correct_segments_with_llm", fake_correct)
    monkeypatch.setattr(
        "app.services.final_transcript_service.persist_final_lines",
        lambda sb, mid, segs, source_meta=None: "rec-9",
    )
    monkeypatch.setattr("app.services.final_transcript_service._make_openai_client", lambda: MagicMock())

    _aio.run(generate_final_transcript(supabase, "m-1"))

    task = get_final_task("m-1")
    assert task.status == "completed"
    assert task.record_id == "rec-9"
