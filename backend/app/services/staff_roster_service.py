"""집행부 공무원/전문위원 명부(staff_roster) 서비스.

속기록(KMS 임시회의록)의 출석 명단 섹션을 파싱해 위원회별 실명 명부를 만든다.
이름 교정·글로서리 바이어스·화자 귀속의 공통 원천.

파싱 대상 형식 (_steno_15575/15577/15580/15594.txt 실측):
    ○ 출석전문위원
    수석전문위원 한태우
    ○ 출석공무원
    ㆍ건설국                     ← 부서 불릿
    국장 배성호                  ← 직책 + 이름
    건설정책과장 홍원표
    ㆍ경기국제공항추진단 단장 조정아   ← 인라인형 (부서+직책+이름 한 줄)
    ㆍ운영지원과장 최희숙            ← 직책 선두 불릿형 (부서 없음, _steno_15575)
    국장 김재훈평생교육과장 홍성덕     ← 쌍이 붙은 줄 (이름 뒤에 다음 직책이 접합)
    실장 박노극경제기획관 권주성       ← '기획관' 직책 접합 (_steno_15577)
    행정1부지사 김성중기획조정실장 정두석 ← 지사/교육감/감사관 선두 직책 (_steno_15599 본회의)
    ○ 기타참석자                 ← 다음 '○' 섹션에서 중단

full_title 규칙: 부서가 "OO국"이고 직책이 "국장"이면 "OO국장"처럼 결합,
직책에 이미 부서가 담겨 있으면(건설정책과장) 그대로.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)

# 파싱 대상 출석 섹션 (다른 '○' 섹션 — 출석위원/기타참석자/기록공무원 등 — 은 제외)
_TARGET_SECTIONS = ("출석전문위원", "출석공무원")

# 직책 토큰 판정용 접미사 (실측 속기록의 직책 어미).
# name_corrector._STAFF_TITLE_RE 와 공유하는 단일 원천 — 여기만 갱신하면 된다.
STAFF_TITLE_SUFFIXES = (
    "국장", "과장", "본부장", "단장", "실장", "팀장", "처장", "소장",
    "원장", "관장", "부장", "차장", "청장", "전문위원", "담당관",
    "기획관",  # 예: 경제기획관 (_steno_15577 '실장 박노극경제기획관 권주성')
    # _steno_15599(본회의) 선두 직책 — 못 알아보면 뒤따르는 '이름+직책' 접합
    # 토큰이 통째로 직책으로 오인돼 두 사람이 융합되던 실측 백필 버그의 원천
    "지사",  # 도지사, 행정1·2부지사, 경제부지사
    "교육감",  # 교육감, 제1·2부교육감
    "감사관",
)

# 하위 호환 별칭 (모듈 내부 관례명)
_TITLE_SUFFIXES = STAFF_TITLE_SUFFIXES

_NAME_RE = re.compile(r"^[가-힣]{2,4}$")


def _is_title(token: str) -> bool:
    """토큰이 직책인지 (예: 국장, 건설정책과장, 수석전문위원)."""
    return len(token) >= 2 and token.endswith(_TITLE_SUFFIXES)


def _is_name(token: str) -> bool:
    """토큰이 사람 이름인지 (한글 2~4자, 직책 어미 제외)."""
    return bool(_NAME_RE.match(token)) and not _is_title(token)


def _split_fused(token: str) -> tuple[str, str] | None:
    """'김재훈평생교육과장'처럼 이름 뒤에 다음 직책이 붙은 토큰을 (이름, 직책)으로 분리.

    한국인 이름은 3자가 압도적이므로 3 → 2 → 4자 순으로 시도한다.
    """
    for name_len in (3, 2, 4):
        name, rest = token[:name_len], token[name_len:]
        if len(token) > name_len and _NAME_RE.match(name) and _is_title(rest):
            return name, rest
    return None


def _full_title(department: str | None, title: str) -> str:
    """부서+직책 결합 직함. 예: 건설국+국장→건설국장, 경기국제공항추진단+단장→경기국제공항추진단장.

    직책에서 '장'을 뗀 어간(국/본부/단)이 부서명 끝과 일치할 때만 결합하고,
    직책에 이미 부서가 담긴 경우(건설정책과장)는 그대로 반환한다.
    """
    if department and title.endswith("장"):
        stem = title[:-1]
        if stem and department.endswith(stem):
            return department + "장"
    return title


def _parse_pairs(line: str, department: str | None, out: list[dict]) -> None:
    """한 줄에서 '직책 이름' 쌍들을 추출해 out에 추가 (붙은 쌍·복수 쌍 포함).

    ★선행 직책 인식이 융합 방지의 핵심: 선두 직책(도지사/부지사/교육감 등)을
    못 알아보면 pending 없이 뒤따르는 '이름+다음직책' 접합 토큰이 통째로 직책
    으로 오인돼 다음 이름과 융합된다('정두석 김성중기획조정실장' 실측 버그).
    새 직책 어미가 나타나면 STAFF_TITLE_SUFFIXES에 추가할 것.
    (해석 불가 토큰 뒤의 직책 토큰을 접합으로 간주해 쪼개는 방어는 두지 않는다
    — '소방학교 교육지원과장 이상태' 같은 실측 기관명 선두 줄에서 순정 직책을
    오분리('교육지'+'원과장')하는 부작용이 더 크다.)
    """
    pending_title: str | None = None
    for token in line.split():
        if pending_title is None:
            if _is_title(token):
                pending_title = token
            continue
        if _is_name(token):
            out.append(_entry(token, pending_title, department))
            pending_title = None
        elif (fused := _split_fused(token)) is not None:
            # '이름+다음직책' 접합 토큰: 이름은 확정, 직책은 다음 쌍으로 이월
            out.append(_entry(fused[0], pending_title, department))
            pending_title = fused[1]
        elif _is_title(token):
            pending_title = token  # 이름 없는 직책 — 새 직책으로 교체
        else:
            pending_title = None  # 해석 불가 토큰 — 쌍 폐기


def _entry(name: str, title: str, department: str | None) -> dict:
    return {
        "name": name,
        "title": title,
        "department": department,
        "full_title": _full_title(department, title),
    }


def parse_steno_attendance(steno_text: str) -> list[dict]:
    """속기록 텍스트의 출석 명단(출석공무원/출석전문위원)을 파싱한다.

    Returns:
        [{"name", "title", "department", "full_title"}] — 문서 등장순.
        섹션이 없으면 [].
    """
    entries: list[dict] = []
    in_target = False
    department: str | None = None

    for raw in (steno_text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("○"):
            section = line.lstrip("○").strip()
            in_target = section.startswith(_TARGET_SECTIONS)
            department = None  # 섹션 전환 시 부서 초기화
            continue
        if not in_target:
            continue
        if line.startswith("ㆍ"):
            body = line.lstrip("ㆍ").strip()
            tokens = body.split()
            if not tokens:
                continue
            if _is_title(tokens[0]):
                # 직책 선두 불릿형: "ㆍ운영지원과장 최희숙", "ㆍ경기도교육청학생교육원장 지미숙"
                # — 부서 없는 단독 항목이므로 직전 부서를 잇지 않는다
                department = None
                _parse_pairs(body, None, entries)
                continue
            department = tokens[0]
            if len(tokens) > 1:
                # 인라인형: "ㆍ경기국제공항추진단 단장 조정아"
                _parse_pairs(" ".join(tokens[1:]), department, entries)
            continue
        _parse_pairs(line, department, entries)

    return entries


def upsert_staff_roster(
    supabase: Any,
    committee: str,
    entries: list[dict],
    source_mntsid: str | None = None,
) -> int:
    """명부 항목을 staff_roster에 upsert한다. UNIQUE(committee,name,full_title) 충돌 시
    last_seen_date/source_mntsid를 갱신한다.

    Returns:
        upsert한 행 수.
    """
    if not committee or not entries:
        return 0
    today = date.today().isoformat()
    # 한 statement 안에 같은 충돌 키가 2번 오면 Postgres upsert가 실패하므로 선(先)중복제거
    dedup: dict[tuple[str, str, str], dict] = {}
    for e in entries:
        row = {
            "committee": committee,
            "name": e["name"],
            "title": e["title"],
            "department": e.get("department"),
            "full_title": e["full_title"],
            "source_mntsid": source_mntsid,
            "last_seen_date": today,
        }
        dedup[(committee, row["name"], row["full_title"])] = row
    rows = list(dedup.values())
    supabase.table("staff_roster").upsert(
        rows, on_conflict="committee,name,full_title"
    ).execute()
    return len(rows)


# 글로서리 프롬프트에서 절대 잘리면 안 되는 직책 — 앞에서부터 이 순서로 올린다.
# 왜 필요한가(2026-09-01 실측): 글로서리는 [의원명 → staff → 용어사전] 순으로 900자에서
# 잘리는데, 본회의 의원명만으로 캡을 거의 다 쓴다. staff 는 앞의 5명 정도만 살아남는다.
# 그런데 load_staff_roster 에 정렬이 없어 DB 물리 순서에 맡겨져 있었다 — 도지사 이름을
# 한 번 UPDATE 하자 그 행이 표 뒤로 밀려 프롬프트에서 통째로 사라졌고, STT 는 힌트를
# 잃고 학습된 옛 도지사 이름을 뱉었다. 순서를 데이터가 아니라 코드로 못박는다.
_LEAD_TITLE_ORDER = (
    "도지사",
    "교육감",
    "행정1부지사",
    "행정2부지사",
    "경제부지사",
    "제1부교육감",
    "제2부교육감",
)


def _lead_rank(row: dict) -> tuple[int, str]:
    """정렬 키 — 선두 직책이 먼저, 그 안에서는 이름순(재실행 시 순서가 흔들리지 않게)."""
    title = (row.get("full_title") or "").strip()
    try:
        return (_LEAD_TITLE_ORDER.index(title), row.get("name") or "")
    except ValueError:
        return (len(_LEAD_TITLE_ORDER), row.get("name") or "")


def load_staff_roster(supabase: Any, committee: str) -> list[dict]:
    """위원회의 staff_roster 행 목록. 테이블 없음/오류 시 warning 로그 + [] (fail-soft).

    마이그레이션(024) 미적용 환경에서도 호출측이 죽지 않아야 한다.
    반환 순서는 _lead_rank 로 고정한다 — DB 물리 순서에 기대면 UPDATE 한 번에
    도지사·교육감이 글로서리 캡 밖으로 밀려난다(위 주석의 실측 사고).
    """
    try:
        rows = (
            supabase.table("staff_roster")
            .select("*")
            .eq("committee", committee)
            .execute()
            .data
            or []
        )
        return sorted(rows, key=_lead_rank)
    except Exception as e:
        logger.warning("staff_roster 조회 실패(무시, committee=%s): %s", committee, e)
        return []


def staff_glossary_terms(entries: list[dict], cap: int = 40) -> list[str]:
    """글로서리 용어 리스트: ["배성호 건설국장", ...] — 명부순, cap 초과 절단."""
    return [f"{e['name']} {e['full_title']}" for e in entries][:cap]


def staff_names(entries: list[dict]) -> list[str]:
    """명부의 이름 리스트 (명부순)."""
    return [e["name"] for e in entries]


def staff_bindings(entries: list[dict]) -> dict[str, str]:
    """이름 → 결합 직함 매핑. 예: {"배성호": "건설국장"}."""
    return {e["name"]: e["full_title"] for e in entries}
