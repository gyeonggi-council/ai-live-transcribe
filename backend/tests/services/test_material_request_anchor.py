"""요구자료 재앵커(plan_reanchor / reanchor_live_requests) 테스트.

픽스처 수치는 기획재정위 실측(라이브 2878.58s 발언 = AI 자막 1494.96s,
정회 편집으로 Δ가 1383.6s→1864.3s로 점프)을 그대로 사용한다.
"""

import asyncio

import pytest

from app.services.material_request_anchor import plan_reanchor, reanchor_live_requests


def _sub(i: str, text: str, start: float, end: float | None = None) -> dict:
    return {"id": i, "text": text, "start_time": start, "end_time": end or start + 8.0}


def _req(i: str, start: float | None, quote: str, subtitle_id: str | None = None) -> dict:
    return {"id": i, "start_time": start, "subtitle_id": subtitle_id,
            "request_text": quote, "summary": quote[:20]}


AI_SUBS = [
    _sub("a1", "먼저 훌륭하신 여러 동료 위원님들 계신데도 감사의 말씀을 드립니다", 33.0),
    _sub("a2", "경영평가 관련해서 평가 지표에 대한 세부 지침 내용의 자료 요구를 드리겠습니다", 1494.96),
    _sub("a3", "그러면 아까 자료 요청드렸던 것처럼 평가 지표 세부 지침 내용하고", 1572.96),
    _sub("a4", "균형발전과 사회적 포용성 강화 30개 과제 진행 자료 현황 자료 부탁드립니다", 4402.84),
    _sub("a5", "마지막으로 위원회 운영에 협조해 주셔서 감사합니다", 9000.0),
]


class TestPlanReanchor:
    def test_text_match_adopts_ai_start(self):
        # 라이브 2878.58s에 감지된 인용문 → AI 자막 1494.96s로 재앵커 (실측 ground truth)
        reqs = [_req("r1", 2878.58, "경영평가 관련해서 평가 지표에 대한 세부 지침 내용의 자료 요구를 드리겠습니다.")]
        plans = plan_reanchor(reqs, AI_SUBS)
        assert plans[0]["method"] == "text"
        assert plans[0]["new_start"] == pytest.approx(1494.96)
        assert plans[0]["subtitle_id"] == "a2"
        assert plans[0]["match_size"] >= 12

    def test_unmatched_uses_nearest_pair_delta(self):
        # 매칭 쌍 2개: Δ1383.62(중반), Δ1864.65(후반 — 정회 편집 이후).
        # 후반의 미매칭 항목은 전역 중앙값이 아니라 '가까운 쌍'의 Δ1864.65를 받아야 한다.
        reqs = [
            _req("r1", 2878.58, "경영평가 관련해서 평가 지표에 대한 세부 지침 내용의 자료 요구를 드리겠습니다."),
            _req("r2", 6267.49, "균형발전과 사회적 포용성 강화 30개 과제 진행 자료 현황 자료 부탁드립니다."),
            _req("r3", 6300.00, "완전히 다른 내용이라 자막 어디에도 없는 인용문입니다 전혀 다른 발언"),
        ]
        plans = {p["request_id"]: p for p in plan_reanchor(reqs, AI_SUBS)}
        assert plans["r2"]["method"] == "text"
        delta_late = 6267.49 - 4402.84  # 1864.65
        assert plans["r3"]["method"] == "offset"
        assert plans["r3"]["new_start"] == pytest.approx(6300.00 - delta_late, abs=0.01)
        assert plans["r3"]["subtitle_id"] is not None

    def test_no_matches_leaves_all_untouched(self):
        reqs = [
            _req("r1", 100.0, "자막 어디에도 등장하지 않는 완전히 새로운 문장 하나"),
            _req("r2", 200.0, "이것도 자막과 전혀 무관한 별개의 다른 인용문 텍스트"),
        ]
        plans = plan_reanchor(reqs, AI_SUBS)
        assert all(p["method"] == "unmatched" for p in plans)
        assert all(p["new_start"] is None for p in plans)

    def test_idempotent_second_run_skips(self):
        # 1회차 결과(subtitle_id=AI id, start_time=AI 시각)를 다시 넣으면 전원 skip
        reqs = [
            _req("r1", 1494.96, "경영평가 관련해서 평가 지표에 대한 세부 지침 내용의 자료 요구를 드리겠습니다.", "a2"),
            _req("r2", 4402.84, "균형발전과 사회적 포용성 강화 30개 과제 진행 자료 현황 자료 부탁드립니다.", "a4"),
        ]
        plans = plan_reanchor(reqs, AI_SUBS, anchored_ids={s["id"] for s in AI_SUBS})
        assert all(p["method"] == "skip_anchored" for p in plans)
        assert all(p["new_start"] == p["old_start"] for p in plans)

    def test_duplicate_phrase_monotonic_order(self):
        # 같은 문구가 두 시점에 반복 — 시간순 요구자료 2건이 순서대로 각 시점에 매칭
        subs = [
            _sub("d1", "결산 자료 세부 내역을 제출해 주시기 바랍니다 이상입니다", 100.0),
            _sub("d2", "중간에 다른 발언이 하나 들어가 있습니다", 200.0),
            _sub("d3", "결산 자료 세부 내역을 제출해 주시기 바랍니다 이상입니다", 300.0),
        ]
        reqs = [
            _req("r1", 1100.0, "결산 자료 세부 내역을 제출해 주시기 바랍니다"),
            _req("r2", 1300.0, "결산 자료 세부 내역을 제출해 주시기 바랍니다"),
        ]
        plans = {p["request_id"]: p for p in plan_reanchor(reqs, subs)}
        assert plans["r1"]["subtitle_id"] == "d1"
        # 단조 제약: 두 번째 요구는 첫 매칭 이전(d1)으로 돌아가지 않는다
        assert plans["r2"]["subtitle_id"] in ("d1", "d3")
        assert plans["r2"]["new_start"] >= plans["r1"]["new_start"]

    def test_window_bridges_sentence_split(self):
        # 인용문이 AI 자막 2개에 걸쳐 나뉜 경우 — 연결 창으로 매칭, 앞 자막에 앵커
        subs = [
            _sub("w1", "경기도 주식회사 경영평가와 관련한", 500.0),
            _sub("w2", "세부 평가 방법 자료를 요청드립니다", 508.0),
        ]
        reqs = [_req("r1", 2000.0, "경기도 주식회사 경영평가와 관련한 세부 평가 방법 자료를 요청드립니다")]
        plans = plan_reanchor(reqs, subs)
        assert plans[0]["method"] == "text"
        assert plans[0]["subtitle_id"] == "w1"

    def test_empty_ai_subs_all_unmatched(self):
        plans = plan_reanchor([_req("r1", 10.0, "아무 인용문")], [])
        assert plans[0]["method"] == "unmatched"


# ─── reanchor_live_requests (I/O 래퍼) — mock supabase ──────────────────────


class _MockResponse:
    def __init__(self, data):
        self.data = data


class _MockQuery:
    def __init__(self, table: str, store: dict, log: list):
        self._table = table
        self._store = store
        self._log = log
        self._filters: dict = {}
        self._update_payload = None

    def select(self, *a, **kw):
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def order(self, *a, **kw):
        return self

    def range(self, *a, **kw):
        return self

    def update(self, payload):
        self._update_payload = payload
        return self

    def execute(self):
        if self._update_payload is not None:
            self._log.append(
                {"table": self._table, "op": "update",
                 "payload": self._update_payload, "filters": dict(self._filters)}
            )
            return _MockResponse([])
        rows = self._store.get(self._table, [])
        for col, val in self._filters.items():
            rows = [r for r in rows if r.get(col) == val]
        return _MockResponse(rows)


class _MockClient:
    def __init__(self, store: dict):
        self._store = store
        self.log: list = []

    def table(self, name: str):
        return _MockQuery(name, self._store, self.log)


class TestReanchorLiveRequests:
    def test_only_live_rows_updated(self):
        mid = "m1"
        store = {
            "material_requests": [
                {**_req("r1", 2878.58,
                        "경영평가 관련해서 평가 지표에 대한 세부 지침 내용의 자료 요구를 드리겠습니다."),
                 "meeting_id": mid, "source": "live"},
                {**_req("r2", 1572.96, "그러면 아까 자료 요청드렸던 것처럼 평가 지표 세부 지침 내용하고"),
                 "meeting_id": mid, "source": "vod_scan"},
                {**_req("r3", 50.0, "수동으로 넣은 항목"), "meeting_id": mid, "source": "manual"},
            ],
            "subtitles": [{**s, "meeting_id": mid, "kind": "ai"} for s in AI_SUBS],
        }
        mock = _MockClient(store)
        stats = asyncio.run(reanchor_live_requests(mock, mid))

        assert stats["total"] == 1  # live 행만 대상
        assert stats["text_matched"] == 1
        updates = [e for e in mock.log if e["op"] == "update"]
        assert len(updates) == 1
        assert updates[0]["filters"].get("id") == "r1"
        assert updates[0]["payload"]["start_time"] == pytest.approx(1494.96)
        assert updates[0]["payload"]["subtitle_id"] == "a2"

    def test_dry_run_no_updates(self):
        mid = "m1"
        store = {
            "material_requests": [
                {**_req("r1", 2878.58,
                        "경영평가 관련해서 평가 지표에 대한 세부 지침 내용의 자료 요구를 드리겠습니다."),
                 "meeting_id": mid, "source": "live"},
            ],
            "subtitles": [{**s, "meeting_id": mid, "kind": "ai"} for s in AI_SUBS],
        }
        mock = _MockClient(store)
        stats = asyncio.run(reanchor_live_requests(mock, mid, apply=False))
        assert stats["text_matched"] == 1
        assert not [e for e in mock.log if e["op"] == "update"]

    def test_no_ai_subs_noop(self):
        mid = "m1"
        store = {
            "material_requests": [
                {**_req("r1", 10.0, "인용문"), "meeting_id": mid, "source": "live"},
            ],
            "subtitles": [],
        }
        mock = _MockClient(store)
        stats = asyncio.run(reanchor_live_requests(mock, mid))
        assert stats["unmatched"] == 1
        assert not [e for e in mock.log if e["op"] == "update"]
