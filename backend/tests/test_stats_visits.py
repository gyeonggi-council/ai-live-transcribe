"""접속자 수(site_visits) API 테스트.

- GET  /api/stats/visits  → 오늘/누적 접속자 수 조회 (증가 없음)
- POST /api/stats/visit   → 방문 1건 기록 후 갱신된 수 반환

프론트가 브라우저당 하루 1회만 POST 하므로, site_visits 1행 = 방문자 1명.
오늘 = visited_on이 오늘인 행 수, 누적 = 전체 행 수.
"""
import pytest
from fastapi.testclient import TestClient

from app.api.stats import seoul_today
from app.core.database import get_supabase
from app.main import app


class _Resp:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _Query:
    """site_visits 테이블에 대해 insert/select+count/eq 필터를 실제로 흉내내는 쿼리."""

    def __init__(self, store, table):
        self._store = store
        self._table = table
        self._count_mode = False
        self._eq = {}
        self._insert = None

    def select(self, *a, **k):
        self._count_mode = k.get("count") == "exact"
        return self

    def eq(self, col, val):
        self._eq[col] = val
        return self

    def insert(self, row):
        self._insert = row
        return self

    def execute(self):
        rows = self._store.setdefault(self._table, [])
        if self._insert is not None:
            new = dict(self._insert)
            rows.append(new)
            return _Resp([new], None)
        filtered = rows
        for c, v in self._eq.items():
            filtered = [r for r in filtered if r.get(c) == v]
        if self._count_mode:
            return _Resp(filtered, len(filtered))
        return _Resp(filtered, None)


class _Client:
    def __init__(self):
        self.store = {}

    def table(self, name):
        return _Query(self.store, name)


@pytest.fixture
def visits_client():
    c = _Client()
    app.dependency_overrides[get_supabase] = lambda: c
    yield TestClient(app), c
    app.dependency_overrides.clear()


def test_get_visits_empty_returns_zeros(visits_client):
    client, _ = visits_client
    r = client.get("/api/stats/visits")
    assert r.status_code == 200
    assert r.json() == {"today": 0, "total": 0}


def test_record_visit_increments_today_and_total(visits_client):
    client, _ = visits_client
    r1 = client.post("/api/stats/visit")
    assert r1.status_code == 200
    assert r1.json() == {"today": 1, "total": 1}

    r2 = client.post("/api/stats/visit")
    assert r2.json() == {"today": 2, "total": 2}


def test_total_counts_past_days_today_only_counts_today(visits_client):
    client, c = visits_client
    # 과거 다른 날짜 방문 2건 (오늘 아님)
    c.store["site_visits"] = [
        {"visited_on": "2020-01-01"},
        {"visited_on": "2020-01-02"},
    ]
    r = client.get("/api/stats/visits")
    body = r.json()
    assert body["total"] == 2
    assert body["today"] == 0

    # 오늘 방문 1건 추가 → today=1, total=3
    client.post("/api/stats/visit")
    body2 = client.get("/api/stats/visits").json()
    assert body2["total"] == 3
    assert body2["today"] == 1


def test_record_visit_stores_today_date(visits_client):
    client, c = visits_client
    client.post("/api/stats/visit")
    rows = c.store["site_visits"]
    assert len(rows) == 1
    assert rows[0]["visited_on"] == seoul_today()
