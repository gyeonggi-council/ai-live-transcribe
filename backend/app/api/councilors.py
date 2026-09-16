"""의원정보 API 라우터"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import Client

from app.core.database import get_supabase
from app.services.councilor_sync import CouncilorSyncService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/councilors", tags=["councilors"])


def _get_service(supabase: Client = Depends(get_supabase)) -> CouncilorSyncService:
    return CouncilorSyncService(supabase)


@router.get("")
async def list_councilors(
    committee: str | None = Query(None, description="위원회 필터"),
    committee_code: str | None = Query(None, description="위원회 코드(C105·E020 …) — 특별위원회 보강용"),
    q: str | None = Query(None, description="검색어 (이름/정당/지역구)"),
    service: CouncilorSyncService = Depends(_get_service),
    supabase: Client = Depends(get_supabase),
) -> list[dict[str, Any]]:
    """의원 목록 조회 (필터/검색).

    `committee` 만으로 비면 `committee_code` 로 의회 홈페이지 명단을 읽어 채운다 —
    예산결산특별위원회·윤리특별위원회는 의원정보 API 에 없기 때문이다.
    """
    if q:
        return service.search(q)
    if committee:
        from app.services.councilor_profile import resolve_committee_members

        return await resolve_committee_members(supabase, committee, committee_code)
    return service.get_all_active()


def _not_found_if_bad_id(exc: Exception) -> None:
    """PostgREST 의 "uuid 가 아니다"(22P02)를 **404 로 바꾼다.**

    주소를 잘못 만든 쪽(빈 id 로 `/api/councilors//photo` → id 가 "photo")의 실수가
    500 으로 보이면 운영 오류 로그가 진짜 오류와 섞인다(2026-09-16 실측).
    id 형식을 미리 검사하지 않고 DB 응답으로 가르는 이유는, 무엇이 유효한 id 인지는
    저장소가 정하기 때문이다(시험 더미처럼 uuid 가 아닌 id 를 쓰는 구성도 있다).
    """
    code = getattr(exc, "code", None) or (getattr(exc, "args", None) or [{}])[0]
    if isinstance(code, dict):
        code = code.get("code")
    if str(code) == "22P02" or "invalid input syntax for type uuid" in str(exc):
        raise HTTPException(status_code=404, detail="의원을 찾을 수 없습니다.") from None


def _get_councilor_or_404(service: CouncilorSyncService, councilor_id: str) -> dict[str, Any]:
    try:
        row = service.get_by_id(councilor_id)
    except Exception as e:
        _not_found_if_bad_id(e)
        raise
    if not row:
        raise HTTPException(status_code=404, detail="의원을 찾을 수 없습니다.")
    return row


@router.get("/sync-status")
async def get_sync_status(
    service: CouncilorSyncService = Depends(_get_service),
) -> dict[str, Any]:
    """동기화 상태 조회"""
    last_sync = service.get_last_sync_time()
    all_active = service.get_all_active()
    return {
        "last_synced_at": last_sync,
        "active_count": len(all_active),
    }


@router.get("/{councilor_id}")
async def get_councilor(
    councilor_id: str,
    service: CouncilorSyncService = Depends(_get_service),
) -> dict[str, Any]:
    """의원 상세 조회"""
    return _get_councilor_or_404(service, councilor_id)


@router.get("/{councilor_id}/detail", summary="의원 상세 — 약력·위원회·최근 발언")
async def get_councilor_detail(
    councilor_id: str,
    speeches: int = Query(8, ge=0, le=30, description="최근 발언 개수"),
    service: CouncilorSyncService = Depends(_get_service),
    supabase: Client = Depends(get_supabase),
) -> dict[str, Any]:
    """의원 한 명의 프로필·약력·소속 위원회·최근 발언을 한 번에 돌려준다.

    약력은 의회 홈페이지에만 있어 **처음 열람할 때 한 번 가져와 DB(`councilors.career`)에
    담아 둔다.** 매번 외부를 때리면 화면이 느려지고 상대 사이트에도 부담이다.
    홈페이지에 닿지 못하면 약력만 빈 채로 나머지를 돌려준다(화면이 죽지 않게).
    """
    row = _get_councilor_or_404(service, councilor_id)

    career = row.get("career") if isinstance(row.get("career"), list) else None
    positions: list[str] = []
    if not career:
        career, positions, changed = await _load_career(supabase, row)
    else:
        changed = False

    name = row.get("name") or ""
    recent = await _recent_speeches(supabase, name, speeches) if speeches else []

    return {
        "councilor": {
            "id": row.get("id"),
            "name": name,
            "party": row.get("party"),
            "district": row.get("district"),
            "district_detail": row.get("district_detail"),
            "term": row.get("term"),
            "office_number": row.get("office_number"),
            "email": row.get("email"),
            "committees": row.get("committees") or [],
            "profile_image_url": row.get("profile_image_url"),
            "homepage_url": row.get("homepage_url"),
        },
        "career": career or [],
        "positions": positions,
        "recent_speeches": recent,
        "career_refreshed": changed,
    }


async def _load_career(supabase: Client, row: dict[str, Any]) -> tuple[list[str], list[str], bool]:
    """약력을 홈페이지에서 가져와 DB 에 담는다. (약력, 직책, 저장여부)"""
    from datetime import datetime, timezone

    from app.services.councilor_profile import fetch_career, fetch_committee_roster

    member_no = row.get("member_no")
    if not member_no:
        # 의원홈페이지 번호는 위원회 명단 페이지에만 있다 — 소속 위원회 하나를 훑어 찾는다.
        committees = [c.get("name") for c in (row.get("committees") or []) if isinstance(c, dict)]
        code = _committee_code_for(committees[0]) if committees else None
        if code:
            for m in await fetch_committee_roster(code):
                if (m.get("name") or "").replace(" ", "") == (row.get("name") or "").replace(" ", ""):
                    member_no = m.get("member_no")
                    break
    if not member_no:
        return [], [], False

    got = await fetch_career(str(member_no))
    career, positions = got.get("career") or [], got.get("positions") or []
    if not career:
        return [], positions, False
    try:
        supabase.table("councilors").update({
            "member_no": str(member_no),
            "homepage_url": f"https://www.ggc.go.kr/site/lwmkr/blog/{member_no}/12",
            "career": career,
            "profile_synced_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", row["id"]).execute()
        saved = True
    except Exception as e:
        logger.warning("약력 저장 실패 %s: %s", row.get("name"), e)
        saved = False
    return career, positions, saved


def _committee_code_for(name: str | None) -> str | None:
    """위원회 이름 → ggc.go.kr 코드 (채널 설정이 이미 같은 코드를 들고 있다)."""
    if not name:
        return None
    from app.core.channels import CHANNELS

    norm = name.replace(" ", "")
    for ch in CHANNELS:
        if (ch.get("name") or "").replace(" ", "") == norm:
            return ch.get("code")
    return None


async def _recent_speeches(supabase: Client, name: str, limit: int) -> list[dict[str, Any]]:
    """이 의원의 최근 발언 — 회의 제목·시각과 함께.

    자막의 화자는 "이대한 위원"처럼 **이름 뒤에 직책이 붙는다.** 그래서 앞부분 일치로 찾는다.
    """
    if not name:
        return []
    try:
        rows = (
            supabase.table("subtitles")
            .select("id,meeting_id,start_time,text,speaker,created_at")
            .like("speaker", f"{name}%")
            .order("created_at", desc=True)
            .limit(max(limit * 4, 40))
            .execute()
        ).data or []
    except Exception as e:
        logger.warning("최근 발언 조회 실패 %s: %s", name, e)
        return []

    # 너무 짧은 추임새는 건너뛴다 — "예", "네" 가 목록을 채우면 쓸모가 없다
    rows = [r for r in rows if len((r.get("text") or "").strip()) >= 15]
    meeting_ids = list(dict.fromkeys([r["meeting_id"] for r in rows if r.get("meeting_id")]))[:12]
    meetings: dict[str, dict] = {}
    if meeting_ids:
        try:
            ms = (
                supabase.table("meetings")
                .select("id,title,committee,meeting_date,channel_id")
                .in_("id", meeting_ids)
                .execute()
            ).data or []
            meetings = {m["id"]: m for m in ms}
        except Exception as e:
            logger.debug("회의 제목 조회 실패: %s", e)

    out = []
    seen_meeting: dict[str, int] = {}
    for r in rows:
        mid = r.get("meeting_id")
        # 한 회의가 목록을 독차지하지 않게 회의당 최대 3건
        if seen_meeting.get(mid, 0) >= 3:
            continue
        seen_meeting[mid] = seen_meeting.get(mid, 0) + 1
        m = meetings.get(mid, {})
        out.append({
            "subtitle_id": r.get("id"),
            "meeting_id": mid,
            "meeting_title": m.get("title"),
            "committee": m.get("committee"),
            "meeting_date": m.get("meeting_date"),
            "start_time": r.get("start_time"),
            "speaker": r.get("speaker"),
            "text": (r.get("text") or "").strip(),
        })
        if len(out) >= limit:
            break
    return out


@router.post("/sync")
async def sync_councilors(
    service: CouncilorSyncService = Depends(_get_service),
) -> dict[str, Any]:
    """경기도의회 API에서 의원정보 동기화 (관리자용)"""
    try:
        result = await service.sync_from_api()
        return {
            "message": "동기화 완료",
            **result,
        }
    except Exception as e:
        logger.error("의원 동기화 실패: %s", e)
        raise HTTPException(
            status_code=502,
            detail=f"경기도의회 API 동기화 실패: {e}",
        ) from e


# ─── 의원 사진 (압축 프록시, 2026-07-20) ─────────────────────────────────
# ggc.go.kr 원본(_org, 수십~수백 KB)을 그대로 쓰면 위원 명단 모달이 무겁다.
# 최초 요청 시 내려받아 축소(폭 128px, JPEG q=72, ~5KB) 후 디스크 캐시.
#
# 캐시는 **쓸 수 있는 곳**에 둔다. 컨테이너 루트가 readOnlyRootFilesystem 이라
# 예전 자리(`/app/data/photo_cache`)는 `[Errno 30] Read-only file system` 으로 500 이었다
# (2026-09-16). /tmp 는 PVC 로 붙어 있어 재시작해도 남는다. 그래도 캐시는 **있으면 좋은 것**이지
# 없으면 안 되는 것이 아니다 — 쓰기에 실패하면 줄인 사진을 그냥 돌려준다.
_PHOTO_CACHE_DIR = os.environ.get("PHOTO_CACHE_DIR", "/tmp/photo_cache")


@router.get("/{councilor_id}/photo")
async def councilor_photo(
    councilor_id: str,
    supabase: Client = Depends(get_supabase),
):
    """의원 사진 (128px 축소 JPEG, 24시간 캐시)"""
    import asyncio
    import io

    import httpx
    from fastapi.responses import FileResponse, Response

    cache_path = os.path.join(_PHOTO_CACHE_DIR, f"{councilor_id}.jpg")
    headers = {"Cache-Control": "public, max-age=86400"}
    if os.path.isfile(cache_path) and os.path.getsize(cache_path) > 512:
        return FileResponse(cache_path, media_type="image/jpeg", headers=headers)

    try:
        row = (
            supabase.table("councilors")
            .select("profile_image_url")
            .eq("id", councilor_id)
            .limit(1)
            .execute()
        ).data
    except Exception as e:
        _not_found_if_bad_id(e)
        raise
    url = (row[0].get("profile_image_url") or "") if row else ""
    if not url:
        raise HTTPException(status_code=404, detail="사진이 등록되지 않았습니다.")
    if url.startswith("/"):
        url = "https://www.ggc.go.kr" + url

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            raw = resp.content
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"사진 원본 조회 실패: {e}") from e

    def _shrink() -> bytes:
        from PIL import Image

        img = Image.open(io.BytesIO(raw)).convert("RGB")
        img.thumbnail((128, 170))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=72, optimize=True)
        return buf.getvalue()

    try:
        small = await asyncio.to_thread(_shrink)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"사진 처리 실패: {e}") from e

    try:
        os.makedirs(_PHOTO_CACHE_DIR, exist_ok=True)
        # 같은 사진을 두 요청이 동시에 받으면 반쪽 파일이 남는다 — 임시 이름으로 쓰고 바꿔 끼운다
        tmp_path = f"{cache_path}.{os.getpid()}.part"
        with open(tmp_path, "wb") as f:
            f.write(small)
        os.replace(tmp_path, cache_path)
    except OSError as e:
        # 캐시를 못 써도 사진은 보여 준다
        logger.warning("사진 캐시 저장 실패(%s) — 캐시 없이 응답한다: %s", _PHOTO_CACHE_DIR, e)
        return Response(content=small, media_type="image/jpeg", headers=headers)
    return FileResponse(cache_path, media_type="image/jpeg", headers=headers)
