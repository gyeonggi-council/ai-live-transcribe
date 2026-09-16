# @TASK P7-T2.1 - AI 요약 서비스 (Meeting Summary Service)
# @SPEC docs/planning/02-trd.md#AI-요약

"""회의 AI 요약 서비스

회의 자막을 분석하여 자동 요약을 생성합니다.
OpenAI GPT API를 사용합니다.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
from supabase import Client

from app.core.config import settings
from app.services.openai_opts import reasoning_kw
from app.services.subtitle_fetch import fetch_all_subtitles
from app.services.subtitle_select import prefer_ai_subtitles

logger = logging.getLogger(__name__)

# 단일 호출에 넣을 자막 텍스트 최대 길이(문자). 넘으면 맵리듀스(2026-09-14, 전에는 여기서 잘라 뒷부분을 버렸다)
MAX_TRANSCRIPT_CHARS = 12000
KST = timezone(timedelta(hours=9))


class SummaryGenerationError(RuntimeError):
    """요약 생성 실패(상류 오류·청크 일부 실패·응답 파싱 실패·저장 실패) — 캐시에 넣지 않는다. 라우터는 502."""


class SummaryLimitError(RuntimeError):
    """하루 요약 생성 상한 초과 — 라우터는 429. 캐시 적중은 차감하지 않는다."""


# 하루 생성 상한 카운터(인메모리, KST) — 요약 라우트·안건 초안 어느 경로로 오든 같은 장부
_daily: dict[str, int] = {}
# 회의별 생성 락 — 캐시 확인과 생성 사이에 같은 회의 요청이 겹치면 둘 다 OpenAI 를 부르던 문제(Codex 검토)
_locks: dict[str, asyncio.Lock] = {}

MAP_SYSTEM_PROMPT = """당신은 경기도의회 회의록 분석 전문가입니다. 주어진 것은 긴 회의의 한 구간 자막입니다.
이 구간만 보고 다음 JSON 을 만드세요. 다른 구간은 모릅니다 — 추측하지 마세요.

{
  "summary": "이 구간의 논의 요약 (3~6문장, 누가 무엇을 주장·질의·답변했는지)",
  "topics": ["주제 1", "주제 2"],
  "decisions": ["이 구간에서 내려진 결정(가결·의결·보류 등)"],
  "action_items": ["요구된 자료·후속 조치"],
  "numbers": ["언급된 수치(예산액·건수·비율)와 그 맥락"],
  "speakers": [{"name": "발언자(자막의 화자 표기 그대로)", "points": ["핵심 발언 요지"]}]
}

규칙: 한국어 · 객관적 · 없는 항목은 빈 배열 · 반드시 유효한 JSON 만 출력."""


SUMMARY_SYSTEM_PROMPT = """당신은 경기도의회 회의록 분석 전문가입니다.
주어진 회의 자막을 분석하여 다음 형식의 JSON으로 요약을 생성하세요.

{
  "summary_text": "전체 회의 요약 (2-3문장)",
  "agenda_summaries": [
    {"order_num": 1, "title": "안건 제목", "summary": "안건별 논의 요약"}
  ],
  "key_decisions": ["결정사항 1", "결정사항 2"],
  "action_items": ["후속 조치 1", "후속 조치 2"]
}

규칙:
- 한국어로 작성
- 객관적이고 간결하게
- 핵심 논의 내용과 결론 위주
- 안건이 명확하지 않으면 agenda_summaries는 빈 배열
- 결정사항이 없으면 key_decisions는 빈 배열
- 후속 조치가 없으면 action_items는 빈 배열
- 반드시 유효한 JSON만 출력하세요. 다른 텍스트는 출력하지 마세요."""

REDUCE_SYSTEM_PROMPT = SUMMARY_SYSTEM_PROMPT + """

추가 규칙(구간 요약 병합):
- 입력은 자막 원문이 아니라 시간순 구간별 요약이다. 구간에 적힌 결정·조치·수치를 빠뜨리지 말고 합쳐라.
- agenda_summaries 의 order_num 은 주어진 안건 목록의 번호를 그대로 쓴다. 목록에 없는 번호를 만들지 마라.
- summary_text 는 회의 전체를 3~5문장으로."""


@dataclass
class MeetingSummary:
    """요약 결과"""

    summary_text: str  # 전체 요약 (2-3 문장)
    agenda_summaries: list[dict] = field(default_factory=list)
    key_decisions: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    model_used: str = "gpt-5-mini"
    # 2026-09-14(migration 034) — 긴 회의 맵리듀스의 중간 결과와 신뢰도 표시
    segments: list[dict] = field(default_factory=list)
    speakers: list[dict] = field(default_factory=list)
    source_chars: int = 0
    complete: bool | None = True  # None = 034 이전 행(알 수 없음)
    generated_from: str = "ai"


def _format_time_hms(seconds: float) -> str:
    """초를 HH:MM:SS 형식으로 변환합니다."""
    td = timedelta(seconds=int(seconds))
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _format_subtitles_for_prompt(
    subtitles: list[dict],
    agendas: list[dict] | None = None,
    truncate: bool = True,
) -> str:
    """자막을 GPT 프롬프트용 텍스트로 변환합니다.

    Format:
    [00:00:30] 화자 1: 안녕하세요, 회의를 시작하겠습니다.
    [00:01:15] 화자 2: 네, 첫 번째 안건부터 논의하겠습니다.

    안건 정보가 있으면 상단에 안건 목록을 추가합니다.
    """
    lines: list[str] = []

    # 안건 목록이 있으면 상단에 추가
    if agendas:
        lines.append("=== 안건 목록 ===")
        for agenda in agendas:
            order_num = agenda.get("order_num", "?")
            title = agenda.get("title", "제목 없음")
            lines.append(f"{order_num}. {title}")
        lines.append("")
        lines.append("=== 회의 자막 ===")

    for sub in subtitles:
        start_time = sub.get("start_time", 0.0)
        speaker = sub.get("speaker") or "발언자 미확인"
        text = sub.get("text", "")
        time_str = _format_time_hms(start_time)
        lines.append(f"[{time_str}] {speaker}: {text}")

    result = "\n".join(lines)

    # 단일 호출 상한: 텍스트가 너무 길면 잘라냄(맵리듀스 경로는 truncate=False 로 전량을 받아 청크로 나눈다)
    if truncate and len(result) > MAX_TRANSCRIPT_CHARS:
        result = result[:MAX_TRANSCRIPT_CHARS] + "\n\n... (이하 생략, 전체 자막 중 일부만 포함)"

    return result


async def _call_openai_json(
    system_prompt: str,
    user_message: str,
    *,
    model: str,
    max_tokens: int,
    timeout: float,
    reasoning_effort: str = "",
) -> dict:
    """OpenAI chat/completions 를 불러 JSON 객체를 돌려준다. 실패·빈 응답·파싱 실패는 SummaryGenerationError.

    Raises:
        ValueError: API 키가 설정되지 않은 경우(예전 계약 유지)
    """
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다.")

    t0 = time.monotonic()
    api_success = False
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    "max_completion_tokens": max_tokens,
                    "response_format": {"type": "json_object"},
                    **reasoning_kw(reasoning_effort),
                },
            )
            response.raise_for_status()
        api_success = True
    except Exception as e:
        logger.error("OpenAI 요약 호출 실패(%s): %s", model, e)
        raise SummaryGenerationError("AI 요약 서비스 호출에 실패했습니다. 잠시 뒤 다시 시도해 주세요.") from e
    finally:
        try:
            from app.api.admin import api_tracker
            latency = (time.monotonic() - t0) * 1000
            api_tracker.record("openai", latency, api_success)
        except Exception:
            pass

    try:
        data = response.json()
        choice = data["choices"][0]
        content = (choice["message"]["content"] or "").strip()
        finish = choice.get("finish_reason")
        usage = data.get("usage") or {}
        logger.info(
            "ai summary model=%s in=%s out=%s reasoning=%s finish=%s %.1fs",
            data.get("model"), usage.get("prompt_tokens"), usage.get("completion_tokens"),
            (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"), finish, time.monotonic() - t0,
        )
    except Exception as e:
        raise SummaryGenerationError("AI 요약 응답을 읽지 못했습니다.") from e
    if finish == "length":
        # 추론 모델(gpt-5.4-mini)은 생각 토큰이 max_completion_tokens 에 포함된다 — 상한이 낮으면 JSON 이 중간에 잘린다
        # (2026-09-14 실측: 청크 1,200 토큰에서 14개 중 11개가 "{" 로 시작하다 끊겼다)
        logger.warning("요약 응답이 토큰 상한(%s)에서 잘렸다(model=%s, %d자)", max_tokens, model, len(content))
        raise SummaryGenerationError("AI 요약 결과가 길이 상한에서 잘렸습니다. 다시 시도해 주세요.")

    # JSON 파싱 (코드블록 제거)
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        # 예전엔 원문 500자를 요약으로 저장했다 — 깨진 결과가 캐시에 남아 회의당 1회 정책에 갇혔다(Codex 검토 2026-09-14)
        logger.warning("요약 응답 JSON 파싱 실패: %s", content[:200])
        raise SummaryGenerationError("AI 요약 결과의 형식이 올바르지 않습니다. 다시 시도해 주세요.") from e
    if not isinstance(parsed, dict):
        raise SummaryGenerationError("AI 요약 결과의 형식이 올바르지 않습니다.")
    return parsed


def _as_str_list(value) -> list[str]:
    return [str(v).strip() for v in (value or []) if str(v).strip()] if isinstance(value, list) else []


async def _call_openai_summary(
    transcript_text: str,
    agendas: list[dict] | None = None,
) -> MeetingSummary:
    """단일 호출 요약(자막 ≤ MAX_TRANSCRIPT_CHARS).

    Raises:
        ValueError: API 키가 설정되지 않은 경우
        SummaryGenerationError: 호출·파싱 실패
    """
    user_message = transcript_text
    if agendas:
        user_message = (
            "안건 목록이 포함된 회의 자막입니다. "
            "안건별로 요약해 주세요.\n\n" + transcript_text
        )
    parsed = await _call_openai_json(
        SUMMARY_SYSTEM_PROMPT, user_message, model=settings.summary_model, max_tokens=settings.summary_max_tokens, timeout=120.0,
        reasoning_effort=settings.summary_reasoning_effort,
    )
    return MeetingSummary(
        summary_text=str(parsed.get("summary_text", "") or ""),
        agenda_summaries=[a for a in (parsed.get("agenda_summaries") or []) if isinstance(a, dict)],
        key_decisions=_as_str_list(parsed.get("key_decisions")),
        action_items=_as_str_list(parsed.get("action_items")),
        model_used=settings.summary_model,
    )


# ── 긴 회의: 청크(맵) → 병합(리듀스) ─────────────────────────────────────────────

def _agenda_anchor_times(agendas: list[dict] | None, subtitles: list[dict]) -> list[float]:
    """안건 상정 시각(초) — rag_context.resolve_agenda_ranges 의 확인된 앵커만. 없으면 빈 리스트."""
    if not agendas:
        return []
    try:
        from app.services.rag_context import resolve_agenda_ranges

        return sorted({r.lo for r in resolve_agenda_ranges(agendas, subtitles) if not r.estimated and r.lo > 0})
    except Exception as e:  # 앵커 실패는 청크 품질 문제일 뿐 요약을 막지 않는다
        logger.debug("안건 앵커 실패(시간순 청크로): %s", e)
        return []


def build_summary_chunks(
    subtitles: list[dict],
    agendas: list[dict] | None = None,
    target_chars: int | None = None,
) -> list[dict]:
    """자막을 요약 청크로 나눈다 — 자막 행을 절단하지 않는다(청크 텍스트의 합 == 전량).

    경계 우선순위: ① 안건 상정 시각(확인된 앵커) ② 목표 글자수를 넘긴 뒤 첫 화자 교대 ③ 목표의 1.5배를 넘기면 강제.
    개의·폐회·미분류 자막도 전부 어느 청크엔가 들어간다.
    각 청크: {idx, order_num, title, start_time, end_time, subtitles}
    """
    target = target_chars or settings.summary_chunk_chars
    if not subtitles:
        return []
    anchors = _agenda_anchor_times(agendas, subtitles)
    agenda_by_time: list[tuple[float, dict]] = []
    if anchors and agendas:
        try:
            from app.services.rag_context import resolve_agenda_ranges

            agenda_by_time = sorted(
                ((r.lo, {"order_num": r.order_num, "title": r.title}) for r in resolve_agenda_ranges(agendas, subtitles) if not r.estimated),
                key=lambda x: x[0],
            )
        except Exception:
            agenda_by_time = []

    def agenda_at(sec: float | None) -> dict | None:
        if sec is None:
            return None
        cur = None
        for t, a in agenda_by_time:
            if t <= sec:
                cur = a
            else:
                break
        return cur

    chunks: list[dict] = []
    cur: list[dict] = []
    cur_chars = 0
    prev_speaker: str | None = None
    next_anchor = 0

    def flush() -> None:
        nonlocal cur, cur_chars
        if not cur:
            return
        first = cur[0]
        ag = agenda_at(first.get("start_time"))
        chunks.append({
            "idx": len(chunks),
            "order_num": ag.get("order_num") if ag else None,
            "title": ag.get("title") if ag else None,
            "start_time": float(first.get("start_time") or 0.0),
            "end_time": float(cur[-1].get("end_time") or cur[-1].get("start_time") or 0.0),
            "subtitles": cur,
        })
        cur, cur_chars = [], 0

    for sub in subtitles:
        sec = sub.get("start_time")
        speaker = sub.get("speaker") or ""
        # ① 안건 경계
        while next_anchor < len(anchors) and sec is not None and sec >= anchors[next_anchor]:
            if cur:
                flush()
            next_anchor += 1
        # ② 목표 초과 + 화자 교대, ③ 강제
        line_len = len(sub.get("text") or "") + 24
        if cur and (
            (cur_chars >= target and speaker != prev_speaker)
            or cur_chars + line_len > target * 1.5
        ):
            flush()
        cur.append(sub)
        cur_chars += line_len
        prev_speaker = speaker
    flush()
    return chunks


def _chunk_text(chunk: dict) -> str:
    return _format_subtitles_for_prompt(chunk["subtitles"], truncate=False)


async def _summarize_chunk(chunk: dict, agendas: list[dict] | None) -> dict:
    """청크 하나를 요약(맵). 실패는 SummaryGenerationError 로 올린다(호출자가 재시도 1회)."""
    head = f"[구간 {chunk['idx'] + 1} · {_format_time_hms(chunk['start_time'])}~{_format_time_hms(chunk['end_time'])}"
    if chunk.get("order_num"):
        head += f" · 안건 {chunk['order_num']}. {chunk.get('title') or ''}"
    head += "]"
    user = head + "\n" + _chunk_text(chunk)
    parsed = await _call_openai_json(
        MAP_SYSTEM_PROMPT, user, model=settings.summary_map_model, max_tokens=settings.summary_map_max_tokens, timeout=90.0,
        reasoning_effort=settings.summary_map_reasoning_effort,
    )
    speakers = []
    for sp in parsed.get("speakers") or []:
        if isinstance(sp, dict) and sp.get("name"):
            speakers.append({"name": str(sp["name"]).strip(), "points": _as_str_list(sp.get("points"))[:5]})
    return {
        "idx": chunk["idx"],
        "order_num": chunk.get("order_num"),
        "title": chunk.get("title"),
        "start_time": chunk["start_time"],
        "end_time": chunk["end_time"],
        "summary": str(parsed.get("summary") or "").strip(),
        "topics": _as_str_list(parsed.get("topics"))[:8],
        "decisions": _as_str_list(parsed.get("decisions")),
        "action_items": _as_str_list(parsed.get("action_items")),
        "numbers": _as_str_list(parsed.get("numbers"))[:12],
        "speakers": speakers,
    }


def _render_segments(segments: list[dict], agendas: list[dict] | None, budget: int) -> str:
    """병합(리듀스) 입력 — 청크를 하나도 버리지 않는다. 예산이 모자라면 요약 본문을 줄이고, 그래도 넘치면 결정·조치·수치 줄을 줄인다.
    (Codex 검토 2026-09-14: 본문만 계산해 놓고 끝에서 잘라 뒤쪽 청크가 통째로 사라졌다 — complete=True 로 저장돼 재생성도 막혔다.)"""
    head_lines: list[str] = []
    if agendas:
        head_lines.append("=== 안건 목록 ===")
        for a in agendas:
            head_lines.append(f"{a.get('order_num', '?')}. {a.get('title', '제목 없음')}")
        head_lines.append("")
    head_lines.append("=== 구간별 요약(시간순) ===")
    head = "\n".join(head_lines) + "\n"

    def block(seg: dict, per: int, extra_cap: int) -> str:
        h = f"[구간 {seg['idx'] + 1} · {_format_time_hms(seg['start_time'])}~{_format_time_hms(seg['end_time'])}"
        if seg.get("order_num"):
            h += f" · 안건 {seg['order_num']}"
        h += "]"
        lines = [h, (seg.get("summary") or "")[:per]]
        for label, key in (("결정", "decisions"), ("조치", "action_items"), ("수치", "numbers")):
            if seg.get(key):
                lines.append((f"{label}: " + " / ".join(seg[key]))[:extra_cap])
        lines.append("")
        return "\n".join(lines)

    n = max(1, len(segments))
    per = max(120, (budget - len(head)) // n)
    extra_cap = 300
    text = head + "".join(block(seg, per, extra_cap) for seg in segments)
    while len(text) > budget and per > 120:
        per = max(120, int(per * 0.8))
        text = head + "".join(block(seg, per, extra_cap) for seg in segments)
    while len(text) > budget and extra_cap > 60:
        extra_cap = max(60, int(extra_cap * 0.7))
        text = head + "".join(block(seg, per, extra_cap) for seg in segments)
    return text


def _merge_speakers(segments: list[dict]) -> list[dict]:
    by: dict[str, list[str]] = {}
    for seg in segments:
        for sp in seg.get("speakers") or []:
            pts = by.setdefault(sp["name"], [])
            for p in sp.get("points") or []:
                if p not in pts and len(pts) < 8:
                    pts.append(p)
    return [{"name": n, "points": p} for n, p in by.items()]


async def _summarize_long(subtitles: list[dict], agendas: list[dict] | None) -> MeetingSummary:
    """청크 요약(맵, 병렬 ≤ summary_map_concurrency, 실패 시 1회 재시도) → 병합 요약(리듀스).

    청크 하나라도 끝내 실패하면 SummaryGenerationError — 부분 요약을 정상처럼 돌려주지 않는다.
    """
    chunks = build_summary_chunks(subtitles, agendas)
    sem = asyncio.Semaphore(max(1, settings.summary_map_concurrency))

    async def one(chunk: dict) -> dict:
        async with sem:
            try:
                return await _summarize_chunk(chunk, agendas)
            except SummaryGenerationError:
                return await _summarize_chunk(chunk, agendas)

    results = await asyncio.gather(*(one(c) for c in chunks), return_exceptions=True)
    failed = [i for i, r in enumerate(results) if isinstance(r, BaseException)]
    if failed:
        first = results[failed[0]]
        raise SummaryGenerationError(
            f"구간 요약 {len(failed)}/{len(chunks)}개가 실패했습니다. 잠시 뒤 다시 시도해 주세요."
        ) from (first if isinstance(first, Exception) else None)
    segments = [r for r in results if isinstance(r, dict)]

    reduce_input = _render_segments(segments, agendas, MAX_TRANSCRIPT_CHARS)
    parsed = await _call_openai_json(
        REDUCE_SYSTEM_PROMPT, reduce_input, model=settings.summary_model, max_tokens=settings.summary_max_tokens, timeout=120.0,
        reasoning_effort=settings.summary_reasoning_effort,
    )
    valid_nums = {a.get("order_num") for a in (agendas or [])}
    agenda_summaries = [
        a for a in (parsed.get("agenda_summaries") or [])
        if isinstance(a, dict) and (not valid_nums or a.get("order_num") in valid_nums)
    ]
    return MeetingSummary(
        summary_text=str(parsed.get("summary_text", "") or ""),
        agenda_summaries=agenda_summaries,
        key_decisions=_as_str_list(parsed.get("key_decisions")),
        action_items=_as_str_list(parsed.get("action_items")),
        model_used=f"{settings.summary_model}+{settings.summary_map_model}(map {len(chunks)})"[:100],
        segments=segments,
        speakers=_merge_speakers(segments),
    )


def _today() -> str:
    return datetime.now(KST).date().isoformat()


def reserve_generation_slot() -> None:
    """하루 생성 상한(KST) — 실제로 OpenAI 를 부르기 직전에만 차감한다."""
    today = _today()
    if today not in _daily:
        _daily.clear()
        _daily[today] = 0
    if _daily[today] >= settings.ai_summary_daily_limit:
        raise SummaryLimitError(
            f"오늘 AI 요약 생성 한도({settings.ai_summary_daily_limit}회)를 모두 썼습니다. 내일 00시(한국시간)에 다시 열립니다."
        )
    _daily[today] += 1


def _row_to_summary(existing: dict) -> MeetingSummary:
    return MeetingSummary(
        summary_text=existing.get("summary_text", "") or "",
        agenda_summaries=existing.get("agenda_summaries", []) or [],
        key_decisions=existing.get("key_decisions", []) or [],
        action_items=existing.get("action_items", []) or [],
        model_used=existing.get("model_used", "") or "",
        segments=existing.get("segments") or [],
        speakers=existing.get("speakers") or [],
        source_chars=existing.get("source_chars") or 0,
        complete=existing.get("complete") if "complete" in existing else None,
        generated_from=existing.get("generated_from") or "unknown",
    )


async def generate_meeting_summary(
    supabase: Client,
    meeting_id: str,
    *,
    refresh_partial: bool = False,
    agendas_override: list[dict] | None = None,
    count_daily: bool = True,
    replace_live: bool = False,
) -> MeetingSummary:
    """회의 자막을 분석하여 AI 요약을 생성합니다.

    1. 캐시(meeting_summaries) 가 있으면 그대로 반환 — 회의당 1회. refresh_partial=True 이고 그 행이
       앞부분만 본 옛 요약(complete=false)이면 다시 만든다.
    2. 자막 전량 조회(1000행 페이지, subtitle_fetch) → live+ai 혼재 시 AI 자막만
    3. 안건 목록 조회(있으면)
    4. 자막이 MAX_TRANSCRIPT_CHARS 이하면 단일 호출, 넘으면 청크 요약 → 병합(맵리듀스)
    5. 저장 성공을 확인한 뒤 반환(회의별 락으로 동시 생성 방지)

    count_daily=False: 하루 상한(ai_summary_daily_limit)을 깎지 않는다 — 요약 미리 만들기(summary_pregen)가 자기 장부로 센다.
    replace_live=True: 캐시가 실시간 자막으로 만든 요약(generated_from=live)이면 AI 자막으로 다시 만든다.

    Raises:
        ValueError: 자막이 없거나 API 키 미설정
        SummaryLimitError: 하루 생성 상한
        SummaryGenerationError: 호출·파싱·저장 실패(캐시에 남기지 않는다)
    """
    def _reusable(row: dict | None) -> bool:
        if not row:
            return False
        if refresh_partial and row.get("complete") is False:
            return False
        if replace_live and row.get("generated_from") == "live":
            return False
        return True

    existing = await get_summary(supabase, meeting_id)
    if _reusable(existing):
        return _row_to_summary(existing)

    lock = _locks.setdefault(meeting_id, asyncio.Lock())
    async with lock:
        existing = await get_summary(supabase, meeting_id)  # 락을 기다리는 동안 남이 만들었을 수 있다
        if _reusable(existing):
            return _row_to_summary(existing)

        # 1. 자막 전량(시간순). live+ai 혼재 시 AI 자막만 사용(중복 발언이 요약을 오염).
        rows = await asyncio.to_thread(fetch_all_subtitles, supabase, meeting_id, "*")
        subtitles = prefer_ai_subtitles(rows or [])
        if not subtitles:
            raise ValueError(f"회의 {meeting_id}에 자막이 없습니다.")
        generated_from = "live" if all(s.get("kind") == "live" for s in subtitles) else "ai"

        # 2. 안건 조회 (테이블이 없을 수 있으므로 try/except). 안건 초안이 방금 추출해 아직 저장 전인 목록은 인자로 받는다
        agendas: list[dict] | None = list(agendas_override) if agendas_override else None
        try:
            if agendas is not None:
                raise StopIteration  # 아래 except 로 — DB 조회 생략
            agenda_resp = (
                supabase.table("meeting_agendas")
                .select("*")
                .eq("meeting_id", meeting_id)
                .order("order_num")
                .execute()
            )
            if agenda_resp.data:
                agendas = agenda_resp.data
        except StopIteration:
            pass
        except Exception:
            logger.debug("meeting_agendas 테이블 조회 실패 (테이블 미존재 가능)")

        # 3. 전량 텍스트 — 단일 호출 여부 판정(여기서 자르지 않는다)
        transcript_text = _format_subtitles_for_prompt(subtitles, agendas, truncate=False)
        source_chars = len(transcript_text)

        # 4. 생성 — 실제 호출 직전에 하루 상한 차감
        if count_daily:
            reserve_generation_slot()
        if source_chars <= settings.summary_single_call_max_chars:
            summary = await _call_openai_summary(transcript_text, agendas)
        else:
            summary = await _summarize_long(subtitles, agendas)
        summary.source_chars = source_chars
        summary.complete = True
        summary.generated_from = generated_from

        # 5. 저장 — 성공을 확인한다. 034 이전 DB(PGRST204) 면 새 컬럼 없이 1회 재시도.
        payload = {
            "meeting_id": meeting_id,
            "summary_text": summary.summary_text,
            "agenda_summaries": summary.agenda_summaries,
            "key_decisions": summary.key_decisions,
            "action_items": summary.action_items,
            "model_used": summary.model_used,
        }
        extra = {
            "segments": summary.segments,
            "speakers": summary.speakers,
            "source_chars": summary.source_chars,
            "complete": True,
            "generated_from": generated_from,
        }
        try:
            _upsert_summary(supabase, {**payload, **extra})
        except Exception as e:
            if "PGRST204" in str(e) or "column" in str(e).lower():
                logger.warning("meeting_summaries 새 컬럼 없음(034 미적용) — 기본 컬럼만 저장: %s", e)
                try:
                    _upsert_summary(supabase, payload)
                except Exception as e2:
                    raise SummaryGenerationError("요약을 저장하지 못했습니다.") from e2
            else:
                logger.error("요약 저장 실패: %s", e)
                raise SummaryGenerationError("요약을 저장하지 못했습니다.") from e
        return summary


def _upsert_summary(supabase: Client, payload: dict) -> None:
    supabase.table("meeting_summaries").upsert(payload, on_conflict="meeting_id").execute()


async def get_summary(
    supabase: Client,
    meeting_id: str,
) -> dict | None:
    """저장된 요약을 조회합니다.

    Args:
        supabase: Supabase 클라이언트
        meeting_id: 회의 ID

    Returns:
        요약 dict 또는 None (없으면)
    """
    resp = (
        supabase.table("meeting_summaries")
        .select("*")
        .eq("meeting_id", meeting_id)
        .execute()
    )
    if resp.data:
        return resp.data[0]
    return None


async def delete_summary(
    supabase: Client,
    meeting_id: str,
) -> bool:
    """요약을 삭제합니다 (재생성용).

    Args:
        supabase: Supabase 클라이언트
        meeting_id: 회의 ID

    Returns:
        삭제 성공 여부
    """
    try:
        supabase.table("meeting_summaries").delete().eq(
            "meeting_id", meeting_id
        ).execute()
        return True
    except Exception as e:
        logger.error("요약 삭제 실패: %s", e)
        return False
