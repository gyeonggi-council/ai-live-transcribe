"""부서별 회의 문서 API (2026-09-15) — 버튼을 눌렀을 때만 만든다. 규칙·서식은 services/meeting_documents.

  GET  /api/meetings/{id}/documents/options                 부서·자료요구·요약 유무(AI 호출 없음)
  POST /api/meetings/{id}/documents/{kind}?department=&request_id=&format=hwpx|json
       kind = monitoring | datareq-list | datareq-cover | press
       datareq-cover 는 request_id 가 있으면 표지 1장(HWPX), 없으면 (부서) 표지 묶음 ZIP
       format=json 은 미리보기(문서 엔진을 부르지 않는다)
권한은 요약과 같다 — 로그인 AI 역할 또는 의회망 손님(담당자 결정 2026-09-15).
"""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from supabase import Client

from app.core.auth_middleware import AI_ROLES, require_role_or_council
from app.core.database import get_supabase
from app.services import meeting_documents as md
from app.services import doc_profile
from app.services.doc_engine import DocEngineError, fill_hwpx, generate_hwpx

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/meetings", tags=["meeting-documents"])
KINDS = {"monitoring", "datareq-list", "datareq-cover", "press"}


def _load(supabase: Client, meeting_id: str) -> dict:
    from app.services.subtitle_embeddings import fingerprint
    from app.services.subtitle_fetch import fetch_all_subtitles
    from app.services.subtitle_select import prefer_ai_subtitles

    meeting = (supabase.table("meetings").select("id, title, meeting_date, committee, status")
               .eq("id", meeting_id).limit(1).execute().data or [None])[0]
    if not meeting:
        raise HTTPException(status_code=404, detail="회의를 찾을 수 없습니다.")
    subs = prefer_ai_subtitles(fetch_all_subtitles(supabase, meeting_id) or [])
    agendas = [a for a in (supabase.table("meeting_agendas").select("order_num, title").eq("meeting_id", meeting_id)
                           .order("order_num").execute().data or []) if a.get("title")]
    requests = supabase.table("material_requests").select("*").eq("meeting_id", meeting_id).execute().data or []
    try:
        staff = supabase.table("staff_roster").select("name, title").eq("committee", meeting.get("committee") or "").execute().data or []
    except Exception:
        staff = []
    staff_titles = {**md.intro_titles(subs), **{s["name"]: s.get("title") for s in staff if s.get("name") and s.get("title")}}
    summary = (supabase.table("meeting_summaries").select("*").eq("meeting_id", meeting_id).limit(1).execute().data or [None])[0]
    known, _ = md.label_departments(subs, staff_titles)
    for r in requests:
        d = md.normalize_department(r.get("department"), known)
        if d != "미분류" and d not in known:
            known.append(d)
    return {"meeting": meeting, "subs": subs, "agendas": agendas, "requests": requests, "staff_titles": staff_titles,
            "summary": summary, "departments": known, "fingerprint": fingerprint(subs, agendas)}


@router.get("/{meeting_id}/documents/options")
async def document_options(
    meeting_id: str,
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role_or_council(*AI_ROLES)),
) -> dict:
    ctx = await asyncio.to_thread(_load, supabase, meeting_id)
    reqs = md.datareq_rows(ctx["requests"], ctx["departments"], None)
    return {
        "committee_short": md.committee_short(ctx["meeting"].get("committee")),
        "departments": ctx["departments"],
        "material_requests": [{"id": r["id"], "councilor": r["name"], "summary": r.get("summary"), "department": r["dept"]}
                              for r in reqs],
        "has_summary": bool(ctx["summary"] and ctx["summary"].get("summary_text")),
        "has_subtitles": bool(ctx["subs"]),
    }


def _file_response(data: bytes, filename: str, media_type: str, disposition: str | None = None) -> Response:
    cd = disposition or f"attachment; filename=\"document\"; filename*=UTF-8''{quote(filename)}"
    return Response(content=data, media_type=media_type, headers={"Content-Disposition": cd, "Cache-Control": "no-store"})


async def _generate_like_form(text: str, title: str, form: str):
    """서식([서식1]·[서식2])의 표 서식을 입혀 만든다.

    프로필을 못 얻으면(이미지에 서식 없음·엔진 오류) **프로필 없이** 만든다 —
    모양은 예전과 같지만 문서는 나온다. 문서가 아예 안 나오는 것이 가장 나쁘다.
    """
    profile = await asyncio.to_thread(doc_profile.profile_for, form, body_rows=md.body_rows(text))
    return await asyncio.to_thread(generate_hwpx, text, title=title, profile=profile)


async def _make_cover(req: dict):
    """요구자료 표지 — [서식3] 파일에 값만 채운다. 서식이 없으면 마크다운으로 만든다."""
    values, edits, title = md.cover_fill(req)
    template = doc_profile.form_bytes("datareq_cover")
    if template:
        try:
            data, cd = await asyncio.to_thread(fill_hwpx, template, title=title, values=values, edits=edits)
            return data, cd, title
        except DocEngineError as e:
            logger.warning("표지 서식 채우기 실패(마크다운으로 대신한다): %s", e.detail)
    text, title = md.cover_markdown(req)
    data, cd = await asyncio.to_thread(generate_hwpx, text, title=title)
    return data, cd, title


@router.post("/{meeting_id}/documents/{kind}")
async def make_document(
    meeting_id: str,
    kind: str,
    department: str | None = Query(None, max_length=60),
    request_id: str | None = Query(None, max_length=64),
    format: str = Query("hwpx", pattern="^(hwpx|json)$"),
    supabase: Client = Depends(get_supabase),
    _user: dict = Depends(require_role_or_council(*AI_ROLES)),
):
    if kind not in KINDS:
        raise HTTPException(status_code=404, detail="모르는 문서 종류입니다.")
    ctx = await asyncio.to_thread(_load, supabase, meeting_id)
    meeting = ctx["meeting"]
    dept = (department or "").strip() or None
    try:
        if kind == "monitoring":
            if not ctx["subs"]:
                raise md.NoDataError("자막이 없는 회의입니다.")
            items = await md.extract_monitoring(ctx["subs"], ctx["fingerprint"], meeting_id, ctx["staff_titles"])
            if format == "json":
                return {"rows": [i for i in items if not dept or dept in i.get("departments", [])],
                        "departments": sorted({d for i in items for d in i.get("departments", [])})}
            text, title = md.monitoring_markdown(meeting, ctx["agendas"], items, dept)
            data, cd = await _generate_like_form(text, title, "monitoring")
            return _file_response(data, title + ".hwpx", "application/vnd.hancom.hwpx", cd)
        if kind == "datareq-list":
            rows = md.datareq_rows(ctx["requests"], ctx["departments"], dept)
            if format == "json":
                return {"rows": [{"name": r["name"], "summary": r.get("summary"), "department": r["dept"]} for r in rows]}
            text, title = md.datareq_list_markdown(meeting, ctx["agendas"], rows, dept)
            data, cd = await _generate_like_form(text, title, "datareq_list")
            return _file_response(data, title + ".hwpx", "application/vnd.hancom.hwpx", cd)
        if kind == "datareq-cover":
            rows = md.datareq_rows(ctx["requests"], ctx["departments"], dept)
            if request_id:
                rows = [r for r in rows if str(r.get("id")) == request_id]
            if not rows:
                raise md.NoDataError("표지를 만들 자료요구가 없습니다.")
            if format == "json":
                return {"rows": [{"id": r["id"], "name": r["name"], "summary": r.get("summary")} for r in rows]}
            if request_id:
                data, cd, title = await _make_cover(rows[0])
                return _file_response(data, title + ".hwpx", "application/vnd.hancom.hwpx", cd)
            files = []
            for r in rows:
                data, _, title = await _make_cover(r)
                files.append((title + ".hwpx", data))
            ymd, _ = md._date_parts(meeting)
            name = f"{ymd} {md.committee_short(meeting.get('committee'))} 요구자료 표지" + (f"_{dept}" if dept else "") + ".zip"
            return _file_response(md.zip_bytes(files), name, "application/zip")
        # press
        text, title = await md.press_release(meeting, ctx["summary"] or {}, ctx["subs"])
        if format == "json":
            return {"markdown": text, "title": title}
        data, cd = await asyncio.to_thread(generate_hwpx, text, title=title, preset="보도자료")
        return _file_response(data, title + ".hwpx", "application/vnd.hancom.hwpx", cd)
    except md.NoDataError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except md.DocumentLimitError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except DocEngineError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("문서 만들기 실패: %s %s", kind, meeting_id)
        raise HTTPException(status_code=502, detail=f"문서를 만들지 못했습니다({type(e).__name__}). 잠시 뒤 다시 시도해 주세요.")
