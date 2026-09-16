"""Speakers API 라우터 - 화자별 발언 타임라인 + 영상 클립 추출 + AI 화자 제안

자막 데이터를 화자별로 그룹핑하여 발언 시간 통계와 구간 목록을 반환합니다.
AI를 사용하여 화자 라벨("화자 1")에서 실제 이름을 추출합니다.

# @TASK P11-T1.1 - 발언 영상 클립 추출 API
"""

import asyncio
import json
import logging
import math
import shutil
import tempfile
import time
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, StreamingResponse
from supabase import Client

from app.core.auth_middleware import require_role
from app.core.channels import get_committee_for_channel
from app.core.config import settings
from app.core.database import get_supabase
from app.services import clip_service
from app.services.councilor_sync import CouncilorSyncService
from app.services.kms_vod_resolver import is_allowed_vod_source
from app.services.speaker_segments import build_speaker_segments
from app.services.subtitle_select import prefer_ai_subtitles

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meetings", tags=["speakers"])


@router.get(
    "/{meeting_id}/speakers",
    summary="화자별 발언 타임라인 조회",
)
async def get_speakers_timeline(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
) -> dict:
    """회의의 자막을 화자별로 그룹핑하여 발언 타임라인을 반환합니다.

    각 화자의 총 발언 시간, 발언 횟수, 개별 발언 구간을 제공합니다.
    """
    result = (
        supabase.table("subtitles")
        .select("id, start_time, end_time, text, speaker, confidence, kind")
        .eq("meeting_id", meeting_id)
        .order("start_time")
        .execute()
    )

    # live+ai 혼재 시 AI 자막만(화자 있는) 사용 — '미확인' 화자 부풀림 방지.
    subtitles = prefer_ai_subtitles(result.data or [])

    if not subtitles:
        return {"speakers": [], "total_duration": 0}

    # 화자별 그룹핑
    speakers_map: dict[str, dict] = {}

    for sub in subtitles:
        speaker = sub.get("speaker") or "(미지정)"
        if speaker not in speakers_map:
            speakers_map[speaker] = {
                "speaker": speaker,
                "total_time": 0.0,
                "segment_count": 0,
                "segments": [],
            }

        start = sub.get("start_time", 0)
        end = sub.get("end_time", 0)
        duration = max(0, end - start)

        speakers_map[speaker]["total_time"] += duration
        speakers_map[speaker]["segment_count"] += 1
        speakers_map[speaker]["segments"].append({
            "id": sub["id"],
            "start_time": start,
            "end_time": end,
            "text": sub.get("text", ""),
            "confidence": sub.get("confidence"),
        })

    # 총 발언 시간 순으로 정렬 (많이 발언한 화자가 위)
    speakers_list = sorted(
        speakers_map.values(),
        key=lambda s: s["total_time"],
        reverse=True,
    )

    # 전체 회의 길이 계산
    total_duration = 0.0
    if subtitles:
        total_duration = max(sub.get("end_time", 0) for sub in subtitles)

    return {
        "speakers": speakers_list,
        "total_duration": total_duration,
    }


# =============================================================================
# GET /{meeting_id}/speakers/segments - 화자별 연속 발언구간 조회
# =============================================================================


@router.get(
    "/{meeting_id}/speakers/segments",
    summary="화자별 연속 발언구간 조회",
)
async def get_speaker_segments(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
) -> dict:
    """회의 자막을 화자별 연속 발언구간으로 병합하여 반환합니다.

    발언영상 추출 기능의 데이터 원천 — 강제 분할 없이 연속 발언 전체를
    하나의 구간으로 유지합니다. (공개 API, 기존 GET /speakers와 동일 정책)
    """
    result = (
        supabase.table("meetings")
        .select("id, title, kms_midx")
        .eq("id", meeting_id)
        .limit(1)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting {meeting_id}을(를) 찾을 수 없습니다.",
        )

    # 동기 Supabase 페이지네이션(수천 행)이 이벤트 루프를 블로킹하지 않도록
    # 워커 스레드로 격리 (라이브 WS/SSE 지연 방지).
    return await asyncio.to_thread(build_speaker_segments, supabase, result.data[0])


# =============================================================================
# POST /{meeting_id}/speakers/suggest - AI 화자 이름 제안
# =============================================================================


@router.post(
    "/{meeting_id}/speakers/suggest",
    summary="AI 화자 이름 제안",
)
async def suggest_speaker_names(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
) -> dict:
    """AI를 사용하여 자막에서 화자의 실제 이름과 직책을 추출합니다.

    전략적 샘플링(시작 30 + 중간 40 + 끝 30)으로 100개 자막을 분석하고,
    위원회 소속 의원 목록을 GPT 프롬프트에 포함하여 정확도를 높입니다.
    """
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenAI API 키가 설정되지 않았습니다.",
        )

    # 전략적 자막 샘플링: 시작(30) + 중간(40) + 끝(30) = 최대 100개
    first_30 = (
        supabase.table("subtitles")
        .select("id, text, speaker, start_time")
        .eq("meeting_id", meeting_id)
        .order("start_time")
        .limit(30)
        .execute()
    )

    if not first_30.data:
        return {"suggestions": []}

    # 총 자막 수 조회
    total_result = (
        supabase.table("subtitles")
        .select("id", count="exact")
        .eq("meeting_id", meeting_id)
        .execute()
    )
    total_count = total_result.count or len(first_30.data)

    all_subtitles = list(first_30.data)
    seen_ids = {s["id"] for s in all_subtitles}

    if total_count > 60:
        # 중간 40개
        mid_offset = max(0, total_count // 2 - 20)
        middle_40 = (
            supabase.table("subtitles")
            .select("id, text, speaker, start_time")
            .eq("meeting_id", meeting_id)
            .order("start_time")
            .range(mid_offset, mid_offset + 39)
            .execute()
        )
        for s in (middle_40.data or []):
            if s["id"] not in seen_ids:
                all_subtitles.append(s)
                seen_ids.add(s["id"])

    if total_count > 30:
        # 끝 30개
        last_30 = (
            supabase.table("subtitles")
            .select("id, text, speaker, start_time")
            .eq("meeting_id", meeting_id)
            .order("start_time", desc=True)
            .limit(30)
            .execute()
        )
        for s in (last_30.data or []):
            if s["id"] not in seen_ids:
                all_subtitles.append(s)
                seen_ids.add(s["id"])

    # start_time 순 정렬
    all_subtitles.sort(key=lambda s: s.get("start_time", 0))

    # 고유 화자 라벨 수집
    speaker_labels = sorted({
        s["speaker"] for s in all_subtitles
        if s.get("speaker") and s["speaker"].startswith("화자")
    })

    if not speaker_labels:
        return {"suggestions": []}

    # 자막 텍스트 구성
    transcript_lines = []
    for s in all_subtitles:
        speaker = s.get("speaker") or "(미지정)"
        transcript_lines.append(f"[{speaker}] {s['text']}")
    transcript_text = "\n".join(transcript_lines)

    # 회의의 위원회 정보 조회
    committee_name = None
    councilor_names_str = ""
    try:
        meeting_result = (
            supabase.table("meetings")
            .select("committee")
            .eq("id", meeting_id)
            .limit(1)
            .execute()
        )
        if meeting_result.data:
            committee_name = meeting_result.data[0].get("committee")

        # 채널 ID인 경우 채널에서 위원회 정보 조회
        if not committee_name:
            committee_name = get_committee_for_channel(meeting_id)

        # 위원회 소속 의원 목록 조회
        if committee_name:
            try:
                councilor_svc = CouncilorSyncService(supabase)
                committee_councilors = councilor_svc.get_by_committee(committee_name)
                if committee_councilors:
                    councilor_names_str = ", ".join(c["name"] for c in committee_councilors)
            except Exception as e:
                logger.warning("위원회 의원 목록 조회 실패: %s", e)
    except Exception as e:
        logger.warning("회의 정보 조회 실패: %s", e)

    # 강화된 GPT 프롬프트
    committee_ctx = f" {committee_name}" if committee_name else ""
    councilor_ctx = f"\n\n## 해당 위원회 소속 의원 (참고)\n{councilor_names_str}" if councilor_names_str else ""

    prompt = f"""경기도의회{committee_ctx} 상임위원회 회의 자막에서 화자를 식별하세요.

## 회의 구조 (상임위 — 매우 중요)
- **위원장**은 회의를 처음부터 끝까지 진행하며 가장 자주 등장(개의/산회, 다음 질의자 호명, 화자 전환).
- **위원**은 위원장이 호명한 순서대로 질의하며, 각 위원은 보통 최대 2번만 발언한다.
- 위원 질의 중에는 **집행부 실·국장(공무원)**과 주고받는다. 동시에 말하는 사람은 최대 2명.
- 즉 한 구간의 화자는 보통 {{위원장, 현재 질의 위원, 집행부 답변자}} 중 2~3명뿐이다.

## 식별 패턴
1. **호명**: "XX 위원님 질의하시기 바랍니다" → 다음 화자가 XX 위원
2. **자기소개**: "XX 위원입니다" → 해당 화자가 XX
3. **위원장 패턴**: 회의 진행/호명/개의·산회 선언 → 위원장
4. **집행부 패턴**: "답변 드리겠습니다", "XX국장", "XX실장" → 집행부 공무원(의원 아님). name은 직책(예: "보건복지국장")으로.
5. **이전 화자 참조**: "방금 XX 위원님 말씀처럼" → XX는 직전 화자{councilor_ctx}

## 규칙
- 위원 이름은 위 "소속 의원" 명부에 있는 이름만 사용(없으면 name=null).
- 공무원은 명부에 없으므로 직책을 name으로, role="집행부".
- 가장 자주 진행/호명하는 화자를 위원장으로 추정.

대상 화자 라벨: {', '.join(speaker_labels)}

자막:
{transcript_text}

반드시 아래 JSON 형식으로만 응답하세요:
{{"suggestions": [{{"speaker_label": "화자 1", "name": "이름 또는 null", "role": "위원장|위원|집행부 또는 null", "confidence": "high|medium|low", "evidence": "근거 자막 발췌 또는 null"}}]}}"""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.openai_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_completion_tokens": 1000,
                },
            )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"OpenAI API 오류 (HTTP {response.status_code})",
            )

        content = response.json()["choices"][0]["message"]["content"]
        # JSON 추출 (마크다운 코드블록 처리)
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        parsed = json.loads(content.strip())

        # 의원 DB 교차 매칭: 정확 매칭 + 위원회 명부 퍼지 매칭(STT 오인식 보정)
        from difflib import SequenceMatcher

        suggestions = parsed.get("suggestions", [])
        councilor_svc = CouncilorSyncService(supabase)

        # 위원회 명부(퍼지 매칭 대상)
        roster: list[dict] = []
        if committee_name:
            try:
                roster = councilor_svc.get_by_committee(committee_name)
            except Exception:
                roster = []
        roster_named = [(c.get("name") or "", c) for c in roster if c.get("name")]

        suggested_names = [s["name"] for s in suggestions if s.get("name") and s["name"] != "null"]
        exact_map: dict[str, dict] = {}
        if suggested_names:
            try:
                exact_map = {c["name"]: c for c in councilor_svc.get_by_names(suggested_names)}
            except Exception as e:
                logger.warning("의원 DB 교차 매칭 실패: %s", e)

        def _fuzzy(name: str) -> dict | None:
            n = name.replace(" ", "")
            best, best_r = None, 0.6
            for rn, c in roster_named:
                r = SequenceMatcher(None, n, rn.replace(" ", "")).ratio()
                if r > best_r:
                    best_r, best = r, c
            return best

        for suggestion in suggestions:
            name = suggestion.get("name")
            role = suggestion.get("role") or ""
            # 집행부(공무원)는 명부에 없으므로 직책 라벨 유지
            if not name or name == "null" or "집행부" in role or "공무원" in role:
                suggestion["councilor"] = None
                continue
            matched = exact_map.get(name) or _fuzzy(name)
            if matched:
                suggestion["councilor"] = matched
                suggestion["name"] = matched.get("name")  # 명부 정식 표기로 정규화
            else:
                suggestion["councilor"] = None

        return parsed

    except json.JSONDecodeError:
        logger.warning("AI 화자 제안 JSON 파싱 실패: %s", content[:200] if 'content' in dir() else "N/A")
        return {"suggestions": [], "error": "AI 응답 파싱 실패"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("AI 화자 제안 실패: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI 화자 제안 처리 실패: {str(e)}",
        )


# =============================================================================
# POST /{meeting_id}/speakers/merge - 화자 병합
# =============================================================================


@router.post(
    "/{meeting_id}/speakers/merge",
    summary="화자 병합",
)
async def merge_speakers(
    meeting_id: str,
    body: dict = Body(...),
    supabase: Client = Depends(get_supabase),
) -> dict:
    """source 화자의 모든 자막을 target 화자로 통합합니다."""
    source = body.get("source")
    target = body.get("target")

    if not source or not target:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source와 target 화자를 모두 지정해야 합니다.",
        )

    if source == target:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source와 target이 같을 수 없습니다.",
        )

    result = (
        supabase.table("subtitles")
        .update({"speaker": target})
        .eq("meeting_id", meeting_id)
        .eq("speaker", source)
        .execute()
    )

    updated_count = len(result.data) if result.data else 0
    logger.info(
        "Merged speaker '%s' into '%s' for meeting %s (%d subtitles)",
        source, target, meeting_id, updated_count,
    )

    return {"merged": source, "into": target, "updated": updated_count}


# =============================================================================
# GET /{meeting_id}/speakers/clip - 발언 영상 클립 추출
# @TASK P11-T1.1 - 발언 영상 클립 추출 API
# @TASK B2-clip - ffmpeg URL-seek 재작성 + 인증 필수화
# =============================================================================


def _check_ffmpeg_available() -> bool:
    """ffmpeg 바이너리가 사용 가능한지 확인합니다."""
    return shutil.which("ffmpeg") is not None


@router.get(
    "/{meeting_id}/speakers/clip",
    summary="발언 영상 클립 추출",
)
async def get_speaker_clip(
    meeting_id: str,
    start: float = Query(..., ge=0, description="시작 시간 (초)"),
    end: float = Query(..., gt=0, description="종료 시간 (초)"),
    user: dict = Depends(require_role(
        "staff", "committee_staff", "meeting_manager", "stenographer", "admin"
    )),
    supabase: Client = Depends(get_supabase),
):
    """회의 VOD에서 특정 구간의 영상 클립을 추출합니다 (로그인 필수).

    전체 VOD 선다운로드 없이 ffmpeg URL-seek(-ss 가 -i 앞 = 입력 시킹)로
    필요한 바이트만 받아 추출 시간 ≈ 구간 길이. StreamingResponse로 MP4 반환.
    """
    # Layer 1: ffmpeg 가용성 확인
    if not _check_ffmpeg_available():
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="ffmpeg가 설치되어 있지 않습니다. 서버에 ffmpeg를 설치해주세요.",
        )

    # Layer 2: 시간 범위 검증
    if end <= start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end 시간은 start 시간보다 커야 합니다.",
        )

    # Layer 3: 구간 길이 상한 (KMS 스로틀 하에서 추출 시간 ≈ 구간 길이)
    if end - start > settings.clip_max_seconds:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"구간 길이가 상한({settings.clip_max_seconds}초)을 초과합니다. "
                "긴 구간은 나눠서 요청해주세요."
            ),
        )

    # Layer 4: meeting 조회 + vod_url 확인
    try:
        result = (
            supabase.table("meetings")
            .select("id, vod_url, title, kms_midx")
            .eq("id", meeting_id)
            .limit(1)
            .execute()
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting {meeting_id}을(를) 찾을 수 없습니다.",
        )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting {meeting_id}을(를) 찾을 수 없습니다.",
        )

    meeting = result.data[0]
    vod_url = meeting.get("vod_url")
    if not vod_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="VOD URL이 없는 회의입니다.",
        )

    # Layer 5: VOD 소스 화이트리스트 (SSRF 방지) — admin 은 예외 허용
    if not is_allowed_vod_source(vod_url) and user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="허용되지 않은 VOD 소스입니다. (kms.ggc.go.kr만 허용)",
        )

    # Layer 6: ffmpeg URL-seek 구간 추출 (임시 디렉토리)
    tmp_dir = tempfile.mkdtemp(prefix="clip_")
    output_path = Path(tmp_dir) / "clip.mp4"

    try:
        await clip_service.extract_clip_mp4(vod_url, start, end, output_path)
    except asyncio.CancelledError:
        # 클라이언트 취소/서버 종료 — clip_service 가 ffmpeg kill 을 마쳤으므로
        # 임시디렉토리만 정리하고 취소를 그대로 전파한다.
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        # stderr(URL·경로 등 내부 정보)는 서버 로그로만 — 응답 detail 유출 금지.
        logger.error("클립 추출 실패: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="클립 추출에 실패했습니다. 잠시 후 다시 시도해 주세요.",
        )

    # StreamingResponse로 반환 + 전송 후 임시파일 정리
    def _iter_file():
        try:
            with open(output_path, "rb") as f:
                while chunk := f.read(64 * 1024):
                    yield chunk
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    filename = clip_service.build_clip_filename(
        meeting.get("kms_midx"), meeting_id, start, end
    )

    return StreamingResponse(
        _iter_file(),
        media_type="video/mp4",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


# =============================================================================
# 병합 클립 백그라운드 잡 — 여러 발언 구간 → 하나의 mp4
# @TASK B3-clip-jobs - KMS 스로틀로 추출이 실시간 배속 → 동기 응답 불가, 잡 처리
# =============================================================================

# clip 과 동일한 인가 역할 (로그인 5역할)
_CLIP_ROLES = ("staff", "committee_staff", "meeting_manager", "stenographer", "admin")

# 완료(성공/실패) 후 임시파일 보존 시간 — 초과분은 새 잡 생성 시 lazy 정리
_CLIP_JOB_TTL_SECONDS = 3600.0

# 미완료(queued/running) 잡 동시 상한 — 잡당 임시파일 ~0.8GB + KMS 스로틀 순차
# 추출이라, 상한 없이는 디스크/회선이 고갈된다. 초과 시 429.
_CLIP_JOB_MAX_ACTIVE = 2

# 프로세스 재시작으로 _clip_jobs 에서 고아가 된 clipjob_* 임시디렉토리 정리 기준
_CLIP_JOB_ORPHAN_MAX_AGE_SECONDS = 24 * 3600.0

# 인메모리 잡 저장소 (meetings._stt_batch 패턴) — 프로세스 재시작 시 소멸
_clip_jobs: dict[str, dict] = {}

# 미지의 job_id 404 안내 — 인메모리 잡은 서버 재시작 시 소멸하므로 원인/행동 안내
_CLIP_JOB_EXPIRED_DETAIL = "서버 재시작으로 작업이 만료되었습니다. 다시 시도해 주세요."


def _cleanup_expired_clip_jobs() -> None:
    """완료 후 1시간 지난 잡의 임시디렉토리와 엔트리를 정리합니다.

    별도 스케줄러 없이 새 잡 생성 시점에 호출하는 lazy 방식으로 충분하다.
    시간 기준은 time.monotonic (시스템 시계 변경에 영향받지 않음).
    """
    now = time.monotonic()
    for job_id, job in list(_clip_jobs.items()):
        finished_at = job.get("finished_at")
        if finished_at is None or now - finished_at <= _CLIP_JOB_TTL_SECONDS:
            continue
        shutil.rmtree(job["tmp_dir"], ignore_errors=True)
        _clip_jobs.pop(job_id, None)


def _cleanup_orphan_clip_tmpdirs() -> None:
    """프로세스 재시작으로 _clip_jobs 추적이 끊긴 clipjob_* 임시디렉토리를 정리합니다.

    잡당 임시파일이 ~0.8GB 라 방치하면 디스크가 고갈된다. 수정시각 24시간 초과 +
    현재 잡 소유가 아닌 디렉토리만 삭제 (새 잡 생성 시 lazy 호출, fail-soft).
    """
    try:
        owned = {job.get("tmp_dir") for job in _clip_jobs.values()}
        now = time.time()
        for entry in Path(tempfile.gettempdir()).glob("clipjob_*"):
            try:
                if str(entry) in owned or not entry.is_dir():
                    continue
                if now - entry.stat().st_mtime > _CLIP_JOB_ORPHAN_MAX_AGE_SECONDS:
                    shutil.rmtree(entry, ignore_errors=True)
            except OSError:
                continue
    except Exception as e:
        logger.debug("고아 clipjob 임시디렉토리 정리 실패(무시): %s", e)


async def _run_clip_job(job_id: str) -> None:
    """잡 실행: 세그먼트 순차 추출(진행률 갱신) → concat 병합 → done.

    KMS 연결당 스로틀 때문에 세그먼트는 순차로만 추출한다 (병렬 금지).
    progress 는 세그먼트당 1/(N+1)씩 오르고 마지막 concat 몫이 1스텝.
    """
    job = _clip_jobs.get(job_id)
    if job is None:
        return

    job["status"] = "running"
    tmp_dir = Path(job["tmp_dir"])
    total = len(job["segments"])

    try:
        parts: list[Path] = []
        for idx, seg in enumerate(job["segments"]):
            job["current_segment"] = idx + 1  # 1-based ("3/5 처리 중" 표시용)
            part_path = tmp_dir / f"part_{idx:03d}.mp4"
            await clip_service.extract_clip_mp4(
                job["vod_url"], seg["start"], seg["end"], part_path
            )
            parts.append(part_path)
            job["progress"] = round((idx + 1) / (total + 1), 3)

        output_path = tmp_dir / job["filename"]
        await clip_service.concat_clips_mp4(parts, output_path)

        job["output_path"] = str(output_path)
        job["progress"] = 1.0
        job["current_segment"] = None
        job["status"] = "done"
    except Exception as e:
        logger.error("병합 클립 잡 실패 (%s): %s", job_id, e)
        job["error"] = str(e)[:300]
        job["current_segment"] = None
        job["status"] = "failed"
    finally:
        # 취소(CancelledError) 포함 어떤 종료든 TTL 정리 대상이 되도록 기록
        job["finished_at"] = time.monotonic()


@router.post(
    "/{meeting_id}/speakers/clip-jobs",
    status_code=status.HTTP_202_ACCEPTED,
    summary="병합 클립 생성 잡 시작",
)
async def create_clip_merge_job(
    meeting_id: str,
    body: dict = Body(...),
    user: dict = Depends(require_role(*_CLIP_ROLES)),
    supabase: Client = Depends(get_supabase),
) -> dict:
    """여러 발언 구간을 순차 추출해 하나의 mp4로 병합하는 잡을 시작합니다.

    KMS 스로틀 하에서 추출 시간 ≈ 구간 길이라 동기 응답이 불가능하므로
    202 + job_id 를 반환하고, 진행 상태는 GET clip-jobs/{job_id} 로 조회합니다.
    """
    # Layer 1: ffmpeg 가용성 확인 (clip 과 동일)
    if not _check_ffmpeg_available():
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="ffmpeg가 설치되어 있지 않습니다. 서버에 ffmpeg를 설치해주세요.",
        )

    # Layer 1.5: 동시 상한 — 미완료(finished_at 없음) 잡이 상한이면 429.
    # (finished_at 은 성공/실패/취소 어떤 종료든 _run_clip_job finally 에서 기록)
    active = sum(1 for j in _clip_jobs.values() if j.get("finished_at") is None)
    if active >= _CLIP_JOB_MAX_ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"병합 작업이 이미 최대 {_CLIP_JOB_MAX_ACTIVE}개 실행 중입니다. "
                "완료 후 다시 시도해 주세요."
            ),
        )

    # Layer 2: 세그먼트 검증 (1 <= N <= clip_job_max_segments, 각 end > start)
    segments = body.get("segments")
    if not isinstance(segments, list) or len(segments) < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="segments 는 1개 이상의 구간 목록이어야 합니다.",
        )
    if len(segments) > settings.clip_job_max_segments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"구간은 최대 {settings.clip_job_max_segments}개까지 허용됩니다.",
        )

    parsed_segments: list[dict] = []
    total_seconds = 0.0
    for seg in segments:
        try:
            seg_start = float(seg["start"])
            seg_end = float(seg["end"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="각 구간은 start/end 숫자 필드가 필요합니다.",
            )
        # NaN 은 모든 부등호 비교가 False 라 아래 검증을 그대로 통과한다
        # (json.loads 는 NaN/Infinity 리터럴 허용) — 유한값만 허용.
        if not (math.isfinite(seg_start) and math.isfinite(seg_end)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="각 구간의 start/end 는 유한한 숫자여야 합니다.",
            )
        if seg_start < 0 or seg_end <= seg_start:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="각 구간은 end 가 start 보다 커야 합니다.",
            )
        total_seconds += seg_end - seg_start
        parsed_segments.append({"start": seg_start, "end": seg_end})

    # Layer 3: 총 길이 상한 (단일 클립 상한의 2배)
    max_total = settings.clip_max_seconds * 2
    if total_seconds > max_total:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"구간 길이 총합이 상한({max_total}초)을 초과합니다.",
        )

    # Layer 4: meeting 조회 + vod_url 확인 (clip 과 동일)
    try:
        result = (
            supabase.table("meetings")
            .select("id, vod_url, title, kms_midx")
            .eq("id", meeting_id)
            .limit(1)
            .execute()
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting {meeting_id}을(를) 찾을 수 없습니다.",
        )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting {meeting_id}을(를) 찾을 수 없습니다.",
        )

    meeting = result.data[0]
    vod_url = meeting.get("vod_url")
    if not vod_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="VOD URL이 없는 회의입니다.",
        )

    # Layer 5: VOD 소스 화이트리스트 (SSRF 방지) — admin 은 예외 허용
    if not is_allowed_vod_source(vod_url) and user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="허용되지 않은 VOD 소스입니다. (kms.ggc.go.kr만 허용)",
        )

    # 만료 잡 + 재시작 고아 임시디렉토리 lazy 정리 후 신규 잡 등록
    _cleanup_expired_clip_jobs()
    _cleanup_orphan_clip_tmpdirs()

    ident = str(meeting["kms_midx"]) if meeting.get("kms_midx") else str(meeting_id)[:8]
    job_id = str(uuid.uuid4())
    _clip_jobs[job_id] = {
        "job_id": job_id,
        "meeting_id": meeting_id,
        "vod_url": vod_url,
        "segments": parsed_segments,
        # 파일명 규약(build_clip_filename)의 병합 변형
        "filename": f"ggc_{ident}_merged_{len(parsed_segments)}clips.mp4",
        "tmp_dir": tempfile.mkdtemp(prefix="clipjob_"),
        "status": "queued",
        "progress": 0.0,
        "current_segment": None,
        "error": None,
        "output_path": None,
        "finished_at": None,
    }

    asyncio.create_task(_run_clip_job(job_id))

    return {"job_id": job_id}


@router.get(
    "/{meeting_id}/speakers/clip-jobs/{job_id}",
    summary="병합 클립 잡 상태 조회",
)
async def get_clip_merge_job_status(
    meeting_id: str,
    job_id: str,
    _user: dict = Depends(require_role(*_CLIP_ROLES)),
) -> dict:
    """잡 진행 상태를 반환합니다 (queued|running|done|failed, progress 0~1)."""
    job = _clip_jobs.get(job_id)
    if job is None or job["meeting_id"] != meeting_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_CLIP_JOB_EXPIRED_DETAIL,
        )

    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "progress": job["progress"],
        "current_segment": job["current_segment"],
        "error": job["error"],
        "filename": job["filename"],
    }


@router.get(
    "/{meeting_id}/speakers/clip-jobs/{job_id}/download",
    summary="병합 클립 다운로드",
)
async def download_clip_merge_job(
    meeting_id: str,
    job_id: str,
    _user: dict = Depends(require_role(*_CLIP_ROLES)),
):
    """완료된 잡의 병합 mp4 를 다운로드합니다 (done 이전에는 404)."""
    job = _clip_jobs.get(job_id)
    if job is None or job["meeting_id"] != meeting_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_CLIP_JOB_EXPIRED_DETAIL,
        )

    if job["status"] != "done" or not job.get("output_path"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="잡이 아직 완료되지 않았습니다.",
        )

    return FileResponse(
        job["output_path"],
        media_type="video/mp4",
        filename=job["filename"],
    )
