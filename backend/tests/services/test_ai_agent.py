"""에이전트형 대화(services/ai_agent, 2026-09-15) — 도구 호출·강제 재검색·도구 결과·폴백."""
import json
from unittest.mock import patch

import pytest

from app.services import ai_agent as ag

SUBS = [
    {"id": "a", "start_time": 100.0, "speaker": "전자영 위원", "text": "개인정보 보안 대책은 어떻게 됩니까?"},
    {"id": "b", "start_time": 110.0, "speaker": "김기덕 팀장", "text": "국정원 보안검토를 받겠습니다."},
    {"id": "c", "start_time": 900.0, "speaker": "이자형 위원", "text": "모바일 공무원증 조직 정보가 틀립니다."},
]
MEETING = {"id": "m1", "title": "운영위"}


def _sse(obj):
    return "data: " + json.dumps(obj, ensure_ascii=False)


def tool_resp(name, args, call_id="c1"):
    return [_sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": call_id, "function": {"name": name, "arguments": ""}}]}}]}),
            _sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": json.dumps(args, ensure_ascii=False)}}]}}]}),
            _sse({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}), "data: [DONE]"]


def text_resp(text):
    return [_sse({"choices": [{"delta": {"content": text}}]}), _sse({"choices": [{"delta": {}, "finish_reason": "stop"}]}), "data: [DONE]"]


def fake_client(responses, bodies):
    class _Resp:
        status_code = 200

        def __init__(self, lines):
            self.lines = lines

        async def aread(self):
            return b""

        async def aiter_lines(self):
            for line in self.lines:
                yield line

    class _Ctx:
        def __init__(self, lines):
            self.lines = lines

        async def __aenter__(self):
            return _Resp(self.lines)

        async def __aexit__(self, *a):
            return False

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, method, url, headers=None, json=None):
            bodies.append(json)
            return _Ctx(responses.pop(0))

    return patch("app.services.ai_agent.httpx.AsyncClient", return_value=_Client())


def toolbox():
    return ag.MeetingToolbox(meeting=MEETING, subs=SUBS, agendas=[], summary={"summary_text": "요약"}, roster=["전자영", "이자형"],
                             requests_loader=lambda: [{"start_time": 100, "councilor_name": "전자영", "summary": "보안 자료", "status": "detected"}])


async def run(responses, bodies):
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]
    events = []
    with patch("app.services.ai_rag_service.settings.openai_api_key", "k"), fake_client(responses, bodies):
        async for e in ag.stream_agent_answer("q", msgs, toolbox(), []):
            events.append(e)
    return events, msgs


@pytest.mark.asyncio
async def test_tool_round_then_answer_with_status_and_sources():
    bodies = []
    events, msgs = await run([tool_resp("read_transcript", {"start": "00:01:30", "end": "00:02:00"}), text_resp("전자영 위원이 물었습니다")], bodies)
    kinds = [k for k, _ in events]
    assert kinds[0] == "start" and "status" in kinds and kinds[-1] == "done"
    assert events[-1][1]["answer"] == "전자영 위원이 물었습니다"
    assert [s["start_time"] for s in events[-1][1]["sources"]][:2] == [100.0, 110.0]   # 도구가 실제로 읽은 행
    tool_msg = next(m for m in msgs if m.get("role") == "tool")
    assert "[00:01:40] 전자영 위원" in tool_msg["content"]
    assert bodies[0]["tool_choice"] == "auto" and bodies[0]["tools"]


@pytest.mark.asyncio
async def test_not_found_without_tools_forces_one_tool_round():
    bodies = []
    events, _ = await run([text_resp("관련 자료를 찾지 못했습니다."), tool_resp("search_meeting", {"query": "보안"}),
                           text_resp("전자영 위원입니다")], bodies)
    kinds = [k for k, _ in events]
    assert "reset" in kinds and events[-1][1]["answer"] == "전자영 위원입니다"
    assert bodies[1]["tool_choice"] == "required"


@pytest.mark.asyncio
async def test_last_round_disables_tools():
    bodies = []
    with patch.object(ag.settings, "ai_agent_max_rounds", 1):
        events, _ = await run([tool_resp("list_speakers", {}), text_resp("답")], bodies)
    assert bodies[-1]["tool_choice"] == "none" and events[-1][1]["answer"] == "답"


@pytest.mark.asyncio
async def test_toolbox_tools():
    tb = toolbox()
    assert "전자영 위원 — 발언 1회" in await tb.run("list_speakers", {})
    long = await tb.run("read_transcript", {"start": "00:00:00", "end": "05:00:00"})
    assert "모바일" not in long                     # 10분으로 자른다(900초 행은 밖)
    assert "시각은" in await tb.run("read_transcript", {"start": "1분", "end": "2분"})
    assert "보안 자료" in await tb.run("get_material_requests", {"councilor": "전자영"})
    hit = await tb.run("search_meeting", {"query": "모바일 공무원증", "speaker": "이자형"})
    assert "모바일 공무원증 조직 정보" in hit
    assert "알 수 없는 도구" in await tb.run("make_document", {})


@pytest.mark.asyncio
async def test_stream_agent_falls_back_when_disabled():
    from app.services import ai_rag_service as svc

    async def fake_stream(*a, **k):
        yield ("start", None)
        yield ("done", {"answer": "한 번 답", "sources": []})

    ctx = [{"source_type": "context_block", "text": "발췌", "sources": [], "stats": {}, "_raw": {"meeting": MEETING}}]
    with patch.object(svc.settings, "ai_agent_enabled", False), patch.object(svc, "stream_answer", fake_stream):
        got = [e async for e in svc.stream_agent("q", ctx, "m1", [], None)]
    assert got[-1][1]["answer"] == "한 번 답"


@pytest.mark.asyncio
async def test_material_requests_page_and_count():
    rows = [{"start_time": i, "councilor_name": f"의원{i}", "summary": f"요구{i}", "status": "detected"} for i in range(31)]
    tb = ag.MeetingToolbox(meeting=MEETING, subs=SUBS, agendas=[], summary={}, roster=[], requests_loader=lambda: rows)
    first = await tb.run("get_material_requests", {})
    assert first.startswith("자료요구 전체 31건 중 1~30번") and "offset=30" in first
    second = await tb.run("get_material_requests", {"offset": 30})
    assert "31~31번" in second and "요구30" in second and "offset=" not in second


@pytest.mark.asyncio
async def test_read_transcript_sources_only_returned_rows():
    subs = [{"id": str(i), "start_time": float(i), "speaker": "이자형 위원", "text": "가" * 1400} for i in range(4)]
    tb = ag.MeetingToolbox(meeting=MEETING, subs=subs, agendas=[], summary={}, roster=[])
    out = await tb.run("read_transcript", {"start": "00:00:00", "end": "00:00:10"})
    shown = out.count("[00:00:0")
    assert shown == 2 and "이하 생략" in out
    assert [r["start_time"] for r in tb.seen] == [0.0, 1.0]


@pytest.mark.asyncio
async def test_overall_time_limit_is_enforced():
    import asyncio as aio

    class _Slow:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, *a, **k):
            class _C:
                async def __aenter__(self_inner):
                    await aio.sleep(0.3)
                    raise AssertionError("should have timed out")

                async def __aexit__(self_inner, *a):
                    return False
            return _C()

    from app.services.ai_rag_service import AiUpstreamError
    with patch.object(ag.settings, "ai_agent_timeout_sec", 0.05), patch("app.services.ai_rag_service.settings.openai_api_key", "k"), \
            patch("app.services.ai_agent.httpx.AsyncClient", return_value=_Slow()):
        with pytest.raises(AiUpstreamError, match="시간이 초과"):
            async for _ in ag.stream_agent_answer("q", [{"role": "user", "content": "q"}], toolbox(), []):
                pass


@pytest.mark.asyncio
async def test_search_without_hits_says_absent_not_sample():
    out = await toolbox().run("search_meeting", {"query": "블록체인"})
    assert out.startswith("'블록체인' 와(과) 일치하는 자막이 없습니다") and "[00:" not in out
