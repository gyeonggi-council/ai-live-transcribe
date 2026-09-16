"""agenda_draft_service 유닛 테스트."""

import asyncio

from app.services import agenda_draft_service
from app.services.agenda_draft_service import _build_order_of_business, ensure_agendas


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeChain:
    """select/eq/order 체인 후 execute로 현재 store 스냅샷을 반환."""

    def __init__(self, store):
        self._store = store

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def execute(self):
        return _FakeResult(list(self._store))


class _FakeInsert:
    def __init__(self, store, row):
        self._store = store
        self._row = row

    def execute(self):
        self._store.append(self._row)
        return _FakeResult([self._row])


class _FakeTable:
    def __init__(self, store):
        self._store = store

    def select(self, *a, **k):
        return _FakeChain(self._store)

    def insert(self, row):
        return _FakeInsert(self._store, row)


class _FakeSupabase:
    def __init__(self, rows=None):
        self.store = list(rows or [])

    def table(self, _name):
        return _FakeTable(self.store)


def test_ensure_agendas_extracts_and_persists_when_empty(monkeypatch):
    """안건 미등록 회의: 자막 추출 결과를 meeting_agendas에 저장하고 목록을 반환(빈 제목 skip)."""
    async def fake_extract(_sb, _mid):
        return [
            {"order_num": 1, "title": "2025회계연도 결산 승인의 건"},
            {"order_num": 2, "title": "  "},  # 빈 제목은 저장 안 함
        ]

    monkeypatch.setattr(agenda_draft_service, "_extract_agendas", fake_extract)
    sb = _FakeSupabase()
    out = asyncio.run(ensure_agendas(sb, "mid-1"))
    assert len(out) == 1
    assert out[0]["title"] == "2025회계연도 결산 승인의 건"
    assert out[0]["meeting_id"] == "mid-1"


def test_ensure_agendas_preserves_existing(monkeypatch):
    """이미 등록된 안건이 있으면 추출하지 않고 그대로 반환(사람 입력 보존)."""
    def _boom(*_a, **_k):  # 호출되면 안 됨
        raise AssertionError("기존 안건이 있으면 _extract_agendas를 호출하면 안 된다")

    monkeypatch.setattr(agenda_draft_service, "_extract_agendas", _boom)
    sb = _FakeSupabase([{"order_num": 1, "title": "사람이 입력한 안건"}])
    out = asyncio.run(ensure_agendas(sb, "mid-2"))
    assert out == [{"order_num": 1, "title": "사람이 입력한 안건"}]


def test_build_order_of_business_orders_and_includes_summaries():
    items = [
        {"order_num": 2, "title": "추가경정예산안", "summary": "추경 심사 요약"},
        {"order_num": 1, "title": "개회", "summary": "성원 보고 및 개회"},
    ]
    md = _build_order_of_business(items)
    # 제목순(order_num) 정렬
    assert md.index("개회") < md.index("추가경정예산안")
    # 의사일정 항 표기 + 요약 포함
    assert "의사일정 제1항 개회" in md
    assert "의사일정 제2항 추가경정예산안" in md
    assert "추경 심사 요약" in md
    assert md.startswith("# 의사일정 (AI 초안)")


def test_build_order_of_business_handles_missing_summary():
    md = _build_order_of_business([{"order_num": 1, "title": "안건만", "summary": ""}])
    assert "의사일정 제1항 안건만" in md  # 요약 없어도 제목은 출력


def test_build_order_of_business_uses_description_fallback():
    # summary가 없고 description만 있으면 description 사용
    md = _build_order_of_business([{"order_num": 1, "title": "X", "description": "설명 내용"}])
    assert "설명 내용" in md
