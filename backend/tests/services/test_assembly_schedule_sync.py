"""의사일정 수집 — 파싱과 갱신 규칙을 고정한다.

네트워크를 타지 않는다. `tests/fixtures/ggc_schedule_2026-09-01.html` 는 2026-08-31 에
의회 홈페이지에서 받은 **실제 응답**이다. 홈페이지 마크업이 바뀌면 이 테스트가 먼저 깨져야
운영에서 조용히 빈 일정이 되는 것을 막을 수 있다.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services.assembly_schedule_sync import (
    _upsert,
    agenda_hash,
    parse_day_html,
    parse_month_html,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ggc_schedule_2026-09-01.html"


@pytest.fixture(scope="module")
def html() -> str:
    return io.open(FIXTURE, encoding="utf-8").read()


# ── 일자 상세 ──────────────────────────────────────────────────────────────
def test_일자_표에서_본회의를_읽는다(html: str) -> None:
    rows = parse_day_html(html)
    assert len(rows) == 1
    row = rows[0]
    # <tr class="A011 table_tr"> 의 class 첫 토큰이 곧 위원회 코드다
    assert row["committee_code"] == "A011"
    assert row["committee_name"] == "본회의"
    assert row["start_time"] == "11:00"


def test_안건을_번호_떼고_목록으로_가른다(html: str) -> None:
    row = parse_day_html(html)[0]
    items = row["agenda_items"]
    assert len(items) == 5
    assert items[0] == "제393회 임시회 회기 결정"
    assert items[1] == "회의록 서명의원 선출"
    # '□ 본회의(11:00)' 은 안건이 아니라 칸의 머리글이라 빠져야 한다
    assert not any(x.startswith("□") for x in items)
    # 번호도 떨어져 있어야 한다
    assert not any(x.startswith("1.") for x in items)


def test_안건_문구에서_회기와_종류를_뽑는다(html: str) -> None:
    row = parse_day_html(html)[0]
    assert row["session_no"] == 393
    assert row["session_kind"] == "임시회"


def test_모르는_위원회_코드는_버린다() -> None:
    rows = parse_day_html(
        '<table><tbody><tr class="ZZ999 table_tr">'
        "<td>없는위원회</td><td>10:00</td><td>1. 안건</td></tr></tbody></table>"
    )
    assert rows == []


def test_안건_번호가_없으면_줄을_그대로_쓴다() -> None:
    rows = parse_day_html(
        '<table><tbody><tr class="A011 table_tr">'
        "<td>본회의</td><td>14:00</td>"
        "<td class='left'>□ 본회의(14:00)<br/>도정질문<br/>교육행정질문</td>"
        "</tr></tbody></table>"
    )
    assert rows[0]["agenda_items"] == ["도정질문", "교육행정질문"]


# ── 월 달력 ────────────────────────────────────────────────────────────────
def test_월_달력에서_회의_있는_날만_고른다(html: str) -> None:
    days = parse_month_html(html)
    # 9/1·2·3·18 에 본회의가 있다 (2026-08-31 실측)
    assert sorted(days.keys()) == [1, 2, 3, 18]
    assert days[1] == [("A011", "본회의")]


def test_휴회일은_회의로_세지_않는다(html: str) -> None:
    """9/4~9/17 은 휴회다. `<li class="day schdl">` 가 붙어 있어도 회의가 아니다.

    이것 때문에 달력 파싱을 `<li>` 클래스가 아니라 **위원회 링크** 기준으로 했다.
    """
    days = parse_month_html(html)
    for d in range(4, 18):
        assert d not in days, f"{d}일은 휴회인데 회의로 잡혔다"


def test_ALL_링크는_회의가_아니다() -> None:
    """fn_calList(N,'ALL') 은 그 날짜를 여는 링크일 뿐이다."""
    assert parse_month_html("<a href=\"javascript:fn_calList(7,'ALL')\">7</a>") == {}


# ── 갱신 규칙 (안건은 수시로 바뀐다) ─────────────────────────────────────────
class _FakeTable:
    def __init__(self, store: dict, name: str, log: list) -> None:
        self._s, self._n, self._log = store, name, log
        self._rows = list(store.get(name, []))
        self._payload: dict | None = None
        self._op: str | None = None
        self._target_id: str | None = None

    # 질의
    def select(self, *_a, **_k):
        return self

    def in_(self, _col, _vals):
        return self

    def gte(self, *_a):
        return self

    def lte(self, *_a):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a):
        return self

    def eq(self, col, val):
        if self._op in ("update", "delete") and col == "id":
            self._target_id = val
        return self

    def is_(self, *_a):
        return self

    # 변경
    def insert(self, payload):
        self._op, self._payload = "insert", payload
        return self

    def update(self, payload):
        self._op, self._payload = "update", payload
        return self

    def execute(self):
        if self._op == "insert":
            self._s.setdefault(self._n, []).append(dict(self._payload))
            self._log.append(("insert", self._payload))
        elif self._op == "update":
            for r in self._s.get(self._n, []):
                if r.get("id") == self._target_id:
                    r.update(self._payload)
            self._log.append(("update", self._target_id, self._payload))
        return type("R", (), {"data": self._rows, "count": len(self._rows)})()


class _FakeSupabase:
    def __init__(self, store: dict) -> None:
        self.store, self.log = store, []

    def table(self, name: str) -> _FakeTable:
        return _FakeTable(self.store, name, self.log)


def _row(agenda: list[str]) -> dict:
    r = {
        "schedule_date": "2026-09-01",
        "committee_code": "A011",
        "committee_name": "본회의",
        "start_time": "11:00",
        "session_no": 393,
        "session_order": 1,
        "session_kind": "임시회",
        "agenda_items": agenda,
    }
    r["agenda_hash"] = agenda_hash(r)
    return r


def test_새_일정은_추가된다() -> None:
    db = _FakeSupabase({"assembly_schedule": []})
    stat = _upsert(db, [_row(["안건 A"])], ["2026-09-01"])
    assert stat["added"] == 1 and stat["changed"] == 0


def test_내용이_같으면_확인시각만_갱신한다() -> None:
    """30분마다 도는 루프가 changed_at 을 매번 밀면 '언제 바뀌었나'를 알 수 없게 된다."""
    row = _row(["안건 A"])
    existing = {
        "id": "m1",
        "schedule_date": "2026-09-01",
        "committee_code": "A011",
        "agenda_hash": row["agenda_hash"],
        "is_cancelled": False,
    }
    db = _FakeSupabase({"assembly_schedule": [existing]})
    stat = _upsert(db, [row], ["2026-09-01"])
    assert stat["unchanged"] == 1
    op = [x for x in db.log if x[0] == "update"][0]
    assert set(op[2].keys()) == {"synced_at"}, "내용이 같은데 다른 칸까지 건드렸다"


def test_안건이_바뀌면_변경시각이_갱신된다() -> None:
    existing = {
        "id": "m1",
        "schedule_date": "2026-09-01",
        "committee_code": "A011",
        "agenda_hash": "옛날해시",
        "is_cancelled": False,
    }
    db = _FakeSupabase({"assembly_schedule": [existing]})
    stat = _upsert(db, [_row(["안건 A", "안건 B(추가됨)"])], ["2026-09-01"])
    assert stat["changed"] == 1
    payload = [x for x in db.log if x[0] == "update"][0][2]
    assert "changed_at" in payload
    assert payload["agenda_items"] == ["안건 A", "안건 B(추가됨)"]


def test_달력에서_사라지면_삭제하지_않고_취소로_표시한다() -> None:
    """사라졌다는 사실 자체가 정보다 — 회의 취소를 화면에서 보여줘야 한다."""
    existing = {
        "id": "m1",
        "schedule_date": "2026-09-01",
        "committee_code": "A011",
        "agenda_hash": "h",
        "is_cancelled": False,
    }
    db = _FakeSupabase({"assembly_schedule": [existing]})
    stat = _upsert(db, [], ["2026-09-01"])
    assert stat["cancelled"] == 1
    payload = [x for x in db.log if x[0] == "update"][0][2]
    assert payload["is_cancelled"] is True
    assert not any(x[0] == "delete" for x in db.log)


def test_해시는_안건_순서까지_구분한다() -> None:
    assert agenda_hash(_row(["A", "B"])) != agenda_hash(_row(["B", "A"]))
