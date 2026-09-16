"""Tools API 라우터 - 영상추출기(exe) 배포/자동업데이트 채널

# @TASK C1-distribution - version.json + 설치파일 호스팅 (brew 식)
# @TASK C2-by-kms - exe 데이터 연계 (KMS midx 로 AI 발언구간 조회)

exe 클라이언트가 version.json 을 폴링하여 새 버전이면 url 에서
설치파일을 내려받아 자동업데이트한다. 업로드는 admin 전용.
"""

import logging
import re
from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, RedirectResponse
from supabase import Client

from app.core.auth_middleware import require_role
from app.core.config import settings
from app.core.database import get_supabase
from app.services import tool_release_service
from app.services.clip_draft_index import build_clip_index

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tools", tags=["tools"])

# 배포 도구 표시명
TOOL_NAME = "경기도의회 영상추출기"

# 버전 형식: 1.2 또는 1.2.3
VERSION_RE = re.compile(r"^\d+\.\d+(\.\d+)?$")

# 구간 미리보기 글자 수 (speaker_segments.PREVIEW_LENGTH 와 같은 값)
PREVIEW_LENGTH = 80

# exe(webui/app.html applyAiSpeakers)가 "이름 직책" 을 가를 때 쓰는 직책 목록.
# 이 집합 밖의 role 을 붙이면 라벨 전체가 이름으로 잡혀 엉뚱한 폴더명이 된다.
_EXE_ROLES = ("위원장", "부위원장", "위원", "의원", "의장", "부의장")


def speaker_label(group: dict) -> str:
    """clip-index 그룹 → exe 가 파싱하는 화자 라벨."""
    name = str(group.get("name") or "").strip()
    role = str(group.get("role") or "").strip()
    if not name:
        return "(미지정)"
    return f"{name} {role}" if role in _EXE_ROLES else name


def _last_end(speakers: list[dict]) -> float:
    """가장 늦게 끝나는 구간의 끝 (회의 길이 대용)."""
    return max((float(seg["end_time"]) for g in speakers for seg in g["segments"]),
               default=0.0)


def clip_index_to_speakers(index: dict) -> list[dict]:
    """웹 /clips 의 clip-index → exe 가 읽는 speakers 형태로 옮긴다.

    ★두 화면이 같은 구간을 보여야 한다. 예전에는 이 API 만 build_speaker_segments
    (같은 화자 라벨의 연속 자막 병합)를 썼는데, 그건 의원이 묻고 집행부가 답할 때마다
    끊겨 한 의원이 10구간 넘게 쪼개졌다(2026-09-08 안전행정위 강성삼 위원 12구간).
    웹은 그때 이미 공식 인덱스 → AI 질의답변 슬롯으로 옮겨 가 있었다 —
    이 함수가 그 결과를 exe 계약(형태 불변)에 실어 보내 둘을 하나로 맞춘다.
    기존 설치본(v1.9.1·v1.10.x)도 응답 키가 그대로라 고치지 않고 동작한다.
    """
    out: list[dict] = []
    for g in index.get("speakers") or []:
        segments = []
        for seg in g.get("segments") or []:
            start = float(seg.get("start") or 0.0)
            end = float(seg.get("end") or 0.0)
            segments.append({
                "start_time": start,
                "end_time": end,
                "duration": float(seg.get("seconds") or max(0.0, end - start)),
                "text_preview": str(seg.get("title") or "")[:PREVIEW_LENGTH],
                # named=False 는 그 의원 코드에 붙은 의사진행·안건 항목이다. 웹 /clips 는
                # 이름이 있는 구간만 기본 선택한다(ClipEditor) — 설치형도 같게 하려면
                # 이 값이 있어야 한다. 옛 설치본(v1.9.1·v1.10.x)은 없는 키로 보고 무시한다.
                "named": bool(seg.get("named", True)),
            })
        if not segments:
            continue
        out.append({
            "speaker": speaker_label(g),
            "total_time": float(g.get("total_seconds") or 0.0),
            "segment_count": len(segments),
            "segments": segments,
        })
    return out


# =============================================================================
# GET - 최신 버전 매니페스트 (공개 — exe 자동업데이트 폴링용)
# =============================================================================


@router.get("/extractor/version.json", summary="영상추출기 최신 버전 매니페스트")
async def get_extractor_version(request: Request) -> dict:
    """최신 배포 버전 정보를 반환합니다. 배포된 버전이 없으면 404."""
    manifest = tool_release_service.load_manifest()
    if manifest is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="배포된 버전이 없습니다.",
        )
    return {
        "name": manifest.get("name") or TOOL_NAME,
        "version": manifest.get("version"),
        "notes": manifest.get("notes", ""),
        "published_at": manifest.get("published_at"),
        "url": tool_release_service.build_download_url(request, settings),
        "sha256": manifest.get("sha256"),
        "size": manifest.get("size"),
        "min_supported_version": manifest.get("min_supported_version"),
    }


# =============================================================================
# GET - 설치파일 다운로드 (공개)
# =============================================================================


@router.get("/extractor/download", summary="영상추출기 설치파일 다운로드")
async def download_extractor():
    """설치파일을 다운로드합니다.

    - external_url 배포면 307 리다이렉트
    - 로컬 배포면 application/octet-stream 파일 응답
    """
    manifest = tool_release_service.load_manifest()
    if manifest is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="배포된 버전이 없습니다.",
        )

    external_url = manifest.get("external_url")
    if external_url:
        return RedirectResponse(
            url=external_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT
        )

    filename = manifest.get("file")
    if not filename:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="설치파일이 없습니다.",
        )

    try:
        file_path = tool_release_service.resolve_release_path(filename)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="설치파일이 없습니다.",
        )

    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="설치파일이 디스크에 존재하지 않습니다.",
        )

    version = manifest.get("version", "")
    return FileResponse(
        path=str(file_path),
        media_type="application/octet-stream",
        filename=tool_release_service.installer_filename(version),
    )


# =============================================================================
# GET - KMS midx 로 AI 발언구간 조회 (공개 — exe 데이터 연계)
# =============================================================================


@router.get(
    "/extractor/meetings/by-kms/{midx}/segments",
    summary="KMS midx로 AI 발언구간 조회",
)
async def get_segments_by_kms_midx(
    midx: int,
    supabase: Client = Depends(get_supabase),
) -> dict:
    """exe 클라이언트가 KMS midx 만으로 의원별 발언구간을 조회합니다.

    ★웹 /clips 와 **같은 인덱스**를 돌려준다 (build_clip_index — 공식 KMS 인덱스가
    있으면 그것, 없으면 AI 자막의 호명·자기소개로 세운 질의답변 슬롯).
    설치형과 웹이 서로 다른 구간을 보여 주던 것을 2026-09-10 에 하나로 합쳤다.

    exe 는 로그인이 없으므로 공개(무인증) 엔드포인트다.
    - 미등록 midx → 404 (웹서비스에 먼저 VOD 등록 안내)
    - 회의는 있으나 의원 구간을 세울 수 없음 → 409 (사유는 인덱스의 경고 문구 그대로)
    """
    result = (
        supabase.table("meetings")
        .select("*")
        .eq("kms_midx", str(midx))  # kms_midx 는 문자열 컬럼
        .limit(5)
        .execute()
    )
    rows = result.data or []
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"KMS midx {midx}에 해당하는 회의가 없습니다. "
                "웹서비스에 먼저 VOD 등록 후 AI 자막을 생성하세요."
            ),
        )
    # 같은 midx 에 회의 레코드가 둘일 수 있다 — 일정 선등록본(VOD 없음)과 KMS 목록
    # 동기화가 새로 만든 본(VOD·AI 자막 있음). 웹 /clips 목록에서 담당자가 고를 수 있는
    # 것은 자를 영상이 있는 쪽이므로 여기서도 그쪽을 고른다
    # (2026-09-04 393회 1차 본회의 a5be7688/080451fc 실측).
    meeting = next((m for m in rows if m.get("vod_url")), rows[0])

    index = await build_clip_index(supabase, meeting)
    speakers = clip_index_to_speakers(index)
    if not speakers:
        warnings = index.get("warnings") or []
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=" ".join(warnings) or "AI 자막 미생성",
        )

    return {
        "meeting": {
            "id": meeting.get("id"),
            "title": meeting.get("title"),
            "meeting_date": meeting.get("meeting_date"),
            "kms_midx": meeting.get("kms_midx"),
            "vod_url": meeting.get("vod_url"),
        },
        # 회의에 길이가 없으면(선등록본) 마지막 구간 끝으로 갈음한다 — 0 을 주면
        # exe 의 진행바가 붙지 않는다
        "total_duration": float(index.get("duration") or 0.0) or _last_end(speakers),
        # source/warnings 는 새 키다 — 옛 exe 는 무시하고, 새 판은 "공식/AI 잠정" 표시에 쓴다
        "source": index.get("source"),
        "warnings": index.get("warnings") or [],
        "speakers": speakers,
    }


# =============================================================================
# POST - 새 버전 업로드 (admin 전용)
# =============================================================================


@router.post(
    "/extractor/upload",
    status_code=status.HTTP_201_CREATED,
    summary="영상추출기 새 버전 배포",
)
async def upload_extractor(
    version: str = Form(...),
    notes: str = Form(""),
    file: UploadFile | None = File(None),
    external_url: str | None = Form(None),
    _user: dict = Depends(require_role("admin")),
) -> dict:
    """새 버전을 배포합니다 (설치파일 업로드 또는 외부 URL 등록).

    - version: ^\\d+\\.\\d+(\\.\\d+)?$ 형식
    - file(.exe) 또는 external_url 중 정확히 하나 필수
    """
    # fullmatch 필수: re.match + '$'는 '1.0\n'처럼 끝 개행 앞에서도 매칭돼
    # 개행이 저장 파일명에 들어가 Windows OSError(500)를 냈다.
    if not VERSION_RE.fullmatch(version):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="버전 형식이 올바르지 않습니다 (예: 1.2 또는 1.2.3).",
        )

    has_file = file is not None and bool(file.filename)
    has_external = bool(external_url)
    if has_file == has_external:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="file 또는 external_url 중 하나만 제공해야 합니다.",
        )

    sha256: str | None = None
    size: int | None = None
    stored_name: str | None = None

    if has_file:
        if not file.filename.lower().endswith(".exe"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=".exe 파일만 업로드할 수 있습니다.",
            )
        try:
            path, sha256, size = tool_release_service.store_installer(
                file.file, version
            )
        except tool_release_service.InstallerTooLargeError as e:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=str(e),
            )
        stored_name = path.name

    manifest = {
        "name": TOOL_NAME,
        "version": version,
        "notes": notes or "",
        "published_at": datetime.now(timezone.utc).isoformat(),
        "sha256": sha256,
        "size": size,
        "file": stored_name,
        "external_url": external_url or None,
        "min_supported_version": None,
    }
    tool_release_service.save_manifest(manifest)
    logger.info(
        "영상추출기 배포: version=%s file=%s external_url=%s",
        version,
        stored_name,
        external_url,
    )
    return manifest
