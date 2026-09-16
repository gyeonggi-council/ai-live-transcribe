# -*- coding: utf-8 -*-
"""회의 시각 기준점 — 자막 시계 ↔ 실제 시각.

핵심은 **정회**다. 자막 시계는 수신된 오디오만 세므로 정회 1시간은 시계에 없지만
실제 시각으로는 1시간이 흘렀다. 기준점 없이 "시작 시각 + 경과 초"로 계산하면
정회 뒤 장면의 시각이 통째로 어긋난다 — 그 어긋남을 여기서 잡는다.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services import meeting_clock


# ─── 테스트용 Supabase 스텁 ────────────────────────────────────────────────
class _Query:
    def __init__(self, rows, recorder=None, fail=False):
        self._rows = rows
        self._recorder = recorder
        self._fail = fail
        self.filters: dict = {}

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def insert(self, payload):
        if self._recorder is not None:
            self._recorder.append(payload)
        return self

    def execute(self):
        if self._fail:
            raise RuntimeError("PostgREST 42P01: relation does not exist")
        return type("Res", (), {"data": list(self._rows)})()


class FakeSupabase:
    def __init__(self, tables: dict, inserts=None, fail_tables=()):
        self._tables = tables
        self.inserts = inserts if inserts is not None else []
        self._fail = set(fail_tables)

    def table(self, name):
        return _Query(
            self._tables.get(name, []),
            recorder=self.inserts,
            fail=name in self._fail,
        )


KST = timezone(timedelta(hours=9))


def _iso(h, m, s=0):
    return datetime(2026, 9, 16, h, m, s, tzinfo=KST).isoformat()


class TestWallAtClock:
    def test_maps_within_one_session(self):
        anchors = [{"clock": 0.0, "wall": _iso(10, 0, 0)}]
        got = meeting_clock.wall_at_clock(anchors, 125.0)
        assert got == datetime(2026, 9, 16, 10, 2, 5, tzinfo=KST)

    def test_recess_does_not_shift_later_scenes(self):
        """정회 1시간 — 자막 시계는 1800초에서 멈췄다가 이어지지만 실제 시각은 1시간 흘렀다."""
        anchors = [
            {"clock": 0.0, "wall": _iso(10, 0, 0)},
            {"clock": 1800.0, "wall": _iso(11, 30, 0)},  # 30분 방송 + 1시간 정회 뒤 재개
        ]
        # 정회 전 장면
        assert meeting_clock.wall_at_clock(anchors, 600.0) == datetime(
            2026, 9, 16, 10, 10, 0, tzinfo=KST
        )
        # 정회 후 장면 — 기준점이 없으면 10:40 으로 1시간 틀렸을 지점
        assert meeting_clock.wall_at_clock(anchors, 2400.0) == datetime(
            2026, 9, 16, 11, 40, 0, tzinfo=KST
        )

    def test_before_first_anchor_extrapolates_backwards(self):
        anchors = [{"clock": 100.0, "wall": _iso(10, 1, 40)}]
        assert meeting_clock.wall_at_clock(anchors, 40.0) == datetime(
            2026, 9, 16, 10, 0, 40, tzinfo=KST
        )

    def test_no_anchor_means_no_answer(self):
        assert meeting_clock.wall_at_clock([], 10.0) is None


class TestRecordAnchor:
    def test_inserts_one_row(self):
        fake = FakeSupabase({})
        wall = datetime(2026, 9, 16, 10, 0, 0, tzinfo=KST)
        assert meeting_clock.record_anchor(fake, "m1", 12.345, wall) is True
        assert len(fake.inserts) == 1
        row = fake.inserts[0]
        assert row["meeting_id"] == "m1"
        assert row["clock_sec"] == pytest.approx(12.35)
        assert row["source"] == "live"
        assert datetime.fromisoformat(row["wall_at"]) == wall

    def test_failure_is_swallowed(self):
        """표가 아직 없어도(마이그레이션 전) STT 는 계속돼야 한다."""
        fake = FakeSupabase({}, fail_tables=("meeting_clock_anchors",))
        assert meeting_clock.record_anchor(fake, "m1", 1.0, datetime.now(timezone.utc)) is False


class TestEstimateAnchors:
    def _subs(self, pairs):
        """(자막 시계, 실제 발언 시각) → DB 행. created_at 은 실제보다 LAG 만큼 늦다."""
        lag = meeting_clock.ESTIMATED_EMIT_LAG_SEC
        return [
            {"start_time": clock, "created_at": (spoken + timedelta(seconds=lag)).isoformat()}
            for clock, spoken in pairs
        ]

    def test_recovers_wall_clock_within_a_second(self):
        base = datetime(2026, 9, 16, 10, 0, 0, tzinfo=KST)
        rows = self._subs([(t, base + timedelta(seconds=t)) for t in range(0, 600, 10)])
        fake = FakeSupabase({"subtitles": rows})

        anchors = meeting_clock.estimate_anchors(fake, "m1")
        assert anchors
        got = meeting_clock.wall_at_clock(anchors, 300.0)
        assert abs((got - (base + timedelta(seconds=300))).total_seconds()) < 1.0

    def test_recess_jump_creates_a_new_anchor(self):
        base = datetime(2026, 9, 16, 10, 0, 0, tzinfo=KST)
        before = [(t, base + timedelta(seconds=t)) for t in range(0, 600, 10)]
        # 시계 600초에서 정회 1시간 → 재개 후에도 시계는 600초부터 이어진다
        after = [
            (600.0 + t, base + timedelta(seconds=600 + 3600 + t)) for t in range(0, 600, 10)
        ]
        fake = FakeSupabase({"subtitles": self._subs(before + after)})

        anchors = meeting_clock.estimate_anchors(fake, "m1")
        got = meeting_clock.wall_at_clock(anchors, 900.0)
        expected = base + timedelta(seconds=600 + 3600 + 300)
        assert abs((got - expected).total_seconds()) < 2.0

    def test_only_live_subtitles_are_used(self):
        """VOD AI 자막의 created_at 은 일괄 생성 시각이라 기준점이 될 수 없다."""
        fake = FakeSupabase({"subtitles": []})
        q = fake.table("subtitles").select("start_time, created_at")
        q = q.eq("meeting_id", "m1").eq("kind", "live")
        assert q.filters["kind"] == "live"
        assert meeting_clock.estimate_anchors(fake, "m1") == []


class TestAnchorsForMeeting:
    def test_recorded_wins_over_estimate(self):
        fake = FakeSupabase(
            {
                "meeting_clock_anchors": [{"clock_sec": 0.0, "wall_at": _iso(10, 0, 0)}],
                "subtitles": [{"start_time": 0.0, "created_at": _iso(11, 0, 0)}],
            }
        )
        anchors, source = meeting_clock.anchors_for_meeting(fake, "m1")
        assert source == "recorded"
        assert anchors == [{"clock": 0.0, "wall": _iso(10, 0, 0)}]

    def test_falls_back_to_estimate(self):
        fake = FakeSupabase(
            {
                "meeting_clock_anchors": [],
                "subtitles": [{"start_time": 0.0, "created_at": _iso(10, 0, 11)}],
            }
        )
        anchors, source = meeting_clock.anchors_for_meeting(fake, "m1")
        assert source == "estimated"
        assert len(anchors) == 1

    def test_none_when_nothing_to_go_on(self):
        fake = FakeSupabase({"meeting_clock_anchors": [], "subtitles": []})
        assert meeting_clock.anchors_for_meeting(fake, "m1") == ([], "none")
