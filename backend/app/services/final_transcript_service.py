"""AI 회의록 최종본 생성 파이프라인.

VOD 고품질 재전사(진실원천) → 글로서리/실시간 자막 힌트 → LLM 교정 → 화자 실명 →
stenography_records(kind='ai_final') 라인 생성.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FinalTaskStatus:
    meeting_id: str
    status: str = "pending"  # pending | running | completed | failed
    progress: float = 0.0
    message: str = ""
    error: str | None = None
    record_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


_final_tasks: dict[str, FinalTaskStatus] = {}


def set_final_task(meeting_id: str, task: FinalTaskStatus) -> None:
    _final_tasks[meeting_id] = task


def get_final_task(meeting_id: str) -> FinalTaskStatus | None:
    return _final_tasks.get(meeting_id)


def is_generating(meeting_id: str) -> bool:
    t = _final_tasks.get(meeting_id)
    return t is not None and t.status in ("pending", "running")

_CORRECTION_SYSTEM = (
    "당신은 한국 지방의회 회의록 교정 전문가입니다. "
    "주어진 STT 세그먼트의 텍스트만 교정하세요: 의회 전문용어, 의원명, 숫자(한글→아라비아), "
    "띄어쓰기, 맞춤법, 문장 종결. 의미를 바꾸거나 내용을 추가/삭제하지 마세요. "
    'JSON으로만 답하세요: {"segments":[{"index":번호,"text":"교정문"}, ...]}'
)


async def correct_segments_with_llm(
    *,
    client: Any,
    segments: list[dict],
    glossary_prompt: str,
    hint_texts: list[str],
    model: str,
) -> list[dict]:
    """세그먼트 텍스트를 LLM으로 교정. 메타(speaker/시간)는 보존. 실패 시 원본 유지."""
    if not segments:
        return []

    numbered = [{"index": i, "text": s.get("text", "")} for i, s in enumerate(segments)]
    hint_block = (
        ("\n참고(실시간 자막, 교차검증용): " + " / ".join(hint_texts[:30])) if hint_texts else ""
    )
    user_content = (
        (glossary_prompt + "\n\n" if glossary_prompt else "")
        + "다음 세그먼트를 교정하세요:\n"
        + json.dumps(numbered, ensure_ascii=False)
        + hint_block
    )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _CORRECTION_SYSTEM},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
        parsed = json.loads(content)
        corrections = {item["index"]: item["text"] for item in parsed.get("segments", [])}
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as e:
        logger.warning("LLM 교정 파싱 실패, 원본 유지: %s", e)
        corrections = {}

    result = []
    for i, seg in enumerate(segments):
        new_seg = dict(seg)
        if i in corrections and corrections[i].strip():
            new_seg["text"] = corrections[i].strip()
        result.append(new_seg)
    return result


def persist_final_lines(
    supabase: Any,
    meeting_id: str,
    segments: list[dict],
    *,
    source_meta: dict | None = None,
) -> str:
    """교정 세그먼트를 ai_final stenography 레코드 + 라인으로 저장. record_id 반환."""
    existing = (
        supabase.table("stenography_records")
        .select("id")
        .eq("meeting_id", meeting_id)
        .eq("kind", "ai_final")
        .limit(1)
        .execute()
        .data
    )

    content_snapshot = "\n".join(s.get("text", "") for s in segments)

    if existing:
        record_id = existing[0]["id"]
        supabase.table("stenography_records").update(
            {"content": content_snapshot, "source_meta": source_meta}
        ).eq("id", record_id).execute()
        supabase.table("stenography_lines").delete().eq("record_id", record_id).execute()
    else:
        rec = (
            supabase.table("stenography_records")
            .insert(
                {
                    "meeting_id": meeting_id,
                    "kind": "ai_final",
                    "content": content_snapshot,
                    "stenographer_name": "AI 자동생성",
                    "status": "draft",
                    "source_meta": source_meta,
                }
            )
            .execute()
            .data
        )
        record_id = rec[0]["id"]

    lines = []
    for i, seg in enumerate(segments):
        lines.append(
            {
                "record_id": record_id,
                "sequence_no": i,
                "text": seg.get("text", ""),
                "speaker": seg.get("speaker"),
                "start_ms": int(round((seg.get("start_time") or 0) * 1000)),
                "end_ms": int(round((seg.get("end_time") or 0) * 1000)),
                "starts_new_paragraph": (
                    i == 0 or seg.get("speaker") != segments[i - 1].get("speaker")
                ),
            }
        )
    if lines:
        supabase.table("stenography_lines").insert(lines).execute()
    return record_id


# ============================================================================
# 오케스트레이터
# ============================================================================


from app.core.config import settings  # noqa: E402
from app.services.glossary_service import load_meeting_glossary, format_glossary_prompt  # noqa: E402


def _make_openai_client():
    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=settings.openai_api_key)


async def _retranscribe_vod(meeting_id: str, vod_url: str, task: "FinalTaskStatus") -> list[dict]:
    """VodSttService 재사용: VOD를 고품질 재전사하여 세그먼트 리스트 반환(DB 저장 X)."""
    from app.services.vod_stt_service import VodSttService, SttTaskStatus as _S

    svc = VodSttService()
    inner = _S(task_id=f"final-{meeting_id}", meeting_id=meeting_id)
    mp4_path = await svc._download_to_file(vod_url, inner)
    try:
        subtitles, _dur = await svc._transcribe_openai(meeting_id, mp4_path, inner)
    finally:
        try:
            os.remove(mp4_path)
        except OSError:
            pass
    return subtitles


def _chunk(seq: list, size: int) -> list[list]:
    return [seq[i : i + size] for i in range(0, len(seq), size)]


async def generate_final_transcript(supabase: Any, meeting_id: str, *, precise_mode: bool = False) -> None:
    """최종본 생성 파이프라인. 진행상태를 _final_tasks에 기록."""
    task = FinalTaskStatus(meeting_id=meeting_id, status="running", message="회의 정보 확인 중")
    set_final_task(meeting_id, task)
    try:
        rows = (
            supabase.table("meetings").select("id, vod_url").eq("id", meeting_id).limit(1).execute().data
        )
        if not rows or not rows[0].get("vod_url"):
            raise ValueError("VOD URL이 없는 회의입니다.")
        vod_url = rows[0]["vod_url"]

        task.message, task.progress = "VOD 재전사 중", 0.1
        segments = await _retranscribe_vod(meeting_id, vod_url, task)

        task.message, task.progress = "글로서리 구성 중", 0.6
        glossary = load_meeting_glossary(supabase, meeting_id)
        glossary_prompt = format_glossary_prompt(glossary)

        hint_rows = (
            supabase.table("subtitles").select("text").eq("meeting_id", meeting_id).order("start_time").execute().data
            or []
        )
        hint_texts = [r.get("text", "") for r in hint_rows if r.get("text")]

        task.message, task.progress = "AI 교정 중", 0.7
        client = _make_openai_client()
        chunks = _chunk(segments, 20)
        corrected_chunks = await asyncio.gather(
            *[
                correct_segments_with_llm(
                    client=client,
                    segments=c,
                    glossary_prompt=glossary_prompt,
                    hint_texts=hint_texts,
                    model=settings.final_transcript_model,
                )
                for c in chunks
            ]
        )
        corrected = [seg for chunk in corrected_chunks for seg in chunk]

        task.message, task.progress = "최종본 저장 중", 0.95
        record_id = persist_final_lines(
            supabase,
            meeting_id,
            corrected,
            source_meta={"model": settings.final_transcript_model, "precise_mode": precise_mode},
        )

        task.status, task.progress, task.message, task.record_id = "completed", 1.0, "완료", record_id
    except Exception as e:  # noqa: BLE001
        logger.exception("최종본 생성 실패: %s", meeting_id)
        task.status, task.error, task.message = "failed", str(e), "실패"
