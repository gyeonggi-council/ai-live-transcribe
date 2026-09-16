"""자막 조각 임베딩(services/subtitle_embeddings · embedding_pregen, 2026-09-15)."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services import embedding_pregen as ep
from app.services import subtitle_embeddings as se


def subs_fixture(n=60):
    labels = ["장한별 위원장", "이자형 위원", "진용국 사무처장"]
    return [{"id": f"r{i}", "start_time": i * 10.0, "end_time": i * 10.0 + 8, "speaker": labels[(i // 3) % 3],
             "text": f"발언{i:03d} " + "가" * 40, "kind": "ai"} for i in range(n)]


def test_chunks_cover_every_row_once_with_header_and_small_overlap():
    subs = subs_fixture()
    chunks = se.build_embedding_chunks(subs, None)
    assert len(chunks) >= 3 and [c["seq"] for c in chunks] == list(range(len(chunks)))
    for s in subs:
        tag = s["text"].split()[0]
        bodies = [c["content"].split("\n", 1)[1] for c in chunks]
        owners = [b for b in bodies if tag in "\n".join(l for l in b.splitlines() if not l.startswith("(앞) "))]
        assert len(owners) == 1, tag
    for c in chunks:
        head = c["content"].splitlines()[0]
        assert "~" in head and "발언:" in head
        overlap = [l for l in c["content"].splitlines() if l.startswith("(앞) ")]
        assert all(len(l) <= 205 for l in overlap) and len(c["content"]) <= 3000
    assert "이자형 위원: " in "\n".join(c["content"] for c in chunks)   # 같은 발언자 행을 한 줄로


def test_fingerprint_changes_with_text():
    subs = subs_fixture(5)
    fp = se.fingerprint(subs)
    subs[2] = {**subs[2], "text": "바뀐 발언"}
    assert se.fingerprint(subs) != fp and fp.startswith("ai:5:")


class FakeTable:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self.op, self.payload = db, name, [], "select", None

    def select(self, *_):
        return self

    def eq(self, k, v):
        self.filters.append(lambda r, k=k, v=v: r.get(k) == v)
        return self

    def gte(self, k, v):
        self.filters.append(lambda r, k=k, v=v: r.get(k) is not None and r.get(k) >= v)
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_):
        return self

    def upsert(self, rows, on_conflict=None):
        self.op, self.payload, self.keys = "upsert", rows if isinstance(rows, list) else [rows], on_conflict.split(",")
        return self

    def update(self, data):
        self.op, self.payload = "update", data
        return self

    def delete(self):
        self.op = "delete"
        return self

    def execute(self):
        rows = self.db.setdefault(self.name, [])
        match = [r for r in rows if all(f(r) for f in self.filters)]
        if self.op == "upsert":
            for new in self.payload:
                old = next((r for r in rows if all(r.get(k) == new.get(k) for k in self.keys)), None)
                (old.update(new) if old else rows.append(dict(new)))
            self.db.setdefault("_upserts", []).append((self.name, len(self.payload)))
        elif self.op == "update":
            for r in match:
                r.update(self.payload)
        elif self.op == "delete":
            self.db[self.name] = [r for r in rows if r not in match]
        return MagicMock(data=[dict(r) for r in match])


class FakeDB:
    def __init__(self):
        self.db = {}

    def table(self, name):
        return FakeTable(self.db, name)


def test_index_meeting_embeds_only_changed_chunks_and_skips_unchanged():
    db = FakeDB()
    subs = subs_fixture()
    calls = []

    def fake_embed(texts, **_):
        calls.append(len(texts))
        return [[0.1] * 4 for _ in texts]

    with patch("app.services.subtitle_fetch.fetch_all_subtitles", side_effect=lambda *_a, **_k: subs), \
            patch.object(se, "embed_texts", side_effect=fake_embed):
        first = se.index_meeting(db, "m1")
        n = first["chunks"]
        assert first["embedded"] == n and len(db.db["subtitle_chunks"]) == n
        assert se.index_meeting(db, "m1") == {"meeting_id": "m1", "skipped": "unchanged"}
        subs[0] = {**subs[0], "text": "첫 발언을 고쳤다"}
        third = se.index_meeting(db, "m1")
    assert calls[0] == n and third["embedded"] < n and third["embedded"] >= 1
    assert db.db["subtitle_chunk_state"][0]["chunk_count"] == n


NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
OLD = (NOW - timedelta(hours=3)).isoformat()


def _pregen_db(meetings, states, live=False):
    client = MagicMock()

    def table(name):
        q = MagicMock()
        for m in ("select", "eq", "in_", "order", "limit"):
            getattr(q, m).return_value = q
        if name == "meetings":
            q.execute.side_effect = lambda: MagicMock(data=[{"id": "L"}] if q.eq.call_args and q.eq.call_args.args == ("status", "live") and live
                                                      else ([] if q.eq.call_args and q.eq.call_args.args == ("status", "live") else meetings))
        else:
            q.execute.return_value = MagicMock(data=states)
        return q

    client.table.side_effect = table
    return client


def test_pregen_selects_missing_stale_and_live_kind_upgrades():
    meetings = [
        {"id": "new", "subtitle_stage": "ai", "updated_at": OLD},
        {"id": "fresh", "subtitle_stage": "ai", "updated_at": (NOW - timedelta(minutes=2)).isoformat()},
        {"id": "same", "subtitle_stage": "ai", "updated_at": OLD},
        {"id": "touched", "subtitle_stage": "ai", "updated_at": OLD},
        {"id": "upgrade", "subtitle_stage": "ai", "updated_at": OLD},
    ]
    later = (NOW - timedelta(hours=1)).isoformat()
    earlier = (NOW - timedelta(hours=5)).isoformat()
    states = [
        {"meeting_id": "same", "kind": "ai", "indexed_at": later, "model": ep.settings.rag_embedding_model},
        {"meeting_id": "touched", "kind": "ai", "indexed_at": earlier, "model": ep.settings.rag_embedding_model},
        {"meeting_id": "upgrade", "kind": "live", "indexed_at": later, "model": ep.settings.rag_embedding_model},
    ]
    got = [m["id"] for m in ep.select_targets(_pregen_db(meetings, states), now=NOW)]
    assert got == ["new", "touched", "upgrade"]


@pytest.mark.asyncio
async def test_pregen_skips_while_live():
    ep._ledger.update({"day": None, "done": set(), "failed": set()})
    with patch("app.services.subtitle_embeddings.index_meeting") as idx:
        result = await ep.run_once(_pregen_db([{"id": "a", "subtitle_stage": "ai", "updated_at": OLD}], [], live=True), now=NOW)
    assert result["skipped_live"] and not idx.called


def test_long_single_row_is_split_not_truncated():
    subs = [{"id": "x", "start_time": 0.0, "end_time": 60.0, "speaker": "이자형 위원", "text": "앞" * 4000 + "끝부분주제", "kind": "ai"}]
    chunks = se.build_embedding_chunks(subs, None)
    assert len(chunks) >= 2 and all(len(c["content"]) <= 3000 for c in chunks)
    assert any("끝부분주제" in c["content"] for c in chunks)
    assert [c["seq"] for c in chunks] == list(range(len(chunks)))


def test_fingerprint_includes_end_time_and_agendas():
    subs = subs_fixture(3)
    fp = se.fingerprint(subs, [{"order_num": 1, "title": "가"}])
    assert se.fingerprint([{**subs[0], "end_time": 99}, *subs[1:]], [{"order_num": 1, "title": "가"}]) != fp
    assert se.fingerprint(subs, [{"order_num": 1, "title": "나"}]) != fp


def test_pregen_rechecks_daily_and_unchanged_does_not_count():
    states = [{"meeting_id": "old", "kind": "ai", "indexed_at": (NOW - timedelta(hours=30)).isoformat(),
               "model": ep.settings.rag_embedding_model}]
    got = [m["id"] for m in ep.select_targets(_pregen_db([{"id": "old", "subtitle_stage": "ai", "updated_at": OLD}], states), now=NOW)]
    assert got == ["old"]


@pytest.mark.asyncio
async def test_unchanged_meetings_do_not_use_daily_limit():
    ep._ledger.update({"day": None, "done": set(), "failed": set()})
    db = _pregen_db([{"id": "a", "subtitle_stage": "ai", "updated_at": OLD}], [])
    with patch("app.services.subtitle_embeddings.index_meeting", return_value={"meeting_id": "a", "skipped": "unchanged"}):
        result = await ep.run_once(db, now=NOW)
    assert result["indexed"] == [] and ep.ledger_status(NOW)["remaining"] == ep.settings.embed_pregen_daily_limit
