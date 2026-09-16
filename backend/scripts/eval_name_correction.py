"""위원 이름 명부 교정(C-2) A/B 평가 하네스 — API 비용 0의 오프라인 측정.

목적(사용자 #1 요구 검증):
  ① 개선폭   — raw STT 대비 위원 이름이 얼마나 더 정확해지는가
  ② 안전성   — 명부 밖 이름을 명부 이름으로 잘못 바꾸는 "오생성"이 0건인가 (가장 중요)

A = raw STT 텍스트(교정 전), B = correct_member_names 적용(교정 후)를 골드(정답)와 비교한다.

사용법:
  python scripts/eval_name_correction.py                 # 내장 데이터셋
  python scripts/eval_name_correction.py --cases my.json  # 사용자 실측 예시 추가
  python scripts/eval_name_correction.py --staff-cases staff.json  # staff 실측 예시 추가

my.json 형식 (실제로 본 STT 오인식을 넣을수록 평가가 정확해집니다):
  [
    {"raw": "김종대 위원님 질의해 주십시오", "gold": "김종배 위원님 질의해 주십시오",
     "roster": ["김종배", "조성환"], "category": "misrec"},
    ...
  ]
  category: misrec(오인식→교정해야) | exact(정답 그대로) |
            nonmember(명부 밖, 손대면 안 됨) | committee(위원회명 등 일반어) |
            adversarial(명부와 비슷하지만 다른 실명 — 절대 바꾸면 안 됨)

staff 케이스(--staff-cases)는 같은 구조에 category만 staff_* 를 쓴다.
roster = 그 위원회 staff_roster(속기록 출석공무원) 이름 목록이며
correct_staff_names(이름+국장/과장/… 직책에서만 발동)로 평가한다:
  category: staff_misrec(오인식→교정해야) | staff_exact(정답 그대로) |
            staff_adversarial(명부 밖 인물+집행부 직책 — 절대 바꾸면 안 됨)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows 콘솔(cp949)에서도 한글·기호 출력이 깨지거나 죽지 않게 UTF-8로 강제.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:
    pass

from app.services.name_corrector import correct_member_names, correct_staff_names


@dataclass
class Case:
    raw: str
    gold: str
    roster: list[str]
    category: str


# 내장 데이터셋: 실제 경기도의회 상임위 발언 패턴을 모사.
# roster = 그 회의 위원회 명부(화면 영상 위원들). 골드 = 사람이 교정한 정답.
_BUILTIN: list[dict] = [
    # ── misrec: 한 글자 오인식 → 명부 이름으로 교정되어야 함 ──────────────
    {"raw": "김종대 위원님 나오셔서 제안설명해 주시기 바랍니다",
     "gold": "김종배 위원님 나오셔서 제안설명해 주시기 바랍니다",
     "roster": ["김종배", "조성환", "김시용", "박옥분"], "category": "misrec"},
    {"raw": "다음은 박옥뷴 위원 질의하시겠습니다",
     "gold": "다음은 박옥분 위원 질의하시겠습니다",
     "roster": ["김종배", "조성환", "김시용", "박옥분"], "category": "misrec"},
    {"raw": "김시영 위원께서 좋은 지적 해주셨습니다",
     "gold": "김시용 위원께서 좋은 지적 해주셨습니다",
     "roster": ["김종배", "조성환", "김시용", "박옥분"], "category": "misrec"},
    # ── exact: 이미 정확 → 손대면 안 됨 ──────────────────────────────────
    {"raw": "조성환 위원장입니다", "gold": "조성환 위원장입니다",
     "roster": ["김종배", "조성환", "김시용", "박옥분"], "category": "exact"},
    {"raw": "박옥분 위원과 김종배 위원이 함께 질의했습니다",
     "gold": "박옥분 위원과 김종배 위원이 함께 질의했습니다",
     "roster": ["김종배", "조성환", "김시용", "박옥분"], "category": "exact"},
    # ── nonmember: 명부 밖 인물(집행부·외부) → 그대로 둬야 함 ──────────────
    {"raw": "이재명 지사께서 답변하셨습니다", "gold": "이재명 지사께서 답변하셨습니다",
     "roster": ["김종배", "조성환", "김시용", "박옥분"], "category": "nonmember"},
    {"raw": "윤성근 국장 답변해 주시기 바랍니다", "gold": "윤성근 국장 답변해 주시기 바랍니다",
     "roster": ["김종배", "조성환", "김시용", "박옥분"], "category": "nonmember"},
    # ── committee: 일반어/위원회명 → 손대면 안 됨 ────────────────────────
    {"raw": "도시환경위원회 제1차 회의를 개의하겠습니다",
     "gold": "도시환경위원회 제1차 회의를 개의하겠습니다",
     "roster": ["김종배", "조성환", "김시용", "박옥분"], "category": "committee"},
    # ── adversarial: 명부와 비슷하지만 *다른* 실명 → 절대 바꾸면 안 됨 ──────
    # "박옥순"(외부인)은 명부 "박옥분"과 한 글자 차이지만 다른 사람.
    {"raw": "참고인 박옥순 위원께서 의견 주셨습니다",
     "gold": "참고인 박옥순 위원께서 의견 주셨습니다",
     "roster": ["김종배", "조성환", "김시용", "박옥분"], "category": "adversarial"},
    # ── committee: 위원회명 조각이 명부 위원명과 겹쳐도 '위원회'는 손대면 안 됨(리뷰 회귀가드) ──
    {"raw": "여성가족평생교육위원회를 개의합니다",
     "gold": "여성가족평생교육위원회를 개의합니다",
     "roster": ["평생교", "조성환"], "category": "committee"},
    # ── misrec: 이름 내부 공백을 STT가 넣어도 깨지지 않고 정규화 교정(리뷰 회귀가드) ──
    {"raw": "김 종배 위원 질의해 주시기 바랍니다",
     "gold": "김종배 위원 질의해 주시기 바랍니다",
     "roster": ["김종배", "조성환", "김시용", "박옥분"], "category": "misrec"},
    # ── adversarial: 동점(같은 ratio) 다수 → 모호하므로 원본 유지(엉뚱한 위원 둔갑 방지) ──
    {"raw": "김영주 위원이 발언했습니다",
     "gold": "김영주 위원이 발언했습니다",
     "roster": ["김영호", "김영수", "김영준"], "category": "adversarial"},
]

# 내장 staff 데이터셋: roster = 그 위원회 staff_roster(속기록 출석공무원) 이름.
# correct_staff_names(이름+집행부 직책에서만 발동)로 평가한다.
_BUILTIN_STAFF: list[dict] = [
    # ── staff_misrec: 실측 쌍 — 이강옥 → 이강욱 (교육행정위, '국장' 호칭 실측) ──────
    {"raw": "이강옥 국장님 답변해 주시기 바랍니다",
     "gold": "이강욱 국장님 답변해 주시기 바랍니다",
     "roster": ["이영창", "이강욱", "차미순", "서은경", "최희숙"], "category": "staff_misrec"},
    # ── staff_misrec: 실측 쌍 — 이해영 → 이애형. 발음은 유사하지만 문자 수준
    #    거리가 커서(3자 중 2자 상이, ratio 0.33) 현행 문자 퍼지매칭으론 미교정 —
    #    원본 유지가 안전 동작이며, 이 케이스는 한계 추적용으로 상시 측정한다. ──────
    {"raw": "이해영 과장님 보고해 주시기 바랍니다",
     "gold": "이애형 과장님 보고해 주시기 바랍니다",
     "roster": ["이애형", "김승영", "홍수민"], "category": "staff_misrec"},
    # ── staff_exact: 이미 정확(부서 결합 직함 포함) → 손대면 안 됨 ────────────────
    {"raw": "배성호 건설국장이 업무보고를 하겠습니다",
     "gold": "배성호 건설국장이 업무보고를 하겠습니다",
     "roster": ["배성호", "윤태완", "추대운", "조정아"], "category": "staff_exact"},
    {"raw": "한태우 수석전문위원 검토보고해 주시기 바랍니다",
     "gold": "한태우 수석전문위원 검토보고해 주시기 바랍니다",
     "roster": ["배성호", "윤태완", "한태우"], "category": "staff_exact"},
    # ── staff_exact: 이름+부서결합직함 무공백 표기 — 탐욕적 이름 그룹이 '배성호건'을
    #    포착해 '건'이 소실되던 회귀('배성호설국장') 감시. 접두 가드로 무변경이어야 함. ──
    {"raw": "배성호건설국장이 보고합니다",
     "gold": "배성호건설국장이 보고합니다",
     "roster": ["배성호", "윤태완"], "category": "staff_exact"},
    # ── staff_adversarial: 명부 밖 인물 + 국장 호칭 → 무변경 ────────────────────
    {"raw": "홍성진 국장이 참석했습니다",
     "gold": "홍성진 국장이 참석했습니다",
     "roster": ["배성호", "윤태완", "추대운"], "category": "staff_adversarial"},
    # ── staff_adversarial: 한 글자 차 동점(같은 ratio 다수) → 모호하므로 보류 ──────
    {"raw": "김영주 과장님 말씀해 주시기 바랍니다",
     "gold": "김영주 과장님 말씀해 주시기 바랍니다",
     "roster": ["김영호", "김영수"], "category": "staff_adversarial"},
]

# 집행부 직책 접미사 (staff 멘션 추출용 — name_corrector._STAFF_TITLE_RE와 동일 집합)
_STAFF_TITLES = r"국장|과장|실장|본부장|단장|처장|차장|팀장|담당관|전문위원"


def _member_mentions(text: str, roster: list[str]) -> list[str]:
    """텍스트에서 '명부 이름 + 위원/의원/위원장' 멘션만 추출 (정확도 채점용)."""
    import re

    names = "|".join(re.escape(n) for n in roster)
    if not names:
        return []
    return re.findall(rf"(?:{names})\s*(?:위원장|위원|의원)", text)


def _staff_mentions(text: str, roster: list[str]) -> list[str]:
    """텍스트에서 '명부 이름 + 집행부 직책' 멘션만 추출 (staff 오생성 채점용)."""
    import re

    names = "|".join(re.escape(n) for n in roster)
    if not names:
        return []
    return re.findall(rf"(?:{names})\s*(?:[가-힣]{{0,6}})?(?:{_STAFF_TITLES})", text)


def evaluate(cases: list[Case], threshold: float | None) -> None:
    cats: dict[str, dict[str, int]] = {}
    # (gold, after) 오생성. 정책상 adversarial 계열은 '알려진 한계', 그 외는 '회귀(regression)'.
    known_limit: list[tuple[str, str]] = []
    regressions: list[tuple[str, str]] = []

    for c in cases:
        is_staff = c.category.startswith("staff_")
        if is_staff:
            after = correct_staff_names(c.raw, c.roster, threshold)
            mentions = _staff_mentions
        else:
            after = correct_member_names(c.raw, c.roster, threshold)
            mentions = _member_mentions
        cat = cats.setdefault(c.category, {"n": 0, "pass_before": 0, "pass_after": 0})
        cat["n"] += 1
        if c.raw == c.gold:
            cat["pass_before"] += 1
        if after == c.gold:
            cat["pass_after"] += 1
        else:
            # 골드와 다른데, 명부 이름 멘션이 골드보다 늘었으면 오생성(없는 이름 만듦)
            after_members = set(mentions(after, c.roster))
            gold_members = set(mentions(c.gold, c.roster))
            if after_members - gold_members:
                (
                    known_limit
                    if c.category in ("adversarial", "staff_adversarial")
                    else regressions
                ).append((c.gold, after))

    print("=" * 64)
    print(f"이름 교정 A/B 평가  (threshold={threshold if threshold is not None else '기본(0.6)'})")
    print("=" * 64)
    print(f"{'category':<14}{'n':>4}{'before':>9}{'after':>9}  개선")
    print("-" * 64)
    tot_n = tot_b = tot_a = 0
    for name in (
        "misrec", "exact", "nonmember", "committee", "adversarial",
        "staff_misrec", "staff_exact", "staff_adversarial",
    ):
        s = cats.get(name)
        if not s:
            continue
        n, b, a = s["n"], s["pass_before"], s["pass_after"]
        tot_n += n; tot_b += b; tot_a += a
        delta = "+" + str(a - b) if a > b else (str(a - b) if a < b else "·")
        print(f"{name:<14}{n:>4}{b:>9}{a:>9}{delta:>6}")
    print("-" * 64)
    print(f"{'전체 정확도':<14}{tot_n:>4}{tot_b:>9}{tot_a:>9}")
    print(f"  before(raw STT): {tot_b}/{tot_n} = {tot_b / tot_n:.0%}")
    print(f"  after (C-2 교정): {tot_a}/{tot_n} = {tot_a / tot_n:.0%}")
    print("=" * 64)
    print("안전성 — 명부 밖 이름을 명부 이름으로 오생성한 건수")
    # 회귀 가드: adversarial 외 카테고리의 오생성은 0이어야 함(0이 깨지면 새 회귀).
    if regressions:
        print(f"  ❌ 회귀 {len(regressions)}건 — 새 안전 위반! (정규식/임계값 변경 의심)")
        for gold, after in regressions:
            print(f"     기대: {gold!r}\n     실제: {after!r}")
    else:
        print("  ✅ 회귀 0건 — 명부 밖 이름은 모두 원본 유지 (adversarial 제외)")
    # 알려진 한계: 문서화된 정책상 허용. 정확도 추적용으로만 표기.
    if known_limit:
        print(f"  ⚠ 알려진 한계 {len(known_limit)}건 (정책상 허용, CLAUDE.md 문서화):")
        for gold, after in known_limit:
            print(f"     기대: {gold!r}\n     실제: {after!r}")
    print("=" * 64)
    # 종료코드: 회귀가 있으면 1 (CI/사전점검에서 실패로 잡히게).
    if regressions:
        sys.exit(1)


def _load_cases_file(path: str, flag: str) -> list[dict]:
    """케이스 JSON 파일을 로드 (형식 오류 시 exit 2)."""
    try:
        with open(path, encoding="utf-8") as f:
            extra = json.load(f)
    except FileNotFoundError:
        print(f"오류: {flag} 파일을 찾을 수 없음: {path}")
        sys.exit(2)
    except json.JSONDecodeError as e:
        print(f"오류: {flag} JSON 파싱 실패 ({path}): {e}")
        sys.exit(2)
    if not isinstance(extra, list):
        print(f"오류: {flag}는 케이스 객체의 JSON 배열이어야 함")
        sys.exit(2)
    return extra


def main() -> None:
    parser = argparse.ArgumentParser(description="위원/공무원 이름 교정 A/B 평가")
    parser.add_argument("--cases", default=None, help="추가 케이스 JSON 파일 (위원)")
    parser.add_argument(
        "--staff-cases", default=None,
        help="추가 staff 케이스 JSON 파일 (category=staff_*, roster=staff 명부)",
    )
    parser.add_argument("--threshold", type=float, default=None, help="퍼지 임계값 오버라이드")
    args = parser.parse_args()

    raw_cases = list(_BUILTIN) + list(_BUILTIN_STAFF)
    if args.cases:
        raw_cases += _load_cases_file(args.cases, "--cases")
    if args.staff_cases:
        raw_cases += _load_cases_file(args.staff_cases, "--staff-cases")

    try:
        cases = [
            Case(raw=d["raw"], gold=d["gold"], roster=d["roster"], category=d.get("category", "misrec"))
            for d in raw_cases
        ]
    except (KeyError, TypeError) as e:
        print(f"오류: --cases 케이스에 필수 필드(raw/gold/roster) 누락 또는 형식 오류: {e}")
        sys.exit(2)
    for c in cases:
        if not isinstance(c.roster, list):
            print(f"오류: roster는 문자열 리스트여야 함: {c.roster!r}")
            sys.exit(2)
    evaluate(cases, args.threshold)


if __name__ == "__main__":
    main()
