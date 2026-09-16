"""임시속기록(KMS 임시회의록) 연결·수집 서비스.

영상회의록 챕터 정확도를 위해, 회의에 해당하는 KMS 임시속기록을 자동으로 찾아 본문을
가져온다. 파이프라인: 실시간 자막 → AI 자막생성 → (속기사가 게시한)임시속기록 → 본 서비스.

- 회의(회기·차수·위원회·날짜) → KMS 최근목록(MntsLatelyList)에서 mntsId 매칭
- mntsId → mntsViewer 본문(<div id=mntshtmlviewer>) 텍스트 추출
속기록이 없으면(미게시) None — 호출측은 결정론 폴백.
"""

from __future__ import annotations

import logging
import re

import httpx

from app.services.hwpx_export import _parse_meeting_title

logger = logging.getLogger(__name__)

_LIST_URL = "https://kms.ggc.go.kr/svc/cms/mnts/MntsLatelyList.do"
_VIEWER_URL = "https://kms.ggc.go.kr/cms/mntsViewer.do"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def _parse_list(html: str) -> list[dict]:
    """최근 임시회의록 목록 → [{mntsid, session, round, committee, date}]."""
    out: list[dict] = []
    for m in re.finditer(r'mntsViewer\.do\?mntsId=(\d+)"\s+title="([^"]+)"', html):
        mntsid, title = m.group(1), m.group(2)
        sess = re.search(r"제\s*(\d+)\s*회", title)
        rnd = re.search(r"제\s*(\d+)\s*차", title)
        comm = re.search(r"([가-힣]+위원회|본회의)", title)
        date = re.search(r"(\d{4})\.(\d{2})\.(\d{2})", title)
        out.append({
            "mntsid": mntsid,
            "session": sess.group(1) if sess else None,
            "round": rnd.group(1) if rnd else None,
            "committee": comm.group(1) if comm else None,
            "date": f"{date.group(1)}-{date.group(2)}-{date.group(3)}" if date else None,
        })
    return out


def _committee_match(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return a in b or b in a


def _resolve_committee(meeting: dict) -> str:
    """회의 dict에서 위원회명을 해석한다 (제목 → committee 필드 → 채널 순)."""
    info = _parse_meeting_title(meeting)
    committee = info.get("committee") or (meeting.get("committee") or "")
    if not committee and meeting.get("channel_id"):
        from app.core.channels import get_committee_for_channel
        committee = get_committee_for_channel(meeting["channel_id"]) or ""
    return committee


def _update_staff_roster(committee: str, steno_text: str, mntsid: str) -> None:
    """속기록 출석 명단 → staff_roster 갱신 훅 (fire-and-forget).

    실패해도 기존 속기록 수집 흐름에 영향을 주지 않는다
    (마이그레이션 미적용/DB 미설정 환경 포함).
    """
    try:
        from app.core.database import get_supabase_client
        from app.services.staff_roster_service import (
            parse_steno_attendance,
            upsert_staff_roster,
        )

        if not committee:
            return
        entries = parse_steno_attendance(steno_text)
        if not entries:
            return
        n = upsert_staff_roster(
            get_supabase_client(), committee, entries, source_mntsid=mntsid
        )
        logger.info("staff_roster 갱신: %s %d명 (mntsId=%s)", committee, n, mntsid)
    except Exception as e:
        logger.warning("staff_roster 갱신 실패(무시): %s", e)


async def find_mntsid(meeting: dict) -> str | None:
    """회의에 해당하는 임시속기록 mntsId를 최근목록에서 찾는다(없으면 None)."""
    info = _parse_meeting_title(meeting)
    committee = _resolve_committee(meeting)
    date = str(meeting.get("meeting_date") or "")[:10]
    try:
        async with httpx.AsyncClient(timeout=30.0) as cli:
            r = await cli.get(_LIST_URL, headers=_UA, follow_redirects=True)
        entries = _parse_list(r.content.decode("utf-8", errors="replace"))
    except Exception as e:
        logger.warning("임시속기록 목록 조회 실패: %s", e)
        return None

    for e in entries:
        if e["session"] == info.get("session") and e["round"] == info.get("round") \
                and _committee_match(e["committee"], committee):
            if not date or not e["date"] or e["date"] == date:
                return e["mntsid"]
    return None


async def fetch_steno_text(mntsid: str) -> str:
    """mntsViewer 본문(<div id=mntshtmlviewer>)을 텍스트로 추출."""
    try:
        async with httpx.AsyncClient(timeout=60.0) as cli:
            r = await cli.get(_VIEWER_URL, params={"mntsId": mntsid}, headers=_UA, follow_redirects=True)
        html = r.content.decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("임시속기록 본문 조회 실패(mntsId=%s): %s", mntsid, e)
        return ""
    start = re.search(r'<div\s+id=["\']mntshtmlviewer["\']', html)
    if not start:
        return ""
    body = html[start.end():]
    end = re.search(r'<div\s+class=["\']pageTopBtn["\']', body)
    if end:
        body = body[:end.start()]
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", body, flags=re.S)
    body = re.sub(r"<br\s*/?>", "\n", body)
    body = re.sub(r"</(p|div|td|tr|h\d|li)>", "\n", body)
    body = re.sub(r"<[^>]+>", "", body)
    body = body.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    body = re.sub(r"&#?\w+;", "", body)
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    return "\n".join(lines)


async def get_meeting_steno(meeting: dict) -> str | None:
    """회의의 임시속기록 본문(없으면 None)."""
    mntsid = await find_mntsid(meeting)
    if not mntsid:
        logger.info("임시속기록 미발견: %s", meeting.get("title"))
        return None
    text = await fetch_steno_text(mntsid)
    if text:
        # 출석 명단 → 위원회별 집행부 명부 갱신 (실패해도 무시)
        _update_staff_roster(_resolve_committee(meeting), text, mntsid)
    return text or None
