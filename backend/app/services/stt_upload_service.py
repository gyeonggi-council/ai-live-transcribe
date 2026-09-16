"""업로드 STT 파이프라인 서비스 — 브라우저 직접 업로드 파일의 자막 생성

api/meetings.py 의 upload-stt / upload-audio-stt 인라인 파이프라인 이관.

※ 이관과 함께 수리됨: 기존 코드는 Phase 12에서 제거된
   VodSttService._send_to_deepgram / _parse_deepgram_response 를 호출해
   런타임 AttributeError 로 죽는 상태였다. 현행 OpenAI 배치 전사 경로
   (_transcribe_openai: ffmpeg 청크 분할 + gpt-4o-transcribe-diarize)로 교체.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from supabase import Client

from app.repositories.meeting_repository import MeetingRepository
from app.repositories.subtitle_repository import SubtitleRepository
from app.services.dictionary import get_default_dictionary
from app.services.vod_stt_service import SttTaskStatus, VodSttService, _tasks

logger = logging.getLogger(__name__)


async def apply_grammar_background(
    supabase: Client, meeting_id: str, log_label: str
) -> None:
    """STT 완료 후 AI 문법 교정을 백그라운드로 적용한다 (실패 무시).

    upload-stt / upload-audio-stt 에 복붙되어 있던 동일 클로저의 단일화.
    """
    try:
        from app.services.grammar_checker import check_grammar_batch

        repo = SubtitleRepository(supabase)
        subs = repo.list_id_text(meeting_id) or []
        issues = await check_grammar_batch(subs)
        for issue in issues:
            try:
                repo.update(issue.subtitle_id, {
                    "text": issue.corrected_text,
                    "original_text": issue.original_text,
                    "is_corrected": True,
                    "correction_state": "corrected",
                })
            except Exception:
                pass
    except Exception as e:
        logger.exception("%s grammar failed: %s", log_label, e)


async def run_upload_stt_pipeline(
    supabase: Client,
    meeting_id: str,
    tmp_path: Path,
    total_bytes: int,
    content_type: str | None = None,
) -> dict:
    """업로드된 미디어 파일로 STT 파이프라인을 실행한다.

    content_type=None 이면 기존 upload-stt(MP4) 경로, 지정되면 upload-audio-stt 경로.
    - 태스크 등록 → OpenAI 배치 전사 → safe-delete(성공 확인 후 삭제+삽입)
    - meetings.subtitle_stage='ai' 승격 → AI 문법 교정 백그라운드
    - 오디오 경로에서 자막 0건이면 ValueError (라우터에서 422 매핑)
    """
    label = "upload-audio-stt" if content_type else "upload-stt"
    size_note = (
        f"{total_bytes / (1024*1024):.0f} MB, {content_type}"
        if content_type
        else f"{total_bytes / (1024*1024):.0f} MB"
    )

    task = SttTaskStatus(
        task_id=str(uuid.uuid4()),
        meeting_id=meeting_id,
        status="running",
        progress=0.2,
        message=f"업로드 완료 ({size_note}) — OpenAI 전사 중",
    )
    _tasks[meeting_id] = task

    service = VodSttService()
    dictionary = get_default_dictionary()
    domain_prompt = VodSttService._build_domain_prompt(supabase, meeting_id)
    all_subtitles, duration = await service._transcribe_openai(
        meeting_id, tmp_path, task, dictionary, domain_prompt=domain_prompt
    )

    task.progress = 0.92
    task.message = "자막 데이터 변환 중"

    subtitle_repo = SubtitleRepository(supabase)

    # safe-delete: STT 성공 확인 후에만 기존 AI 자막 삭제.
    # 실시간 자막(kind='live')은 초안으로 보존한다.
    if all_subtitles:
        subtitle_repo.delete_by_meeting(meeting_id, kind="ai")
        task.message = "기존 AI 자막 교체 중"
        await VodSttService._insert_subtitles(supabase, all_subtitles)
        task.progress = 0.95
    elif content_type:
        raise ValueError("STT가 자막을 추출하지 못했습니다. 오디오 품질을 확인해주세요.")

    # meeting 상태 업데이트 — subtitle_stage='ai'로 승격
    MeetingRepository(supabase).update(meeting_id, {
        "status": "ended",
        "subtitle_stage": "ai",
        "duration_seconds": int(duration) if duration else None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })

    task.status = "completed"
    task.progress = 1.0
    task.message = f"완료 — {len(all_subtitles)}개 자막 생성"

    # AI 문법 교정은 백그라운드 (응답 지연 방지)
    asyncio.create_task(apply_grammar_background(supabase, meeting_id, label))

    response = {
        "meeting_id": meeting_id,
        "status": "completed",
        "subtitles_count": len(all_subtitles),
        "uploaded_mb": round(total_bytes / (1024 * 1024), 1),
        "duration_seconds": int(duration) if duration else None,
        "message": f"자막 {len(all_subtitles)}개 생성 완료 (AI 교정 진행 중)",
    }
    if content_type:
        response["subtitle_stage"] = "ai"
        response["content_type"] = content_type
    return response


def mark_upload_task_failed(meeting_id: str, error: str) -> None:
    """파이프라인 실패 시 태스크 상태를 failed로 표기한다 (라우터 except 절에서 호출)."""
    task = _tasks.get(meeting_id)
    if task:
        task.status = "failed"
        task.error = error
