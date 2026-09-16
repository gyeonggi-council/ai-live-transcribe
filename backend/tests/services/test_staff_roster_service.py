# -*- coding: utf-8 -*-
"""staff_roster_service 테스트 — 속기록 출석 명단 파싱 + 명부 헬퍼.

픽스처는 실제 임시속기록(_steno_15580.txt, 건설교통위원회)의 출석 블록을 내장한다.
"""

from app.services.staff_roster_service import (
    load_staff_roster,
    parse_steno_attendance,
    staff_bindings,
    staff_glossary_terms,
    staff_names,
)

# _steno_15580.txt 말미의 실제 출석 블록 (제391회 정례회 제1차 건설교통위원회)
STENO_15580_TAIL = """(15시00분 산회)
○ 출석위원(10명)
강태형
김동영
문병근
박명숙
박옥분
서성란
안명규
이홍근
성복임
허원
○ 청가위원(1명)
이영주
○ 출석전문위원
수석전문위원 한태우
○ 출석공무원
ㆍ건설국
국장 배성호
건설정책과장 홍원표
건설안전기술과장 이은철
도로정책과장 이용원
도로안전과장 표명규
하천과장 박현진
ㆍ교통국
국장 윤태완
광역교통정책과장 이관행
버스정책과장 구현모
버스관리과장 유충호
택시교통과장 정찬웅
ㆍ철도항만물류국
국장 추대운
철도정책과장 고태호
철도건설과장 박영신
철도운영과장 이철규
물류항만과장 박인희
ㆍ경기국제공항추진단 단장 조정아
ㆍ경기도건설본부
본부장 박재영
도로건설과장 김영섭
북부도로과장 이남용
건축시설과장 이훈
○ 기타참석자
ㆍ경기교통공사장 박재만
ㆍ평택항만공사 사장직무대행 김금규
○ 기록공무원
조현경
맨위로 이동"""

# _steno_15594.txt 말미의 실제 출석 블록 — 한 줄에 '직책 이름' 쌍이 붙어 나오는 형식
STENO_15594_TAIL = """○ 출석전문위원
수석전문위원 이창희
○ 출석공무원
ㆍ미래평생교육국
국장 김재훈평생교육과장 홍성덕
청년기회과장 김선화청소년과장 이승희
ㆍ여성가족국
국장 박연경보육정책과장 고현숙
아동돌봄과장 오명숙
○ 기타참석자
ㆍ경기도미래세대재단 대표이사 김현삼
○ 기록공무원
안현선"""

# _steno_15577.txt 말미의 실제 출석 블록 (제391회 제3차 경제노동위원회)
# — '실장 박노극경제기획관 권주성'처럼 '기획관' 직책이 접합된 형식 포함
STENO_15577_TAIL = """(14시58분 산회)
○ 출석위원(9명)
고은정김선영남경순이병숙이재영이채영정하용최민한원찬
○ 출석전문위원
수석전문위원 최종신
○ 출석공무원
ㆍ경제실
실장 박노극경제기획관 권주성
일자리경제정책과장 서갑수지역금융과장 남궁웅
공정경제과장 서봉자소상공인과장 김평원
산업입지과장 이민우규제개혁과장 김백식
ㆍ사회혁신경제국
국장 송은실사회혁신기획과장 정영호
베이비부머기회과장 남경아사회적경제육성과장 한유경
ㆍ노동국
국장 김도형노동정책과장 허영길
노동안전과장 이인용
ㆍ경기경제자유구역청
청장 김능식혁신성장본부장 예창섭
기획행정과장 김천광개발과장 안성현
투자유치과장 이문교
○ 기타참석자
ㆍ경기신용보증재단 이사장 시석중
ㆍ경기도사회적경제원장 남양호
○ 기록공무원
박은정"""

# _steno_15599 (제391회 제4차 본회의) 말미의 실제 출석 블록 발췌
# — 미인식 선두 직책(도지사/행정1부지사/교육감/감사관 등) 뒤에 '이름+다음직책'이
#   접합된 형식. 선두 직책을 못 알아보면 pending 없이 접합 토큰 전체가 직책으로
#   오인돼 "정두석 김성중기획조정실장"처럼 두 사람이 융합되던 실측 백필 버그.
STENO_15599_TAIL = """(11시32분 산회)
○ 청가의원(2명)
김태형서광범
○ 의회사무처(2명)
의정국장 박호순디지털의사과장 도연수
○ 출석공무원(45명)
- 경기도(33명)
ㆍ도지사
도지사 김동연
ㆍ행정1부지사
행정1부지사 김성중기획조정실장 정두석
안전관리실장 김규식도시주택실장 손임성
도시개발국장 이은선자치행정국장 조병래
정책기획관 정종국
ㆍ행정2부지사
행정2부지사 김대순균형발전기획실장 조장석
경기북부특별자치도추진단장 배진기평화협력국장 박현석
ㆍ경제부지사
경제부지사 안정곤경제실장 박노극
국제협력국장 박근균기후환경에너지국장 차성수
ㆍ소방재난본부
소방재난본부장 홍장표북부소방재난본부장 전용호
- 경기도교육청(12명)
ㆍ교육감
교육감 임태희홍보기획관 이길호
ㆍ제1부교육감
제1부교육감 김진수기획조정실장 윤소영
행정국장 이영창협력국장 하덕호
감사관 정진민정책기획관 서혜정
ㆍ제2부교육감
제2부교육감 홍정표학교교육국장 고아영
지역교육국장 차미순디지털인재국장 서은경
○ 기록공무원
이춘영
맨위로 이동"""

# _steno_15575.txt 말미의 실제 출석 블록 (제391회 제2차 교육행정위원회)
# — 'ㆍ운영지원과장 최희숙'처럼 불릿 선두 토큰이 부서가 아니라 직책인 형식 포함
STENO_15575_TAIL = """(15시39분 산회)
○ 출석위원(10명)
김근용김일중김회철문승호변재석오세풍이애형이은주이자형장한별
○ 출석전문위원
수석전문위원 김정희
○ 출석공무원
ㆍ운영지원과장 최희숙
ㆍ지방공무원인사과장 김승영
ㆍ행정국
국장 이영창학교설립과장 최복윤
재무관리과장 이강욱학교안전과장 진성규
시설과장 안정훈학교공간조성과장 성동규
사립학교과장 조완석
ㆍ지역교육국
국장 차미순지역교육정책과장 이강수
융합교육과장 홍수민생활교육과장 김영명
체육건강교육과장 김동권진로직업교육과장 김혜리
ㆍ경기도교육청학생교육원장 지미숙
ㆍ디지털인재국
국장 서은경디지털교육정책과장 이정현
교육역량과장 김태석평생교육과장 김휘도
ㆍ경기도교육청율곡연수원장 이근규
ㆍ경기도교육청미래과학교육원장 현계명
ㆍ경기도교육청국제교육원장 박숙열
ㆍ경기도교육청중앙도서관장 이승호
ㆍ경기도교육청성남도서관장 우호삼
ㆍ경기도교육청화성도서관장 이은형
ㆍ경기도교육청의정부도서관장 이미경
○ 기록공무원
신지원"""


def _by_name(entries: list[dict]) -> dict[str, dict]:
    return {e["name"]: e for e in entries}


class TestParseStenoAttendance:
    def test_parse_attendance_department_prefix(self):
        """부서 불릿(ㆍ건설국) + '국장 배성호' → full_title '건설국장'."""
        entries = parse_steno_attendance(STENO_15580_TAIL)
        by_name = _by_name(entries)

        assert by_name["배성호"] == {
            "name": "배성호",
            "title": "국장",
            "department": "건설국",
            "full_title": "건설국장",
        }
        # 직책에 이미 부서가 담긴 경우(건설정책과장)는 그대로
        assert by_name["홍원표"]["full_title"] == "건설정책과장"
        assert by_name["홍원표"]["department"] == "건설국"
        # 부서가 바뀌면 department도 갱신 (교통국 국장 → 교통국장)
        assert by_name["윤태완"]["full_title"] == "교통국장"
        # 본부장 결합 (경기도건설본부 + 본부장 → 경기도건설본부장)
        assert by_name["박재영"]["full_title"] == "경기도건설본부장"

    def test_parse_attendance_inline_form(self):
        """인라인형 'ㆍ경기국제공항추진단 단장 조정아' — 불릿 한 줄에 부서+직책+이름."""
        entries = parse_steno_attendance(STENO_15580_TAIL)
        by_name = _by_name(entries)

        assert by_name["조정아"] == {
            "name": "조정아",
            "title": "단장",
            "department": "경기국제공항추진단",
            "full_title": "경기국제공항추진단장",
        }

    def test_parse_includes_expert_advisors(self):
        """'○ 출석전문위원' 섹션(수석전문위원 한태우)도 포함한다."""
        entries = parse_steno_attendance(STENO_15580_TAIL)
        by_name = _by_name(entries)

        assert by_name["한태우"]["title"] == "수석전문위원"
        assert by_name["한태우"]["full_title"] == "수석전문위원"
        assert by_name["한태우"]["department"] is None

    def test_parse_stops_at_next_section(self):
        """다음 '○' 섹션(기타참석자/기록공무원)에서 중단 — 그 인원은 미포함."""
        entries = parse_steno_attendance(STENO_15580_TAIL)
        names = staff_names(entries)

        assert "박재만" not in names  # 기타참석자
        assert "김금규" not in names  # 기타참석자
        assert "조현경" not in names  # 기록공무원
        assert "강태형" not in names  # 출석위원(의원)
        # 출석전문위원 1 + 출석공무원 21
        assert len(entries) == 22

    def test_parse_fused_pairs_on_one_line(self):
        """'국장 김재훈평생교육과장 홍성덕'처럼 쌍이 붙은 줄(_steno_15594 형식) 분리."""
        entries = parse_steno_attendance(STENO_15594_TAIL)
        by_name = _by_name(entries)

        assert by_name["김재훈"]["full_title"] == "미래평생교육국장"
        assert by_name["홍성덕"]["full_title"] == "평생교육과장"
        assert by_name["김선화"]["full_title"] == "청년기회과장"
        assert by_name["이승희"]["full_title"] == "청소년과장"
        assert by_name["박연경"]["full_title"] == "여성가족국장"
        assert by_name["고현숙"]["full_title"] == "보육정책과장"
        assert "김현삼" not in by_name  # 기타참석자

    def test_parse_missing_section_returns_empty(self):
        """출석공무원/출석전문위원 섹션이 없으면 빈 리스트."""
        assert parse_steno_attendance("○ 출석위원(3명)\n강태형\n김동영\n문병근") == []
        assert parse_steno_attendance("") == []

    def test_parse_fused_gihoekgwan_title(self):
        """'실장 박노극경제기획관 권주성'(_steno_15577 형식) — '기획관' 직책 접합 분리.

        '경제기획관'이 직책으로 인식되지 않으면 pending '실장' 쌍까지 폐기되어
        경제실장 박노극·경제기획관 권주성 2명이 조용히 누락되는 회귀 케이스.
        """
        entries = parse_steno_attendance(STENO_15577_TAIL)
        by_name = _by_name(entries)

        assert by_name["박노극"] == {
            "name": "박노극",
            "title": "실장",
            "department": "경제실",
            "full_title": "경제실장",
        }
        assert by_name["권주성"]["title"] == "경제기획관"
        assert by_name["권주성"]["full_title"] == "경제기획관"
        assert by_name["권주성"]["department"] == "경제실"
        # 출석전문위원 1 + 출석공무원 20 — 누락 0
        assert len(entries) == 21
        # 기타참석자(산하기관)는 미포함
        assert "시석중" not in by_name
        assert "남양호" not in by_name

    def test_parse_multiple_pairs_after_unrecognized_leading_title(self):
        """'행정1부지사 김성중기획조정실장 정두석'(_steno_15599 본회의 형식) — 융합 방지.

        선두 직책(도지사/부지사/교육감/감사관)을 못 알아보면 접합 토큰
        '김성중기획조정실장' 전체가 직책으로 오인돼 다음 이름과 융합되던
        실측 백필 버그("정두석 김성중기획조정실장" 등 4건)의 재현 케이스.
        한 줄 안의 복수 '직책 이름' 쌍이 각각 분리되어야 한다.
        """
        entries = parse_steno_attendance(STENO_15599_TAIL)
        by_name = _by_name(entries)

        # 실측 융합 4건 — 쌍이 각각 분리되어야 함
        assert by_name["정두석"]["full_title"] == "기획조정실장"
        assert by_name["김성중"]["full_title"] == "행정1부지사"
        assert by_name["이길호"]["full_title"] == "홍보기획관"
        assert by_name["임태희"]["full_title"] == "교육감"
        assert by_name["윤소영"]["full_title"] == "기획조정실장"
        assert by_name["김진수"]["full_title"] == "제1부교육감"
        assert by_name["서혜정"]["full_title"] == "정책기획관"
        assert by_name["정진민"]["full_title"] == "감사관"
        assert by_name["고아영"]["full_title"] == "학교교육국장"
        assert by_name["홍정표"]["full_title"] == "제2부교육감"
        # 나머지 선두 직책 인물도 각자 직책으로 포착
        assert by_name["김동연"]["full_title"] == "도지사"
        assert by_name["김대순"]["full_title"] == "행정2부지사"
        assert by_name["안정곤"]["full_title"] == "경제부지사"
        # 융합 잔존 0: 어떤 full_title도 '이름(2~4자)+직책' 접합 토큰이 아니어야 함
        fused_titles = [
            e["full_title"]
            for e in entries
            if e["full_title"].startswith(("김성중", "임태희", "김진수", "정진민", "홍정표", "김대순", "안정곤"))
        ]
        assert fused_titles == []
        # 비대상 섹션(의회사무처/청가의원/기록공무원)은 미포함
        assert "박호순" not in by_name
        assert "도연수" not in by_name
        assert "이춘영" not in by_name
        # 발췌 인원 전원 (경기도 18 + 교육청 12 = 30)
        assert len(entries) == 30

    def test_parse_title_leading_bullet(self):
        """'ㆍ운영지원과장 최희숙'(_steno_15575 형식) — 불릿 선두가 부서가 아닌 직책.

        선두 토큰을 무조건 부서로 간주하면 과장/원장/관장급 10명이 누락되는 회귀 케이스.
        """
        entries = parse_steno_attendance(STENO_15575_TAIL)
        by_name = _by_name(entries)

        assert by_name["최희숙"] == {
            "name": "최희숙",
            "title": "운영지원과장",
            "department": None,
            "full_title": "운영지원과장",
        }
        # 직전 부서(지역교육국)가 직책 불릿으로 새어들지 않아야 함
        assert by_name["지미숙"]["department"] is None
        assert by_name["지미숙"]["full_title"] == "경기도교육청학생교육원장"
        # 기존 누락 10명 전원 검출 (과장/원장/관장급)
        for name in (
            "최희숙", "김승영", "지미숙", "이근규", "현계명",
            "박숙열", "이승호", "우호삼", "이은형", "이미경",
        ):
            assert name in by_name, f"{name} 누락"
        # 출석전문위원 1 + 출석공무원 27 — 누락 0
        assert len(entries) == 28


class TestRosterHelpers:
    def test_staff_glossary_terms_format(self):
        """글로서리 용어는 '이름 직함' 형식, 명부순, cap 초과 절단."""
        entries = parse_steno_attendance(STENO_15580_TAIL)
        terms = staff_glossary_terms(entries)

        assert "배성호 건설국장" in terms
        assert "조정아 경기국제공항추진단장" in terms
        assert "한태우 수석전문위원" in terms
        # cap 초과 절단 (명부순 유지)
        capped = staff_glossary_terms(entries, cap=3)
        assert len(capped) == 3
        assert capped == terms[:3]

    def test_staff_names_and_bindings(self):
        entries = parse_steno_attendance(STENO_15580_TAIL)

        names = staff_names(entries)
        assert "배성호" in names
        assert len(names) == len(entries)

        bindings = staff_bindings(entries)
        assert bindings["배성호"] == "건설국장"
        assert bindings["한태우"] == "수석전문위원"


class _ExplodingSupabase:
    """table() 접근부터 예외 — 테이블 미존재/마이그레이션 미적용 환경 모사."""

    def table(self, name: str):
        raise RuntimeError('relation "staff_roster" does not exist')


def test_load_staff_roster_fail_soft():
    """staff_roster 테이블이 없거나 오류여도 [] 반환 (앱은 죽지 않아야 함)."""
    assert load_staff_roster(_ExplodingSupabase(), "건설교통위원회") == []
class _FakeSupabase:
    """load_staff_roster 가 보는 최소 인터페이스만 흉내낸다."""

    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        assert name == "staff_roster"
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def execute(self):
        class R:
            pass

        r = R()
        r.data = list(self._rows)
        return r


def test_load_staff_roster_도지사_교육감이_맨_앞에_온다():
    """DB 물리 순서와 무관하게 선두 직책이 먼저 나와야 한다.

    글로서리 프롬프트는 900자에서 잘리고 의원명이 앞을 거의 다 차지해, staff 는 앞
    몇 명만 살아남는다. 도지사 이름을 한 번 UPDATE 했더니 그 행이 표 뒤로 밀려
    프롬프트에서 사라졌고 STT 가 옛 도지사 이름을 뱉었다(2026-09-01 실측).
    """
    rows = [
        {"name": "김성중", "full_title": "행정1부지사"},
        {"name": "이은선", "full_title": "도시개발국장"},
        {"name": "안민석", "full_title": "교육감"},
        {"name": "정두석", "full_title": "기획조정실장"},
        {"name": "추미애", "full_title": "도지사"},
    ]
    got = load_staff_roster(_FakeSupabase(rows), "본회의")

    assert [r["name"] for r in got][:3] == ["추미애", "안민석", "김성중"]
    assert len(got) == len(rows)  # 아무도 빠뜨리지 않는다


def test_load_staff_roster_같은_등급은_이름순_고정():
    """선두 직책이 아닌 나머지는 이름순 — 실행마다 순서가 흔들리면 프롬프트가 흔들린다."""
    rows = [
        {"name": "정두석", "full_title": "기획조정실장"},
        {"name": "김규식", "full_title": "안전관리실장"},
        {"name": "이은선", "full_title": "도시개발국장"},
    ]
    got = load_staff_roster(_FakeSupabase(rows), "본회의")

    assert [r["name"] for r in got] == ["김규식", "이은선", "정두석"]
