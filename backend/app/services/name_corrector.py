"""위원/의원 이름 명부 교정 — 자막 본문의 'OO 위원/의원' 이름을 그 회의 위원회
명부와 퍼지매칭해 정확한 이름으로 교체한다.

핵심 원칙(사용자 요구): 화면 영상의 위원회에 속한 위원 이름만, 오타 없이 표시.
- 명부에 충분히 가까운 이름이 있으면 → 그 정확한 이름으로 교체.
- 명부에 충분히 가까운 이름이 없으면 → 원본 유지(없는 이름을 만들어내지 않음).
- 이미 명부에 정확히 있는 이름은 손대지 않음.

speaker_cue_tracker와 동일한 difflib 임계값(settings.cue_match_threshold)을 쓴다.

알려진 한계 (정책: 현행 유지 + 위험 문서화, 사용자 승인 2026-06-09):
  문자 거리만으로는 "STT가 위원 이름을 잘못 들음"(김종대→김종배, 교정 옳음)과
  "명부와 비슷한 다른 사람"(박옥순≠박옥분, 교정 그름)을 구분할 수 없다. 3글자 한글
  이름은 끝 글자 하나만 달라도 difflib 비율이 0.667이라 둘이 동점이다. 따라서 비명부
  인물이 '위원/의원' 호칭으로 불리고 명부 위원과 한 글자 차이면 그 명부 위원으로
  오교정될 수 있다(= 명부 밖 이름을 명부 이름으로 바꿈).
  완화책 ① 정규식이 '이름+위원/의원/위원장' 호칭에서만 발동 → 실무상 비명부 인물은
  '국장/참고인'으로 불려 발동 안 함(천연 방어막). ② 더 강한 정밀도가 필요하면 화자
  신원(diarize/voiceprint)과 결합해 '명부 위원으로 식별된 화자' 구간에서만 교정.
  이 한계는 scripts/eval_name_correction.py의 'adversarial' 케이스로 회귀 감시한다
  (오생성 0건이 깨지면 즉시 드러남).

  staff 규칙(correct_staff_names)도 동일 정책이다: '이름 + 집행부 직책(국장/과장/
  실장/…/전문위원)'에서만 발동하고, staff 명부(속기록 출석명단)와 유일 퍼지매칭될
  때만 교체한다. 비명부 인물이 집행부 직책으로 불리고 명부 이름과 한 글자 차이면
  member 경로처럼 오교정될 수 있다(정책상 허용, 'staff_adversarial' 케이스로 감시).
  '위원/의원' 계열 호칭은 correct_member_names 영역이며 staff 경로는 건드리지
  않는다(단, '전문위원'은 집행부 직책이므로 staff 쪽).
  불변식: 직책이 '위원장'으로 끝나면(위원장/부위원장/OO위원장) staff 경로는 절대
  발동하지 않는다 — '위원장'이 부서접두 '위'+접미사 '원장'으로 정규식에 매칭되는
  한계 때문에 위원장 이름이 staff 명부 이름으로 오염되던 결함의 가드. '연수원장'
  '교육원장' 같은 정당한 staff 직책('원장' 접미)은 계속 발동한다.
  방어 가드: 이름+부서결합직함이 공백 없이 붙은 표기('배성호건설국장')에서 탐욕적
  이름 그룹이 부서 접두 첫 글자를 흡수해 후보가 '명부 이름 + 여분 글자'가 되는데,
  이때 퍼지매칭 교체는 그 글자를 소실시킨다 → 명부 이름이 후보의 정확한 접두면
  원본이 이미 정확한 것으로 보고 보류한다(정확 일치 무변경 원칙의 확장).
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.core.config import settings
# staff 직책 접미사의 단일 원천 — 파서(staff_roster_service)와 정규식이 어긋나
# '기획관' 등 명부에는 있는 직책에서 교정이 미발동하던 결함 방지.
# (staff_roster_service는 표준 라이브러리만 import — 순환 import 없음)
from app.services.staff_roster_service import STAFF_TITLE_SUFFIXES

# "OO 위원장/부위원장/위원/의원" — 이름(2~4 한글, 내부 공백 허용) + 호칭.
#   (?<![가-힣])          앞이 한글이면 매칭 시작 금지 → 앞 단어 꼬리 잠식 방지
#                          (예: '저는김종대 위원'에서 '는'을 먹어 '저김종대'로 손상되는 것 차단)
#   [가-힣](?:\s*(?!부위원장)[가-힣]){1,3}  2~4음절 이름, 음절 사이 공백 흡수.
#                          ★(?!부위원장): 이름 그룹이 '부위원장'의 '부'를 흡수하는 버그 차단.
#                          과거 '심원순 부위원장'→이름='심원순부'(4글자)가 되어 명부 '심홍순'과의
#                          퍼지 비율이 0.667→0.571로 떨어져 임계값 미달→교정 실패했다.
#                          (예: STT가 '김 종배'로 띄우면 group(1)='김 종배' 전체 포착은 유지)
#   부위원장               '부위원장'을 호칭으로 직접 인식(부가 이름에 새지 않게 alternation 최상단).
#   위원(?!회)             '위원회'의 '위원'은 제외 → 위원회명 손상 방지. 위원장은 별도 분기로 보존.
_NAME_RE = re.compile(
    r"(?<![가-힣])([가-힣](?:\s*(?!부위원장)[가-힣]){1,3})(\s*)(부위원장|위원장|위원(?!회)|의원)"
)

# "OO 국장/과장/…" — 이름(2~4 한글) + 집행부 직책에서만 발동 (staff 이름 교정용).
#   직책 앞의 부서 접두(≤6 한글, 예: '건설정책'과장, '수석'전문위원)를 흡수해
#   결합 직함 전체를 보존한다. '위원/의원' 계열은 member 경로 영역이라 제외
#   (전문위원만 집행부 직책으로 staff 쪽에서 처리).
#   접미사 집합은 staff_roster_service.STAFF_TITLE_SUFFIXES 단일 원천을 공유한다
#   (긴 접미사 우선 alternation — '본부장'이 '부장'보다 먼저 시도되도록).
_STAFF_TITLE_RE = re.compile(
    r"(?<![가-힣])([가-힣]{2,4})\s*"
    r"((?:[가-힣]{0,6})?(?:"
    + "|".join(sorted(STAFF_TITLE_SUFFIXES, key=len, reverse=True))
    + r"))"
)

# 부동소수 ratio 동점 비교 허용 오차
_EPS = 1e-9


def _norm(name: str) -> str:
    return re.sub(r"\s+", "", name or "")


def _norm_roster(names: list[str]) -> list[tuple[str, str]]:
    """명부를 (정규화 이름, 원본 이름) 쌍으로 변환 (2글자 미만 제외)."""
    return [(_norm(n), n) for n in names if n and len(_norm(n)) >= 2]


def _match_unique(cand: str, norm_roster: list[tuple[str, str]], threshold: float) -> str | None:
    """cand에 대해 명부에서 '유일한 임계값 초과' 매칭을 찾으면 그 명부 이름, 없으면 None.

    동점(같은 ratio 다수)이면 어느 사람인지 모호하므로 None(엉뚱한 사람으로
    둔갑 금지 — '없는/틀린 이름 생성 금지' 원칙). member/staff 경로가 공유한다.
    """
    # 이미 명부에 정확히 존재 → 명부 표기 반환(내부 공백만 제거, 이름 보존).
    for rn_n, rn in norm_roster:
        if rn_n == cand:
            return rn
    best_ratio = threshold
    best_names: list[str] = []
    for rn_n, rn in norm_roster:
        r = SequenceMatcher(None, cand, rn_n).ratio()
        if r > best_ratio + _EPS:
            best_ratio = r
            best_names = [rn]
        elif best_names and abs(r - best_ratio) <= _EPS:
            best_names.append(rn)
    return best_names[0] if len(set(best_names)) == 1 else None


def correct_member_names(
    text: str,
    roster_names: list[str],
    threshold: float | None = None,
) -> str:
    """자막 텍스트의 위원/의원 이름을 명부와 매칭해 교정한 새 문자열을 반환한다."""
    if not text or not roster_names:
        return text
    # 운영 경로(settings)는 0.5 하한으로 클램프 — cue_match_threshold env 오설정이
    # no-invention 원칙을 약화시키는 것 방지. 명시적 threshold 인자(eval 테스트)는 그대로 honor.
    th = threshold if threshold is not None else max(settings.cue_match_threshold, 0.5)
    norm_roster = _norm_roster(roster_names)
    if not norm_roster:
        return text

    def _repl(m: "re.Match[str]") -> str:
        cand = _norm(m.group(1))
        if len(cand) < 2:
            return m.group(0)
        # 후보 변형: 기본(전체) + (4글자면 앞 1글자 떼기). 4글자 후보는 앞에 조사/접미사가
        # 붙은 경우가 많다(예: '박정진 씨 임충식'→그룹 '씨 임충식'→'씨임충식'). 뒤 3글자
        # '임충식'이 명부 '윤충식'과 매칭된다. 한국 위원 이름은 대부분 2~3음절이라,
        # 전체가 매칭 안 될 때만 뒤 3글자를 시도해 오교정 위험을 최소화한다.
        variants = [cand]
        if len(cand) == 4:
            variants.append(cand[1:])
        for v in variants:
            if len(v) < 2:
                continue
            hit = _match_unique(v, norm_roster, th)
            if hit is not None:
                return f"{hit}{m.group(2)}{m.group(3)}"
        # 후보 없음 또는 동점 모호 → 원본 유지.
        return m.group(0)

    return _NAME_RE.sub(_repl, text)


def correct_staff_names(
    text: str,
    staff_names: list[str],
    threshold: float | None = None,
) -> str:
    """자막 텍스트의 집행부 공무원 이름('OO 국장/과장/…')을 staff 명부와 매칭해 교정한다.

    correct_member_names와 동일 원칙: 명부와 유일 퍼지매칭될 때만 교체, 동점/모호는
    보류, 명부 밖 이름은 절대 생성하지 않으며, 정확 일치는 무변경. '위원/의원' 계열
    호칭은 member 경로 영역이라 발동하지 않는다(전문위원은 staff 직책).
    불변식: 직책이 '위원장'으로 끝나면(위원장/부위원장/OO위원장) 무조건 원본 유지 —
    '위'+'원장' 정규식 매칭 한계로 위원장 이름이 staff 이름으로 오염되는 것 차단.
    """
    if not text or not staff_names:
        return text
    th = threshold if threshold is not None else max(settings.cue_match_threshold, 0.5)
    norm_roster = _norm_roster(staff_names)
    if not norm_roster:
        return text

    def _repl(m: "re.Match[str]") -> str:
        # ★위원장 가드: '위원장'은 부서접두([가-힣]{0,6})가 '위'/'부위'를 흡수하고
        # 접미사 '원장'에 매칭돼('위원장'='위'+'원장') staff 직책으로 오인된다.
        # 위원장/부위원장/OO위원장은 위원 호칭(correct_member_names 영역)이므로
        # staff 명부로 교체하면 위원장 이름이 staff 이름으로 오염된다 → 무조건 원본
        # 유지. '연수원장'/'교육원장' 같은 정당한 staff 직책은 '위원장'으로 끝나지
        # 않아 계속 발동한다(endswith('위원장')만 제외).
        if m.group(2).endswith("위원장"):
            return m.group(0)
        cand = _norm(m.group(1))
        if len(cand) < 2:
            return m.group(0)
        # 이름+부서결합직함이 공백 없이 붙으면 탐욕적 이름 그룹([가-힣]{2,4})이 부서
        # 접두 첫 글자를 흡수한다(예: '배성호건설국장' → cand='배성호건'). 이때 명부
        # 이름이 cand의 정확한 접두이면 원본이 이미 정확한 표기이므로 보류 — 퍼지매칭
        # 으로 교체하면 흡수된 글자가 소실된다('배성호건'→'배성호' 치환 시 '건' 증발).
        if any(cand != rn_n and cand.startswith(rn_n) for rn_n, _ in norm_roster):
            return m.group(0)
        hit = _match_unique(cand, norm_roster, th)
        if hit is None:
            return m.group(0)  # 후보 없음 또는 동점 모호 → 원본 유지
        ws = m.string[m.end(1):m.start(2)]  # 이름-직책 사이 원본 공백 보존
        return f"{hit}{ws}{m.group(2)}"

    return _STAFF_TITLE_RE.sub(_repl, text)
