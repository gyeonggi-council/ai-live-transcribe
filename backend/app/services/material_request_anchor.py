"""요구자료 시각 재앵커 — 라이브 자막 시계 → VOD(AI) 자막 시계.

생중계 중 감지된 요구자료(material_requests, source='live')는 라이브 STT 시계의
start_time과 라이브 자막 행 subtitle_id를 그대로 저장한다. VOD AI 자막이 생성되면
타임라인이 영상 파일 기준으로 바뀌고, 두 시계의 오프셋은 상수가 아니다(방송 선행
구간 + 정회가 VOD에서 편집되며 회의 중간에 점프 — 기재위 실측 Δ1383.6s→Δ1864.3s).
따라서 상수 보정 대신 각 항목의 인용문(request_text)을 새 AI 자막에 텍스트 매칭해
start_time/subtitle_id를 항목별로 재지정한다.

논-골: speaker·request_text 원문은 갱신하지 않는다 — 인용문은 감지 당시 증거이며
내용상 동일 발언이므로 재작성은 불필요한 위험이다.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

logger = logging.getLogger(__name__)

# 정규화(공백 제거) 기준 최소 연속 일치 길이 — 한국어 4~6어절이면 우연 일치가 거의 없다
MIN_MATCH_CHARS = 12
# 이미 현존 AI 자막에 앵커된 것으로 판정하는 시각 허용 오차 (멱등 스킵)
ANCHORED_TOLERANCE_S = 1.0
# 사전 스크리닝 n-gram — 12자 연속 일치는 스텝 4의 8-gram 중 최소 하나를 반드시 포함
_SCREEN_N = 8
_SCREEN_STEP = 4


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "")


def _screen_grams(query: str) -> list[str]:
    """query에서 스텝 간격 8-gram 추출 — C 속도 `in` 연산으로 후보 자막을 거른다."""
    if len(query) <= _SCREEN_N:
        return [query] if query else []
    return [query[k: k + _SCREEN_N] for k in range(0, len(query) - _SCREEN_N + 1, _SCREEN_STEP)]


def plan_reanchor(
    live_requests: list[dict],
    ai_subs: list[dict],
    anchored_ids: set[str] | None = None,
) -> list[dict]:
    """순수 함수: 각 라이브 요구자료의 재앵커 계획을 산출한다 (I/O 없음).

    반환 항목: {request_id, old_start, new_start, subtitle_id,
               method: 'text'|'offset'|'skip_anchored'|'unmatched', match_size}

    - text: 인용문의 최장 연속 일치(정규화 ≥12자)가 있는 AI 자막에 앵커.
      요구자료를 시간순으로 처리하며 매칭 자막 인덱스는 단조 증가(같음 허용) —
      같은 문구가 회의에서 반복돼도 순서가 보존된다. 후보 텍스트는 인접 2개
      자막 연결 창(문장 분리 경계 보완, 매칭 시작이 앞 자막 안이어야 채택).
    - offset: 텍스트 미매칭 항목은 '가장 가까운 매칭 쌍'의 Δ를 적용(구간별 오프셋 —
      정회 편집으로 Δ가 점프하므로 전역 중앙값은 쓰지 않는다).
    - skip_anchored: subtitle_id가 현존 AI 자막이고 시각도 일치 → 이미 재앵커됨(멱등).
    - unmatched: 매칭 쌍이 하나도 없으면 추측하지 않고 무변경.
    """
    anchored = anchored_ids or set()
    subs = sorted(
        (s for s in ai_subs if s.get("start_time") is not None),
        key=lambda s: s["start_time"],
    )
    if not subs:
        return [
            {
                "request_id": r["id"], "old_start": r.get("start_time"),
                "new_start": None, "subtitle_id": None,
                "method": "unmatched", "match_size": 0,
            }
            for r in live_requests
        ]

    sub_norm = [_norm(s.get("text")) for s in subs]
    ai_start_by_id = {s["id"]: s["start_time"] for s in subs if s.get("id")}
    last_end = max(
        (s.get("end_time") or s["start_time"] for s in subs), default=subs[-1]["start_time"]
    )

    def _sub_at(t: float) -> dict:
        """시각 t를 포함하는 자막(없으면 시작 시각 최근접)."""
        for s in subs:
            end = s.get("end_time") or s["start_time"]
            if s["start_time"] <= t < end:
                return s
        return min(subs, key=lambda s: abs(s["start_time"] - t))

    reqs = sorted(
        live_requests,
        key=lambda r: (r.get("start_time") is None, r.get("start_time") or 0.0),
    )
    plans: dict[str, dict] = {}
    matched_pairs: list[tuple[float, float]] = []  # (old_start, new_start)
    last_i = -1

    for r in reqs:
        rid = r["id"]
        old = r.get("start_time")

        # 멱등 스킵: 이미 현존 AI 자막에 앵커된 행 (재실행·재훅 안전)
        sid = r.get("subtitle_id")
        if (
            sid in anchored
            and sid in ai_start_by_id
            and old is not None
            and abs(old - ai_start_by_id[sid]) <= ANCHORED_TOLERANCE_S
        ):
            plans[rid] = {
                "request_id": rid, "old_start": old, "new_start": old,
                "subtitle_id": sid, "method": "skip_anchored", "match_size": 0,
            }
            matched_pairs.append((old, ai_start_by_id[sid]))
            continue

        query = _norm(r.get("request_text") or r.get("summary"))[:500]
        best_size, best_i = 0, -1
        if len(query) >= MIN_MATCH_CHARS:
            grams = _screen_grams(query)
            sm = SequenceMatcher(None, query, "")
            for i in range(len(subs)):
                if i < last_i:  # 단조 제약 (같음 허용 — 한 자막에 여러 요구 대응)
                    continue
                head = sub_norm[i]
                window = head + (sub_norm[i + 1] if i + 1 < len(subs) else "")
                if len(window) < MIN_MATCH_CHARS:
                    continue
                if not any(g in window for g in grams):  # C 속도 사전 스크리닝
                    continue
                sm.set_seq2(window)
                m = sm.find_longest_match(0, len(query), 0, len(window))
                # 매칭 시작이 앞 자막(head) 안이어야 i에 앵커 — 뒤 자막 전용 매칭은
                # i+1 창에서 잡힌다 (한 발언이 이중 앵커되는 것 방지)
                if m.size >= MIN_MATCH_CHARS and m.b < max(len(head), 1) and m.size > best_size:
                    best_size, best_i = m.size, i

        if best_i >= 0:
            hit = subs[best_i]
            last_i = best_i
            plans[rid] = {
                "request_id": rid, "old_start": old, "new_start": hit["start_time"],
                "subtitle_id": hit.get("id"), "method": "text", "match_size": best_size,
            }
            if old is not None:
                matched_pairs.append((old, hit["start_time"]))
        else:
            plans[rid] = {
                "request_id": rid, "old_start": old, "new_start": None,
                "subtitle_id": None, "method": "unmatched", "match_size": 0,
            }

    # 오프셋 폴백 — 매칭 쌍이 있을 때만. 정회 편집으로 Δ가 회의 중간에 점프하므로
    # 전역 중앙값이 아니라 시각상 가장 가까운 매칭 쌍의 Δ를 쓴다(구간별 상수 근사).
    if matched_pairs:
        for r in reqs:
            p = plans[r["id"]]
            if p["method"] != "unmatched" or p["old_start"] is None:
                continue
            old = p["old_start"]
            near_old, near_new = min(matched_pairs, key=lambda pr: abs(pr[0] - old))
            shifted = min(max(old - (near_old - near_new), 0.0), last_end)
            hit = _sub_at(shifted)
            p.update(
                new_start=shifted, subtitle_id=hit.get("id"), method="offset"
            )

    # 입력 순서 보존해 반환
    return [plans[r["id"]] for r in live_requests if r["id"] in plans]


async def reanchor_live_requests(
    supabase: Any, meeting_id: str, *, apply: bool = True
) -> dict:
    """회의의 source='live' 요구자료를 현재 AI 자막 타임라인에 재앵커한다.

    VOD STT 완료 훅과 백필 스크립트가 공유하는 진입점. AI 자막은 DB에서 재조회한다
    (STT 파이프라인의 인메모리 자막에는 DB 생성 id가 없음).
    반환: {"total","text_matched","offset_applied","skipped","unmatched","plans"}
    """

    def _fetch_requests() -> list[dict]:
        return (
            supabase.table("material_requests")
            .select("id,start_time,subtitle_id,request_text,summary")
            .eq("meeting_id", meeting_id)
            .eq("source", "live")
            .order("start_time")
            .execute()
        ).data or []

    def _fetch_ai_subs() -> list[dict]:
        rows: list[dict] = []
        offset = 0
        while True:
            page = (
                supabase.table("subtitles")
                .select("id,text,start_time,end_time")
                .eq("meeting_id", meeting_id)
                .eq("kind", "ai")
                .order("start_time")
                .range(offset, offset + 999)
                .execute()
            ).data or []
            rows += page
            if len(page) < 1000:
                return rows
            offset += 1000

    requests = await asyncio.to_thread(_fetch_requests)
    stats = {
        "total": len(requests), "text_matched": 0, "offset_applied": 0,
        "skipped": 0, "unmatched": 0, "plans": [],
    }
    if not requests:
        return stats

    ai_subs = await asyncio.to_thread(_fetch_ai_subs)
    if not ai_subs:
        stats["unmatched"] = len(requests)
        return stats

    plans = plan_reanchor(requests, ai_subs, anchored_ids={s["id"] for s in ai_subs})
    stats["plans"] = plans
    counter = {"text": "text_matched", "offset": "offset_applied",
               "skip_anchored": "skipped", "unmatched": "unmatched"}
    now = datetime.now(timezone.utc).isoformat()

    for p in plans:
        stats[counter[p["method"]]] += 1
        if not apply or p["method"] not in ("text", "offset"):
            continue

        def _update(plan: dict = p) -> None:
            supabase.table("material_requests").update(
                {
                    "start_time": plan["new_start"],
                    "subtitle_id": plan["subtitle_id"],
                    "updated_at": now,
                }
            ).eq("id", plan["request_id"]).execute()

        try:
            await asyncio.to_thread(_update)
        except Exception as e:  # 행 단위 fail-soft — 나머지 항목은 계속 진행
            logger.warning("요구자료 재앵커 UPDATE 실패 (%s): %s", p["request_id"], e)

    return stats
