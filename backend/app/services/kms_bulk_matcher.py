"""KMS 최근 VOD 목록을 파싱해 DB의 vod_url 미등록 회의와 일괄 매칭하는 서비스.

사용 흐름:
1. `fetch_recent_vod_list()` — KMS /caster/content/vms/VodLatelyList.do 페이지 크롤링
2. 각 행에서 회기/차수/위원회명/날짜/재생시간/페이지 URL 추출
3. `match_and_update()` — DB에서 vod_url이 null인 meetings를 찾아 매칭 후
   `resolve_kms_vod_url()`로 MP4 직접 링크 추출 후 UPDATE

매칭 규칙:
- meeting_date 일치 +
- KMS 제목의 위원회명이 DB meeting 제목에 포함(또는 역방향 포함)

의존성: httpx, re — 추가 패키지 없이 표준 정규식만 사용.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

import httpx
from supabase import Client

from app.core.config import settings
from app.services.grammar_checker import check_grammar_batch
from app.services.kms_vod_resolver import VodNotConvertedError, resolve_kms_vod_url
from app.services.vod_stt_service import VodSttService, is_processing

logger = logging.getLogger(__name__)

KMS_LIST_URL = f"{settings.kms_base_url.rstrip('/')}/caster/content/vms/VodLatelyList.do?confcode=N"
KMS_HOST = settings.kms_base_url.rstrip("/")

# <tr> 블록 내에서 각 필드를 추출하는 정규식
_ROW_REGEX = re.compile(r"<tr>(.*?)</tr>", re.DOTALL)
_TD_NUM_REGEX = re.compile(r'class=["\']v_num["\']>\s*(\d+)\s*</td>')
_SESSION_REGEX = re.compile(r"제\s*(\d+)\s*회")
_ORDER_REGEX = re.compile(r"제\s*(\d+)\s*차")
_TITLE_A_REGEX = re.compile(
    r'href=["\'](/caster/player/vodViewer\.do\?midx=\d+[^"\']*)["\'][^>]*>\s*(.*?)\s*</a>',
    re.DOTALL,
)
_DATE_REGEX = re.compile(r'class=["\']v_date["\']>\s*(\d{4})\.(\d{2})\.(\d{2})')
_DURATION_REGEX = re.compile(
    r'class=["\']v_time["\']>\s*(\d{1,2}):(\d{2}):(\d{2})\s*</td>'
)


def _clean_html(s: str) -> str:
    """HTML 태그 제거 + 엔티티 디코드 + 공백 정규화.

    당일 영상 제목에는 '<span class="qvod">퀵 VOD</span>' 배지가 섞여 오므로
    (2026-07-07 제392회 1차 본회의에서 실측) 태그 안 내용까지 함께 제거한다.
    """
    s = re.sub(r"<span[^>]*>.*?</span>", "", s, flags=re.S)  # 배지류: 내용째 제거
    s = re.sub(r"<[^>]+>", "", s)  # 잔여 태그는 태그만 제거
    s = s.replace("&amp;", "&").replace("&nbsp;", " ").replace("&quot;", '"')
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _extract_committee(title: str) -> str:
    """'제389회 제1차 미래과학협력위원회' → '미래과학협력위원회'.

    회기·차수 접두사를 모두 제거하고 남은 문자열 반환.
    패턴이 안 맞으면 원문 그대로 반환 (매칭 실패해도 DB 제목 비교로 커버).
    """
    m = re.search(r"제\s*\d+\s*회\s+제\s*\d+\s*차\s+(.+)$", title)
    if m:
        return m.group(1).strip()
    # 회기만 있는 경우 (예: '제389회 본회의')
    m2 = re.search(r"제\s*\d+\s*회\s+(.+)$", title)
    if m2:
        return m2.group(1).strip()
    return title.strip()


def _parse_vod_rows(html: str) -> list[dict[str, Any]]:
    """KMS 목록 페이지 HTML에서 회의 행들을 파싱한다."""
    entries: list[dict[str, Any]] = []
    for row_html in _ROW_REGEX.findall(html):
        # 헤더 행 또는 비어있는 행 필터링
        num_match = _TD_NUM_REGEX.search(row_html)
        title_match = _TITLE_A_REGEX.search(row_html)
        date_match = _DATE_REGEX.search(row_html)
        if not (num_match and title_match and date_match):
            continue

        href = title_match.group(1)
        title = _clean_html(title_match.group(2))
        session = _SESSION_REGEX.search(title)
        order = _ORDER_REGEX.search(title)

        date_ymd = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"

        # 재생시간은 행에서 2개 <td class=v_time>이 있음 — 두 번째가 실제 duration
        durations = _DURATION_REGEX.findall(row_html)
        duration_seconds = 0
        if durations:
            h, mi, s = durations[-1]
            duration_seconds = int(h) * 3600 + int(mi) * 60 + int(s)

        page_url = f"{KMS_HOST}{href}".replace("&amp;", "&")
        midx_match = re.search(r"midx=(\d+)", page_url)

        entries.append(
            {
                "list_num": int(num_match.group(1)),
                "kms_midx": int(midx_match.group(1)) if midx_match else None,
                "session_no": int(session.group(1)) if session else None,
                "session_order": int(order.group(1)) if order else None,
                "title": title,
                "committee": _extract_committee(title),
                "meeting_date": date_ymd,
                "duration_seconds": duration_seconds,
                "page_url": page_url,
            }
        )
    return entries


async def fetch_recent_vod_list(pages: int = 1) -> list[dict[str, Any]]:
    """KMS 최근회의영상 목록을 파싱해 반환.

    pages>1이면 ?p=N 페이지네이션으로 이전 페이지까지 누적한다 (페이지당 15건).
    KMS 목록은 본회의·상임위·특위를 회차 역순으로 한 목록에 섞어 보여주므로,
    한 회기 전체(예: 391회 ~20건)를 받으려면 2페이지면 충분하다.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; GGC-Subtitle-Bot/1.0)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }
    all_entries: list[dict[str, Any]] = []
    seen: set = set()
    async with httpx.AsyncClient(timeout=30.0) as client:
        for p in range(1, max(1, pages) + 1):
            url = KMS_LIST_URL + (f"&p={p}" if p > 1 else "")
            res = await client.get(url, headers=headers)
            res.raise_for_status()
            page_entries = _parse_vod_rows(res.text)
            fresh = [e for e in page_entries if e.get("kms_midx") not in seen]
            for e in fresh:
                seen.add(e.get("kms_midx"))
            all_entries.extend(fresh)
            if not fresh:  # 더 이상 새 항목이 없으면 조기 종료
                break
    return all_entries


# meetings.kms_no(의회 홈페이지 목록 번호) 컬럼 존재 여부 캐시 —
# 마이그레이션 전 환경에서도 일괄 등록이 동작하도록 방어적으로 감지한다.
_KMS_NO_COLUMN: bool | None = None


def _has_kms_no_column(supabase: Client) -> bool:
    global _KMS_NO_COLUMN
    if _KMS_NO_COLUMN is None:
        try:
            supabase.table("meetings").select("kms_no").limit(1).execute()
            _KMS_NO_COLUMN = True
        except Exception:
            _KMS_NO_COLUMN = False
            logger.info("meetings.kms_no 컬럼 없음 — 의회 번호 저장 생략 (마이그레이션 필요)")
    return _KMS_NO_COLUMN


def _match_meeting_to_entry(
    meeting: dict[str, Any], entries: Iterable[dict[str, Any]]
) -> dict[str, Any] | None:
    """회의 1건에 대한 KMS 후보 1건을 찾습니다.

    1순위: meeting_date 일치 + 위원회명이 서로 포함
    2순위: meeting_date 일치 (위원회명 일치는 못 했지만 해당 일자 후보 1건뿐일 때)
    """
    meeting_date = meeting.get("meeting_date")
    meeting_title = (meeting.get("title") or "").strip()

    same_date = [e for e in entries if e["meeting_date"] == meeting_date]

    # 1. 위원회명 교차 매칭
    for e in same_date:
        committee = e["committee"]
        if committee and (committee in meeting_title or meeting_title in e["title"]):
            return e
        # 단어 공통 부분 확인 — 공백 제거 후 비교 (예: '생중계' 접미 무시)
        stripped = meeting_title.replace(" ", "").replace("생중계", "")
        if committee and committee.replace(" ", "") in stripped:
            return e

    # 2. 해당 일자 후보가 유일하면 그것으로 채택 — 단, 양쪽 모두 위원회명이
    #    있고 서로 다르면 채택하지 않는다 (예: '교육기획위원회 생중계'가 같은 날
    #    유일 후보라는 이유로 교육행정위 영상에 붙던 오매칭 — vod_url 유니크
    #    제약이 막아줬지만 규칙 자체를 안전하게).
    if len(same_date) == 1:
        e = same_date[0]
        m_comm = re.search(r"([가-힣]+위원회)", meeting_title)
        e_comm = (e.get("committee") or "")
        if m_comm and "위원회" in e_comm and m_comm.group(1) != e_comm:
            return None
        return e

    return None


async def _vod_reachable(vod_url: str, timeout: float = 20.0) -> bool:
    """VOD URL에 실제 접속 가능한지 Range 요청으로 사전 체크.

    True 리턴 시에만 기존 자막을 삭제하고 재생성 진행해야 함 (자막 손실 방지).
    """
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            # KMS 보안정책(2026-07-21): 비브라우저 UA 차단 → 브라우저형 헤더 필수
            from app.services.kms_vod_resolver import KMS_BROWSER_HEADERS

            r = await client.get(
                vod_url,
                headers={**KMS_BROWSER_HEADERS, "Range": "bytes=0-1023"},
            )
            if r.status_code not in (200, 206):
                logger.warning("vod_reachable: %s → HTTP %s", vod_url, r.status_code)
                return False
            return True
    except Exception as e:
        logger.warning("vod_reachable: %s → %s", vod_url, e)
        return False


async def _regenerate_pipeline(
    meeting_id: str, vod_url: str, supabase: Client
) -> None:
    """한 회의에 대한 재생성 파이프라인 (safe-delete):
    0) VOD URL 접속 가능 여부 HEAD 체크 (실패 시 기존 자막 유지, 조용히 skip)
    1) 접속 가능 시에만 기존 자막 삭제
    2) VOD STT 재실행  3) AI 문법 교정 적용
    """
    if is_processing(meeting_id):
        logger.info("regenerate: meeting %s already processing — skip", meeting_id)
        return

    # 0) 사전 접속 체크 — 실패 시 자막 손실 방지를 위해 skip
    if not await _vod_reachable(vod_url):
        logger.warning(
            "regenerate: VOD unreachable for %s — preserving existing subtitles, skip",
            meeting_id,
        )
        return

    # 1) 기존 AI 자막만 삭제 (접속 가능 확인 후에만).
    #    실시간 자막(kind='live')은 초안으로 보존한다 — 회의 상세에서 AI 완성본과
    #    나란히 비교할 수 있어야 한다.
    try:
        supabase.table("subtitles").delete().eq("meeting_id", meeting_id).eq(
            "kind", "ai"
        ).execute()
        logger.info("regenerate: cleared existing AI subtitles for %s", meeting_id)
    except Exception as e:
        logger.exception("regenerate: failed to clear subtitles for %s: %s", meeting_id, e)
        return

    # 2) VOD STT 재실행
    try:
        service = VodSttService()
        await service.process(meeting_id, vod_url, supabase)
        logger.info("regenerate: VOD STT completed for %s", meeting_id)
        # STT 성공 → subtitle_stage='ai'로 승격
        try:
            supabase.table("meetings").update(
                {"subtitle_stage": "ai"}
            ).eq("id", meeting_id).execute()
        except Exception as se:
            logger.warning("regenerate: subtitle_stage update failed: %s", se)
    except Exception as e:
        logger.exception("regenerate: VOD STT failed for %s: %s", meeting_id, e)
        return

    # 3) AI 문법 교정 (flagship gpt-5.4 — batch_correction_model)
    try:
        subs_result = (
            supabase.table("subtitles")
            .select("id, text")
            .eq("meeting_id", meeting_id)
            .execute()
        )
        items = subs_result.data or []
        if not items:
            logger.warning("regenerate: no subtitles after STT for %s", meeting_id)
            return

        issues = await check_grammar_batch(items)
        applied = 0
        for issue in issues:
            try:
                supabase.table("subtitles").update(
                    {
                        "text": issue.corrected_text,
                        "original_text": issue.original_text,
                        "is_corrected": True,
                        "correction_state": "corrected",
                    }
                ).eq("id", issue.subtitle_id).execute()
                applied += 1
            except Exception as e:
                logger.warning(
                    "regenerate: grammar apply failed for sub %s: %s",
                    issue.subtitle_id,
                    e,
                )
        logger.info(
            "regenerate: grammar correction applied %d/%d for %s",
            applied,
            len(items),
            meeting_id,
        )
    except Exception as e:
        logger.exception("regenerate: grammar step failed for %s: %s", meeting_id, e)


async def _regenerate_all_sequential(
    matched_list: list[dict[str, Any]], supabase: Client
) -> None:
    """매칭된 회의들을 **순차적으로** 재생성 (Railway 메모리 + Deepgram rate limit 고려)."""
    for m in matched_list:
        try:
            await _regenerate_pipeline(m["id"], m["vod_url"], supabase)
        except Exception as e:
            logger.exception("regenerate_all: %s failed: %s", m.get("id"), e)
    logger.info("regenerate_all: completed %d meetings", len(matched_list))


async def regenerate_for_session(
    supabase: Client,
    session_number: int | None = None,
    include_today: bool = True,
    limit: int = 50,
) -> dict[str, Any]:
    """이미 vod_url이 있는 회의들의 자막을 **강제 재생성** (이미 매칭된 회의 대상).

    매칭 규칙: (title에 '제{session_number}회' 포함) OR (meeting_date == 오늘 KST)
    - 기존 자막을 삭제하고 VOD STT로 재생성 + AI 문법 교정 적용
    - 백그라운드 순차 처리 (회의당 약 10분)
    """
    # 1) 현재 세션 임시회 + 오늘 개최 회의 중 vod_url 있는 것들 조회
    result = (
        supabase.table("meetings")
        .select("id, title, meeting_date, vod_url")
        .not_.is_("vod_url", "null")
        .order("meeting_date", desc=True)
        .limit(limit)
        .execute()
    )
    all_meetings: list[dict[str, Any]] = result.data or []

    # KST 오늘
    from datetime import datetime as _dt
    import zoneinfo
    today_kst = _dt.now(zoneinfo.ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")

    targets: list[dict[str, Any]] = []
    for m in all_meetings:
        title = m.get("title") or ""
        date = m.get("meeting_date") or ""
        session_match = (
            session_number is not None and f"제{session_number}회" in title
        )
        today_match = include_today and date == today_kst
        if session_match or today_match:
            targets.append(
                {
                    "id": m["id"],
                    "vod_url": m["vod_url"],
                    "title": title,
                    "meeting_date": date,
                }
            )

    regeneration_started = False
    if targets:
        try:
            asyncio.create_task(_regenerate_all_sequential(list(targets), supabase))
            regeneration_started = True
            logger.info(
                "regenerate_session: background task started for %d meetings", len(targets)
            )
        except Exception as e:
            logger.exception("regenerate_session: failed to start background: %s", e)

    return {
        "session_number": session_number,
        "include_today": include_today,
        "today_kst": today_kst,
        "targets_count": len(targets),
        "targets": targets,
        "regeneration_started": regeneration_started,
    }


async def match_and_update(
    supabase: Client, limit: int = 200, regenerate_subtitles: bool = True,
    pages: int = 2,
) -> dict[str, Any]:
    """vod_url이 null인 meeting을 KMS 목록에 매칭해 DB 갱신.

    pages: KMS 목록 페이지 수(기본 2 = 30건). 한 회기 전체(본회의 포함)를
    받으려면 2페이지가 필요하다. 신규 등록은 '현재(최신) 회기'로 제한해
    과거 회기까지 무더기로 등록되는 것을 막는다.
    regenerate_subtitles=True이면 매칭 성공 건에 대해 백그라운드로
    기존 자막 삭제 → VOD STT 재실행 → AI 문법 교정 파이프라인을 순차 실행.
    """
    # 1. KMS 목록 크롤 (여러 페이지 — 한 회기 전체 커버)
    try:
        entries = await fetch_recent_vod_list(pages=pages)
    except httpx.HTTPError as e:
        raise ValueError(f"KMS 목록 가져오기 실패: {e}") from e

    if not entries:
        return {
            "kms_entries": 0,
            "pending": 0,
            "matched": [],
            "unmatched": [],
            "errors": ["KMS 목록이 비어 있습니다."],
        }

    # KMS 목록의 날짜 범위 — 매칭 대상을 이 범위로 제한해 과거 생중계 스텁이
    # '매칭 실패'로 잡히는 혼란을 막는다 (KMS 최근목록엔 최근 ~15건만 노출됨).
    entry_dates = sorted({e["meeting_date"] for e in entries})
    min_kms_date = entry_dates[0] if entry_dates else "1970-01-01"

    # 2. vod_url null + ended/processing 회의 조회 (KMS 목록 날짜 범위 내만)
    pending_result = (
        supabase.table("meetings")
        .select("*")
        .is_("vod_url", "null")
        .gte("meeting_date", min_kms_date)
        .in_("status", ["ended", "processing", "live"])
        .order("meeting_date", desc=True)
        .limit(limit)
        .execute()
    )
    pending: list[dict[str, Any]] = pending_result.data or []

    matched: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    duplicate: list[dict[str, Any]] = []  # 같은 영상이 이미 등록된 중복 스텁
    promoted: list[dict[str, Any]] = []  # 영상 변환 전 제목·회기만 먼저 승격/등록
    consumed_midx: set = set()  # 이번 매칭에 쓰인 KMS 항목 (신규 등록에서 제외)

    for meeting in pending:
        candidate = _match_meeting_to_entry(meeting, entries)
        if not candidate:
            unmatched.append(
                {
                    "id": meeting["id"],
                    "title": meeting.get("title"),
                    "meeting_date": meeting.get("meeting_date"),
                    "reason": "no_kms_match",
                }
            )
            continue

        # 제목 업그레이드 — 기존 제목이 '생중계'로 끝나거나 회기 정보 없을 때만 KMS 제목으로 교체
        # (변환 완료/미완료 공통으로 쓰므로 resolve 이전에 계산)
        new_title = meeting.get("title") or candidate["title"]
        needs_title_update = (
            "생중계" in new_title
            or "제389" not in new_title and candidate["session_no"] is not None
            or "제" not in new_title
        )
        if needs_title_update:
            date_label = candidate["meeting_date"]
            new_title = f"{candidate['title']} [{date_label}]"

        # KMS 페이지 URL → MP4 직접링크 변환
        try:
            mp4_url = await resolve_kms_vod_url(candidate["page_url"])
        except VodNotConvertedError:
            # 영상 변환 전 — 제목·회기·번호만 먼저 승격해 회기 탭에 즉시 노출한다
            # (사용자 정책 2026-07-08). vod_url은 null로 두고, 다음 주기에 변환이
            # 끝나면 이 회의가 여전히 pending(vod_url null)이라 재매칭되어 채워진다.
            promote_payload: dict[str, Any] = {
                "title": new_title,
                "session_no": candidate.get("session_no"),
                "duration_seconds": candidate["duration_seconds"],
                "kms_midx": str(candidate["kms_midx"]) if candidate.get("kms_midx") else None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            if _has_kms_no_column(supabase):
                promote_payload["kms_no"] = candidate.get("list_num")
            try:
                supabase.table("meetings").update(promote_payload).eq(
                    "id", meeting["id"]
                ).execute()
                promoted.append(
                    {"id": meeting["id"], "new_title": new_title, "reason": "vod_not_converted"}
                )
                if candidate.get("kms_midx"):
                    consumed_midx.add(candidate["kms_midx"])
            except Exception as e:
                # kms_midx 유니크 제약 위반 = 같은 KMS 영상이 이미 다른 회의로
                # 승격됨(오늘 깜빡임으로 조각난 스텁 중 하나). 에러가 아니라 '중복'.
                if "23505" in str(e) or "duplicate key" in str(e):
                    duplicate.append({"id": meeting["id"], "title": meeting.get("title")})
                else:
                    errors.append(
                        {"id": meeting["id"], "title": meeting.get("title"), "error": f"promote_failed: {e}"}
                    )
            continue
        except Exception as e:
            logger.exception("resolve_kms_vod_url failed: %s", candidate["page_url"])
            errors.append(
                {
                    "id": meeting["id"],
                    "title": meeting.get("title"),
                    "error": f"resolve_failed: {e}",
                }
            )
            continue

        update_payload = {
            "vod_url": mp4_url,
            "duration_seconds": candidate["duration_seconds"],
            "status": "ended",
            "title": new_title,
            "kms_midx": str(candidate["kms_midx"]) if candidate.get("kms_midx") else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if _has_kms_no_column(supabase):
            update_payload["kms_no"] = candidate.get("list_num")

        try:
            supabase.table("meetings").update(update_payload).eq(
                "id", meeting["id"]
            ).execute()
        except Exception as e:
            # vod_url 유니크 제약 위반 = 같은 영상이 이미 정식 회의로 등록됨.
            # 이 회의는 중복 생중계 스텁이므로 에러가 아니라 '중복'으로 분류.
            if "23505" in str(e) or "duplicate key" in str(e):
                duplicate.append(
                    {"id": meeting["id"], "title": meeting.get("title")}
                )
                continue
            errors.append(
                {
                    "id": meeting["id"],
                    "title": meeting.get("title"),
                    "error": f"db_update_failed: {e}",
                }
            )
            continue

        matched.append(
            {
                "id": meeting["id"],
                "old_title": meeting.get("title"),
                "new_title": new_title,
                "vod_url": mp4_url,
                "duration_seconds": candidate["duration_seconds"],
                "kms_page": candidate["page_url"],
            }
        )
        if candidate.get("kms_midx"):
            consumed_midx.add(candidate["kms_midx"])

    # 3. 우리 DB에 아직 없는 KMS 회의 신규 등록 — 생중계(STT)를 타지 않은
    #    회의도 회의 목록에 보이도록 한다. 자막은 만들지 않으며(stage none),
    #    관리자가 [AI 자막 생성]을 눌러 명시적으로 실행한다 (사용자 요청 2026-06-12).
    created: list[dict[str, Any]] = []
    has_no_col = _has_kms_no_column(supabase)
    try:
        existing_rows = (
            supabase.table("meetings")
            .select("id,title,meeting_date,kms_midx")
            .in_("meeting_date", entry_dates)
            .execute()
            .data
            or []
        )
    except Exception:
        existing_rows = []
    existing_midx = {
        int(r["kms_midx"]) for r in existing_rows
        if r.get("kms_midx") and str(r["kms_midx"]).isdigit()
    }

    def _already_registered(e: dict[str, Any]) -> bool:
        midx = e.get("kms_midx")
        if midx and (midx in existing_midx or midx in consumed_midx):
            return True
        comm = (e.get("committee") or "").replace(" ", "")
        if not comm:
            return False
        for r in existing_rows:
            if r.get("meeting_date") == e["meeting_date"] and comm in (r.get("title") or "").replace(" ", ""):
                return True
        return False

    # 신규 등록은 관리 시작 회기(kms_min_session_no, 기본 391) 이후만 —
    # 과거 회기 무더기 등록은 막되, 392·393·394처럼 여러 회기가 동시에
    # 진행 중이면(임시회 병행) 하한을 넘는 회기는 모두 등록한다.
    # (이전 정책 '최신 회기 1개만'은 병행 회기에서 이전 회기 누락을 유발했음)
    from app.core.config import settings as _settings

    min_session = _settings.kms_min_session_no

    now_iso = datetime.now(timezone.utc).isoformat()
    for e in entries:
        if not e.get("session_no") or e["session_no"] < min_session:
            continue
        if _already_registered(e):
            continue
        # 영상 변환 전이라도 회기·제목을 먼저 등록한다 (사용자 정책 2026-07-08).
        # 변환 미완료면 vod_url=null 로 등록 → 다음 주기 pending 매칭에서 채워진다.
        pending_video = False
        try:
            mp4_url = await resolve_kms_vod_url(e["page_url"])
        except VodNotConvertedError:
            mp4_url = None
            pending_video = True
        except Exception as ex:
            errors.append({"id": None, "title": e["title"], "error": f"resolve_failed: {ex}"})
            continue
        row: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "title": f"{e['title']} [{e['meeting_date']}]",
            "meeting_date": e["meeting_date"],
            "vod_url": mp4_url,
            "duration_seconds": e["duration_seconds"],
            "status": "ended",
            "committee": e.get("committee"),
            "session_no": e.get("session_no"),
            "kms_midx": str(e["kms_midx"]) if e.get("kms_midx") else None,
            "subtitle_stage": "none",
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        if has_no_col:
            row["kms_no"] = e.get("list_num")
        try:
            supabase.table("meetings").insert(row).execute()
            entry = {"id": row["id"], "title": row["title"], "kms_no": e.get("list_num")}
            if pending_video:
                promoted.append({**entry, "reason": "vod_not_converted"})
            else:
                created.append(entry)
        except Exception as ex:
            errors.append({"id": None, "title": e["title"], "error": f"db_insert_failed: {ex}"})

    # 3.5 kms_no 백필 — 이미 등록된 회의에도 의회 번호를 채운다.
    #     ① kms_midx 일치 ② (날짜+위원회+차수) 제목 매칭 — midx 없는 회의도 커버.
    if has_no_col:
        midx_to_no = {e["kms_midx"]: e["list_num"] for e in entries if e.get("kms_midx")}
        # (날짜, 위원회공백제거, 차수) → list_num
        key_to_no: dict[tuple, int] = {}
        for e in entries:
            comm = (e.get("committee") or "").replace(" ", "")
            key_to_no[(e["meeting_date"], comm, e.get("session_order"))] = e["list_num"]
        try:
            rows_no = (
                supabase.table("meetings")
                .select("id,title,meeting_date,kms_midx")
                .is_("kms_no", "null")
                .in_("meeting_date", entry_dates)
                .execute()
                .data
                or []
            )
            for r in rows_no:
                no = None
                midx_str = str(r.get("kms_midx") or "")
                if midx_str.isdigit():
                    no = midx_to_no.get(int(midx_str))
                if no is None:
                    title = r.get("title") or ""
                    cm = re.search(r"([가-힣]+위원회|본회의)", title)
                    om = re.search(r"제\s*(\d+)\s*차", title)
                    comm = cm.group(1) if cm else ""
                    order = int(om.group(1)) if om else None
                    no = key_to_no.get((r["meeting_date"], comm, order))
                if no:
                    supabase.table("meetings").update({"kms_no": no}).eq("id", r["id"]).execute()
        except Exception as ex:
            logger.debug("kms_no 백필 스킵: %s", ex)

    # 매칭 성공 건에 대해 백그라운드 재생성 파이프라인 시작 (기본 ON)
    regeneration_started = False
    if regenerate_subtitles and matched:
        try:
            asyncio.create_task(_regenerate_all_sequential(list(matched), supabase))
            regeneration_started = True
            logger.info(
                "regenerate: background task started for %d meetings", len(matched)
            )
        except Exception as e:
            logger.exception("regenerate: failed to start background task: %s", e)

    return {
        "kms_entries": len(entries),
        "pending": len(pending),
        "matched_count": len(matched),
        "created_count": len(created),
        "promoted_count": len(promoted),
        "duplicate_count": len(duplicate),
        "unmatched_count": len(unmatched),
        "error_count": len(errors),
        "matched": matched,
        "created": created,
        "promoted": promoted,
        "duplicate": duplicate,
        "unmatched": unmatched,
        "errors": errors,
        "regeneration_started": regeneration_started,
    }
