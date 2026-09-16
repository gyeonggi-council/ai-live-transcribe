"""요구자료(의원 자료 제출 요구) 감지 서비스.

실시간 자막 모니터링 직원과 의회사무처가 회의 중 의원의 자료 제출 요구를
목록화할 수 있도록 자막에서 요구자료 발언을 자동 감지한다.

2단계 파이프라인 (비용 최소화 — live-stt 배치 전사와 동일 철학):
  1) 정규식 프리필터 (비용 0): '자료/서면/보고서 + 제출/요구/요청' 계열 후보만 통과.
     고재현율 — 정밀도는 2단계가 담당.
  2) LLM 확정·추출 (gpt-5.4-mini): 주변 자막 맥락과 함께 배치 판정.
     의원→집행부 방향의 실제 요구만 채택 (공무원의 '보고자료로 대체',
     '자료 확인하겠습니다' 류 답변, 위원장의 절차 안내는 제외).

라이브: live_batch_stt._emit_sentences 훅(observe)으로 후보를 모아 디바운스 배치 판정
        → material_requests insert + WS material_request_detected 브로드캐스트.
VOD:    scan_meeting_subtitles로 전체 자막 사후 스캔 (온디맨드 버튼).

실측 근거: 기획재정위 391회 1차(2026-06-10, 170분·1,321자막)에서
'자료로 제출해 주시고요'(87:33), '자료제출 해주셨으면 좋겠습니다'(140:00),
'서류로 제출해 주세요'(143:44) 등 — KMS 요구자료 목록(mntsId=15582)과 대응.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# ─── 1단계: 정규식 프리필터 ────────────────────────────────────────────────

# 자료 명사류
_NOUN = r"(?:자료|서면|서류|보고서|현황|내역|목록|리스트|명세)"
# 제출 요구 동사류 (요청 화행)
_VERB = r"(?:제출|송부|제공|보고)"

PREFILTER_PATTERNS: list[re.Pattern[str]] = [
    # "자료(로) 제출해 주세요/주시기 바랍니다/해주셨으면", "서류로 제출해 주세요"
    re.compile(rf"{_NOUN}\s*(?:로|을|를|도)?\s*.{{0,12}}?{_VERB}\s*(?:을|를)?\s*(?:해|하여)?\s*주"),
    # "제출해 주시기 바랍니다" 앞쪽에 자료 명사가 조금 떨어져 있는 경우
    re.compile(rf"{_NOUN}.{{0,25}}{_VERB}(?:해|하여)?\s*주(?:세요|시기|시면|십시오|셨으면|시고)"),
    # "자료 요구/요청 합니다", "자료를 요구드립니다"
    re.compile(rf"{_NOUN}\s*(?:을|를)?\s*.{{0,8}}?(?:요구|요청)"),
    # "자료제출" 붙여쓰기 (STT 특성)
    re.compile(r"자료\s?제출"),
    # 명령형 활용: "정리해서 제출하시되", "제출하세요", "제출하시기 바랍니다"
    re.compile(rf"{_NOUN}.{{0,25}}{_VERB}\s*하\s*(?:시|세요|십시오)"),
    # 공무원의 수락 응답 — 직전 의원 요구를 확정하는 강한 신호
    re.compile(rf"{_NOUN}\s*(?:은|는|을|를)?\s*.{{0,10}}?{_VERB}\s*하(?:겠|도록 하겠)"),
]

# 명백한 비요구(집행부 상용구) — 프리필터 단계에서 컷 (LLM 비용 절약)
_NEGATIVE_RE = re.compile(
    r"보고\s?자료로\s*대체|서면\s?자료로\s*대체|자료를?\s*(?:좀\s*)?(?:확인|살펴|찾아|쳐다)"
    r"|자료\s*(?:를)?\s*갖고\s*있|자료\s*있으시면"
)

# 위원장 절차 안내 ("자료 요구하실 의원님 계신가요?") — 요구 아님, 맥락 마커로만 사용
CHAIR_PROMPT_RE = re.compile(r"자료\s*요구.{0,14}(?:의원|위원)님?\s*(?:계신가요|있으신가요|계십니까)")


def prefilter_material_request(text: str) -> bool:
    """요구자료 후보 여부 (고재현율 프리필터). LLM 판정 전 1차 필터."""
    if not text or len(text) < 6:
        return False
    if CHAIR_PROMPT_RE.search(text):
        return False
    if _NEGATIVE_RE.search(text):
        return False
    return any(p.search(text) for p in PREFILTER_PATTERNS)


# ─── 2단계: LLM 확정·추출 ────────────────────────────────────────────────

_SYSTEM_PROMPT = """당신은 대한민국 광역의회(경기도의회) 회의 자막에서 '요구자료'를 식별하는 분석기입니다.
요구자료란 의원이 집행부(공무원·산하기관)에 제출을 요구한 자료·서면·보고서를 말합니다.
의회사무처 직원이 요구자료 목록(예: "이혜원 의원 요구자료(지방채 발행 검토 자료)")을 만들 수 있도록,
실제 요구 발언만 골라 구조화하세요.

[요구자료로 판정]
- 의원이 자료/서면/보고서/현황/내역 등의 제출·송부를 요구: "자료로 제출해 주시고요",
  "자료제출 해주셨으면 좋겠습니다", "서류로 제출해 주세요", "서면으로 보고해 주시기 바랍니다"
- 공무원이 "자료 제출하겠습니다"라고 수락한 경우 → 직전 맥락의 의원 요구 내용으로 판정

[요구자료가 아님 — 반드시 제외]
- 공무원의 설명·답변: "보고자료로 대체하겠습니다", "자료를 확인해 보겠습니다", "자료 갖고 있습니다"
- 위원장의 절차 안내: "자료 요구하실 의원님 계신가요?"
- 이미 배부된 자료 언급, 자료 내용에 대한 단순 질의, 조례상 제출 의무에 대한 논의

[출력]
각 후보 번호에 대해 JSON 배열로만 답하세요 (설명 금지):
[{"index": 후보번호, "is_request": true/false, "summary": "간결한 자료 제목 (조사 없이 명사형, 예: '지방채 발행 검토 자료')",
  "councilor": "요구 의원 실명 (맥락에서 확실할 때만, 불명확하면 null)",
  "department": "요구 대상 부서·기관 (언급된 경우만, 없으면 null)",
  "confidence": "high|medium|low", "request_text": "핵심 요구 문장 (원문 그대로 1문장)"}]
동일한 요구가 여러 후보에 걸쳐 있으면 가장 명확한 후보 하나만 is_request=true로 하세요."""


def _fmt_time(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def build_llm_input(
    candidates: list[dict],
    committee: str | None = None,
    questioner_hint: str | None = None,
) -> str:
    """후보 자막(±맥락 포함)을 LLM 입력 블록으로 포맷한다.

    candidates: [{"index", "text", "speaker", "start_time", "context_before": [...], "context_after": [...]}]
    """
    lines: list[str] = []
    if committee:
        lines.append(f"[회의] {committee}")
    if questioner_hint:
        lines.append(f"[현재 질의 중인 의원 추정] {questioner_hint}")
    for c in candidates:
        lines.append(f"\n### 후보 {c['index']} [{_fmt_time(c.get('start_time') or 0)}]")
        for b in c.get("context_before", []):
            lines.append(f"  (앞) {b.get('speaker') or '?'}: {b['text']}")
        lines.append(f"  ▶ 후보: {c.get('speaker') or '?'}: {c['text']}")
        for a in c.get("context_after", []):
            lines.append(f"  (뒤) {a.get('speaker') or '?'}: {a['text']}")
    return "\n".join(lines)


def parse_llm_response(content: str) -> list[dict]:
    """LLM 응답에서 JSON 배열을 관대하게 파싱한다 (코드펜스/부가설명 허용)."""
    text = content.strip()
    m = re.search(r"\[[\s\S]*\]", text)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    out = []
    for item in arr:
        if isinstance(item, dict) and item.get("is_request") and (item.get("summary") or "").strip():
            out.append(item)
    return out


async def _call_llm(user_block: str) -> list[dict]:
    """OpenAI chat completions로 후보 배치를 판정한다."""
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다.")
    t0 = time.monotonic()
    api_success = False
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.material_request_model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_block},
                    ],
                    "max_completion_tokens": 1200,
                },
            )
            resp.raise_for_status()
        api_success = True
    finally:
        try:
            from app.api.admin import api_tracker

            api_tracker.record("openai", (time.monotonic() - t0) * 1000, api_success)
        except Exception:
            pass
    content = resp.json()["choices"][0]["message"]["content"] or ""
    return parse_llm_response(content)


# ─── 중복 병합 ────────────────────────────────────────────────────────────

def dedupe_requests(items: list[dict], *, time_window: float = 60.0) -> list[dict]:
    """근접 시각 + 유사 제목의 중복 감지를 병합한다 (가장 신뢰도 높은 것 유지)."""
    rank = {"high": 3, "medium": 2, "low": 1}
    kept: list[dict] = []
    for item in sorted(items, key=lambda x: x.get("start_time") or 0):
        dup = None
        for k in kept:
            close = abs((item.get("start_time") or 0) - (k.get("start_time") or 0)) <= time_window
            sim = difflib.SequenceMatcher(
                None, item.get("summary") or "", k.get("summary") or ""
            ).ratio()
            if sim >= 0.6 and (close or (item.get("councilor_name") or "") == (k.get("councilor_name") or "")):
                dup = k
                break
        if dup is None:
            kept.append(item)
        elif rank.get(item.get("confidence"), 0) > rank.get(dup.get("confidence"), 0):
            kept[kept.index(dup)] = item
    return kept


# ─── 후보 → 컨텍스트 조립 ────────────────────────────────────────────────

def collect_candidates(subtitles: list[dict], *, ctx: int = 3) -> list[dict]:
    """자막 리스트에서 프리필터 후보를 앞뒤 맥락과 함께 수집한다."""
    candidates = []
    for i, s in enumerate(subtitles):
        if not prefilter_material_request(s.get("text") or ""):
            continue
        candidates.append(
            {
                "index": len(candidates) + 1,
                "subtitle_id": s.get("id"),
                "text": s.get("text") or "",
                "speaker": s.get("speaker"),
                "start_time": s.get("start_time"),
                "context_before": [
                    {"speaker": p.get("speaker"), "text": (p.get("text") or "")[:120]}
                    for p in subtitles[max(0, i - ctx): i]
                ],
                "context_after": [
                    {"speaker": n.get("speaker"), "text": (n.get("text") or "")[:120]}
                    for n in subtitles[i + 1: i + 1 + ctx]
                ],
            }
        )
    return candidates


def _assemble_quote(cand: dict, llm_text: str, min_chars: int = 140) -> str:
    """핵심 요구 문장에 앞뒤 자막 문맥을 붙여 검토 가능한 분량(2~3줄+)으로 조립한다.

    요구 문장 자체("자료로 제출해 주시기 바랍니다")에는 대상이 없는 경우가 많아,
    앞 발언(질의 내용)을 우선 보강한다. min_chars 도달까지 앞→뒤 순으로 확장.
    """
    core = (llm_text or cand.get("text") or "").strip()
    parts = [core]
    before = [str(b.get("text") or "").strip() for b in cand.get("context_before", [])]
    after = [str(a.get("text") or "").strip() for a in cand.get("context_after", [])]

    def _dup(text: str) -> bool:
        # 배치 STT 오버랩으로 원본 자막에 같은 문장이 반복되는 경우가 있어
        # 이미 담긴 부분과 포함 관계면 건너뛴다.
        return any(text in p or p in text for p in parts)

    bi, ai = len(before) - 1, 0
    while len(" ".join(parts)) < min_chars and (bi >= 0 or ai < len(after)):
        if bi >= 0:
            if before[bi] and not _dup(before[bi]):
                parts.insert(0, before[bi])
            bi -= 1
        else:
            if after[ai] and not _dup(after[ai]):
                parts.append(after[ai])
            ai += 1
    return " ".join(p for p in parts if p).strip()[:500]


def _to_row(meeting_id: str, cand_by_index: dict[int, dict], verdict: dict, source: str) -> dict:
    cand = cand_by_index.get(verdict.get("index") or -1, {})
    return {
        "id": str(uuid.uuid4()),
        "meeting_id": meeting_id,
        "subtitle_id": cand.get("subtitle_id"),
        "start_time": cand.get("start_time"),
        "speaker": cand.get("speaker"),
        "councilor_name": verdict.get("councilor") or None,
        "summary": (verdict.get("summary") or "").strip()[:200],
        "request_text": _assemble_quote(cand, verdict.get("request_text") or ""),
        "department": verdict.get("department") or None,
        "confidence": verdict.get("confidence") if verdict.get("confidence") in ("high", "medium", "low") else "medium",
        "status": "detected",
        "source": source,
    }


# ─── VOD 사후 스캔 ────────────────────────────────────────────────────────

async def scan_meeting_subtitles(supabase: Any, meeting_id: str) -> list[dict]:
    """회의 전체 자막을 스캔해 요구자료를 감지·저장하고 목록을 반환한다.

    재스캔 시 사람 손이 닿지 않은(status='detected') vod_scan 행만 교체한다.
    """

    def _fetch_subs() -> list[dict]:
        rows: list[dict] = []
        offset = 0
        while True:
            page = (
                supabase.table("subtitles")
                .select("id,text,speaker,start_time")
                .eq("meeting_id", meeting_id)
                .order("start_time")
                .range(offset, offset + 999)
                .execute()
            ).data or []
            rows += page
            if len(page) < 1000:
                return rows
            offset += 1000

    subtitles = await asyncio.to_thread(_fetch_subs)
    if not subtitles:
        raise ValueError("자막이 없어 요구자료를 분석할 수 없습니다.")

    candidates = collect_candidates(subtitles)
    logger.info("요구자료 스캔 %s: 자막 %d → 후보 %d", meeting_id, len(subtitles), len(candidates))

    committee = None
    try:
        meeting = await asyncio.to_thread(
            lambda: (
                supabase.table("meetings").select("committee,title").eq("id", meeting_id).limit(1).execute()
            ).data
        )
        if meeting:
            committee = meeting[0].get("committee") or meeting[0].get("title")
    except Exception:
        pass

    verdicts: list[dict] = []
    cand_by_index = {c["index"]: c for c in candidates}
    batch_size = 8
    for i in range(0, len(candidates), batch_size):
        batch = candidates[i: i + batch_size]
        try:
            verdicts += await _call_llm(build_llm_input(batch, committee=committee))
        except Exception as e:
            logger.warning("요구자료 LLM 배치 실패 (%d~): %s", i, e)

    rows = [_to_row(meeting_id, cand_by_index, v, "vod_scan") for v in verdicts]
    rows = [r for r in rows if r["summary"]]
    rows = dedupe_requests(
        [{**r, "start_time": r.get("start_time") or 0} for r in rows]
    )

    def _persist() -> list[dict]:
        # 사람 손이 닿지 않은 이전 스캔 결과만 교체
        supabase.table("material_requests").delete().eq("meeting_id", meeting_id).eq(
            "source", "vod_scan"
        ).eq("status", "detected").execute()
        if rows:
            supabase.table("material_requests").insert(rows).execute()
        return (
            supabase.table("material_requests")
            .select("*")
            .eq("meeting_id", meeting_id)
            .order("start_time")
            .execute()
        ).data or []

    return await asyncio.to_thread(_persist)


# ─── 라이브 감지기 ────────────────────────────────────────────────────────

class LiveMaterialRequestDetector:
    """라이브 자막 스트림에서 요구자료를 감지한다 (채널별 상태).

    observe()는 논블로킹 — 후보 발견 시 디바운스 태스크를 걸고,
    잠잠해지면(추가 맥락 수집 후) 한 번에 LLM 판정한다.
    """

    CONTEXT_SIZE = 3          # 후보 앞뒤 맥락 자막 수
    BUFFER_SIZE = 24          # 채널별 최근 자막 링버퍼
    DEBOUNCE_SECONDS = 12.0   # 후보 수집 후 판정까지 대기 (후속 맥락 확보)

    def __init__(self) -> None:
        self._buffers: dict[str, list[dict]] = {}
        self._pending: dict[str, list[dict]] = {}
        self._meeting: dict[str, str] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._seen: dict[str, list[dict]] = {}  # 채널별 확정 목록 (세션 내 dedupe)

    def start_channel(self, channel_id: str, meeting_id: str) -> None:
        self._buffers[channel_id] = []
        self._pending[channel_id] = []
        self._meeting[channel_id] = meeting_id
        self._seen[channel_id] = []

    def drop_channel(self, channel_id: str) -> None:
        task = self._tasks.pop(channel_id, None)
        if task and not task.done():
            task.cancel()
        for d in (self._buffers, self._pending, self._meeting, self._seen):
            d.pop(channel_id, None)

    def observe(self, channel_id: str, meeting_id: str, subtitle: dict) -> bool:
        """확정 자막 1건 관찰. 후보면 True (판정은 비동기 디바운스)."""
        if not settings.material_request_enabled:
            return False
        if channel_id not in self._buffers:
            self.start_channel(channel_id, meeting_id)
        buf = self._buffers[channel_id]
        buf.append(
            {
                "id": subtitle.get("id"),
                "text": subtitle.get("text") or "",
                "speaker": subtitle.get("speaker"),
                "start_time": subtitle.get("start_time"),
            }
        )
        del buf[: -self.BUFFER_SIZE]

        if not prefilter_material_request(subtitle.get("text") or ""):
            return False

        self._pending[channel_id].append({"buffer_pos": len(buf) - 1, "sub": buf[-1]})
        self._schedule(channel_id)
        return True

    def _schedule(self, channel_id: str) -> None:
        existing = self._tasks.get(channel_id)
        if existing and not existing.done():
            return  # 이미 대기 중 — 그 사이 쌓인 후보는 같은 배치에 포함됨
        self._tasks[channel_id] = asyncio.create_task(self._debounced_process(channel_id))

    async def _debounced_process(self, channel_id: str) -> None:
        try:
            await asyncio.sleep(self.DEBOUNCE_SECONDS)
            await self._process(channel_id)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("요구자료 라이브 판정 실패 ch=%s: %s", channel_id, e)

    async def _process(self, channel_id: str) -> None:
        pending = self._pending.get(channel_id) or []
        self._pending[channel_id] = []
        if not pending:
            return
        buf = self._buffers.get(channel_id) or []
        meeting_id = self._meeting.get(channel_id) or channel_id

        candidates = []
        for n, p in enumerate(pending, start=1):
            sub = p["sub"]
            # 링버퍼에서 현재 위치 기준 앞뒤 맥락 (버퍼가 흘렀어도 id로 재탐색)
            try:
                pos = next(i for i, b in enumerate(buf) if b["id"] == sub["id"])
            except StopIteration:
                pos = None
            before = buf[max(0, pos - self.CONTEXT_SIZE): pos] if pos is not None else []
            after = buf[pos + 1: pos + 1 + self.CONTEXT_SIZE] if pos is not None else []
            candidates.append(
                {
                    "index": n,
                    "subtitle_id": sub["id"],
                    "text": sub["text"],
                    "speaker": sub.get("speaker"),
                    "start_time": sub.get("start_time"),
                    "context_before": [{"speaker": b.get("speaker"), "text": b["text"][:120]} for b in before],
                    "context_after": [{"speaker": a.get("speaker"), "text": a["text"][:120]} for a in after],
                }
            )

        questioner = None
        try:
            from app.services.speaker_cue_tracker import speaker_cue_tracker

            questioner = speaker_cue_tracker.current_member_name(channel_id)
        except Exception:
            pass

        verdicts = await _call_llm(build_llm_input(candidates, questioner_hint=questioner))
        if not verdicts:
            return

        cand_by_index = {c["index"]: c for c in candidates}
        rows = [_to_row(meeting_id, cand_by_index, v, "live") for v in verdicts]
        # 요구 의원 미확정 시 cue tracker의 현재 질의 의원으로 보완
        for r in rows:
            if not r["councilor_name"] and questioner:
                r["councilor_name"] = questioner

        merged = dedupe_requests(self._seen.get(channel_id, []) + rows)
        new_rows = [r for r in merged if any(r["id"] == x["id"] for x in rows)]
        if not new_rows:
            return
        self._seen[channel_id] = merged[-40:]

        await self._persist_and_broadcast(channel_id, meeting_id, new_rows)

    async def _persist_and_broadcast(
        self, channel_id: str, meeting_id: str, rows: list[dict]
    ) -> None:
        from app.api.websocket import manager
        from app.core.database import get_supabase_client

        if meeting_id != channel_id:  # 등록된 회의일 때만 DB 저장 (채널 단독 방송은 WS만)
            try:
                await asyncio.to_thread(
                    lambda: get_supabase_client().table("material_requests").insert(rows).execute()
                )
            except Exception as e:
                logger.warning("요구자료 저장 실패 ch=%s: %s", channel_id, e)
        for r in rows:
            payload = {**r, "created_at": datetime.now(timezone.utc).isoformat()}
            try:
                await manager.broadcast_material_request(channel_id, payload)
            except Exception as e:
                logger.debug("요구자료 브로드캐스트 실패 ch=%s: %s", channel_id, e)
            logger.info(
                "Channel %s: [요구자료 감지] %s — %s",
                channel_id,
                r.get("councilor_name") or r.get("speaker") or "?",
                r["summary"],
            )


material_request_detector = LiveMaterialRequestDetector()
