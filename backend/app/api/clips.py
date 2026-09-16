# -*- coding: utf-8 -*-
"""발언영상 클립 워크벤치 API — 데스크톱 영상추출기(exe) 대체 (2026-09)

- GET  /api/meetings/{id}/clip-index            공식(KMS) → AI 자막 순 의원별 구간 (AI 자막 전엔 없음 = 수동)
- PUT  /api/meetings/{id}/clip-offset           초안 인덱스 시간축 보정 (회의당 1회)
- POST /api/meetings/{id}/clip-jobs             202 + job_id (영속 잡, PVC 보관 7일)
- GET  /api/meetings/{id}/clip-jobs/{job_id}    상태
- GET  /api/meetings/{id}/clip-jobs/{job_id}/download?file=   mp4/srt
- DELETE /api/meetings/{id}/clip-jobs/{job_id}  취소 또는 즉시 삭제
- GET  /api/clip-jobs?scope=mine|all&days=7     추출 기록
- GET  /api/clip-jobs/resolve?midx=             KMS midx → meeting_id (옛 exe 링크 회수용)
- POST /api/clip-jobs/sweep                     저장소 정리 (admin, 검증용)

기존 speakers.py 의 동기 /speakers/clip 과 인메모리 clip-jobs 는 그대로 둔다 —
/vod/[id]/speaker 화면이 아직 쓴다. 이 라우터가 자리를 잡으면 그쪽을 걷어낸다.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from app.api.deps import get_clip_job_repository
from app.core.auth_middleware import require_role, require_role_or_council
from app.core.config import settings
from app.repositories.clip_job_repository import ClipJobRepository
from app.services import clip_service, clip_store
from app.services.clip_draft_index import build_clip_index
from app.services.clip_job_service import clip_job_service, sweep_store
from app.services.kms_vod_resolver import is_allowed_vod_source

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["clips"])

# speakers._CLIP_ROLES 와 같은 값 — 로그인 5역할. 워크벤치 라우트는 여기에 더해
# 로그인하지 않은 의회망 방문자를 손님(council_guest)으로 들인다(require_role_or_council, 2026-09-11)
CLIP_ROLES = ("staff", "committee_staff", "meeting_manager", "stenographer", "admin")
SOURCE_KINDS = ("official", "ai", "live", "manual")
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
MAX_OFFSET_SECONDS = 3600.0
MAX_PAD_SECONDS = 120.0
EXPIRED_DETAIL = "보존 기간(7일) 또는 저장 공간 한도로 삭제된 클립입니다. 다시 추출해 주세요."


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _owner_fields(user: dict) -> tuple[Optional[str], str]:
    uid = str(user.get("id") or "")
    return (uid if _UUID_RE.match(uid) else None), str(user.get("username") or uid or "unknown")


def _is_owner_or_admin(job: dict, user: dict) -> bool:
    if user.get("role") == "admin":
        return True
    if job.get("origin") == "auto":
        return True          # 자동 클립은 모두의 것 — 로그인 5역할 누구나 보고 받는다(2026-09-10)
    owner_id, owner_name = _owner_fields(user)
    if owner_id and str(job.get("owner_user_id") or "") == owner_id:
        return True
    return (not owner_id) and str(job.get("owner_username") or "") == owner_name


def _job_public(job: dict, brief: Optional[dict] = None) -> dict:
    meeting_id = str(job.get("meeting_id"))
    job_id = str(job.get("id"))
    files = job.get("files") or []
    urls = {}
    if job.get("status") == "done":
        for f in files:
            name = str(f.get("name") or "")
            if name:
                urls[name] = f"/api/meetings/{meeting_id}/clip-jobs/{job_id}/download?file={quote(name)}"
    segments = job.get("segments") or []
    out = {
        "job_id": job_id,
        "meeting_id": meeting_id,
        "origin": job.get("origin") or "manual",
        "compress": bool(job.get("compress")),
        # 파일 ↔ 구간 짝(자동 클립 목록의 "▶ 보기" 가 영상 위치로 간다) — 여유가 들어간 실제 구간
        "segments": [{"start": float(s.get("start") or 0), "end": float(s.get("end") or 0),
                      **({"no": int(s["no"])} if s.get("no") else {})} for s in segments],
        "label": job.get("label"),
        "speaker_name": job.get("speaker_name"),
        "source_kind": job.get("source_kind"),
        "status": job.get("status"),
        "progress": float(job.get("progress") or 0.0),
        "current_segment": job.get("current_segment"),
        "segment_count": len(segments),
        "total_seconds": float(job.get("total_seconds") or 0.0),
        "merge": bool(job.get("merge")),
        "with_srt": bool(job.get("with_srt")),
        "error": job.get("error"),
        "files": files,
        "bytes_total": int(job.get("bytes_total") or 0),
        "created_at": job.get("created_at"),
        "finished_at": job.get("finished_at"),
        "expires_at": job.get("expires_at"),
        "evicted_reason": job.get("evicted_reason"),
        "owner_username": job.get("owner_username"),
        "download_urls": urls,
    }
    if brief:
        out["meeting_title"] = brief.get("title")
        out["meeting_date"] = brief.get("meeting_date")
    return out


def _load_meeting(repo: ClipJobRepository, meeting_id: str) -> dict:
    try:
        meeting = repo.get_meeting(meeting_id)
    except Exception:  # noqa: BLE001
        meeting = None
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Meeting {meeting_id}을(를) 찾을 수 없습니다.")
    return meeting


def _load_job(repo: ClipJobRepository, meeting_id: str, job_id: str, user: dict) -> dict:
    job = repo.get(job_id) if _UUID_RE.match(job_id or "") else None
    if not job or str(job.get("meeting_id")) != str(meeting_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="작업을 찾을 수 없습니다.")
    if not _is_owner_or_admin(job, user):
        # 남의 잡은 존재 여부도 알리지 않는다
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="작업을 찾을 수 없습니다.")
    return job


def _ensure_service_configured(repo: ClipJobRepository) -> None:
    """lifespan 이 configure 하지 못한 환경(테스트·단독 실행)에서도 잡이 돈다."""
    if clip_job_service._repo_factory is None:  # noqa: SLF001
        clip_job_service.configure(lambda: repo)


# =============================================================================
# 인덱스
# =============================================================================
@router.get("/meetings/{meeting_id}/clip-index", summary="의원별 발언 구간 인덱스 (공식→AI, 그 전엔 수동)")
async def get_clip_index(
    meeting_id: str,
    _user: dict = Depends(require_role_or_council(*CLIP_ROLES)),
    repo: ClipJobRepository = Depends(get_clip_job_repository),
) -> dict:
    meeting = _load_meeting(repo, meeting_id)
    return await build_clip_index(repo.client, meeting)


@router.put("/meetings/{meeting_id}/clip-offset", summary="초안 인덱스 시간축 보정 저장")
async def put_clip_offset(
    meeting_id: str,
    body: dict = Body(...),
    _user: dict = Depends(require_role(*CLIP_ROLES)),
    repo: ClipJobRepository = Depends(get_clip_job_repository),
) -> dict:
    try:
        offset = float(body.get("time_offset"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="time_offset 은 숫자(초)여야 합니다.")
    if not math.isfinite(offset) or abs(offset) > MAX_OFFSET_SECONDS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"time_offset 은 ±{int(MAX_OFFSET_SECONDS)}초 안이어야 합니다.")
    _load_meeting(repo, meeting_id)
    repo.set_meeting_offset(meeting_id, offset)
    return {"meeting_id": meeting_id, "time_offset": offset}


# =============================================================================
# 잡 생성 / 조회 / 다운로드 / 삭제
# =============================================================================
def _parse_segments(body: dict) -> tuple[list[dict], float]:
    segments = body.get("segments")
    if not isinstance(segments, list) or len(segments) < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="segments 는 1개 이상의 구간 목록이어야 합니다.")
    if len(segments) > settings.clip_job_max_segments:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"구간은 최대 {settings.clip_job_max_segments}개까지 허용됩니다.")
    parsed: list[dict] = []
    total = 0.0
    seen_no: set[int] = set()
    for seg in segments:
        try:
            s, e = float(seg["start"]), float(seg["end"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="각 구간은 start/end 숫자 필드가 필요합니다.")
        if not (math.isfinite(s) and math.isfinite(e)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="각 구간의 start/end 는 유한한 숫자여야 합니다.")
        if s < 0 or e <= s:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="각 구간은 end 가 start 보다 커야 합니다.")
        total += e - s
        item = {"start": round(s, 3), "end": round(e, 3)}
        # no = 그 의원 구간 목록의 순번 → 파일 이름 `이름_회의명_번호` 의 번호 (선택, 2026-09-10).
        # 같은 번호가 둘이면 한 잡 안에서 파일 이름이 겹쳐 앞 파일이 덮이므로 거부한다.
        if seg.get("no") is not None:
            no = seg["no"]
            if isinstance(no, bool) or not isinstance(no, int) or not 1 <= no <= 9999 or no in seen_no:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                    detail="구간 번호(no)는 서로 다른 1~9999 정수여야 합니다.")
            seen_no.add(no)
            item["no"] = no
        parsed.append(item)
    if total > settings.clip_job_max_total_seconds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"구간 길이 총합이 상한({settings.clip_job_max_total_seconds}초)을 초과합니다.")
    return parsed, total


def _parse_pad(body: dict, key: str) -> float:
    try:
        v = float(body.get(key, 0) or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{key} 는 숫자(초)여야 합니다.")
    if not math.isfinite(v) or v < 0 or v > MAX_PAD_SECONDS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"{key} 는 0~{int(MAX_PAD_SECONDS)}초 안이어야 합니다.")
    return v


@router.post("/meetings/{meeting_id}/clip-jobs", status_code=status.HTTP_202_ACCEPTED,
             summary="클립 추출 잡 생성 (영속)")
async def create_clip_job(
    meeting_id: str,
    body: dict = Body(...),
    user: dict = Depends(require_role_or_council(*CLIP_ROLES)),
    repo: ClipJobRepository = Depends(get_clip_job_repository),
) -> dict:
    segments, total = _parse_segments(body)
    pad_before, pad_after = _parse_pad(body, "pad_before"), _parse_pad(body, "pad_after")
    source_kind = str(body.get("source_kind") or "manual")
    if source_kind not in SOURCE_KINDS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"source_kind 는 {', '.join(SOURCE_KINDS)} 중 하나여야 합니다.")
    try:
        time_offset = float(body.get("time_offset", 0) or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="time_offset 은 숫자여야 합니다.")
    if not math.isfinite(time_offset) or abs(time_offset) > MAX_OFFSET_SECONDS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"time_offset 은 ±{int(MAX_OFFSET_SECONDS)}초 안이어야 합니다.")
    label = clip_service.sanitize_filename(body.get("label"), max_len=120) or "클립"
    speaker_name = (str(body.get("speaker_name") or "").strip()[:100]) or None

    meeting = _load_meeting(repo, meeting_id)
    vod_url = meeting.get("vod_url")
    if not vod_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="VOD URL이 없는 회의입니다.")
    if not is_allowed_vod_source(vod_url) and user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="허용되지 않은 VOD 소스입니다. (kms.ggc.go.kr만 허용)")

    # 여유·병합은 서버가 확정한다 (파일에 실제 담기는 구간 = DB 의 segments)
    from app.services.kms_angun_service import pad_and_merge
    duration = meeting.get("duration_seconds") or None
    merged = pad_and_merge(segments, pad_before, pad_after, duration)
    total = sum(s["end"] - s["start"] for s in merged)
    if total > settings.clip_job_max_total_seconds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"여유를 더한 구간 총합이 상한({settings.clip_job_max_total_seconds}초)을 초과합니다.")

    owner_id, owner_name = _owner_fields(user)
    # 자동 클립 잡은 작업자 파드의 큐다 — 사람의 대기 상한·중복 판정에 섞지 않는다
    active = repo.list_active("manual")
    # 같은 사람이 같은 구간을 또 요청하면(연타·두 탭·캐시 지연) 새 잡을 만들지 않고 그 잡을 돌려준다
    for prior in active:
        if ((prior.get("owner_user_id") == owner_id if owner_id
             else prior.get("owner_username") == owner_name)
                and str(prior.get("meeting_id")) == str(meeting_id)
                and prior.get("segments") == merged
                and bool(prior.get("merge")) == bool(body.get("merge", True))):
            ahead = [a for a in active if a["created_at"] < prior["created_at"]]
            return {"job_id": prior["id"], "status": prior.get("status"), "duplicate": True,
                    "queue_position": max(0, len(ahead) + 1 - settings.clip_job_max_active)}

    # 동시 상한
    running = sum(1 for r in active if r.get("status") == "running")
    queued = sum(1 for r in active if r.get("status") == "queued")
    if running + queued >= settings.clip_job_max_active + settings.clip_job_max_queued:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="추출 작업이 너무 많이 대기 중입니다. 잠시 후 다시 시도해 주세요.")

    # 저장 공간 프리플라이트 — 부족하면 먼저 정리, 그래도 부족하면 507
    est = clip_store.estimate_bytes(total)
    if clip_store.usage_bytes() + est > settings.clip_store_max_bytes:
        await asyncio.to_thread(sweep_store, repo, extra_free_bytes=est)
        used = clip_store.usage_bytes()
        if used + est > settings.clip_store_max_bytes:
            raise HTTPException(
                status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
                detail=(f"저장 공간이 부족합니다 (사용 {used / 1024**2:.0f}MB / "
                        f"상한 {settings.clip_store_max_bytes / 1024**2:.0f}MB). "
                        "추출 기록에서 오래된 클립을 삭제하거나 잠시 후 다시 시도해 주세요."))

    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    row = {
        "id": job_id,
        "meeting_id": str(meeting_id),
        "owner_user_id": owner_id,
        "owner_username": owner_name,
        "label": label,
        "speaker_name": speaker_name,
        "source_kind": source_kind,
        "segments": merged,
        "pad_before": pad_before,
        "pad_after": pad_after,
        "merge": bool(body.get("merge", True)),
        "with_srt": bool(body.get("with_srt", True)),
        "time_offset": time_offset,
        "vod_url": vod_url,
        "total_seconds": round(total, 2),
        "status": "queued",
        "attempts": 0,
        "progress": 0.0,
        "files": [],
        "bytes_total": 0,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(days=max(1, settings.clip_store_ttl_days))).isoformat(),
        "origin": "manual",
    }
    repo.insert(row)
    _ensure_service_configured(repo)
    clip_job_service.submit(job_id)
    position = max(0, running + queued + 1 - settings.clip_job_max_active)
    return {"job_id": job_id, "status": "queued", "queue_position": position}


@router.get("/meetings/{meeting_id}/clip-jobs/{job_id}", summary="클립 잡 상태")
async def get_clip_job(
    meeting_id: str,
    job_id: str,
    user: dict = Depends(require_role_or_council(*CLIP_ROLES)),
    repo: ClipJobRepository = Depends(get_clip_job_repository),
) -> dict:
    return _job_public(_load_job(repo, meeting_id, job_id, user))


@router.get("/meetings/{meeting_id}/clip-jobs/{job_id}/download", summary="클립 파일 다운로드")
async def download_clip_job_file(
    meeting_id: str,
    job_id: str,
    file: str = Query(..., description="files[].name"),
    user: dict = Depends(require_role_or_council(*CLIP_ROLES)),
    repo: ClipJobRepository = Depends(get_clip_job_repository),
):
    job = _load_job(repo, meeting_id, job_id, user)
    if job.get("status") == "expired":
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=EXPIRED_DETAIL)
    if job.get("status") != "done":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="작업이 아직 완료되지 않았습니다.")
    names = {str(f.get("name")) for f in (job.get("files") or [])}
    if file not in names:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="그런 파일이 없습니다.")
    try:
        path = clip_store.safe_file(job_id, file)
    except clip_store.UnsafePathError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="파일명이 올바르지 않습니다.")
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=EXPIRED_DETAIL)
    media = "application/x-subrip" if file.lower().endswith(".srt") else "video/mp4"
    return FileResponse(str(path), media_type=media, filename=file)


@router.delete("/meetings/{meeting_id}/clip-jobs/{job_id}", summary="클립 잡 취소 또는 삭제")
async def delete_clip_job(
    meeting_id: str,
    job_id: str,
    user: dict = Depends(require_role_or_council(*CLIP_ROLES)),
    repo: ClipJobRepository = Depends(get_clip_job_repository),
) -> dict:
    job = _load_job(repo, meeting_id, job_id, user)
    st = job.get("status")
    if job.get("origin") == "auto":
        # 모두가 받는 파일이라 지우는 것은 관리자만, 작업자가 자르는 중인 것은 여기서 멈출 수 없다
        if user.get("role") != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="자동 클립은 관리자만 지울 수 있습니다.")
        if st in ("queued", "running"):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="자동 작업자가 처리 중인 클립입니다. 끝난 뒤 지워 주세요.")
    if st in ("queued", "running"):
        _ensure_service_configured(repo)
        await clip_job_service.cancel(job_id)
        return {"job_id": job_id, "status": "cancelled"}
    if st == "done" and not job.get("evicted_at"):
        clip_store.remove_job_files(job_id)
        repo.mark_evicted(job_id, "manual")
        return {"job_id": job_id, "status": "expired"}
    return {"job_id": job_id, "status": st}


# =============================================================================
# 목록 / 역조회 / 정리
# =============================================================================
@router.get("/clip-jobs", summary="추출 기록 (기본 7일)")
async def list_clip_jobs(
    scope: str = Query("mine", pattern="^(mine|all)$"),
    days: int = Query(7, ge=1, le=30),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    meeting_id: Optional[str] = Query(None),
    user: dict = Depends(require_role_or_council(*CLIP_ROLES)),
    repo: ClipJobRepository = Depends(get_clip_job_repository),
) -> dict:
    if scope == "all" and user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="전체 기록은 관리자만 볼 수 있습니다.")
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    if scope == "all":
        rows = repo.list_all(since_iso=since, limit=limit, offset=offset, meeting_id=meeting_id)
    else:
        owner_id, owner_name = _owner_fields(user)
        rows = repo.list_for_owner(owner_id, owner_name, since_iso=since, limit=limit,
                                   offset=offset, meeting_id=meeting_id)
    briefs = repo.get_meetings_brief([str(r.get("meeting_id")) for r in rows]) if rows else {}
    return {
        "jobs": [_job_public(r, briefs.get(str(r.get("meeting_id")))) for r in rows],
        "store": {
            "used_bytes": clip_store.usage_bytes(),
            "max_bytes": settings.clip_store_max_bytes,
            "ttl_days": settings.clip_store_ttl_days,
        },
    }


@router.get("/clip-jobs/resolve", summary="KMS midx → meeting_id")
async def resolve_meeting_by_midx(
    midx: str = Query(..., min_length=1, max_length=12),
    _user: dict = Depends(require_role_or_council(*CLIP_ROLES)),
    repo: ClipJobRepository = Depends(get_clip_job_repository),
) -> dict:
    if not midx.isdigit():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="midx 는 숫자여야 합니다.")
    meeting = repo.get_meeting_by_midx(midx)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="이 영상 번호로 등록된 회의가 아직 없습니다. 회의 목록에서 찾아 주세요.")
    return {"meeting_id": str(meeting["id"]), "title": meeting.get("title")}


_NAME_RE = re.compile(r"^[가-힣]{2,10}$")


def find_meetings_by_member(client, name: str) -> list[str]:
    """의원 이름 → 그 이름이 나온 회의 id (회의 목록 검색창의 이름 검색, 2026-09-11 담당자 요청).

    두 갈래의 합집합이다 — 한쪽만으로는 모자랐다(393회 실측: 박상현 라벨 5회의 · 언급 10회의).
      ① AI 자막 화자 라벨 `박상현 위원` (09-05 화자 융합 뒤 회의만 이름이 붙는다)
      ② 자막 본문의 호명·자기소개 `박상현 위원/의원` (그 전 회의·공식 인덱스 회의도 잡힌다)
    ②는 발언 없이 이름만 불린 회의도 잡으므로 "후보" 다 — 회의를 열면 인덱스가 정답이다.
    이름은 한글 2~10자만 받는다(PostgREST or 필터 문자열에 그대로 들어간다). 실측 50~80ms.
    """
    ids: set[str] = set()
    by_label = (client.table("subtitles").select("meeting_id")
                .eq("kind", "ai").ilike("speaker", f"{name}%").limit(20000).execute())
    by_text = (client.table("subtitles").select("meeting_id")
               .or_(f"text.ilike.*{name} 위원*,text.ilike.*{name} 의원*").limit(20000).execute())
    for row in (by_label.data or []) + (by_text.data or []):
        if row.get("meeting_id"):
            ids.add(str(row["meeting_id"]))
    return sorted(ids)


@router.get("/clip-meetings/by-member", summary="의원 이름으로 회의 찾기 (라벨·호명)")
async def clip_meetings_by_member(
    name: str = Query(..., min_length=2, max_length=10),
    _user: dict = Depends(require_role_or_council(*CLIP_ROLES)),
    repo: ClipJobRepository = Depends(get_clip_job_repository),
) -> dict:
    name = name.strip()
    if not _NAME_RE.match(name):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="의원 이름은 한글 2~10자로 입력해 주세요.")
    ids = await asyncio.to_thread(find_meetings_by_member, repo.client, name)
    return {"name": name, "meeting_ids": ids}


@router.post("/clip-jobs/sweep", summary="저장소 정리 (관리자·검증용)")
async def sweep_clip_store(
    dry_run: bool = Query(True),
    max_bytes: Optional[int] = Query(None, ge=0),
    _user: dict = Depends(require_role("admin")),
    repo: ClipJobRepository = Depends(get_clip_job_repository),
) -> dict:
    return await asyncio.to_thread(sweep_store, repo, max_bytes=max_bytes, dry_run=dry_run)


# =============================================================================
# 자동 클립 (2026-09-10) — AI 자막이 끝난 회의의 의원 전원 영상을 작업자 파드가 미리 잘라 둔다
# =============================================================================
AUTO_NOTICE = ("AI 가 자막으로 찾은 구간을 자동으로 자른 영상입니다. 드물게 다른 사람의 발언이 섞일 수 있으니 "
               "공유하기 전에 한 번 재생해 확인해 주세요.")


def _auto_payload(rows: list[dict], repo: ClipJobRepository, *, with_meeting: bool) -> dict:
    briefs = (repo.get_meetings_brief([str(r.get("meeting_id")) for r in rows])
              if rows and with_meeting else {})
    return {
        "jobs": [_job_public(r, briefs.get(str(r.get("meeting_id")))) for r in rows],
        "ttl_days": settings.clip_auto_ttl_days,
        "enabled": settings.clip_auto_enabled,
        "notice": AUTO_NOTICE,
    }


@router.get("/meetings/{meeting_id}/auto-clips", summary="이 회의의 자동 클립 (의원별 잡)")
async def list_meeting_auto_clips(
    meeting_id: str,
    _user: dict = Depends(require_role_or_council(*CLIP_ROLES)),
    repo: ClipJobRepository = Depends(get_clip_job_repository),
) -> dict:
    _load_meeting(repo, meeting_id)
    rows = await asyncio.to_thread(repo.list_auto, meeting_id=meeting_id)
    return {"meeting_id": meeting_id, **_auto_payload(rows, repo, with_meeting=False)}


@router.get("/auto-clips", summary="최근 자동 클립 (회의 정보 포함)")
async def list_recent_auto_clips(
    days: int = Query(3, ge=1, le=14),
    _user: dict = Depends(require_role_or_council(*CLIP_ROLES)),
    repo: ClipJobRepository = Depends(get_clip_job_repository),
) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = await asyncio.to_thread(repo.list_auto, since_iso=since)
    return _auto_payload(rows, repo, with_meeting=True)


@router.get("/auto-clips/status", summary="자동 클립 큐·예산·디스크 여유 (관리자)")
async def auto_clips_status(
    _user: dict = Depends(require_role("admin")),
    repo: ClipJobRepository = Depends(get_clip_job_repository),
) -> dict:
    from app.services import auto_clip_service

    return await asyncio.to_thread(auto_clip_service.status, repo)


@router.post("/auto-clips/enqueue", summary="이 회의의 자동 클립을 (다시) 만든다 (관리자)")
async def auto_clips_enqueue(
    meeting_id: str = Query(...),
    _user: dict = Depends(require_role("admin")),
    repo: ClipJobRepository = Depends(get_clip_job_repository),
) -> dict:
    """AI 자막을 다시 만든 회의 등 — 이전 자동 클립을 지우고 새 인덱스로 큐에 넣는다. 자르기는 작업자 파드가 한다."""
    from app.services import auto_clip_service

    meeting = _load_meeting(repo, meeting_id)
    prior = await asyncio.to_thread(repo.list_auto, meeting_id=meeting_id)
    if any(j.get("status") in ("queued", "running") for j in prior):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="이 회의의 자동 클립을 작업자가 처리 중입니다. 끝난 뒤 다시 시도해 주세요.")
    for j in prior:
        if j.get("status") == "done" and not j.get("evicted_at"):
            clip_store.remove_job_files(str(j["id"]))
            repo.mark_evicted(str(j["id"]), "manual")
    return await auto_clip_service.enqueue_meeting(repo, meeting)
