"""hwpx(한글) 전자회의록 생성기.

★직렬화 엔진: pyhwpxlib(한컴 호환 hwpx 빌더).
  손수 만든 OWPML(이전 구현)은 데스크톱 한글에선 열렸지만, 모바일 한컴오피스
  무료 뷰어가 불완전한 header/구조를 "지원하지 않는 암호화 방식(-41003)"으로
  오탐해 열지 못했다. 완전한 fontfaces/styles/secPr/Preview를 갖춘 한컴 호환
  파일을 안정적으로 만들기 위해 유지보수 라이브러리로 교체했다.
  (레퍼런스 neolord0/hwpxlib 대조: 우리 header 7KB vs 라이브러리 44KB.)

이 모듈은 '공식 전자회의록 문단 구조'를 만들고, 실제 ZIP/OWPML 직렬화는
HwpxBuilder에 위임한다.

공식 전자회의록(KMS) 구조:
  제N회 경기도의회(임시회/정례회)   ← 가운데
  {위원회} 회의록                   ← 가운데, 큰글씨
  제 N 호 / 경기도의회사무처         ← 가운데
  일  시 / 장  소
  의사일정 / 심사된 안건 (안건 목록)
  (개의)
  ○ {발언자}\n{발언}…
  출석위원 / 출석공무원 (말미, 근사)
"""

from __future__ import annotations

import os
import re
import tempfile
from datetime import date as _date


def _hms(seconds: float) -> str:
    s = int(seconds or 0)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _speaker_heading(entry: dict) -> str:
    """발언자 + 발언 시간대 헤딩 (예: ○ 김영수 위원 (00:05:10 ~ 00:06:42)).

    docx_export에서도 재사용한다.
    """
    speaker = entry.get("speaker") or "발언자 미확인"
    start = entry.get("start_time")
    end = entry.get("end_time")
    if start is not None and end is not None:
        return f"○ {speaker}  ({_hms(start)} ~ {_hms(end)})"
    return f"○ {speaker}"


# ─── 공식 전자회의록(KMS) 양식 빌더 ────────────────────────────────────────

_SESSION_RE = re.compile(r"제\s*(\d+)\s*회")
_ROUND_RE = re.compile(r"제\s*(\d+)\s*차")
_KIND_RE = re.compile(r"(정례회|임시회)")
_WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")
# 집행부 직책 접미사 — 출석공무원 추출용.
_EXEC_SUFFIX_HWPX = re.compile(
    r"(실장|국장|과장|본부장|단장|처장|차관|센터장|소장|원장|차장|팀장|부장|담당관|전문위원)$"
)


def _format_date_korean_day(date_str: str) -> str:
    """'2026-04-24' → '2026년 4월 24일(금)'. 파싱 실패 시 원본 반환."""
    parts = (date_str or "").split("-")
    if len(parts) == 3:
        try:
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            wd = _WEEKDAYS[_date(y, m, d).weekday()]
            return f"{y}년 {m}월 {d}일({wd})"
        except (ValueError, IndexError):
            return date_str
    return date_str


def _parse_meeting_title(meeting: dict) -> dict:
    """회의 제목에서 회기/차수/회의종류/위원회명을 파싱.

    예: '제391회 제3차 경제노동위원회 [2026-06-16]'
        → session=391, round=3, kind=None, committee='경제노동위원회'
        '제389회 [임시회] 제2차 건설교통위원회'
        → session=389, round=2, kind='임시회', committee='건설교통위원회'
    """
    title = (meeting.get("title") or "").strip()
    base = re.sub(r"\[[^\]]*\]", " ", title)  # [날짜]/[임시회] 등 대괄호 제거
    session = (_SESSION_RE.search(base) or [None, None])[1]
    rnd = (_ROUND_RE.search(base) or [None, None])[1]
    kind_m = _KIND_RE.search(title)  # 종류는 대괄호 안에 있을 수 있어 원본 검색
    kind = kind_m.group(1) if kind_m else None

    committee = base
    committee = _SESSION_RE.sub(" ", committee)
    committee = _ROUND_RE.sub(" ", committee)
    committee = _KIND_RE.sub(" ", committee)
    committee = re.sub(r"\s+", " ", committee).strip()
    if not committee:
        committee = (meeting.get("committee") or "").strip()
    return {"session": session, "round": rnd, "kind": kind, "committee": committee}


def _kind_from_grouped(grouped: list[dict]) -> str | None:
    """자막 본문(개의 멘트)에서 회의종류(정례회/임시회)를 보강 추출. 없으면 None.

    제목에 종류가 없을 때 사용 — 위원장 개의 멘트가 보통 '제N회 …정례회 …회의를
    개의하겠습니다'라 앞부분 몇 그룹만 훑어도 잡힌다.
    """
    for g in (grouped or [])[:6]:
        joined = " ".join(g.get("texts", []))
        m = _KIND_RE.search(joined)
        if m:
            return m.group(1)
    return None


def _attendance_footer(grouped: list[dict]) -> list[tuple[str, bool, bool]]:
    """발언자에서 출석위원·출석공무원을 도출해 말미 명단을 만든다(근사).

    실제 출석부가 없으므로 '발언한 사람'을 출석자로 본다. 의장(위원장)은 위원에 포함.
    """
    members: list[str] = []
    execs: list[str] = []
    seen_m: set[str] = set()
    seen_e: set[str] = set()
    for g in grouped:
        spk = (g.get("speaker") or "").strip()
        if not spk:
            continue
        # 위원/위원장 → 출석위원 (이름만)
        if spk.endswith("위원") or spk.endswith("위원장"):
            name = re.sub(r"\s*(부?위원장|위원)$", "", spk).strip()
            if name and name not in seen_m:
                seen_m.add(name)
                members.append(name)
        elif _EXEC_SUFFIX_HWPX.search(spk):
            if spk not in seen_e:
                seen_e.add(spk)
                execs.append(spk)

    out: list[tuple[str, bool, bool]] = []
    if members:
        out.append(("", False, False))
        out.append((f"○ 출석위원({len(members)}명)", True, False))
        out.append(("  " + "  ".join(members), False, False))
    if execs:
        out.append((f"○ 출석공무원({len(execs)}명)", True, False))
        out.append(("  " + "  ".join(execs), False, False))
    return out


def _build_official_paragraphs(
    meeting: dict, grouped: list[dict], agendas: list[dict] | None = None
) -> list[tuple[str, bool, bool]]:
    """(텍스트, bold, center) 공식 전자회의록 문단 목록."""
    info = _parse_meeting_title(meeting)
    session = info["session"]
    rnd = info["round"]
    kind = info["kind"] or _kind_from_grouped(grouped)  # 제목에 없으면 자막에서 보강
    committee = info["committee"] or "위원회"
    date_kor = _format_date_korean_day(str(meeting.get("meeting_date") or "")[:10])

    # 머리글(가운데 정렬)
    head_kind = f"({kind})" if kind else ""
    session_line = f"제{session}회 경기도의회{head_kind}" if session else "경기도의회"
    out: list[tuple[str, bool, bool]] = [
        (session_line, True, True),
        (f"{committee} 회의록", True, True),
        (f"제 {rnd} 호" if rnd else "", False, True),
        ("경기도의회사무처", False, True),
        ("", False, False),
    ]
    if date_kor:
        out.append((f"일  시: {date_kor}", False, False))
    out.append((f"장  소: {committee} 회의실", False, False))
    out.append(("", False, False))

    # 의사일정 / 심사된 안건
    agenda_titles = [
        f"{a.get('order_num', i + 1)}. {(a.get('title') or '').strip()}"
        for i, a in enumerate(agendas or [])
        if (a.get("title") or "").strip()
    ]
    for header in ("의사일정", "심사된 안건"):
        out.append((header, True, False))
        if agenda_titles:
            for t in agenda_titles:
                out.append((t, False, False))
        else:
            out.append(("(안건 정보가 등록되지 않았습니다.)", False, False))
        out.append(("", False, False))

    # 개의 표시 — 정확한 벽시계 시각을 알 수 없어 구조 표시만.
    out.append(("(개의)", False, True))
    out.append(("", False, False))

    # 본문 — ○ 발언자 / 발언. 같은 발언자가 이어지면 '○ 발언자' 머리표는 생략(반복 제거).
    if not grouped:
        out.append(("(자막 데이터가 없습니다.)", False, False))
    else:
        prev_speaker = None
        for entry in grouped:
            speaker = (entry.get("speaker") or "발언자 미확인").strip()
            text = " ".join(entry.get("texts", []))
            if speaker != prev_speaker:
                out.append((f"○ {speaker}", True, False))
                prev_speaker = speaker
            out.append((text, False, False))

    # 말미 출석 명단(근사)
    out.extend(_attendance_footer(grouped))

    # AI 생성 안내
    out.append(("", False, False))
    out.append(
        ("※ 본 회의록은 AI 음성인식으로 자동 생성된 초안이며, 공식 회의록과 다를 수 있습니다.",
         False, True)
    )
    return out


def export_hwpx(
    meeting: dict, grouped: list[dict], agendas: list[dict] | None = None
) -> bytes:
    """회의록을 hwpx(한컴 호환) 바이트로 생성한다 — KMS 공식 전자회의록 양식.

    문단 구조는 _build_official_paragraphs로 만들고, ZIP/OWPML 직렬화는
    pyhwpxlib HwpxBuilder에 위임한다(모바일 한컴오피스 호환).

    grouped: transcript_export._group_by_speaker() 출력 형태
             ({speaker, start_time, end_time, texts}).
    agendas: meeting_agendas 행 목록(order_num, title) — 의사일정/심사된 안건에 사용.
    """
    from pyhwpxlib import HwpxBuilder

    paras = _build_official_paragraphs(meeting, grouped, agendas)
    builder = HwpxBuilder()
    for text, bold, center in paras:
        builder.add_paragraph(
            text or "",
            bold=bold,
            alignment="CENTER" if center else "JUSTIFY",
        )

    # HwpxBuilder.save는 파일 경로만 받으므로 임시파일을 경유해 바이트를 얻는다.
    fd, path = tempfile.mkstemp(suffix=".hwpx")
    os.close(fd)
    try:
        builder.save(path)
        with open(path, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
