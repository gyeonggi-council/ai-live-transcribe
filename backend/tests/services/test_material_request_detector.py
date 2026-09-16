"""요구자료 감지 서비스 테스트.

프리필터 케이스는 기획재정위 391회 1차(2026-06-10) 실제 자막에서 추출 —
KMS 요구자료 목록(mntsId=15582)과 대응되는 실측 데이터다.
"""

import asyncio

import pytest

from app.services.material_request_detector import (
    LiveMaterialRequestDetector,
    build_llm_input,
    collect_candidates,
    dedupe_requests,
    parse_llm_response,
    prefilter_material_request,
)


class TestPrefilter:
    """1단계 정규식 프리필터 — 고재현율(진짜는 모두 통과) + 명백한 상용구 컷."""

    @pytest.mark.parametrize(
        "text",
        [
            # 실측 진짜 요구 발언 (521af6e1)
            "어 알겠습 그러면 그건 일단 자료로 제출해 주시고요.",
            "더 세어나가 국회 출장 결과 보고서 요것도 자료제출 해주셨으면 좋겠습니다.",
            "네. 거기 관련된 내용도 서류로 제출해 주세요.",
            "내용에 대한 보고서를 명확하게 정리해서 제출하시되 앞서 말씀드렸던",
            # 전형 패턴
            "관련 자료를 서면으로 제출해 주시기 바랍니다.",
            "미수납액 현황을 제출해 주십시오.",
            "그 목록 좀 보내주시고 자료 요청드립니다.",
            # 공무원 수락 응답 (직전 요구 확정 신호)
            "네, 알겠습니다. 저희가 자료 제출하도록 하겠습니다.",
        ],
    )
    def test_true_requests_pass(self, text):
        assert prefilter_material_request(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            # 실측 함정 (집행부 상용구/절차 안내)
            "사업별 결산 세부내역은 양해해 주신다면 보고자료로 대체하도록 하겠습니다.",
            "다음은 자료 요구 혹시 있으신 의원님 계신가요? 없으시죠?",
            "지리 답변에 앞서서 혹시 자료 요구하실 의원님 계신가요? 안 계시죠?",
            "네, 여기에서 지금 제가 자료 갖고 있거든요.",
            "그것은 제가 좀 준비가 안 돼 있습니다. 좀 자료를 쳐다봐야 될 것 같습니다.",
            "저희가 그 사업은 잠시 저기 자료를 좀 확인한 다음에 답변드리도록 하겠습니다.",
            "지금 정확히 수치가 안 나는데 거기 자료 있으시면 아마 그렇게 분류돼 있을 건데",
            "네, 효율적인 회의 진행을 위해서 제안 설명은 서면 자료로 대체하겠습니다.",
            # 일반 비요구
            "의석을 정돈해 주시기 바랍니다.",
            "기본적으로 보는 자료입니다.",
            "",
        ],
    )
    def test_non_requests_cut(self, text):
        assert prefilter_material_request(text) is False


class TestParseLlmResponse:
    def test_parses_plain_json_array(self):
        content = '[{"index":1,"is_request":true,"summary":"지방채 발행 검토 자료","confidence":"high"}]'
        out = parse_llm_response(content)
        assert len(out) == 1
        assert out[0]["summary"] == "지방채 발행 검토 자료"

    def test_parses_code_fenced_json(self):
        content = '분석 결과:\n```json\n[{"index":2,"is_request":true,"summary":"국회 출장 결과 보고서"}]\n```'
        assert parse_llm_response(content)[0]["summary"] == "국회 출장 결과 보고서"

    def test_filters_non_requests_and_empty_summary(self):
        content = (
            '[{"index":1,"is_request":false,"summary":"뭔가"},'
            '{"index":2,"is_request":true,"summary":"  "}]'
        )
        assert parse_llm_response(content) == []

    def test_garbage_returns_empty(self):
        assert parse_llm_response("응답 불가") == []


class TestDedupe:
    def test_merges_similar_nearby(self):
        items = [
            {"id": "a", "summary": "지방채 발행 검토 자료", "start_time": 1490.0, "confidence": "medium", "councilor_name": None},
            {"id": "b", "summary": "지방채 발행 검토 자료 목록", "start_time": 1500.0, "confidence": "high", "councilor_name": None},
        ]
        out = dedupe_requests(items)
        assert len(out) == 1
        assert out[0]["confidence"] == "high"

    def test_keeps_distinct_requests(self):
        items = [
            {"id": "a", "summary": "지방채 발행 검토 자료", "start_time": 1490.0, "confidence": "high", "councilor_name": "이혜원"},
            {"id": "b", "summary": "국회 출장 결과 보고서", "start_time": 8400.0, "confidence": "high", "councilor_name": "조성환"},
        ]
        assert len(dedupe_requests(items)) == 2


class TestCollectCandidates:
    def test_context_window(self):
        subs = [
            {"id": f"s{i}", "text": t, "speaker": None, "start_time": float(i)}
            for i, t in enumerate(
                [
                    "앞맥락1",
                    "앞맥락2",
                    "그건 일단 자료로 제출해 주시고요.",
                    "뒷맥락1",
                ]
            )
        ]
        cands = collect_candidates(subs, ctx=2)
        assert len(cands) == 1
        c = cands[0]
        assert c["subtitle_id"] == "s2"
        assert [b["text"] for b in c["context_before"]] == ["앞맥락1", "앞맥락2"]
        assert [a["text"] for a in c["context_after"]] == ["뒷맥락1"]

    def test_llm_input_contains_hint(self):
        block = build_llm_input(
            [{"index": 1, "text": "자료 제출해 주세요", "speaker": "화자 4", "start_time": 100.0,
              "context_before": [], "context_after": []}],
            questioner_hint="이혜원",
        )
        assert "이혜원" in block
        assert "후보 1" in block


class TestLiveDetector:
    def test_non_candidate_does_not_schedule(self):
        det = LiveMaterialRequestDetector()
        det.start_channel("ch1", "m1")

        async def run():
            return det.observe("ch1", "m1", {"id": "s1", "text": "의석을 정돈해 주시기 바랍니다.", "start_time": 1.0})

        assert asyncio.run(run()) is False
        assert det._pending["ch1"] == []

    def test_candidate_buffers_and_processes(self, monkeypatch):
        det = LiveMaterialRequestDetector()
        det.DEBOUNCE_SECONDS = 0.01
        det.start_channel("ch1", "meeting-1")

        captured: dict = {}

        async def fake_llm(block):
            captured["block"] = block
            return [{"index": 1, "is_request": True, "summary": "국회 출장 결과 보고서",
                     "confidence": "high", "request_text": "자료제출 해주셨으면 좋겠습니다"}]

        async def fake_persist(channel_id, meeting_id, rows):
            captured["rows"] = rows

        monkeypatch.setattr(
            "app.services.material_request_detector._call_llm", fake_llm
        )
        monkeypatch.setattr(det, "_persist_and_broadcast", fake_persist)

        async def run():
            det.observe("ch1", "meeting-1", {"id": "s0", "text": "앞선 발언입니다.", "start_time": 1.0})
            hit = det.observe(
                "ch1", "meeting-1",
                {"id": "s1", "text": "국회 출장 결과 보고서 요것도 자료제출 해주셨으면 좋겠습니다.", "start_time": 8400.0},
            )
            assert hit is True
            await asyncio.sleep(0.2)  # 디바운스 + 처리 대기

        asyncio.run(run())
        assert "rows" in captured, "LLM 확정 후 persist가 호출되어야 함"
        row = captured["rows"][0]
        assert row["summary"] == "국회 출장 결과 보고서"
        assert row["meeting_id"] == "meeting-1"
        assert row["subtitle_id"] == "s1"
        assert row["source"] == "live"
        assert "앞선 발언" in captured["block"], "앞 맥락이 LLM 입력에 포함되어야 함"

    def test_duplicate_suppressed_within_session(self, monkeypatch):
        det = LiveMaterialRequestDetector()
        det.DEBOUNCE_SECONDS = 0.01
        det.start_channel("ch1", "meeting-1")

        calls: list = []

        async def fake_llm(block):
            return [{"index": 1, "is_request": True, "summary": "지방채 발행 검토 자료",
                     "confidence": "high"}]

        async def fake_persist(channel_id, meeting_id, rows):
            calls.append(rows)

        monkeypatch.setattr("app.services.material_request_detector._call_llm", fake_llm)
        monkeypatch.setattr(det, "_persist_and_broadcast", fake_persist)

        async def run():
            det.observe("ch1", "meeting-1", {"id": "s1", "text": "그 자료를 제출해 주시기 바랍니다.", "start_time": 100.0})
            await asyncio.sleep(0.15)
            det.observe("ch1", "meeting-1", {"id": "s2", "text": "그 자료를 꼭 제출해 주시기 바랍니다.", "start_time": 120.0})
            await asyncio.sleep(0.15)

        asyncio.run(run())
        total = sum(len(r) for r in calls)
        assert total == 1, f"동일 요구 반복 감지는 1건으로 병합되어야 함 (got {total})"
