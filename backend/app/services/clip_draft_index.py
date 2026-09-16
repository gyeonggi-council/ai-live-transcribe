# -*- coding: utf-8 -*-
"""클립 인덱스 — 공식(KMS) → AI 자막(잠정) 순으로 의원별 발언 구간을 만든다.
AI 자막이 없으면(실시간 자막뿐) 의원 구간을 내지 않는다 — 수동 자르기만.

실측(2026-09-03, 09-02 본회의 실시간 자막 1,896건):
  - 실시간 자막의 speaker 는 "추미애 도지사"·"집행부 국장"·"위원장" 같은 직책 라벨이고,
    의원 발언에도 그 라벨이 그대로 붙어 있었다 → 화자 컬럼으로 의원 구간을 못 만든다.
  - 대신 본문에 "…더불어민주당 박은주 의원입니다"(자기소개) / "김태희 의원님 질문하시고"(호명)가
    STT 로 살아남는다. 공식 KMS 인덱스도 정확히 그 순간에 찍히므로 형태가 같다.
  → 본문 단서 규칙(build_draft_from_cues)은 그렇게 생겼다.
  ⚠ 실시간 자막을 시간축 오프셋(clip_time_offset)으로 보정해 쓰던 폴백은 2026-09-08 에 뺐다 —
    VOD 등록 직후 AI 자막 전 회의에서 엉뚱한 의원이 잘렸다(사용자 결정: AI 자막 완료 전엔 수동만).

실측 2(2026-09-04, 393회 본회의 1·3차):
  - 본회의는 KMS 공식 인덱스가 "회의 개의" 한 줄뿐이라 의원 항목이 없다 → 본회의는 늘 초안 방식이다.
  - AI 자막(VOD 전사)도 speaker 가 비어 있을 수 있다(1차 645건 전부 None). 본문 단서는 그대로
    살아 있으므로 AI 자막에도 같은 단서 규칙을 쓴다. 시간축이 VOD 라 오프셋은 필요 없다.
  - 호명("김해철 의원님 나오셔서")과 자기소개("김회철 의원입니다")가 1분 안에 붙어 나오는데 STT 가
    한쪽을 틀리면 다른 두 사람의 짧은 구간으로 갈라졌다 → 90초 안의 연속 단서는 한 사람으로 합친다.
  - 마지막 호명 뒤로 집행부 답변 3시간이 통째로 붙었다(김진명 02:36→05:40) → 의장의 마무리
    문구("일괄 답변", "이상으로 … 마치겠습니다", "산회")와 상한(45분)으로 끝을 자른다.
"""

from __future__ import annotations

import asyncio
import logging
import re
from difflib import SequenceMatcher
from typing import Any, Callable, Optional

from app.services import kms_angun_service as kms
from app.services.speaker_segments import _fetch_all_subtitles, build_speaker_segments

logger = logging.getLogger(__name__)

# 자기소개: "… 박은주 의원입니다" / "김태희 도의원입니다" / "홍길동 위원입니다"
_SELF_RE = re.compile(r"([가-힣]{2,4})\s*(?:도의원|위원장|부위원장|위원|의원)\s*입니다")
# "의정부 출신 도의원 조병진입니다" — 직책이 이름 앞에 오는 자기소개.
# ★'(수석)전문위원 OOO입니다' 는 의원이 아니다 — '위원' 이 '전문위원' 의 꼬리로 걸려 김정희 수석전문위원의
#   검토보고 5분이 자모 퍼지로 김태희 의원 클립이 됐다(2026-09-10, 393회 도시환경위 3차 00:14:07).
_NOT_MEMBER_TITLE = r"(?<!전문)"      # '전문위원'·'수석전문위원' 의 '위원' 은 의원 직함이 아니다
_SELF_ROLE_FIRST_RE = re.compile(_NOT_MEMBER_TITLE + r"(?:도의원|위원|의원)\s+([가-힣]{2,4})\s*입니다")
# 이름과 직함 사이 STT 잡음 2글자('김철환 부연위원님') — '전문' 이면 '김정희 전문위원님' 이 김태희 의원 호명·마무리가 된다
_NOISE2 = r"(?:(?!전문)[가-힣]{2})?"
# "장민수원입니다" — STT 가 '의' 를 삼킨 자기소개. 명부 정확일치일 때만 믿는다(find_cues 에서 검사)
_SELF_LENIENT_RE = re.compile(r"([가-힣]{3})원입니다")
# "김포 출신 김철환입니다" / "고향의 류기준입니다" — 직책 없는 자기소개(지역 뒤). 명부에 있어야 한다
_SELF_NAME_ONLY_RE = re.compile(r"(?:출신의?|[가-힣]{2,6}의)\s+([가-힣]{2,4})\s*입니다")
# "안녕하세요, 박상현입니다" — 이름만의 자기소개. 명부에서 풀려야만 쓴다(집행부 이름은 명부에 없다)
_SELF_BARE_RE = re.compile(r"(?:^|[\s,.])([가-힣]{3,4})입니다")   # 2글자는 "수원 국중입니다"(학교명) 가 국중범에 붙는다
# 위원장 본인 질의 — "본위원장도 몇 마디" / "제가 질의를 하도록"
_CHAIR_SELF_Q_RE = re.compile(r"본\s*위원장(?:도|이|의)|제\s*차례|제가\s*(?:몇\s*마디|이\s*자리에서|질의를?\s*(?:하도록|하겠))")
# 마무리 — "OO 의원님 수고하셨습니다": OO 의 슬롯은 여기서 끝난다(호명이 STT 에서 빠졌을 때 슬롯을 여기서 가른다)
_CLOSING_RE = re.compile(r"(?!전문)([가-힣]{2,4})\s*" + _NOISE2 + r"(?:의원|위원|부위원장|위원장)님?[,\s]*(?:수고|고생)")
# 호명(위원장이 발언권을 줄 때): "김태희 의원님 질의하십시오" / "홍길동 위원 발언해 주시기 바랍니다" /
# "나오셔서 …". "질의 잘 들었습니다" 같은 답변 속 언급은 매치되지 않게 명령형만 잡는다.
_CALL_RE = re.compile(
    r"([가-힣]{2,4})\s*" + _NOISE2 + r"(?:도의원|위원|의원|부위원장)(?:님)?(?:께서는)?[,\s]*"   # '김철환 부연위원님' 의 잡음 2글자 허용 · "께서는 좌석에서"
    r"(?:좌석에서\s*)?(?:간단한\s*)?"                                                  # "김선희 부위원장님께서는 좌석에서 인사 말씀을"
    r"(?:(?:보충\s*|의사진행\s*)?(?:질의|질문|발언)(?:을|를)?\s*(?:해\s*주|하여\s*주|하시|하십|해주|부탁)"
    r"|말씀\s*(?:해\s*주|해주|부탁)"                      # "말씀하신" 은 집행부 답변 속 언급이라 뺀다
    r"|자료\s*(?:요청|요구|청)\s*(?:해\s*주|해주|하시|부탁)"  # 자료요구 순서
    r"|인사\s*(?:말씀(?:을|를)?\s*)?(?:해\s*주|해주|하시|말씀|부탁)"   # 인사 순서 — "OO 의원님 인사(말씀을) 해 주시기 바랍니다"
    r"|나오(?:셔서|시)|부탁\s*드리|먼저\s*(?:해|하)\s*주)"
)
# 의장·위원장의 마무리 문구 — 이 뒤는 의원 발언이 아니다(집행부 일괄 답변·다음 안건·산회).
# 의원 본인의 "이상으로 질문을 마치겠습니다" 도 잡히지만, 그 뒤는 답변이라 잘라도 맞다.
# "답변을 듣" 은 의장의 "답변을 듣도록/듣겠습니다" 만 — 의원이 일문일답 중에 "답변 듣고 궁금하잖아요"
# 라고 한 것이 걸려 김태희 도정질문이 17분 일찍 잘렸다(2026-09-02 2차 실측).
_END_RE = re.compile(
    r"(일괄\s*답변|답변을?\s*듣(?:도록|겠)|이상으로\s*.{0,20}(?:마치|끝내)|산회를?\s*선포|정회를?\s*선포"
    r"|의사일정\s*제?\s*\d+\s*항)"
)
# 위원장 줄에서만 — "네, 이어서 김태희 의원님." / "없으신가요? 전자영 의원님?" 처럼 이름으로 끝나는 호명.
# (집행부의 "OO 의원님 말씀하신…" 을 호명으로 오인하지 않도록 위원장 라벨 줄에만 적용한다)
_CHAIR_CALL_RE = re.compile(r"([가-힣]{2,4})\s*(?:의원|위원|부위원장)?님[\s.?!,]*$")   # "네, 김태현님." 도 위원장 줄이면 호명
# 질문형 호명 — "유기준 의원님 보충 질의하실 수 있습니까?" 는 뒤에 그 의원(닮은 라벨)이 말하면 호명이고,
# "이건한 의원님 보충 질의 하시겠어요?" 뒤에 위원장이 직접 질의하면 호명이 아니다 → 60초 안 의원 라벨로 확인한다
_CALL_QUESTION_RE = re.compile(
    r"([가-힣]{2,4})\s*" + _NOISE2 + r"(?:도의원|위원|의원|부위원장)(?:님)?[,\s]*(?:보충\s*)?(?:질의|질문)\s*(?:하실\s*수|하시겠)"
)
# 줄머리 호명 — "전석훈 의원님, 진례(질의)해 주시기 바랍니다" 처럼 동사가 STT 로 깨져도 이름으로 시작하면 호명이다.
# 집행부 줄은 제외하고, 의원 라벨 줄은 라벨과 다른 이름일 때만(자기 이름으로 시작하는 건 자기소개·답변).
_LINE_START_CALL_RE = re.compile(
    r"^[네예아,.\s]*(?:그러면\s*|그러시면\s*|그럼\s*|자[,\s]*|그다음에?\s*|이어서\s*|다음(?:은|에는|으로|에)?[,\s]*)?(?:존경하는\s*)?(?:우리\s*)?"
    r"([가-힣]{2,4})\s*(?:의원|위원|부위원장)님"
)
# 위원장의 진행 전환 — "OO 의원님 수고하셨습니다. 다음은 XX 의원님 질의해 주시기 바랍니다" /
# "더 이상 질의하실 의원님 안 계시므로 …". 앞 의원의 슬롯은 여기서 끝난다(호명 정규식이 못 잡아도).
_BOUNDARY_RE = re.compile(
    r"(?:의원|위원|부위원장|위원장)님?[,\s]*(?:수고|고생)\s*(?:하셨|많으셨)"   # "OO 의원님 수고하셨습니다" — 의원이 집행부에게 "수고하셨고요" 는 아니다
    r"|질의\s*하실\s*(?:의원|위원)님|(?:다음|이어서)\s*(?:은|에는|으로)?[,\s]*[가-힣]{2,4}\s*(?:의원|위원)님"
    r"|질의\s*(?:해\s*주시기|하시기|해\s*주십시오|해주십시오)"   # 이름이 앞 줄에 잘려도 "질의해 주시기 바랍니다" 는 전환이다
)
# 위원장 라벨 줄이면 이름 없는 "수고하셨습니다" 도 전환이다
_BOUNDARY_CHAIR_RE = re.compile(r"(?:수고|고생)\s*(?:하셨|많으셨)")
_ROLE_RE = re.compile(r"^([가-힣]{2,4})\s*(도의원|위원장|부위원장|위원|의원|부의장|의장)?\b")
_CHAIR_ROLES = ("위원장", "부위원장", "의장", "부의장")
# 의원이 아닌 라벨 — AI 자막 화자명에서 버린다. 전문위원·조사관은 위원회 사무처 직원이다(2026-09-10)
_NON_MEMBER_RE = re.compile(r"(도지사|교육감|집행부|국장|과장|부장|실장|본부장|차관|장관|전문위원|조사관|미지정|^화자\s*\d+$)")
# 이름 바로 앞의 비의원 직함 — "수석전문위원 김정희입니다"·"건설국장 배성호입니다" 의 이름은 의원이 아니다.
# 명부 퍼지(자모 0.78)가 김정희→김태희 로 풀어 남의 클립이 됐다. '위원장' 은 의원이라 '(?<!위)원장' 으로 빼고,
# '대표' 는 넣지 않는다 — "비례대표 최혜경입니다" 는 의원 자기소개다(넣었다가 392회 경제노동위 1차 최혜경 2구간이 사라졌다)
_TITLE_BEFORE_NAME_RE = re.compile(
    r"(?:전문위원|조사관|국장|과장|실장|본부장|단장|담당관|청장|부장|차장|팀장|주무관|(?<!위)원장|사장|"
    r"교육감|지사|차관|장관|비서관|소장|관장|센터장)님?\s*$"
)

MIN_SEGMENT_SECONDS = 20.0        # 이보다 짧은 초안 구간은 오탐으로 본다
MIN_CUE_SLOT_SECONDS = 8.0        # 호명으로 열린 슬롯은 더 짧아도 실제다 — 인사 순서는 10~16초(안전행정위 실측)
CUE_MERGE_SECONDS = 90.0          # 이 안에 붙은 호명→자기소개(닮은 이름)는 한 사람이다
CUE_NOISE_SECONDS = 10.0          # 이 안에 붙은 단서 둘은 이름이 달라도 STT 잡음 — 한 사람
END_PHRASE_MIN_SECONDS = 60.0     # 단서 직후 60초 안의 마무리 문구는 앞사람 것이다
MAX_SEGMENT_SECONDS = 45 * 60.0   # 5분 발언·도정질문 어느 쪽도 이보다 길지 않다
CHAIR_TALK_MIN_SECONDS = 60.0     # 위원장 발언이 이보다 길면 진행 멘트가 아니라 본인 질의다
RUN_GAP_SECONDS = 180.0           # 같은 의원의 다음 발언까지 이보다 비면 새 구간(한 번 끝났다가 다시 나온 것)
END_PHRASE_FALLBACK_SECONDS = 20 * 60.0   # 위원장 전환 없이 이보다 길면 마무리 문구("이상으로 … 마치")로 자른다


def detect_subtitle_kind(subs: list[dict]) -> str:
    """'ai' | 'live' | 'legacy'(kind 없음) | 'none'"""
    if not subs:
        return "none"
    if any(s.get("kind") == "ai" for s in subs):
        return "ai"
    if any(s.get("kind") == "live" for s in subs):
        return "live"
    return "legacy"


def _make_group(name: str, role: str, key: str) -> dict:
    return {"key": key, "code": "", "name": name, "role": role or "의원",
            "party": None, "district": None, "photo_url": None, "councilor_id": None,
            "segments": [], "total_seconds": 0.0}


def _classify_label(label: str, roster: list[dict]) -> Optional[tuple[str, str, str]]:
    """AI 자막 화자 라벨 → ("member"|"chair", 이름, 역할). 집행부·미지정·화자 N 은 None.

    '최현정 인권담당관'·'배진기 추진단장' 처럼 이름 뒤에 의원 직책이 아닌 꼬리말이 붙은 라벨은
    명부 퍼지 매칭에 넣지 않는다 — 3음절 이름은 한 글자만 겹쳐도 0.767 로 의원에 붙는다.
    """
    label = str(label or "").strip()
    if not label or _NON_MEMBER_RE.search(label):
        return None
    m = _ROLE_RE.match(label)
    if not m:
        return None
    name, role = m.group(1), m.group(2)
    if role is None and len(label.split()) > 1:
        return None
    if roster and not kms.match_councilor(name, roster):
        return None
    return ("chair" if role in _CHAIR_ROLES else "member"), name, (role or "의원")


def _line_not_executive(label: Any) -> bool:
    """호명 단서가 든 자막 줄이 집행부 것이 아닌가. 위원장 줄이 다른 의원으로 잘못 붙는 일이 흔해
    (라벨 오귀속) 의원 라벨은 통과시킨다 — 의원끼리 "OO 의원님 질의해 주시기 바랍니다" 라고는 하지 않는다.
    집행부 답변 속 "OO 의원님 질의하신…" 만 걸러낸다."""
    label = str(label or "").strip()
    if not label or re.search(r"미지정|^화자\s*\d+$", label):
        return True
    return not _NON_MEMBER_RE.search(label)


def build_draft_from_ai(segments_result: dict, roster: list[dict],
                        subs: Optional[list[dict]] = None,
                        duration: float | None = None,
                        label_supplement: bool = True) -> list[dict]:
    """AI 자막 → 의원별 **질의답변 슬롯**. `subs`(AI 자막 본문)가 있으면 위원장 호명 단서가 뼈대다.

    실측(2026-09-08, 393회 1차 안전행정위): 화자 교대 단위 그대로 내면 강성삼 위원이 12구간
    (123·35·72·26·11초…)으로 쪼개진다 — 의원이 묻고 집행부가 답할 때마다 끊기기 때문이다.
    담당자가 원하는 단위는 KMS 공식 인덱스의 `질의답변(전자영 위원)` 처럼 **의원의 첫 발언부터
    위원장이 다음 의원을 부르는 순간까지**(집행부 답변 포함, 약 5분) 다.

    실측 2(같은 날, 공식 인덱스가 있는 392회 위원회 8건·공식 구간 298개로 채점 — scripts/eval_clip_slots.py):
    화자 라벨만으로 세운 슬롯은 57%(질의답변 66%). 틀린 것은 거의 전부 **라벨이 틀린 것**이었다 —
    위원장은 "다음은 윤충식 의원님 질의해 주시기 바랍니다" 라고 정확히 불렀는데 그 뒤 발언이 통째로
    박영선 위원으로 붙어(음성 융합 오귀속) 윤충식 슬롯이 3분에서 끊기고, 집행부 답변 17분이
    윤도희 위원 한 turn 으로 붙어 다음 의원까지 삼켰다. 반면 위원장의 호명·"수고하셨습니다" 는
    STT 본문에 그대로 살아 있고 KMS 공식 인덱스가 찍는 지점과 같다.
    → 슬롯의 뼈대는 **호명 단서**(시작 = 호명 줄, 끝 = 다음 호명·전환 문구·45분), 라벨은 호명이
    없는 의원(자료요구·인사 순서)에만 보조로 쓴다. 라벨 슬롯이 호명 슬롯과 절반 넘게 겹치면 버린다.

    라벨 규칙(보조): 슬롯을 여는 turn = 의원, 또는 60초 이상 말한 위원장(본인 질의). 같은 의원의
    연속 turn 은 사이에 집행부·위원장 진행 멘트가 끼어도 한 런이고, 다음 본인 발언까지 180초 넘게
    비면 새 런. 끝 = 마지막 본인 발언 뒤 첫 경계(위원장·다른 의원) turn 의 시작. 경계가 없으면
    뒤따르는 집행부 답변 끝. 45분 상한·20초 하한은 본문 단서 방식과 같다.
    """
    label_slots = _label_slots(segments_result, roster)
    slots = _cue_slots(subs, roster, duration) if subs else []
    if not slots:
        return _group_slots(label_slots)
    slots = _split_missed_calls(slots, label_slots, _closing_times(subs, roster))
    # 라벨 슬롯도 위원장 전환 문구("수고하셨습니다")에서 끊는다 — 라벨이 다음 의원까지 이어져 붙는 것을 막는다
    boundaries = _boundary_times(subs)
    for s in label_slots if label_supplement else []:
        cut = next((t for t in boundaries if s["start"] + END_PHRASE_MIN_SECONDS <= t < s["end"]), None)
        if cut is not None:
            s["end"], s["estimated"] = cut, False
        length = s["end"] - s["start"]
        covered = sum(max(0.0, min(s["end"], c["end"]) - max(s["start"], c["start"])) for c in slots)
        same = any(c["name"] == s["name"] and min(s["end"], c["end"]) > max(s["start"], c["start"]) for c in slots)
        if covered / length > 0.5 and not same:
            continue                       # 호명 슬롯이 이미 덮는 시간 — 라벨이 틀렸을 가능성이 크다
        for c in slots:                    # 호명 슬롯과 겹치는 가장자리는 잘라낸다 (같은 사람이면 남는 뒷부분 = 보충 발언)
            if c["start"] <= s["start"] < c["end"]:
                s["start"] = c["end"]
            if c["start"] < s["end"] <= c["end"]:
                s["end"] = c["start"]
        if s["end"] - s["start"] >= MIN_SEGMENT_SECONDS:
            slots.append(s)
    return _group_slots(slots)


def _cue_slots(subs: list[dict], roster: list[dict], duration: float | None) -> list[dict]:
    """위원장 호명 단서 → 슬롯. 시작 = 호명 자막 줄, 끝 = 다음(다른 사람) 호명 · 전환 문구
    ("수고하셨습니다"·"질의하실 의원님", 시작 60초 뒤부터) · 마무리 문구 · 45분 상한 · 마지막 자막."""
    by_start = sorted(subs, key=_start)

    def _is_chair_line(s: dict) -> bool:
        return bool(re.search(r"위원장|의장", str(s.get("speaker") or "")))

    cues = find_cues([s for s in by_start
                      if _SELF_RE.search(str(s.get("text") or ""))
                      or _line_not_executive(s.get("speaker"))], roster, chair_line=_is_chair_line)
    if not cues:
        return []
    last_end = max((float(s.get("end_time") or s.get("start_time") or 0) for s in subs), default=0.0)
    if duration and duration > last_end:
        last_end = float(duration)
    boundaries = _boundary_times(subs)
    end_phrases = _end_phrase_times(subs)
    out: list[dict] = []
    for i, c in enumerate(cues):
        if i > 0 and cues[i - 1]["name"] == c["name"]:
            continue
        j = i + 1
        while j < len(cues) and cues[j]["name"] == c["name"]:
            j += 1
        group = cues[i:j]
        # 자기소개(집행부 동명이인·오인식)가 먼저 나오고 90초 안에 위원장 호명이 따르면 호명이 진짜 시작이다
        first_call = next((g for g in group if g["kind"].startswith("call") and g["start"] - c["start"] <= CUE_MERGE_SECONDS), None)
        if first_call is not None and c["kind"] == "self" and first_call is not c:
            c = dict(c, start=first_call["start"], text=first_call["text"])
        end = cues[j]["start"] if j < len(cues) else last_end
        estimated = j >= len(cues)
        floor = c["start"] + END_PHRASE_MIN_SECONDS
        own_lines = {g["start"] for g in group}             # 같은 사람을 다시 부르는 줄은 전환이 아니다
        cut = min((t for t in boundaries if floor <= t < end and t not in own_lines), default=None)
        if (cut if cut is not None else end) - c["start"] > END_PHRASE_FALLBACK_SECONDS:
            # 의원 본인의 "이상으로 질의를 마치겠습니다" 뒤에도 집행부 마지막 답변이 붙는다 — 다음 호명·전환까지가
            # 20분을 넘을 때만 마무리 문구로 자른다(본회의 집행부 일괄답변 3시간 방지)
            cut = min((t for t in boundaries + end_phrases if floor <= t < end and t not in own_lines), default=None)
        if cut is not None:
            end, estimated = cut, False
        if end - c["start"] > MAX_SEGMENT_SECONDS:
            end, estimated = c["start"] + MAX_SEGMENT_SECONDS, True
        if end - c["start"] < MIN_CUE_SLOT_SECONDS:
            continue
        out.append({"name": c["name"], "role": c["role"], "start": c["start"], "end": end,
                    "title": c["text"], "estimated": estimated})
    return out


def _split_missed_calls(slots: list[dict], label_slots: list[dict],
                        closings: list[tuple[float, str]]) -> list[dict]:
    """호명이 STT 에서 빠져 한 슬롯이 다음 의원까지 삼킨 경우를 가른다.

    슬롯 S 가 자기 이름의 마무리("S 의원님 수고하셨습니다")로 끝났으면 통째로 믿는다(라벨이 틀린 경우가
    그 반대보다 많다 — 윤충식 8분이 박영선으로 붙었던 실측). 아니면 S 안에 다른 의원 X 의 마무리가 있고
    X 의 라벨 발언이 그 앞에 있으면 X 의 첫 라벨 발언에서 가른다(김지호 호명이 STT 에서 빠진 실측).
    """
    out = sorted((dict(s) for s in slots), key=lambda s: s["start"])
    added: list[dict] = []
    for s in out:
        if any(closing_matches(nm, s["name"]) and abs(t - s["end"]) <= 20 for t, nm in closings):
            continue
        own_last = max((L["end"] for L in label_slots if L["name"] == s["name"]
                        and s["start"] <= L["start"] < s["end"]), default=s["start"])
        # 자료요구 순서는 한 사람이 20~40초라 앞사람 슬롯이 60초를 못 채운다 — 하한은 20초
        floor = max(s["start"] + MIN_SEGMENT_SECONDS, own_last)
        cut = None
        for t, x in sorted(closings):
            if closing_matches(x, s["name"]) or not (floor <= t <= s["end"] + 5):
                continue
            if not any(L["name"] == x for L in label_slots):
                continue                                   # 명부에서 못 푼 원문은 가르는 근거로 안 쓴다
            first = min((L["start"] for L in label_slots if L["name"] == x and s["start"] < L["start"] < t),
                        default=None)
            # 앞사람이 60초는 말했거나, X 가 마무리 직전 90초 안에서만 말한 짧은 순서(자료요구)일 때만 가른다
            if first is not None and (first - s["start"] >= END_PHRASE_MIN_SECONDS
                                      or (first - s["start"] >= MIN_SEGMENT_SECONDS and t - first <= 90.0)):
                cut = (first, x, min(t, s["end"]), False)
                break
        # ponytail: 마무리 없이 "다른 의원 라벨 런 90초+" 만으로 가르는 규칙은 넣었다 뺐다 — 라벨이 틀린 경우가
        # 맞는 경우만큼 많아 채점이 80.2 → 80.9% 로 오히려 좋아졌다(2026-09-08 A/B). 라벨을 더 믿게 되면 다시.
        if cut is not None:
            start, name, end, est = cut
            added.append({"name": name, "role": next((L["role"] for L in label_slots if L["name"] == name), "의원"),
                          "start": start, "end": end, "title": f"호명 누락 — 라벨·마무리로 추정 · {name}",
                          "estimated": est})
            s["end"], s["estimated"] = start, False
    return [s for s in out + added if s["end"] - s["start"] >= MIN_CUE_SLOT_SECONDS]


def _group_slots(slots: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for s in sorted(slots, key=lambda x: x["start"]):
        g = groups.get(s["name"]) or _make_group(s["name"], s["role"], f"ai:{s['name']}")
        groups[s["name"]] = g
        seconds = s["end"] - s["start"]
        g["segments"].append({
            "idx": len(g["segments"]), "start": s["start"], "end": s["end"], "seconds": seconds,
            "time": _hms(s["start"]), "title": s["title"], "named": True, "end_estimated": s["estimated"],
        })
        g["total_seconds"] += seconds
    return sorted(groups.values(), key=lambda g: -g["total_seconds"])


def _label_slots(segments_result: dict, roster: list[dict]) -> list[dict]:
    """화자 라벨 turn → 런 → 슬롯 (규칙은 build_draft_from_ai docstring)."""
    turns: list[dict] = []
    for sp in segments_result.get("speakers") or []:
        cls = _classify_label(sp.get("speaker"), roster)
        for seg in sp.get("segments") or []:
            start, end = float(seg.get("start_time") or 0), float(seg.get("end_time") or 0)
            if end <= start:
                continue
            turns.append({"start": start, "end": end, "cls": cls,
                          "text": str(seg.get("text_preview") or "")})
    turns.sort(key=lambda t: t["start"])

    def _opens(t: dict) -> bool:
        return t["cls"] is not None and (
            t["cls"][0] == "member" or t["end"] - t["start"] >= CHAIR_TALK_MIN_SECONDS)

    runs: list[dict] = []
    for t in turns:
        if not _opens(t):
            continue
        _, name, role = t["cls"]
        cur = runs[-1] if runs else None
        if cur and cur["name"] == name and t["start"] - cur["last_end"] <= RUN_GAP_SECONDS:
            cur["last_end"] = max(cur["last_end"], t["end"])
            cur["count"] += 1
        else:
            runs.append({"name": name, "role": role, "start": t["start"], "last_end": t["end"],
                         "count": 1, "text": t["text"]})

    slots: list[dict] = []
    for run in runs:
        after = [t for t in turns if t["start"] >= run["last_end"] and t["start"] > run["start"]]
        boundary = next((t for t in after if t["cls"] is not None), None)
        if boundary is not None:
            end, estimated = boundary["start"], False
        else:
            # 경계가 없다 — 이어지는(180초 안에 붙는) 집행부 답변까지
            end, estimated = run["last_end"], True
            for t in after:
                if t["start"] - end > RUN_GAP_SECONDS:
                    break
                end = max(end, t["end"])
        if end - run["start"] > MAX_SEGMENT_SECONDS:
            end, estimated = run["start"] + MAX_SEGMENT_SECONDS, True
        if end - run["start"] < MIN_SEGMENT_SECONDS:
            continue
        slots.append({"name": run["name"], "role": run["role"], "start": run["start"], "end": end,
                      "title": f"발언 {run['count']}회·답변 포함 · {run['text'][:40]}", "estimated": estimated})
    return slots


def _hms(sec: float) -> str:
    s = max(0, int(sec))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _start(s: dict) -> float:
    return float(s.get("start_time") or 0)


def _cue_rank(c: dict) -> tuple[int, int]:
    """이름의 믿음직함 — 명부 정확일치 > 퍼지, 같으면 호명(의장이 명단을 읽는다) > 자기소개."""
    return (1 if c.get("exact") else 0, 1 if c.get("kind") == "call" else 0)


def _similar_names(a: Optional[str], b: Optional[str]) -> bool:
    """STT 가 한 글자 틀린 같은 사람인가 (김해철 ↔ 김회철). 3글자 중 2글자."""
    if not a or not b:
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.66


def _merge_adjacent_cues(cues: list[dict]) -> list[dict]:
    """90초 안에 붙어 나온 **같은 사람**의 단서(호명 → 자기소개, STT 가 이름을 한 글자 틀린 것)는 하나로.

    시작은 앞 단서를 유지하고 이름만 더 믿음직한 쪽으로 바꾼다. 이름을 못 정한 단서
    (명부 퍼지 동점, name=None)는 뒤따르는 단서가 이름을 정해 주고, 아니면 버린다.
    ⚠ 이름이 닮지 않은 단서는 붙어 있어도 다른 사람이다 — 위원회 인사·자료요구 순서는 30초마다
    사람이 바뀌는데, 예전 규칙(90초 안이면 무조건 한 사람)은 12명 인사를 한 단서로 뭉쳤다(2026-09-08 실측).
    호명 직후 30초 안의 자기소개만 이름이 달라도 한 사람으로 본다.
    """
    out: list[dict] = []
    for c in cues:
        prev = out[-1] if out else None
        if prev is not None and c["start"] - prev["start"] < CUE_MERGE_SECONDS and prev["name"] != c["name"]:
            gap = c["start"] - prev["start"]
            # 둘 다 명부 정확일치인 다른 이름(김영희·김선희 같은 위원회)은 닮았어도 다른 사람이다
            both_exact = bool(prev.get("exact") and c.get("exact") and prev["name"] and c["name"])
            same_person = ((_similar_names(prev["name"], c["name"]) and not both_exact)
                           or gap < CUE_NOISE_SECONDS
                           or (prev["kind"].startswith("call") and c["kind"] == "self" and gap < 30 and not both_exact))
            if same_person:
                # 호명 직후 다른 이름을 다시 호명하면 정정이다("박상현 의원님 부탁 … 아, 양보하셨네요. 윤도희 의원님")
                # (의원 라벨 줄의 "윤순옥 부위원장님 … 자료 요청에 덧붙여서" 를 정정에서 빼 봤으나 1건 얻고 1건 잃어 안 넣었다)
                corrected = prev["kind"].startswith("call") and c["kind"] == "call" and gap < CUE_NOISE_SECONDS \
                    and not _similar_names(prev["name"], c["name"])
                if c["name"] is not None and (prev["name"] is None or corrected or _cue_rank(c) > _cue_rank(prev)):
                    prev.update({"name": c["name"], "exact": c["exact"], "kind": c["kind"]})
                continue
        out.append(dict(c))
    return [c for c in out if c["name"]]


def find_cues(subs: list[dict], roster: list[dict],
              chair_line: Optional[Callable[[dict], bool]] = None) -> list[dict]:
    """자막 본문의 자기소개·호명 단서 → [{start, name, role, text, kind, exact}] 시간순.

    이름은 명부와 맞아야 한다(명부가 비었으면 정규식 매치를 그대로 믿는다).
    명부 퍼지 매칭이 동점이면(김해철 → 김회철/김철환) 이름을 비워 두고 옆 단서에 맡긴다.
    같은 이름이 60초 안에 다시 나오면 한 단서로 본다.
    `chair_line(sub)` 이 True 인 줄(위원장 라벨)에서는 이름으로 끝나는 짧은 호명도 잡는다.
    """
    ordered = sorted(subs, key=_start)
    # 라벨에 붙은 의원 이름(시각순) — 호명 이름이 STT 로 깨졌을 때 뒤따르는 발언 라벨로 후보를 고른다
    labeled: list[tuple[float, str]] = []
    if roster:
        for s in ordered:
            cls = _classify_label(s.get("speaker"), roster)
            if cls is not None and cls[0] == "member":        # 위원장은 호명 대상이 아니다
                labeled.append((_start(s), kms.norm_name(cls[1])))

    def _label_names_after(t: float, window: float = 90.0) -> set[str]:
        return {n for ts, n in labeled if t <= ts <= t + window}

    def _first_resolved(matches, *, lenient: bool = False, t: float = 0.0):
        """정규식 매치들 중 명부에서 이름이 풀리는 첫 것 → (raw, name, exact). 명부가 비면 첫 매치를 믿는다."""
        for mm in matches:
            raw = mm.group(1)
            if re.match(r"\s*(?:셨|셔서|주셨|(?:주)?신(?!\s*바랍))", mm.string[mm.end():mm.end() + 8]):
                continue                                    # "OO 의원님께서 질의해 주셨는데" — 지난 발언 언급 ("해주신 바랍니다" 는 STT 오타 호명)
            if _TITLE_BEFORE_NAME_RE.search(mm.string[max(0, mm.start(1) - 12):mm.start(1)]):
                continue                                    # "수석전문위원 김정희입니다" — 직원·집행부 이름이다
            if not roster:
                return raw, raw, True
            r = _resolve_name(raw, roster, lenient=lenient, label_names=_label_names_after(t))
            if r is not None:
                return raw, r[0], r[1]
        return None

    cues: list[dict] = []
    for s in ordered:
        text = str(s.get("text") or "")
        t = _start(s)
        is_chair = chair_line is not None and chair_line(s)
        kind = "self"
        hit = _first_resolved([m for pat in (_SELF_RE, _SELF_ROLE_FIRST_RE, _SELF_NAME_ONLY_RE)
                               for m in pat.finditer(text)], t=t)
        if hit is None:
            kind = "call"
            hit = _first_resolved(_CALL_RE.finditer(text), t=t)
            if hit is None and roster and _CALL_RE.search(text) and _line_not_executive(s.get("speaker")):
                # 호명 문장은 분명한데 이름이 명부에서 안 풀린다('장장 의원님 자료 요청해') — 60초 안에
                # 의원 라벨이 딱 한 사람이면 그 사람이다
                after = _label_names_after(t, 60.0)
                raw_call = next((mm.group(1) for mm in _CALL_RE.finditer(text)), "")
                if len(after) == 1:
                    nm = next(iter(after))
                    # 라벨도 틀릴 수 있으니 이름이 조금은 닮아야 한다(성이 같거나 자모 40%) — '곽상윤'→윤도희 는 아니다
                    if raw_call and (raw_call[0] == nm[0] or SequenceMatcher(None, _jamo(raw_call), _jamo(nm)).ratio() >= 0.4):
                        hit = (nm, next((str(c.get("name")) for c in roster if kms.norm_name(str(c.get("name") or "")) == nm), nm), False)
            if hit is None and roster and _line_not_executive(s.get("speaker")):
                # 질문형 호명 — 60초 안에 닮은 이름의 의원 라벨이 말해야 호명으로 친다
                mq = _CALL_QUESTION_RE.search(text)
                if mq:
                    raw_q = mq.group(1)
                    r = _resolve_name(raw_q, roster, label_names=_label_names_after(t))
                    target = kms.norm_name(r[0]) if r and r[0] else None
                    after = _label_names_after(t, 60.0)
                    ok = [nm for nm in after if nm == target or raw_q[0] == nm[0]
                          or SequenceMatcher(None, _jamo(raw_q), _jamo(nm)).ratio() >= 0.4]
                    if len(ok) == 1:
                        nm = ok[0]   # (명부에서 풀린 이름을 우선해 봤으나 채점이 93.3 → 93.0 으로 내려가 라벨 쪽을 둔다)
                        hit = (raw_q, next((str(c.get("name")) for c in roster if kms.norm_name(str(c.get("name") or "")) == nm), nm), nm == target)
        if hit is None and is_chair:
            hit = _first_resolved(_CHAIR_CALL_RE.finditer(text), t=t)
            if hit is None and _CHAIR_SELF_Q_RE.search(text):
                own = _classify_label(s.get("speaker"), roster)
                if own is not None:
                    hit = (own[1], own[1], True)               # 위원장 본인 질의 — "본위원장도 몇 마디"
        if hit is None and _line_not_executive(s.get("speaker")):
            m = _LINE_START_CALL_RE.search(text)
            if m and (re.search(r"수고|고생|감사|고맙|께서|말씀하|답변|질의\s*(?:하신|하셨|한)", text[m.end():m.end() + 14])
                      or re.match(r"\s*[은는이]\b|\s*[은는이](?![가-힣])", text[m.end():m.end() + 3])):
                m = None                                    # "OO 의원님 수고하셨습니다"·"OO 의원님은 …" 은 호명이 아니다
            if m and not is_chair:
                own = _classify_label(s.get("speaker"), roster)
                if own is not None and kms.norm_name(own[1]) == kms.norm_name(m.group(1)):
                    m = None                                # 자기 이름으로 시작 — 자기소개·답변이지 호명이 아니다
            if m:
                hit = _first_resolved([m], t=t)
                if hit is not None:
                    kind = "call-weak"                      # 줄머리 이름만 — 앞의 정식 호명을 "정정" 하지는 못한다
        if hit is None and roster:
            kind = "self"
            hit = _first_resolved(_SELF_LENIENT_RE.finditer(text), lenient=True, t=t)
            if hit is None and _line_not_executive(s.get("speaker")):
                hit = _first_resolved(_SELF_BARE_RE.finditer(text), t=t)
        if hit is None:
            continue
        raw, name, exact = hit
        if name and cues and cues[-1]["name"] == name and t - cues[-1]["start"] < 60:
            continue
        cues.append({"start": t, "name": name, "role": "의원", "text": text[:60],
                     "kind": kind, "exact": exact})
    return _merge_adjacent_cues(cues)


_JAMO_L = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JAMO_V = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_JAMO_T = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"


def _jamo(s: str) -> str:
    out = []
    for ch in s:
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            out.append(_JAMO_L[code // 588] + _JAMO_V[code % 588 // 28] + _JAMO_T[code % 28].strip())
        else:
            out.append(ch)
    return "".join(out)


def _resolve_name(raw: str, roster: list[dict], *, lenient: bool = False,
                  label_names: Optional[set[str]] = None) -> Optional[tuple[Optional[str], bool]]:
    """STT 가 적은 이름 → 명부 이름. (이름, 정확일치) · 동점이면 (None, False) · 명부 밖이면 None.

    글자 단위 퍼지(kms.rank_councilors)에 **자모 단위** 점수를 더한다 — STT 는 모음·받침을 틀린다
    ('강송상'→강성삼, '김기곤'→김귀근, '유기준'→류기준(성까지 틀림)). 둘이 비등하면 뒤따르는 발언
    라벨에 있는 쪽. `lenient` 는 '…원입니다' 같은 약한 패턴 — 정확일치만 받는다.
    """
    n = kms.norm_name(raw)
    if not n:
        return None
    scored: dict[str, tuple[float, dict]] = {}
    for sc, c in kms.rank_councilors(raw, roster):
        scored[kms.norm_name(str(c.get("name") or ""))] = (sc, c)
    if not (scored and max(v[0] for v in scored.values()) >= 1.0):
        if lenient:
            return None
        jn = _jamo(n)
        for c in roster:
            cand = kms.norm_name(str(c.get("name") or ""))
            if not cand or len(cand) != len(n):
                continue
            r = SequenceMatcher(None, jn, _jamo(cand)).ratio()
            if cand[0] == n[0]:
                r = min(0.999, r + 0.05)
            if r >= 0.78 and r > scored.get(cand, (0.0, None))[0]:
                scored[cand] = (r, c)
    if not scored:
        return None
    ranked = sorted(scored.values(), key=lambda t: -t[0])
    if ranked[0][0] < 1.0 and len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.05:
        near = [c for sc, c in ranked if ranked[0][0] - sc < 0.05]
        hit = [c for c in near if kms.norm_name(str(c.get("name") or "")) in (label_names or set())]
        if len(hit) == 1:
            ranked = [(0.999, hit[0])]
        elif abs(ranked[0][0] - ranked[1][0]) < 1e-9:
            return None, False                               # 동점 — 누구인지 모른다
    name = str(ranked[0][1].get("name") or raw)
    return name, kms.norm_name(name) == n


def _closing_times(subs: list[dict], roster: list[dict]) -> list[tuple[float, str]]:
    """'OO 의원님 수고하셨습니다' — (시각, 이름). 그 의원의 슬롯이 여기서 끝난다.
    명부에서 못 푼 이름은 STT 원문을 그대로 둔다('유효종'·'장성용') — closing_matches 가 슬롯 이름과 느슨히 맞춰 본다."""
    out: list[tuple[float, str]] = []
    for s in sorted(subs, key=_start):
        for m in _CLOSING_RE.finditer(str(s.get("text") or "")):
            r = _resolve_name(m.group(1), roster) if roster else (m.group(1), True)
            out.append((_start(s), r[0] if r and r[0] else m.group(1)))
            break
    return out


def closing_matches(closing_name: str, slot_name: str) -> bool:
    """마무리에 적힌 이름이 이 슬롯 의원인가 — 명부로 풀린 이름은 같아야 하고, 못 푼 원문은 자모로 절반만 닮아도
    같은 사람으로 본다(위원장이 앞사람 이름을 부르는 자리라 후보가 사실상 하나다)."""
    if closing_name == slot_name:
        return True
    if not closing_name or not slot_name or abs(len(closing_name) - len(slot_name)) > 1:
        return False
    return SequenceMatcher(None, _jamo(closing_name), _jamo(slot_name)).ratio() >= 0.5


def _end_phrase_times(subs: list[dict]) -> list[float]:
    return sorted(_start(s) for s in subs if _END_RE.search(str(s.get("text") or "")))


def _boundary_times(subs: list[dict]) -> list[float]:
    out = []
    for s in subs:
        text = str(s.get("text") or "")
        if _BOUNDARY_RE.search(text) or (
                re.search(r"위원장|의장", str(s.get("speaker") or "")) and _BOUNDARY_CHAIR_RE.search(text)):
            out.append(_start(s))
    return sorted(out)


def build_draft_from_cues(subs: list[dict], roster: list[dict],
                          duration: float | None) -> list[dict]:
    """자막 본문 단서 → 의원별 구간. start = 단서 자막 시각(자막 시계 그대로, 미보정),
    end = 다음(다른 사람) 단서 · 의장 마무리 문구 · 45분 상한 · 마지막 자막 끝 중 가장 이른 것."""
    cues = find_cues(subs, roster)
    if not cues:
        return []
    last_end = max((float(s.get("end_time") or s.get("start_time") or 0) for s in subs), default=0.0)
    if duration and duration > last_end:
        last_end = float(duration)
    end_phrases = _end_phrase_times(subs)
    groups: dict[str, dict] = {}
    for i, c in enumerate(cues):
        # 같은 사람의 연속 단서는 하나로 (다음 '다른 사람' 단서까지)
        j = i + 1
        while j < len(cues) and cues[j]["name"] == c["name"]:
            j += 1
        if i > 0 and cues[i - 1]["name"] == c["name"]:
            continue
        end = cues[j]["start"] if j < len(cues) else last_end
        estimated = j >= len(cues)
        phrase = next((t for t in end_phrases if t >= c["start"] + END_PHRASE_MIN_SECONDS), None)
        if phrase is not None and phrase < end:
            end, estimated = phrase, False
        if end - c["start"] > MAX_SEGMENT_SECONDS:
            end, estimated = c["start"] + MAX_SEGMENT_SECONDS, True
        seconds = end - c["start"]
        if seconds < MIN_SEGMENT_SECONDS:
            continue
        g = groups.get(c["name"]) or _make_group(c["name"], c["role"], f"live:{c['name']}")
        groups[c["name"]] = g
        g["segments"].append({
            "idx": len(g["segments"]), "start": c["start"], "end": end, "seconds": seconds,
            "time": _hms(c["start"]), "title": c["text"], "named": True,
            "end_estimated": estimated,
        })
        g["total_seconds"] += seconds
    return sorted(groups.values(), key=lambda g: -g["total_seconds"])


_COMMITTEE_RE = re.compile(r"([가-힣]+위원회)")


def _load_roster(supabase: Any, meeting: dict) -> list[dict]:
    """위원회 명부 → 없으면 전체 현역. 실패해도 빈 목록으로 진행(기능 저하 없이)."""
    try:
        from app.core.channels import get_committee_for_channel
        from app.services.councilor_sync import CouncilorSyncService

        svc = CouncilorSyncService(supabase)
        committee = meeting.get("committee")
        if not committee and meeting.get("channel_id"):
            committee = get_committee_for_channel(str(meeting["channel_id"]))
        if not committee:
            m = _COMMITTEE_RE.search(str(meeting.get("title") or ""))
            committee = m.group(1) if m else None
        rows = svc.get_by_committee(committee) if committee else []
        if not rows:
            rows = svc.get_all_active()
        return rows or []
    except Exception as e:  # noqa: BLE001
        logger.info("의원 명부 조회 실패(무시): %s", e)
        return []


async def build_clip_index(supabase: Any, meeting: dict) -> dict:
    """회의 → {meeting_id, kms_midx, duration, source, time_offset, speakers, warnings}"""
    meeting_id = str(meeting.get("id"))
    kms_midx = meeting.get("kms_midx")
    duration = meeting.get("duration_seconds") or None
    warnings: list[str] = []
    roster = await asyncio.to_thread(_load_roster, supabase, meeting)

    speakers: list[dict] = []
    source = "none"
    if kms_midx:
        angun = await kms.fetch_angun(str(kms_midx))
        if angun:
            speakers = kms.build_speakers(angun, duration)
            # 코드만 있고 이름 없는 그룹 — KMS 의원 정보로 이름을 채우고, 그래도 없으면 버린다
            for g in speakers:
                if not g["name"] and g["code"]:
                    g["name"] = await kms.fetch_member_name(g["code"]) or ""
            speakers = [g for g in speakers if g["name"]]
            if speakers:
                source = "official"
            else:
                warnings.append("KMS 인덱스에 의원 발언 항목이 없습니다.")
        else:
            warnings.append("KMS 발언자 인덱스가 아직 없습니다 (보통 다음 날 등록).")

    if source == "none":
        subs = await asyncio.to_thread(_fetch_all_subtitles, supabase, meeting_id)
        kind = detect_subtitle_kind(subs)
        if kind in ("ai", "legacy"):
            ai_subs = [s for s in subs if s.get("kind") == "ai"] if kind == "ai" else subs
            if kind == "ai":
                seg_result = await asyncio.to_thread(build_speaker_segments, supabase, meeting)
                speakers = build_draft_from_ai(seg_result, roster, ai_subs, duration)
            if not speakers:
                # 화자 라벨이 비었거나 직책 라벨뿐 → 본문 호명·자기소개로 (시간축은 VOD 그대로)
                speakers = build_draft_from_cues(ai_subs, roster, duration)
            source = "ai" if speakers else "none"
            if speakers:
                warnings.append("AI 자막의 호명·자기소개로 추정한 구간입니다. 시작·끝을 영상에서 확인하세요.")
            else:
                warnings.append("AI 자막에서 의원 이름·호명을 찾지 못했습니다. 수동 자르기를 이용하세요.")
        else:
            # 실시간 자막(kind=live)은 쓰지 않는다 — 시각이 STT 시계라 VOD 와 어긋나 엉뚱한 의원이
            # 잘렸다(2026-09-08 문화체육관광위 실제 사고, 사용자 결정). AI 자막 완료 전엔 수동 자르기만.
            warnings.append("AI 자막이 아직 생성되지 않았습니다. 실시간 자막은 시간축이 VOD 와 달라 "
                            "의원 구간에 쓰지 않습니다 — AI 자막 완료 뒤 다시 열거나, "
                            "지금은 시작 [ · 종료 ] 로 직접 잘라 주세요.")
        if not duration and subs:
            duration = max((float(s.get("end_time") or 0) for s in subs), default=None) or None

    speakers = kms.enrich_with_councilors(speakers, roster)
    return {
        "meeting_id": meeting_id,
        "kms_midx": kms_midx,
        "duration": duration,
        "source": source,
        "time_offset": float(meeting.get("clip_time_offset") or 0.0),
        "speakers": speakers,
        "warnings": warnings,
    }
