"""회의록 내보내기 API 라우터"""

import json
import logging
from enum import Enum
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from supabase import Client

from app.api.meetings import get_meeting_by_id_service
from app.core.auth_middleware import optional_auth
from app.core.database import get_supabase
from app.services import kordoc_service
from app.services.docx_export import export_docx
from app.services.hwpx_export import export_hwpx
from app.services.minutes_markdown import build_official_markdown
from app.services.subtitle_select import prefer_ai_subtitles as _prefer_ai_subtitles
from app.services.transcript_export import (
    _group_by_speaker,
    export_html,
    export_json,
    export_markdown,
    export_official,
    export_srt,
)
from app.services.video_minutes_service import (
    derive_chapters_llm,
    export_video_minutes_html,
    export_video_minutes_js,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meetings", tags=["exports"])


def _export_filename(meeting: dict) -> str:
    """다운로드 파일명: 위원회_제목_일자 — 제목만 봐도 어떤 회의록인지 식별 가능하게.

    예: 기획재정위원회_기획재정위원회_생중계_2026-06-11
    (제목에 위원회/일자가 이미 들어 있으면 중복 추가하지 않음)
    """
    from app.core.channels import get_committee_for_channel

    title = (meeting.get("title") or "회의록").strip()
    committee = (meeting.get("committee") or "").strip()
    if not committee and meeting.get("channel_id"):
        committee = get_committee_for_channel(meeting["channel_id"]) or ""
    date = str(meeting.get("meeting_date") or "").strip()[:10]

    parts: list[str] = []
    if committee and committee not in title:
        parts.append(committee)
    parts.append(title)
    if date and date not in title:
        parts.append(date)
    name = "_".join(parts).replace(" ", "_")
    # 파일명에 부적합한 문자 제거
    return "".join(c for c in name if c not in '\\/:*?"<>|')


class ExportFormat(str, Enum):
    MARKDOWN = "markdown"
    SRT = "srt"
    JSON = "json"
    OFFICIAL = "official"
    HTML = "html"
    HWPX = "hwpx"
    DOCX = "docx"


class HwpxEngine(str, Enum):
    """hwpx 생성 엔진 — native(자체 OWPML 라이터) | kordoc(npm, 공문서 서식)."""

    NATIVE = "native"
    KORDOC = "kordoc"


async def _kordoc_markdown_to_hwpx_or_503(markdown: str) -> bytes:
    """kordoc으로 마크다운 → hwpx 변환. 불가/실패 시 503 + 명확한 detail."""
    if not kordoc_service.is_available():
        raise HTTPException(
            status_code=503,
            detail="kordoc 엔진을 사용할 수 없습니다 — 서버에 npx(Node.js)가 설치되어 있지 않습니다.",
        )
    try:
        return await kordoc_service.markdown_to_hwpx(markdown)
    except RuntimeError as exc:
        # subprocess stderr(경로·버전 등 내부 정보)는 서버 로그로만 — detail 유출 금지.
        logger.error("kordoc hwpx 생성 실패: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="kordoc hwpx 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.",
        ) from exc


def _load_final_or_subtitle_groups(
    meeting_id: str, subtitles: list[dict], supabase: Client, authorized: bool
) -> list[dict]:
    """ai_final 라인이 있고 인증된 사용자면 최종본을, 그 외에는 subtitles를 화자그룹으로 반환.

    authorized=False(비인증)이면 ai_final 조회를 건너뛰고 항상 자막 폴백을 반환한다.
    이를 통해 미검토 최종본이 공개 엔드포인트로 노출되는 것을 방지한다.
    """
    if authorized:
        # stenography_records 테이블이 없는 환경(마이그레이션 010/020 미적용)에서도
        # 500이 아니라 자막 폴백으로 동작해야 한다 (fail-soft).
        try:
            rec = (
                supabase.table("stenography_records").select("id")
                .eq("meeting_id", meeting_id).eq("kind", "ai_final").limit(1).execute().data
            )
        except Exception:
            logger.warning("ai_final 조회 실패 — 자막 폴백 사용 (meeting_id=%s)", meeting_id)
            rec = None
        if rec:
            lines = (
                supabase.table("stenography_lines").select("*")
                .eq("record_id", rec[0]["id"]).order("sequence_no").execute().data or []
            )
            as_subs = [
                {
                    "text": ln.get("text", ""),
                    "speaker": ln.get("speaker"),
                    "start_time": (ln.get("start_ms") or 0) / 1000.0,
                    "end_time": (ln.get("end_ms") or 0) / 1000.0,
                }
                for ln in lines
            ]
            return _group_by_speaker(as_subs)
    return _group_by_speaker(subtitles)


def _fetch_agendas(supabase: Client, meeting_id: str) -> list[dict]:
    """회의 안건 목록(의사일정/심사된 안건)을 order_num 순으로 조회. 없으면 빈 목록."""
    try:
        result = (
            supabase.table("meeting_agendas")
            .select("order_num,title,description")
            .eq("meeting_id", meeting_id)
            .order("order_num")
            .execute()
        )
        return result.data or []
    except Exception:
        return []


def _fetch_all_subtitles(supabase: Client, meeting_id: str) -> list[dict]:
    """회의의 전체 자막을 시간순으로 조회합니다."""
    all_subtitles = []
    offset = 0
    page_size = 1000

    while True:
        result = (
            supabase.table("subtitles")
            .select("*")
            .eq("meeting_id", meeting_id)
            .order("start_time")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        if not result.data:
            break
        all_subtitles.extend(result.data)
        if len(result.data) < page_size:
            break
        offset += page_size

    return all_subtitles


def _fetch_export_subtitles(supabase: Client, meeting_id: str) -> list[dict]:
    """회의록 내보내기용 자막 — AI 자막(화자구분)을 우선 조회한다."""
    return _prefer_ai_subtitles(_fetch_all_subtitles(supabase, meeting_id))


@router.get(
    "/{meeting_id}/export",
    summary="회의록 내보내기",
    description="회의 자막을 지정 형식으로 내보냅니다. (markdown, srt, json, official)",
)
async def export_meeting_transcript(
    meeting_id: str,
    format: ExportFormat = Query(
        ExportFormat.MARKDOWN, description="내보내기 형식"
    ),
    engine: HwpxEngine = Query(
        HwpxEngine.NATIVE,
        description="hwpx 생성 엔진: native(기본, 자체 OWPML) | kordoc(공문서 서식). "
        "hwpx 외 형식에서는 무시됩니다.",
    ),
    supabase: Client = Depends(get_supabase),
    _user: dict | None = Depends(optional_auth),
):
    """회의록 내보내기 — 공개 형식(markdown/srt/json/official/html)은 인증 불필요.
    hwpx의 ai_final 최종본은 인증 사용자에게만 제공되며, 비인증 시 자막 폴백.
    """
    meeting = get_meeting_by_id_service(supabase, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="회의를 찾을 수 없습니다.")

    subtitles = _fetch_export_subtitles(supabase, meeting_id)

    # AI 요약 조회 (있으면 포함)
    summary = None
    try:
        result = (
            supabase.table("meeting_summaries")
            .select("*")
            .eq("meeting_id", meeting_id)
            .execute()
        )
        if result.data:
            summary = result.data[0]
    except Exception:
        pass  # 요약 테이블 없어도 무시

    base_name = _export_filename(meeting)

    # hwpx/docx는 bytes를 반환하고 별도 미디어 타입·확장자를 사용하므로 분기 처리
    if format in (ExportFormat.HWPX, ExportFormat.DOCX):
        grouped = _load_final_or_subtitle_groups(
            meeting_id, subtitles, supabase, authorized=_user is not None
        )
        if format == ExportFormat.HWPX:
            # 의사일정/안건: 미등록 회의는 자막(원천데이터)에서 추출·저장해 채운다.
            # LLM 비용 방지를 위해 인증 사용자만 추출(저장분은 이후 모두가 재사용).
            if _user is not None:
                from app.services.agenda_draft_service import ensure_agendas

                try:
                    agendas = await ensure_agendas(supabase, meeting_id)
                except Exception:
                    agendas = _fetch_agendas(supabase, meeting_id)
            else:
                agendas = _fetch_agendas(supabase, meeting_id)
            if engine == HwpxEngine.KORDOC:
                # kordoc 변환은 node 서브프로세스로 서버 자원을 사용하므로 로그인
                # 사용자 전용 (video-minutes/minutes-markdown과 동일한 401 패턴).
                # native 기본 경로(export_hwpx)는 기존대로 비로그인 허용.
                if _user is None:
                    raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
                # kordoc 엔진: 동일 데이터로 마크다운 중간층을 만들고 공문서 서식 hwpx 생성
                markdown = build_official_markdown(meeting, grouped, agendas)
                payload = await _kordoc_markdown_to_hwpx_or_503(markdown)
            else:
                payload = export_hwpx(meeting, grouped, agendas)
            ext, media = "hwpx", "application/hwp+zip"
        else:
            payload = export_docx(meeting, grouped)
            ext = "docx"
            media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        encoded_name = quote(f"{base_name}.{ext}")
        disposition = f"attachment; filename*=UTF-8''{encoded_name}"
        return Response(
            content=payload,
            media_type=media,
            headers={"Content-Disposition": disposition},
        )

    ext_map = {
        ExportFormat.MARKDOWN: ("text/markdown; charset=utf-8", "md"),
        ExportFormat.SRT: ("text/plain; charset=utf-8", "srt"),
        ExportFormat.JSON: ("application/json; charset=utf-8", "json"),
        ExportFormat.OFFICIAL: ("text/plain; charset=utf-8", "txt"),
        ExportFormat.HTML: ("text/html; charset=utf-8", "html"),
    }
    media_type, ext = ext_map[format]
    # RFC 5987: 한글 파일명을 UTF-8 URL-인코딩
    encoded_name = quote(f"{base_name}.{ext}")
    disposition = f"attachment; filename*=UTF-8''{encoded_name}"

    if format == ExportFormat.MARKDOWN:
        content = export_markdown(meeting, subtitles, summary=summary)
    elif format == ExportFormat.SRT:
        content = export_srt(subtitles)
    elif format == ExportFormat.OFFICIAL:
        content = export_official(meeting, subtitles, summary=summary)
    elif format == ExportFormat.HTML:
        content = export_html(meeting, subtitles, summary=summary)
    else:
        data = export_json(meeting, subtitles)
        content = json.dumps(data, ensure_ascii=False, indent=2)

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )


# ─── kordoc 마크다운 중간층 (미리보기/편집 → hwpx 재생성) ─────────────────────

#: 편집 마크다운 최대 크기(2MB) — 초과 시 413
_MAX_MARKDOWN_BYTES = 2 * 1024 * 1024


class HwpxFromMarkdownRequest(BaseModel):
    """편집된 회의록 마크다운 → hwpx 재생성 요청 바디."""

    markdown: str


@router.get(
    "/{meeting_id}/minutes-markdown",
    summary="회의록 마크다운(미리보기/편집용)",
    description="공식 전자회의록과 동일한 구조의 마크다운 중간층을 반환합니다. "
    "편집 후 hwpx-from-markdown으로 공문서 서식 hwpx를 재생성할 수 있습니다.",
)
async def get_minutes_markdown(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
    _user: dict | None = Depends(optional_auth),
):
    """회의록 마크다운 조회 — hwpx(ai_final) 접근과 동일하게 로그인 사용자 전용."""
    if _user is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    meeting = get_meeting_by_id_service(supabase, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="회의를 찾을 수 없습니다.")

    subtitles = _fetch_export_subtitles(supabase, meeting_id)
    grouped = _load_final_or_subtitle_groups(
        meeting_id, subtitles, supabase, authorized=True
    )
    if not grouped:
        raise HTTPException(
            status_code=409,
            detail="자막이 없어 회의록 마크다운을 만들 수 없습니다. 먼저 AI 자막을 생성하세요.",
        )

    # 의사일정/안건: hwpx 내보내기와 동일 로직 (미등록 시 자막에서 추출·저장, 실패 시 폴백)
    try:
        from app.services.agenda_draft_service import ensure_agendas

        agendas = await ensure_agendas(supabase, meeting_id)
    except Exception:
        agendas = _fetch_agendas(supabase, meeting_id)

    return {
        "markdown": build_official_markdown(meeting, grouped, agendas),
        "kordoc_available": kordoc_service.is_available(),
    }


@router.post(
    "/{meeting_id}/export/hwpx-from-markdown",
    summary="편집 마크다운 → hwpx 재생성",
    description="편집된 회의록 마크다운을 kordoc(회의록 preset)으로 공문서 서식 "
    "hwpx로 변환해 다운로드합니다.",
)
async def export_hwpx_from_markdown(
    meeting_id: str,
    body: HwpxFromMarkdownRequest,
    supabase: Client = Depends(get_supabase),
    _user: dict | None = Depends(optional_auth),
):
    """편집 마크다운 → hwpx — 로그인 사용자 전용. 2MB 초과 시 413, kordoc 불가 시 503."""
    if _user is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    if len(body.markdown.encode("utf-8")) > _MAX_MARKDOWN_BYTES:
        raise HTTPException(
            status_code=413, detail="마크다운이 최대 크기(2MB)를 초과했습니다."
        )

    meeting = get_meeting_by_id_service(supabase, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="회의를 찾을 수 없습니다.")

    payload = await _kordoc_markdown_to_hwpx_or_503(body.markdown)

    base_name = f"{_export_filename(meeting)}_edited"
    encoded_name = quote(f"{base_name}.hwpx")
    return Response(
        content=payload,
        media_type="application/hwp+zip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"
        },
    )


@router.get(
    "/{meeting_id}/video-minutes",
    summary="영상회의록 안건시간(KMS 등록용)",
    description="자막에서 영상회의록 챕터(회의 개의/안건/제안설명/검토보고/질의답변)를 도출해 "
    "KMS 영상회의록 '안건 시간 등록'용으로 반환합니다. "
    "format=html(표·플레이어) | json | js(KMS 편집기 콘솔 자동입력 스크립트).",
)
async def export_video_minutes(
    meeting_id: str,
    format: str = Query("html", description="출력 형식: html | json | js"),
    supabase: Client = Depends(get_supabase),
    _user: dict | None = Depends(optional_auth),
):
    """영상회의록 안건시간 — LLM으로 챕터를 도출(비용 발생)하므로 로그인 사용자만 허용."""
    if _user is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    meeting = get_meeting_by_id_service(supabase, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="회의를 찾을 수 없습니다.")

    subtitles = _fetch_export_subtitles(supabase, meeting_id)
    if not subtitles:
        raise HTTPException(
            status_code=409,
            detail="자막이 없어 영상회의록 안건시간을 만들 수 없습니다. 먼저 AI 자막을 생성하세요.",
        )

    # 안건은 미등록 시 자막에서 추출·저장(개선된 전체 스캔).
    try:
        from app.services.agenda_draft_service import ensure_agendas

        agendas = await ensure_agendas(supabase, meeting_id)
    except Exception:
        agendas = _fetch_agendas(supabase, meeting_id)

    # ★임시속기록(정확한 안건명·이름·직책)이 있으면 하이브리드로 정확도 향상.
    #   파이프라인: 실시간 자막 → AI 자막생성 → (속기사 게시)임시속기록 → 이 단계.
    #   속기록 미게시 회의는 결정론+LLM(derive_chapters_llm)로 폴백.
    from app.services.video_minutes_service import _is_plenary, derive_chapters_hybrid

    chapters = None
    if not _is_plenary(meeting):
        try:
            from app.services.steno_service import get_meeting_steno

            steno = await get_meeting_steno(meeting)
            if steno:
                chapters = await derive_chapters_hybrid(meeting, subtitles, agendas, steno)
        except Exception:
            chapters = None
    if not chapters:
        # 회의 글로서리(의원명·의안명·용어)로 이름·안건명 표기 정확도 보완(텍스트 전용, 저비용).
        try:
            from app.services.glossary_service import load_meeting_glossary

            glossary = load_meeting_glossary(supabase, meeting_id)
        except Exception:
            glossary = None
        # 위원회 명부 — 챕터 라벨의 위원 이름 오인식(명부 밖 이름)을 명부 표기로 교정.
        try:
            from app.services.hwpx_export import _parse_meeting_title
            from app.services.roster_loader import load_committee_with_roles

            committee = (meeting.get("committee") or "").strip() or _parse_meeting_title(
                meeting
            ).get("committee")
            roster_names = [
                r["name"] for r in load_committee_with_roles(supabase, committee) if r.get("name")
            ] or None
        except Exception:
            roster_names = None
        chapters = await derive_chapters_llm(meeting, subtitles, agendas, glossary, roster_names)

    if format == "json":
        return {
            "meeting_id": meeting_id,
            "title": meeting.get("title"),
            "chapters": chapters,
        }

    if format == "js":
        js_doc = export_video_minutes_js(meeting, chapters)
        base_name = _export_filename(meeting)
        encoded_name = quote(f"{base_name}_영상회의록_KMS등록.js")
        return Response(
            content=js_doc,
            media_type="application/javascript; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
        )

    html_doc = export_video_minutes_html(meeting, chapters)
    base_name = _export_filename(meeting)
    encoded_name = quote(f"{base_name}_영상회의록.html")
    disposition = f"attachment; filename*=UTF-8''{encoded_name}"
    return Response(
        content=html_doc,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": disposition},
    )
