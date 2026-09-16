"""용어 사전 기반 후처리 서비스

용어 교정 및 의원 이름 교정을 위한 서비스입니다.
DB 기반 사전 로드를 지원합니다.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Literal

from supabase import Client

logger = logging.getLogger(__name__)


# ── 한국어 숫자 → 아라비아 숫자 변환 ──

# 한자어(Sino-Korean) 숫자 매핑
_SINO_DIGITS = {
    "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5,
    "육": 6, "칠": 7, "팔": 8, "구": 9,
}
_SINO_UNITS = {
    "십": 10, "백": 100, "천": 1000,
}
_SINO_LARGE = {
    "만": 10_000, "억": 100_000_000, "조": 1_000_000_000_000,
}

# 고유어(native Korean) 숫자 매핑
_NATIVE_MAP: dict[str, int] = {
    "하나": 1, "둘": 2, "셋": 3, "넷": 4, "다섯": 5,
    "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10,
    "스물": 20, "서른": 30, "마흔": 40, "쉰": 50,
    "예순": 60, "일흔": 70, "여든": 80, "아흔": 90,
}

# 단위어 (숫자 뒤에 붙는 조사/단위)
_UNIT_SUFFIXES = (
    "명", "원", "건", "개", "호", "차", "번", "일", "월", "년",
    "시간", "분", "초", "퍼센트", "프로", "배", "세",
    "석", "채", "마리", "그루", "벌", "장", "권", "대",
    "층", "평", "살", "세대", "가구",
)

# 한자어 숫자 패턴: "삼백오십" 등을 매칭
_SINO_CHARS = "일이삼사오육칠팔구십백천만억조"
_SINO_PATTERN = re.compile(
    rf"([{_SINO_CHARS}]{{2,}})({'|'.join(re.escape(s) for s in _UNIT_SUFFIXES)})?"
)

# 고유어 숫자 패턴
_NATIVE_KEYS_SORTED = sorted(_NATIVE_MAP.keys(), key=len, reverse=True)
_NATIVE_PATTERN = re.compile(
    rf"({'|'.join(re.escape(k) for k in _NATIVE_KEYS_SORTED)})"
    rf"({'|'.join(re.escape(k) for k in _NATIVE_KEYS_SORTED)})?"
    rf"({'|'.join(re.escape(s) for s in _UNIT_SUFFIXES)})"
)


def _parse_sino_number(text: str) -> int | None:
    """한자어 숫자 문자열을 정수로 파싱합니다.

    예: "삼백오십" → 350, "이천삼백" → 2300, "팔십" → 80
    """
    if not text:
        return None

    # 큰 단위(만/억/조) 기준으로 분할
    result = 0
    remaining = text

    for large_name, large_val in sorted(_SINO_LARGE.items(), key=lambda x: -x[1]):
        if large_name in remaining:
            parts = remaining.split(large_name, 1)
            left = parts[0]
            remaining = parts[1] if len(parts) > 1 else ""

            left_val = _parse_sino_small(left) if left else 1
            if left_val is None:
                return None
            result += left_val * large_val

    if remaining:
        small_val = _parse_sino_small(remaining)
        if small_val is None:
            return None
        result += small_val

    return result if result > 0 else None


def _parse_sino_small(text: str) -> int | None:
    """만 이하의 한자어 숫자를 파싱합니다.

    예: "삼백오십" → 350, "팔십" → 80, "구" → 9
    """
    if not text:
        return None

    result = 0
    current = 0

    for ch in text:
        if ch in _SINO_DIGITS:
            current = _SINO_DIGITS[ch]
        elif ch in _SINO_UNITS:
            if current == 0:
                current = 1  # "십" alone = 10
            result += current * _SINO_UNITS[ch]
            current = 0
        else:
            return None  # 숫자가 아닌 문자

    result += current  # 마지막 자릿수
    return result if result > 0 else None


def convert_korean_numbers(text: str) -> str:
    """텍스트 내의 한국어 숫자를 아라비아 숫자로 변환합니다.

    - 한자어: "삼백오십명" → "350명", "팔십명" → "80명"
    - 고유어+단위: "여든명" → "80명", "스물다섯명" → "25명"
    - 단위어 없는 독립 숫자는 변환하지 않음 (오인식 방지)
    """
    if not text:
        return text

    result = text

    # 고유어 숫자 + 단위 변환
    def _replace_native(m: re.Match) -> str:
        tens_part = m.group(1)
        ones_part = m.group(2)
        suffix = m.group(3)

        val = _NATIVE_MAP.get(tens_part, 0)
        if ones_part:
            val += _NATIVE_MAP.get(ones_part, 0)
        return f"{val}{suffix}" if val > 0 else m.group(0)

    result = _NATIVE_PATTERN.sub(_replace_native, result)

    # 한자어 숫자 + 단위 변환
    def _replace_sino(m: re.Match) -> str:
        num_text = m.group(1)
        suffix = m.group(2) or ""

        # 단위어 없는 경우, 3글자 이상일 때만 변환 (오인식 방지)
        if not suffix and len(num_text) < 3:
            return m.group(0)

        # 큰 단위(억, 조, 만)가 끝에 있으면 단위 라벨로 보존
        # 예: "삼천억원" → "3,000억원" (억 이하 계산, 억은 라벨 보존)
        for large_name in ("조", "억", "만"):
            if num_text.endswith(large_name) and len(num_text) > len(large_name):
                prefix_text = num_text[:-len(large_name)]
                parsed_prefix = _parse_sino_number(prefix_text)
                if parsed_prefix is not None:
                    formatted = f"{parsed_prefix:,}" if parsed_prefix >= 1000 else str(parsed_prefix)
                    return f"{formatted}{large_name}{suffix}"

        parsed = _parse_sino_number(num_text)
        if parsed is None:
            return m.group(0)

        # 천 단위 이상이면 콤마 포맷팅
        formatted = f"{parsed:,}" if parsed >= 1000 else str(parsed)
        return f"{formatted}{suffix}"

    result = _SINO_PATTERN.sub(_replace_sino, result)

    return result


@dataclass
class DictionaryEntry:
    """사전 항목

    Attributes:
        wrong_text: 잘못된 텍스트 (교정 대상)
        correct_text: 올바른 텍스트 (교정 결과)
        category: 카테고리 (councilor: 의원 이름, term: 의회 용어, general: 일반)
    """

    wrong_text: str
    correct_text: str
    category: Literal["councilor", "term", "general"] | None = None


class DictionaryService:
    """사전 기반 텍스트 교정 서비스

    용어 사전을 기반으로 텍스트를 교정합니다.
    - wrong_text -> correct_text 변환
    - 의원 이름, 의회 용어 등 교정
    """

    def __init__(self, entries: list[DictionaryEntry] | None = None):
        """사전 서비스 초기화

        Args:
            entries: 초기 사전 항목 목록
        """
        self._entries: dict[str, DictionaryEntry] = {}
        if entries:
            for entry in entries:
                self._entries[entry.wrong_text] = entry

    def correct(self, text: str) -> str:
        """텍스트 교정

        사전에 등록된 잘못된 텍스트를 올바른 텍스트로 교정하고,
        한국어 숫자를 아라비아 숫자로 변환합니다.

        Args:
            text: 교정할 텍스트

        Returns:
            교정된 텍스트
        """
        if not text:
            return text

        result = text
        for wrong_text, entry in self._entries.items():
            result = result.replace(wrong_text, entry.correct_text)

        # 한국어 숫자 → 아라비아 숫자 변환
        result = convert_korean_numbers(result)

        return result

    def add_entry(self, entry: DictionaryEntry) -> None:
        """사전 항목 추가

        Args:
            entry: 추가할 사전 항목
        """
        self._entries[entry.wrong_text] = entry

    def remove_entry(self, wrong_text: str) -> bool:
        """사전 항목 제거

        Args:
            wrong_text: 제거할 잘못된 텍스트

        Returns:
            제거 성공 여부
        """
        if wrong_text in self._entries:
            del self._entries[wrong_text]
            return True
        return False

    def get_entries(self) -> list[DictionaryEntry]:
        """모든 사전 항목 조회

        Returns:
            사전 항목 목록
        """
        return list(self._entries.values())

    def get_entries_by_category(
        self, category: Literal["councilor", "term", "general"]
    ) -> list[DictionaryEntry]:
        """카테고리별 사전 항목 조회

        Args:
            category: 조회할 카테고리

        Returns:
            해당 카테고리의 사전 항목 목록
        """
        return [
            entry for entry in self._entries.values() if entry.category == category
        ]

    def load_from_db(self, supabase: Client) -> int:
        """Supabase dictionary 테이블에서 사전 항목을 로드하여 병합합니다.

        기존 하드코딩 항목은 유지하고, DB 항목을 추가/덮어씁니다.

        Returns:
            로드된 DB 항목 수
        """
        try:
            result = supabase.table("dictionary").select("*").execute()
            count = 0
            for row in result.data or []:
                entry = DictionaryEntry(
                    wrong_text=row["wrong_text"],
                    correct_text=row["correct_text"],
                    category=row.get("category"),
                )
                self._entries[entry.wrong_text] = entry
                count += 1
            logger.info("DB에서 사전 %d개 항목 로드 완료", count)
            return count
        except Exception as e:
            logger.warning("DB 사전 로드 실패 (하드코딩 사전만 사용): %s", e)
            return 0

    def clear(self) -> None:
        """모든 사전 항목 제거"""
        self._entries.clear()

    def __len__(self) -> int:
        """사전 항목 개수"""
        return len(self._entries)


# ── 경기도의회 기본 사전 (Deepgram 한국어 STT 오인식 보정) ──

_PARLIAMENT_ENTRIES = [
    # 의회 용어
    DictionaryEntry("사내를 선포", "산회를 선포", "term"),
    DictionaryEntry("사내 를 선포", "산회를 선포", "term"),
    DictionaryEntry("사내선포", "산회 선포", "term"),
    DictionaryEntry("사내합니다", "산회합니다", "term"),
    DictionaryEntry("사내를", "산회를", "term"),
    DictionaryEntry("사내 합니다", "산회합니다", "term"),
    DictionaryEntry("개이합니다", "개의합니다", "term"),
    DictionaryEntry("개이를 선포", "개의를 선포", "term"),
    DictionaryEntry("정회를 선포", "정회를 선포", "term"),  # 이미 맞지만 확인용
    # ★"소개합니다"→"속개합니다" 항목 제거 (2026-06-12): "간부 공무원을
    #   소개합니다" 같은 정상 문장을 오염시키는 위험 치환이었음.
    DictionaryEntry("속계합니다", "속개합니다", "term"),
    DictionaryEntry("상정 하겠습니다", "상정하겠습니다", "term"),
    DictionaryEntry("의안을 상정 합니다", "의안을 상정합니다", "term"),
    DictionaryEntry("의결 하겠습니다", "의결하겠습니다", "term"),
    # 직위/기관
    DictionaryEntry("위원장 님", "위원장님", "term"),
    DictionaryEntry("의원 님", "의원님", "term"),
    DictionaryEntry("도지사 님", "도지사님", "term"),
    DictionaryEntry("경기 도의회", "경기도의회", "term"),
    DictionaryEntry("경기도 의회", "경기도의회", "term"),
    DictionaryEntry("보건 복지 위원회", "보건복지위원회", "term"),
    # 기타 오인식
    DictionaryEntry("질의 하겠습니다", "질의하겠습니다", "term"),
    DictionaryEntry("답변 하겠습니다", "답변하겠습니다", "term"),
    DictionaryEntry("출석을 부르겠습니다", "출석을 부르겠습니다", "term"),
    # ── 속기 정답 대조로 발굴한 회의 절차 보일러플레이트 오인식 (2026-06-20,
    #    제391회 제1차 건설교통위 mntsId=15580 속기록 vs AI 자막 윈도우 정렬 대조).
    #    매 회의 반복되는 절차 문구라 모든 채널·VOD에 효과. 모두 '오인식 표기가
    #    정상 문맥에 등장할 확률 ≈ 0'인 안전 치환만 선별(설계 규칙 준수). ──
    #    '촉9 건의안' — 한글 단어 안에 숫자가 섞인 STT 산물(정상 표기 불가).
    DictionaryEntry("촉9", "촉구", "term"),
    #    개의 정족수 선언 — 매 회의 첫 문장. '성언이 되었으므로'는 정상 문맥 부재.
    DictionaryEntry("성언이 되었으므로", "성원이 되었으므로", "term"),
    #    결산 회의 — '회계연도'를 '회의 개년도/회의개년도'로 오인식.
    DictionaryEntry("회의 개년도", "회계연도", "term"),
    DictionaryEntry("회의개년도", "회계연도", "term"),
    #    결산 회의 — '예비비'를 '예비 비상'으로 분절 오인식(3-그램으로 안전).
    DictionaryEntry("예비 비상 승인", "예비비 승인", "term"),
    #    '일률적으로'를 '일일적으로'로(─'일일적'은 표준어 아님).
    DictionaryEntry("일일적으로", "일률적으로", "term"),
    #    절차 용어 띄어쓰기 분절 — 정식 표기로 병합(기존 '추경 예산'→'추경예산' 패턴 동일).
    DictionaryEntry("제안 설명", "제안설명", "term"),
    DictionaryEntry("대표 발의", "대표발의", "term"),
    DictionaryEntry("공동 발의", "공동발의", "term"),
    DictionaryEntry("검토보고 하여", "검토보고하여", "term"),
    # ── 다회의 속기 대조 2차 발굴(2026-06-20): 건설교통위(15580)·경제노동위(15577)·
    #    교육행정위(15575) 3개 위원회 속기록 vs AI 자막 윈도우 정렬 → 후보 89건 →
    #    145-에이전트 적대검증(후보별 3 반증 시도, '정상문맥 충돌 0건'만 채택) → 29건.
    #    기각 18건은 충돌 예시로 위험 입증(예 '속도 제한'→'속도제한'은 "차량 속도,
    #    제한 구역"과 충돌 / '거소 신청'→'거수로 신청'은 부재자투표 '거소신청'과 충돌). ──
    # 건설교통위 — 의결·조문·의안 보일러플레이트
    DictionaryEntry("권유안은 원한 가결", "건의안은 원안 가결", "term"),
    DictionaryEntry("수석전문의원", "수석전문위원", "term"),  # 직책 '전문위원'→'전문의원'
    DictionaryEntry("대폐발의", "대표발의", "term"),
    DictionaryEntry("낙시", "낚시", "term"),  # 낚시금지구역 의안 빈출
    DictionaryEntry("심하 시간대", "심야시간대", "term"),
    DictionaryEntry("피로감이 유적되고", "피로감이 누적되고", "term"),
    DictionaryEntry("소호간 산무의 원칙", "소관 사무의 원칙", "term"),
    DictionaryEntry("지방재정법에 입안되지 않도록", "지방재정법에 위반되지 않도록", "term"),
    DictionaryEntry("안제 1조", "안 제1조", "term"),  # 조문 인용 '안 제N조'
    DictionaryEntry("안제 6조", "안 제6조", "term"),
    DictionaryEntry("쓰레기 투기 행위", "쓰레기 투기행위", "term"),
    # 경제노동위 — 결산·질의 보일러플레이트
    DictionaryEntry("회계년도", "회계연도", "term"),  # 비표준 '회계년도'(경노위 3회)
    DictionaryEntry("결산승인회권", "결산 승인의 건", "term"),  # '승인의 건'→'승인회권'
    DictionaryEntry("납부 요청서", "납부요청서", "term"),
    DictionaryEntry("지대해 주시기", "질의해 주시기", "term"),  # '질의해'→'지대해/지뢰해'
    DictionaryEntry("지뢰하실", "질의하실", "term"),
    DictionaryEntry("지뢰해 주시기", "질의해 주시기", "term"),
    DictionaryEntry("정화하게 인쇄", "정확하게 인쇄", "term"),
    DictionaryEntry("자금벌 세탁", "자금 세탁", "term"),
    DictionaryEntry("경기경제자육역청", "경기경제자유구역청", "term"),
    # 교육행정위 — 숫자혼입(육→6, 율→7, 공무→9)·예산회계명·기관명
    DictionaryEntry("교6원", "교육원", "term"),  # 학생교6원/미래과학교6원/국제교6원(4회)
    DictionaryEntry("7곡연수원", "율곡연수원", "term"),
    DictionaryEntry("지방9원", "지방공무원", "term"),  # '공무'→9(교육행정위 2회)
    DictionaryEntry("추경안경정 예산안", "추가경정예산안", "term"),
    DictionaryEntry("추가경전예산안", "추가경정예산안", "term"),  # '경정'→'경전'
    DictionaryEntry("경기도 교육비 특별회계", "경기도교육비특별회계", "term"),
    DictionaryEntry("경기도교육비 특별회계", "경기도교육비특별회계", "term"),
    DictionaryEntry("교육 지원 천 현안", "교육지원청 현안", "term"),  # '교육지원청'→'교육 지원 천'
    DictionaryEntry("바론데로", "발언대로", "term"),
    # ── 속기 정답 대조 채굴 (2026-07-04, 여성가족평생교육위 15594) — 적대검증 통과.
    #    속기록 vs AI 자막 diff 110쌍 → confirmed 20건. wrong 문자열이 4개 속기
    #    전문(15594/15575/15577/15580)에서 0회 출현함을 전수 확인. 긴 앵커 문자열은
    #    일반 문맥 충돌 차단용 의도적 문맥 고정(예: '원한대로' 단독은 정상어
    #    '원한 대로'와 충돌해 기각 — 앵커형만 채택). ──
    # 의의(意義)→이의(異議) — 이 회의 8회 발생 시스템성 오류(앵커로 정상 '의의' 보호)
    DictionaryEntry("의의가 있으십니까", "이의가 있으십니까", "term"),
    DictionaryEntry("의의가 없으므로 검토보고는", "이의가 없으므로 검토보고는", "term"),
    DictionaryEntry("의의가 없고 집행부", "이의가 없고 집행부", "term"),
    # 질의/토론 '종결'→'정결' 오인식(4회) — '정결(淨潔)을 선포'는 회의록에서 성립 불가
    DictionaryEntry("정결을 선포", "종결을 선포", "term"),
    # '원활한'→'운할한' (비단어, 15580 대조에서도 동형 관찰 — 재현성 확인)
    DictionaryEntry("운할한", "원활한", "term"),
    # 검토보고(서)로 '갈음'→'가름' 계열(6회) — '~로/를' 앵커로 '승부를 가름' 정상 용법과 분리
    DictionaryEntry("검토보고로 가름", "검토보고로 갈음", "term"),
    DictionaryEntry("검토보고서로 가름", "검토보고서로 갈음", "term"),
    DictionaryEntry("검토보고서를 가름", "검토보고서로 갈음", "term"),  # 조사 를→로 동시 교정
    # 종결 선포 연결어미 '계시므로'→'계심으로' 계열(10회)
    DictionaryEntry("안 계심으로", "안 계시므로", "term"),
    DictionaryEntry("안계심으로", "안 계시므로", "term"),
    DictionaryEntry("위원님이 계심으로", "위원님이 계시므로", "term"),
    # '원안대로'→'원한대로' — 의결/가결 선포 정형구 앵커형만(단독형 기각)
    DictionaryEntry("원한대로 의결하고자", "원안대로 의결하고자", "term"),
    DictionaryEntry("원한대로 가결됐음을", "원안대로 가결됐음을", "term"),
    # '논의를 거쳐'→'논의를 걸쳐' ('~를 걸쳐'는 비문 — 원표기 등장 불가)
    DictionaryEntry("논의를 걸쳐", "논의를 거쳐", "term"),
    # '거수로'→'거소로' — 짧은 '거소 신청'은 부재자투표 '거소신청'과 충돌해 기각됐던 건을
    # '거소로 …하여 주시기' 장문 앵커로 재구성(부재자투표 문맥은 이 표면형 불가)
    DictionaryEntry("거소로 신청하여 주시기", "거수로 신청하여 주시기", "term"),
    # '좌석에 배부해 드린'→'자세하게 배부해드린' ('자세하게'+'배부하다'는 비문;
    # 정형구 '보다 자세한 사항은 배부해 드린'과는 표면형 상이 — 충돌 없음)
    DictionaryEntry("자세하게 배부해드린", "좌석에 배부해 드린", "term"),
    # 규칙명 음절 탈락 — '경기도의회의 규칙'(조사+띄어쓰기)과 표면형 상이해 literal 안전
    DictionaryEntry("경기도의회의규칙", "경기도의회 회의규칙", "term"),
    # 부서명 — '이민사위국'은 비실재 조직명(소관 회의마다 재등장, 재현성 높음)
    DictionaryEntry("이민사위국장", "이민사회국장", "term"),
    # 의안명 병합/조사 탈락 — '아동놀'은 비단어
    DictionaryEntry("경기도아동놀권리증진", "경기도 아동의 놀 권리 증진", "term"),
    DictionaryEntry("아동놀 권리 증진", "아동의 놀 권리 증진", "term"),
    # ── 복구 체인(순서 의존 — 반드시 위 '계심으로' 계열 항목들 **뒤**에 위치) ──
    # correct()는 삽입순 순차 치환이므로, 위 '안 계심으로'/'위원님이 계심으로' 치환이
    # 정상 구문 '~계심으로 인해'(원인 표현: '안 계심으로 인해 연기')를 비문
    # '계시므로 인해'로 오염시킨 경우 이 항목이 원문으로 되돌린다.
    # 진양성(예: '안 계시므로 질의 종결을 선포')에는 '계시므로 인해' 표면형이
    # 등장하지 않으므로 무영향.
    DictionaryEntry("계시므로 인해", "계심으로 인해", "term"),
]


def get_default_dictionary() -> DictionaryService:
    """경기도의회 기본 사전이 탑재된 DictionaryService 싱글톤을 반환합니다."""
    return DictionaryService(entries=_PARLIAMENT_ENTRIES)
