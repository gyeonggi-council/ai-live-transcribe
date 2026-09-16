# -*- coding: utf-8 -*-
"""접속 통계 API (2026-09-16 담당자 요청).

- POST /api/stats/access  → 접속·시청 신호 1건 기록
- GET  /api/stats/access  → 접속처·시간대·회의·기능 집계 (site= 로 드릴다운)

**이 테스트의 핵심은 "IP 가 저장되지 않는다"** 이다. 접속처 이름만 남는다.
대역 숫자는 저장소에 두지 않는 원칙대로 문서용 예시 대역(TEST-NET, RFC 5737)을 쓴다.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import get_supabase
from app.main import app
from app.services import access_stats_service as access_stats

# "이름=대역" 표기 — 운영에서는 ConfigMap COUNCIL_SITE_LABELS 가 같은 모양의 실제 값을 준다
SPEC = "무선인터넷=192.0.2.146-158; 의회사무처(직원)=198.51.100.102,198.51.100.162"


class _Resp:
    def __init__(self, data=None, count=None):
        self.data = data or []
        self.count = count


class _Query:
    """insert 를 받아 적고, select 는 준비된 행을 돌려주는 최소 쿼리."""

    def __init__(self, store, table):
        self._store = store
        self._table = table
        self._insert = None

    def select(self, *a, **k):
        return self

    def insert(self, row):
        self._insert = row
        return self

    def delete(self):
        return self

    # 필터·정렬은 이 테스트에서 걸러낼 것이 없다 — 체인만 이어 준다
    def eq(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def lt(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self._insert is not None:
            if self._store.insert_fails:
                raise RuntimeError("relation \"access_events\" does not exist")
            self._store.inserted.append((self._table, self._insert))
            return _Resp([self._insert])
        return _Resp(self._store.rows.get(self._table, []))


class _Supabase:
    def __init__(self, rows=None, insert_fails=False):
        self.rows = rows or {}
        self.inserted: list[tuple[str, dict]] = []
        self.insert_fails = insert_fails

    def table(self, name):
        return _Query(self, name)


@pytest.fixture(autouse=True)
def _labels_and_clean_state(monkeypatch):
    monkeypatch.setattr(settings, "council_site_labels", SPEC)
    access_stats._seen.clear()
    access_stats._hourly.clear()
    yield
    access_stats._seen.clear()
    access_stats._hourly.clear()
    app.dependency_overrides.pop(get_supabase, None)


def _client(fake):
    app.dependency_overrides[get_supabase] = lambda: fake
    return TestClient(app)


def _post(client, ip, **payload):
    body = {"kind": "page", "visitor_key": "vk-1", **payload}
    return client.post("/api/stats/access", json=body, headers={"X-Real-IP": ip})


class TestRecord:
    def test_ip_becomes_a_name_and_is_never_stored(self):
        """저장된 행 어디에도 IP 문자열이 없어야 한다 — 담당자 결정(2026-09-16)."""
        fake = _Supabase()
        res = _post(_client(fake), "198.51.100.102")
        assert res.status_code == 200 and res.json() == {"recorded": True}

        table, row = fake.inserted[0]
        assert table == "access_events"
        assert row["site_label"] == "의회사무처(직원)"
        assert "198.51.100.102" not in str(row)
        assert not {"ip", "client_ip", "user_agent"} & set(row)

    def test_unknown_ip_is_outside(self):
        fake = _Supabase()
        _post(_client(fake), "8.8.8.8")
        assert fake.inserted[0][1]["site_label"] == "외부"

    def test_last_octet_range(self):
        fake = _Supabase()
        _post(_client(fake), "192.0.2.150")
        assert fake.inserted[0][1]["site_label"] == "무선인터넷"

    def test_no_labels_configured_means_everyone_is_outside(self, monkeypatch):
        monkeypatch.setattr(settings, "council_site_labels", "")
        fake = _Supabase()
        _post(_client(fake), "198.51.100.102")
        assert fake.inserted[0][1]["site_label"] == "외부"

    def test_repeat_within_window_is_dropped(self):
        fake = _Supabase()
        client = _client(fake)
        assert _post(client, "8.8.8.8").json() == {"recorded": True}
        assert _post(client, "8.8.8.8").json() == {"recorded": False}
        assert len(fake.inserted) == 1

    def test_watch_counts_five_minutes(self):
        fake = _Supabase()
        _post(_client(fake), "8.8.8.8", kind="watch_live", meeting_id="ch60")
        row = fake.inserted[0][1]
        assert row["seconds"] == access_stats.WATCH_TICK_SECONDS
        # 채널 ID 는 UUID 가 아니므로 meeting_id 로 넣지 않는다(insert 가 깨진다)
        assert "meeting_id" not in row
        assert row["detail"]["channel"] == "ch60"

    def test_uuid_meeting_is_kept(self):
        fake = _Supabase()
        mid = "70ebdfbb-b7eb-48a0-82c5-6c9993d68c5e"
        _post(_client(fake), "8.8.8.8", kind="watch_vod", meeting_id=mid)
        assert fake.inserted[0][1]["meeting_id"] == mid

    def test_unknown_kind_is_ignored(self):
        fake = _Supabase()
        res = _post(_client(fake), "8.8.8.8", kind="해킹시도")
        assert res.json() == {"recorded": False} and fake.inserted == []

    def test_missing_table_does_not_break_the_page(self):
        """마이그레이션 033 전에도 화면이 죽지 않는다(021 과 같은 원칙)."""
        fake = _Supabase(insert_fails=True)
        res = _post(_client(fake), "8.8.8.8")
        assert res.status_code == 200 and res.json() == {"recorded": False}


class TestAggregate:
    ROWS = {
        "v_access_daily": [
            {"visit_date": "2026-09-16", "site_label": "무선인터넷", "visitors": 3,
             "page_views": 9, "login_prompts": 0, "watch_seconds": 1800},
            {"visit_date": "2026-09-16", "site_label": "외부", "visitors": 7,
             "page_views": 20, "login_prompts": 0, "watch_seconds": 3600},
            {"visit_date": "2026-09-16", "site_label": "의회사무처(직원)", "visitors": 0,
             "page_views": 0, "login_prompts": 4, "watch_seconds": 0},
        ],
        "v_access_hourly": [
            {"visit_date": "2026-09-16", "weekday_kst": 2, "hour_kst": 10, "visitors": 8, "watch_seconds": 3600},
            {"visit_date": "2026-09-16", "weekday_kst": 2, "hour_kst": 14, "visitors": 2, "watch_seconds": 1800},
        ],
        "v_access_meeting": [
            {"visit_date": "2026-09-16", "meeting_id": "70ebdfbb-b7eb-48a0-82c5-6c9993d68c5e",
             "site_label": "외부", "viewers": 5, "watch_seconds": 3000},
        ],
        "v_access_feature": [
            {"visit_date": "2026-09-16", "site_label": "외부", "kind": "page", "device": "mobile",
             "events": 20, "visitors": 7},
            {"visit_date": "2026-09-16", "site_label": "외부", "kind": "search", "device": "mobile",
             "events": 4, "visitors": 2},
        ],
        "meetings": [
            {"id": "70ebdfbb-b7eb-48a0-82c5-6c9993d68c5e", "title": "제393회 제4차 예산결산특별위원회",
             "meeting_date": "2026-09-16", "status": "ended"},
        ],
        "access_events": [],
    }

    def test_shape(self):
        client = _client(_Supabase(rows=self.ROWS))
        body = client.get("/api/stats/access?days=7").json()

        assert body["days"] == 7 and len(body["daily"]) == 7
        assert {s["label"] for s in body["sites"]} == {"무선인터넷", "외부", "의회사무처(직원)"}
        assert body["totals"]["visitors"] == 10
        assert body["totals"]["login_prompts"] == 4          # 앱 로그인 안내를 본 횟수
        assert body["hourly"][10]["visitors"] == 8
        assert body["weekday_hour"][2][14] == 2
        assert body["meetings"][0]["title"].endswith("예산결산특별위원회")
        assert any(f["kind"] == "search" for f in body["features"])
        assert body["insights"]                              # 운영 판단 문장

    def test_share_adds_up(self):
        client = _client(_Supabase(rows=self.ROWS))
        sites = client.get("/api/stats/access?days=7").json()["sites"]
        assert round(sum(s["share"] for s in sites)) == 100

    def test_empty_when_nothing_collected(self):
        client = _client(_Supabase(rows={}))
        body = client.get("/api/stats/access").json()
        assert body["totals"]["visitors"] == 0 and body["sites"] == []
        assert body["detail_since"] is None
