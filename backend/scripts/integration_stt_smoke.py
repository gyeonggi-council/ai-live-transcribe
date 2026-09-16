"""실서비스 통합 스모크 — OpenAiRealtimeSttService + DiarizeService를 실제 영상으로 end-to-end 구동.

manager(WebSocket broadcast)와 Supabase를 인메모리로 가로채, 실제 ffmpeg + OpenAI Realtime/diarize
파이프라인을 그대로 돌린다. verify_openai_stt.py가 API 계약만 보는 것과 달리, 리팩터된 서비스 코드
(commit 윈도우 타임스탬프 앵커링, 태스크 회수, diarize 시간 매칭, speaker 부여)를 통째로 검증한다.

사용 (backend 디렉터리): python scripts/integration_stt_smoke.py [url] [--seconds 25]
필요: ffmpeg, OPENAI_API_KEY(.env). 네트워크/요금 발생.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

DEFAULT_URL = (
    "https://m.webcast.go.kr/vod/_definst_/FULL/2024/bokji/"
    "DKP332241704_01_202408280920.mp4/playlist.m3u8"
)


# ─── 인메모리 가짜 Supabase (필요한 체이닝만 지원) ────────────────────────
class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, store, table):
        self.store = store
        self.table = table
        self._filters = []  # (op, col, val)
        self._payload = None
        self._op = "select"
        self._order = None
        self._desc = False
        self._limit = None

    def select(self, *a, **k):
        self._op = "select"
        return self

    def insert(self, row):
        self._op = "insert"
        self._payload = row
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def lte(self, col, val):
        self._filters.append(("lte", col, val))
        return self

    def gte(self, col, val):
        self._filters.append(("gte", col, val))
        return self

    def order(self, col, desc=False):
        self._order = col
        self._desc = desc
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        rows = self.store.setdefault(self.table, [])
        if self._op == "insert":
            rows.append(dict(self._payload))
            return _Resp([self._payload])
        if self._op == "update":
            updated = []
            for r in rows:
                if all(r.get(c) == v for (op, c, v) in self._filters if op == "eq"):
                    r.update(self._payload)
                    updated.append(r)
            return _Resp(updated)
        # select
        res = []
        for r in rows:
            ok = True
            for (op, c, v) in self._filters:
                rv = r.get(c)
                if op == "eq" and rv != v:
                    ok = False
                elif op == "lte" and not (rv is not None and rv <= v):
                    ok = False
                elif op == "gte" and not (rv is not None and rv >= v):
                    ok = False
            if ok:
                res.append(r)
        if self._order:
            res = sorted(res, key=lambda x: x.get(self._order) or 0, reverse=self._desc)
        if self._limit:
            res = res[: self._limit]
        return _Resp(res)


class _FakeSupabase:
    def __init__(self):
        self.store = {}

    def table(self, name):
        return _Query(self.store, name)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?", default=DEFAULT_URL)
    ap.add_argument("--seconds", type=int, default=25)
    args = ap.parse_args()

    import app.services.openai_realtime_stt as rt
    import app.services.diarize_service as ds
    from app.core.config import settings

    if not settings.openai_api_key:
        print("OPENAI_API_KEY 미설정")
        return 1

    fake = _FakeSupabase()
    rt.get_supabase_client = lambda: fake
    ds.get_supabase_client = lambda: fake

    created, interims, corrected = [], [], []

    async def cap_created(room, data):
        created.append(data["subtitle"])

    async def cap_interim(room, data):
        interims.append(data.get("text", ""))

    async def cap_corrected(room, data):
        corrected.append(data)

    # 두 서비스가 같은 websocket.manager 싱글톤을 참조 → 인스턴스 메서드 패치
    rt.manager.broadcast_subtitle = cap_created
    rt.manager.broadcast_interim_subtitle = cap_interim
    rt.manager.broadcast_corrected_subtitle = cap_corrected
    rt.manager.clear_history = lambda room: None

    # diarize 버퍼를 빠르게 보기 위해 약간 줄임(기본 12초)
    settings.diarize_buffer_seconds = 8.0

    await ds.diarize_service.start()
    svc = rt.OpenAiRealtimeSttService()

    print(f"[smoke] start: url={args.url}  seconds={args.seconds}  "
          f"model={settings.openai_realtime_stt_model}")
    t0 = time.monotonic()
    await svc.start("chSMOKE", args.url, meeting_id="smoke-meeting-uuid")
    await asyncio.sleep(args.seconds)
    await svc.stop("chSMOKE")
    # diarize 잔여 배치 마무리 대기
    await asyncio.sleep(6.0)
    await ds.diarize_service.stop()
    print(f"[smoke] elapsed {time.monotonic() - t0:.1f}s")

    print("\n=== subtitle_created (경로 A 실시간 전사) ===")
    for s in created:
        print(f"  [{s['start_time']:.1f}-{s['end_time']:.1f}s] spk={s['speaker']}  {s['text'][:70]}")
    print(f"  → {len(created)}건, interim {len(interims)}건")

    print("\n=== subtitle_corrected (경로 B 화자 구분) ===")
    for c in corrected:
        print(f"  id={c['id'][:8]} speaker={c.get('speaker')} source={c.get('source')}")
    speakers = sorted({c.get("speaker") for c in corrected if c.get("speaker")})
    print(f"  → {len(corrected)}건, 화자={speakers}")

    # 타임스탬프 단조성/양수 구간 검증
    ts_ok = all(s["end_time"] >= s["start_time"] >= 0 for s in created)
    mono_ok = all(
        created[i]["start_time"] <= created[i + 1]["start_time"] + 0.01
        for i in range(len(created) - 1)
    )
    db_rows = fake.store.get("subtitles", [])
    db_with_speaker = [r for r in db_rows if r.get("speaker")]

    print("\n=== 검증 ===")
    print(f"  자막 생성: {'PASS' if created else 'FAIL'} ({len(created)}건)")
    print(f"  타임스탬프 end>=start>=0: {'PASS' if ts_ok else 'FAIL'}")
    print(f"  start_time 단조 증가: {'PASS' if mono_ok else 'FAIL'}")
    print(f"  DB 저장: {len(db_rows)}건, 화자 부여됨: {len(db_with_speaker)}건")
    print(f"  화자 구분 동작: {'PASS' if corrected else 'WARN(배치 미도달/무음)'}")

    ok = bool(created) and ts_ok and mono_ok
    print(f"\n결과: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
