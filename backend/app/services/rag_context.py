"""회의 자막에서 질문에 맞는 요약과 발췌를 고르는 순수 함수.

2026-09-15 개편(담당자 신고: "이자형 의원이 모바일 공무원증 얘기를 했는데 AI 가 못 찾는다, 대화할수록 이상하다") —
원인은 ① 안건 제목의 흔한 낱말("공무원")이 질문 속 긴 낱말("모바일공무원증") 안에서 걸려 안건 구간이 절대 필터가 된 것,
② 발언자∧안건 교집합이 비면 회의 전체에서 8줄을 뽑고도 "관련 구간 발췌"라고 모델에 말한 것, ③ 후속 질문 복원이 헐거운 것.
지금 규칙: 제목 매칭은 고유 낱말만·가점만(명시 번호만 필터), 교집합이 비면 단계적으로 완화하고 그 사실을 [검색 안내]로 알린다.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from app.services.name_match import resolve_person, similarity
from app.services.video_minutes_service import _TURN_END_RE, _anchor_agendas, _is_chair_speaker

MAX_CONTEXT_CHARS = 12000
_MEMBER_TOKENS = {"위원", "위원장", "부위원장", "의원", "의장", "부의장"}
_STOP = set(("무엇 뭐 뭐라고 어떤 어떻게 누구 언제 어디 왜 대해 대한 관련 "
             "질의 질의했나 질문 답변 발언 의원 위원 의원님 위원님 안건 의사일정 "
             "결론 결과 전체 정리 요약 회의 얘기 나왔나 했나 했어 알려줘 해줘 "
             "그 이번 해당 어느 모든 내용 번째 초반 중반 후반 마지막 이후 이전 시간 분 쯤 "
             "안건별 논의 사항 주요").split())
# 질문에 흔한 서술어·잡담 — 검색어가 되면 엉뚱한 행을 맞히거나 진짜 검색어의 점수를 흐린다(2026-09-15)
_CHAT = set(("없어 없나 없니 없었어 없었나 없는지 있어 있나 있니 있었어 있었나 있는지 있었는지 나왔어 나왔는지 "
             "했니 했는지 했던 했다 말했 말했어 말했나 말한 말하는 발언한 발언했 발언했어 발언했나 발언하신 "
             "얘기한 얘기했 얘기했어 얘기했나 이야기 이야기한 이야기했 궁금 궁금해 궁금해요 알려 알려주세요 알려줄래 "
             "해주세요 해줄래 정리해 정리해줘 정리해주세요 요약해 요약해줘 뭐야 뭐였어 뭐지 뭔가 뭘까 되나 됐나 됐어 "
             "어때 어땠어 보여줘 찾아줘 찾아 좀 혹시 그냥 무슨 뭔 뭘 누가 누구야 그래서 그럼 그런데 그리고 관해 관해서 "
             "관련해 관련해서 대해서 것 것중 중에 거 부분 쪽 그거 그것 그건 그게 그걸 거기 그분 방금 아까 앞서 "
             "사람 사람들 분들 누군가").split())
_PARTICLE = re.compile(
    r"(?:에서부터|으로부터|로부터|에게서|한테서|께서는|에게는|에서는|으로는|에서도|으로도|이라고|이라는|"
    r"이랑|라고|라는|한테|에서|에게|께서|으로|까지|부터|처럼|보다|마저|조차|밖에|이나|은요|는요|"
    r"은|는|이|가|을|를|의|에|도|과|와|로|만|랑|요)$")
_STRUCT = re.compile(r"\d+(?:번째|번|분|시간|시|초|항|차|회)")
# "답했어·질의한·말씀하신" — 말하기 동사의 활용형은 검색어가 아니다("김기덕 팀장이 뭐라고 답했어?"가 '답했어'를 찾다 실패)
_SPEECH_VERB = re.compile(r"^(?:답|답변|대답|말|말씀|질의|질문|발언|얘기|이야기|언급|물어|물어보|물어봤|주장|지적|설명)"
                          r"(?:했어요|했어|했나요|했나|했니|했는지|했던|했다|했습니까|하셨나요|하셨어요|하셨나|하셨|하신|한|하는|해요|해|하였)?$")
_WORD = re.compile(r"[가-힣A-Za-z0-9]+")
_DECISION = re.compile(r"가결|의결|통과|수정|보류|채택|부결|원안|이의없|표결")
_NOTICE = ("위 자막은 질문과 관련된 구간만 발췌한 것이며 (중략) 은 생략 표시다. "
           "요약은 AI 생성물이고 발췌 원문이 우선한다.")
_SAMPLE_NOTICE = ("위 자막은 질문과 일치하는 구간이 없어 회의 전체에서 고르게 뽑은 표본이며 질문과 무관할 수 있다. "
                  "요약은 AI 생성물이고 발췌 원문이 우선한다.")
_OVERVIEW_NOTICE = ("위 자막은 회의 전반에서 고르게 뽑은 발췌이며 (중략) 은 생략 표시다. "
                    "요약은 AI 생성물이고 발췌 원문이 우선한다.")
_SEPARATOR = "\n--- (중략) ---\n"
# 안건 제목의 흔한 낱말 — 이것들로는 안건을 고르지 않는다("모바일 공무원증" 질문이 "공무원 공무국외출장규칙" 안건으로 가던 사고)
_AGENDA_GENERIC = set(("경기도 경기도의회 경기도교육청 의회 도의회 공무원 조례 규칙 일부개정 전부개정 개정안 제정안 동의안 "
                       "승인안 건의안 결의안 계획안 보고 업무보고 주요업무 추진 추진상황 지원 운영 관리 설치 위원회 사무처 "
                       "의회사무처 예산 결산 기금 관한 대한 위한 관련 사업 계획 협의 채택 구성 경기 도민 활성화 촉진 증진 "
                       "진흥 개정 제출 심사 처리 변경 기본 시행 특별 추가경정예산안 추가경정예산 예산안 결산안").split())
_NON_NAME_LABELS = {"화자", "발언자", "집행부", "미확인", "사회자"}
# 발언자 표기가 직함부터 시작하면("사무처장 진용국") 첫 낱말은 이름이 아니다
_TITLE_SUFFIX = re.compile(r"(?:처장|총장|실장|국장|과장|팀장|관장|본부장|원장|센터장|부장|차장|청장|소장|의장|"
                           r"대변인|협치관|기획관|정책관|감사관|담당관|조사관|전문위원|사무관|주무관)$")
# 이름 뒤 의원·위원 — '의회운영(위원회)'·'수석전문(위원)' 에서 가짜 이름을 뽑지 않는다
_NAME_RE = re.compile(r"(?:^|\s)([가-힣]{2,4})\s*(?<!전문)(?:의원|위원)(?!회)(?:님|이|의|은|께서|한테)?")
_SUMMON_RE = re.compile(r"[가-힣]{2,4}\s*(?:의원|위원)님")
_NOT_NAME_END = re.compile(r"(?:만|로|으로|랑|이랑|한테|에게|께서|에서|까지|부터|처럼|도|을|를)$")
# 후속 질문의 지시어 — '그래서·그럼' 은 아니다
_ANAPHOR = re.compile(r"(?<![가-힣])(?:그|그거|그것|그건|그게|그걸|거기|그분|방금|아까|앞서|해당)"
                      r"(?=$|[^가-힣]|(?:은|는|이|가|을|를|의|에|도|요)(?:$|[^가-힣]))")
_OVERVIEW_CUE = re.compile(r"전체|정리|요약")


@dataclass
class QueryPlan:
    """현재 질문과 직전 사용자 질문에서 얻은 검색 조건."""
    terms: list[str]
    names: list[str]
    agenda_nums: list[int]
    time_ranges: list[tuple[float, float]]
    intent: set[str]
    from_history: bool
    agenda_explicit: list[int] = field(default_factory=list)   # "안건 N"·"의사일정 제N항" — 필터
    agenda_hint: list[int] = field(default_factory=list)       # 제목 낱말 일치 — 가점만
    unresolved: list[str] = field(default_factory=list)        # 명단에 없는 이름 — 발언자 필터가 아니라 본문 검색어
    renamed: dict[str, str] = field(default_factory=dict)      # 질문의 이름 → 발언자 이름(오타 보정)


@dataclass
class AgendaRange:
    """확인된 상정 시각 또는 인접 앵커로 한정한 추정 구간."""
    order_num: int
    title: str
    lo: float
    hi: float
    estimated: bool


@dataclass
class ContextBundle:
    """프롬프트 본문과 실제 포함된 자막의 출처 및 선택 통계."""
    text: str
    sources: list[dict]
    speakers: list[str]
    stats: dict


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _label_name(label: str | None) -> str:
    toks = (label or "").split()
    return toks[0] if toks and toks[0] not in _MEMBER_TOKENS else ""


def _seconds(value: float | None) -> float | None:
    return float(value) if value is not None and math.isfinite(value) and value >= 0 else None


def _end(subtitles: list[dict]) -> float:
    return max((_seconds(s.get(k)) or 0 for s in subtitles
                for k in ("start_time", "end_time")), default=0)


def _hms(value: float) -> str:
    seconds = int(value)
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _stem(word: str) -> str:
    """조사를 최대 두 번 뗀다(두 글자 미만이 되면 멈춤) — '공무원증이랑은'→'공무원증'."""
    stem = word
    for _ in range(2):
        cut = _PARTICLE.sub("", stem)
        if cut == stem or len(cut) < 2:
            break
        stem = cut
    return stem


def _terms(question: str, drop_prefixes: Iterable[str] = ()) -> list[str]:
    drops = [d for d in drop_prefixes if d]
    terms: list[str] = []
    for word in _WORD.findall(question):
        stem = _stem(word)
        if word.isdigit() or _STRUCT.fullmatch(word):
            continue
        if word in _STOP or stem in _STOP or word in _CHAT or stem in _CHAT or _SPEECH_VERB.match(word):
            continue
        if any(word.startswith(d) for d in drops):  # '이자형의원이' — 이름은 발언자 조건으로 따로 쓴다
            continue
        terms.extend(t for t in (word, stem) if 2 <= len(t) <= 20)
    return list(dict.fromkeys(terms))


def _title_words(title: str) -> list[str]:
    out = []
    for w in _WORD.findall(title or ""):
        s = re.sub(r"(?:조례안|조례|의건|규칙안)$", "", _stem(w))
        if len(s) >= 2 and not s.isdigit():
            out.append(s)
    return out


def _lcs(a: str, b: str) -> int:
    best = 0
    prev = [0] * (len(b) + 1)
    for ca in a:
        cur = [0] * (len(b) + 1)
        for j, cb in enumerate(b, 1):
            if ca == cb:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


def _agenda_hints(question: str, agendas: list[dict]) -> list[int]:
    """제목의 고유 낱말(흔한 말이 아니고 한 안건에만 있는 낱말)로만 안건을 짐작한다.

    긴 질문 낱말 안에 든 제목 낱말은 인정하지 않는다 — '모바일공무원증' 속 '공무원' 금지.
    """
    qtoks: set[str] = set()
    for w in _WORD.findall(question):
        qtoks.update((w, _stem(w)))
    per = [(int(a["order_num"]), a.get("title") or "", _title_words(a.get("title") or ""))
           for a in agendas if a.get("order_num") is not None]
    df = Counter(w for _, _, ws in per for w in set(ws))
    qc = _compact(question)
    hints: list[int] = []
    for num, title, words in per:
        distinct = [w for w in words if w not in _AGENDA_GENERIC and df[w] == 1]
        tc = _compact(title)
        hit = False
        for t in qtoks:
            if len(t) < 2 or t in _STOP or t in _CHAT:
                continue
            if t in distinct:
                hit = True                                   # 수소버스는 → 수소버스
            elif len(t) >= 3 and any(t in w and t != w for w in distinct):
                hit = True                                   # 국외출장 ⊂ 공무국외출장규칙
            elif len(t) >= 4 and t in tc and any(w in t for w in distinct):
                hit = True                                   # 수소버스보급 = 이어진 제목 낱말
            if hit:
                break
        if not hit and len(tc) >= 6 and _lcs(qc, tc) >= max(6, len(tc) // 2):
            hit = True                                       # 제목을 거의 그대로 적은 경우
        if hit:
            hints.append(num)
    return hints


def _explicit_agendas(q: str) -> list[int]:
    nums = [int(next(g for g in m.groups() if g)) for m in re.finditer(
        r"(?:안건제?(\d+)|(\d+)번안건|의사일정제?(\d+)항)", q)]
    ordinals = {"첫": 1, "한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5,
                "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10}
    nums.extend(ordinals[m.group(1)] for m in re.finditer(
        r"(첫|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)번째안건", q))
    return nums


def _restore(history: list[dict], depth: int, **kw) -> QueryPlan | None:
    """직전 사용자 질문부터 최대 depth 개를 거슬러 조건이 있는 첫 질문의 계획(그 질문도 자기 앞을 복원한 결과)."""
    users = [k for k, h in enumerate(history) if h.get("role") == "user" and h.get("content")]
    for k in reversed(users[-depth:]):
        prior = parse_question(history[k]["content"], history=history[:k], _depth=depth - 1, **kw)
        if prior.names or prior.agenda_explicit or prior.time_ranges or prior.terms:
            return prior
    return None


def parse_question(question: str, *, known_speakers: set[str], agendas: list[dict],
                   duration: float | None, history: list[dict] | None = None,
                   roster: Iterable[str] = (), _depth: int = 3) -> QueryPlan:
    """시간·안건·화자를 함께 추출하고 지시어가 있거나 생략된 후속 질문만 복원한다."""
    roster = list(roster)
    no_clock = re.sub(r"(?:오전|오후)\s*\d{1,2}\s*시(?:\s*\d+\s*분)?", "", question)
    q = _compact(no_clock)

    # 이름 — 이 회의 발언자 이름은 질문에 있으면 그대로, '○○ 의원/위원' 형태는 발언자+명단에 자모 유사도로 맞춘다
    label_names = sorted({n for n in (_label_name(s) for s in known_speakers)
                          if n and n not in _NON_NAME_LABELS and not re.search(r"\d", n)
                          and not (len(n) >= 3 and _TITLE_SUFFIX.search(n))})
    candidates = list(dict.fromkeys(label_names + [r for r in roster if r]))
    names = [name for name in label_names if name in q]
    unresolved: list[str] = []
    renamed: dict[str, str] = {}
    raw_names: list[str] = []
    for raw in _NAME_RE.findall(no_clock):
        # '혹시 의원님'·'예산만 의원한테' 의 앞말은 이름이 아니다 — 잡담어·확실한 조사로 끝나는 낱말은 버린다
        if raw in _STOP or raw in _CHAT or raw in names or raw in raw_names or _NOT_NAME_END.search(raw):
            continue
        raw_names.append(raw)
        if candidates:
            hit = resolve_person(raw, candidates, prefer=label_names)
            if hit:
                if hit != raw:
                    renamed[raw] = hit
                if hit not in names:
                    names.append(hit)
            else:
                unresolved.append(raw)
        else:
            names.append(raw)
    terms = _terms(no_clock, drop_prefixes=names + raw_names)
    # 공무원 표기는 음성 인식이 이름을 갈라 적는다(진용국/진용복 사무처장) — 의원이 아닌 발언자만 비슷한 표기를 같은 사람으로 묶는다.
    # 의원 표기는 명단으로 이미 정규화돼 있고, 비슷한 이름의 다른 의원을 섞으면 안 된다.
    def _official_name(lab: str) -> str:
        toks = lab.split()
        if not toks or set(toks) & _MEMBER_TOKENS:
            return ""
        return next((t for t in toks if t not in _NON_NAME_LABELS and not _TITLE_SUFFIX.search(t)
                     and re.fullmatch(r"[가-힣]{2,4}", t)), "")

    officials = {_official_name(lab) for lab in known_speakers} - {""} - set(roster)
    asked_officials = [nme for nme in names if nme in officials]  # 의원 이름에는 별칭을 붙이지 않는다(김태희 ≠ 김부희)
    for alias in sorted(officials):
        if alias not in names and any(similarity(alias, nme) >= 0.75 for nme in asked_officials):
            names.append(alias)
    # 물은 발언자의 표기 낱말(직함)은 검색어가 아니다 — "진용국 사무처장 답변"의 '사무처장'이 발췌를 1건으로 좁혔다
    label_toks = {tok for lab in known_speakers if any(t in names for t in lab.split()) for tok in lab.split()}
    terms = [t for t in terms if not any(tok.endswith(t) or tok.endswith(_stem(t)) for tok in label_toks)]
    terms.extend(u for u in unresolved if u not in terms)  # 명단에 없는 이름은 본문 언급으로만 찾는다

    explicit = _explicit_agendas(q)
    hints = [n for n in _agenda_hints(no_clock, agendas) if n not in explicit]
    ranges: list[tuple[float, float]] = []
    end = _seconds(duration)

    def add_range(center: float, suffix: str) -> None:
        lo, hi = max(0, center - 300), center + 300
        if suffix == "이후":
            lo, hi = center, end if end is not None else math.inf
        elif suffix == "이전":
            lo, hi = 0, center
        if end is not None:
            hi = min(hi, end)
        if hi >= lo:
            ranges.append((lo, hi))

    for m in re.finditer(r"(?<!\d)(\d{1,3}):([0-5]\d):([0-5]\d)(이후|이전|쯤)?", q):
        add_range(int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]), m[4] or "")
    for m in re.finditer(r"(?:(\d+)시간(?:(\d+)분)?|(\d+)분)(이후|이전|쯤)?", q):
        add_range(int(m[1] or 0) * 3600 + int(m[2] or m[3] or 0) * 60, m[4] or "")
    if not ranges and end is not None:
        for cue, lo, hi in (("초반", 0, .25), ("중반", .25, .75),
                            ("후반", .75, 1), ("마지막", .75, 1)):
            if cue in q:
                ranges.append((lo * end, hi * end))

    # 후속 질문 — 지시어가 있거나 검색어 없이 생략된 질문만, 이번 질문에 발언자·명시 안건·시간이 없을 때만
    restored = False
    if history and _depth > 0 and not (names or explicit or ranges or hints):
        anaphor = bool(_ANAPHOR.search(question))
        elliptical = not terms and not _OVERVIEW_CUE.search(q)
        if anaphor or elliptical:
            prior = _restore(history, _depth, known_speakers=known_speakers, agendas=agendas,
                             duration=duration, roster=roster)
            if prior:
                names, explicit, ranges = list(prior.names), list(prior.agenda_explicit), list(prior.time_ranges)
                took_terms = not terms and bool(prior.terms)
                if took_terms:
                    terms = list(prior.terms)
                took_hints = not hints and bool(prior.agenda_hint)   # "수소버스는?" → "그 결과는?" (Codex 검토)
                if took_hints:
                    hints = list(prior.agenda_hint)
                restored = bool(names or explicit or ranges or took_terms or took_hints)

    nums = list(dict.fromkeys(explicit + hints))
    intent: set[str] = set()
    if ranges:
        intent.add("time")
    if explicit:
        intent.update(("agenda", "conclusion"))
    if hints:
        intent.add("agenda")
    if names:
        intent.add("speaker")
    if re.search(r"결론|결과|결정|처리|가결|의결|통과|보류|부결|표결", q):
        intent.add("conclusion")
    if re.search(r"마지막|최근", q):
        intent.add("recent")
    if not (names or nums or ranges) and (not terms or _OVERVIEW_CUE.search(q)):
        intent.add("overview")
    if terms and not names and not nums:
        intent.add("topic")
    return QueryPlan(terms, list(dict.fromkeys(names)), nums, list(dict.fromkeys(ranges)), intent, restored,
                     agenda_explicit=list(dict.fromkeys(explicit)), agenda_hint=hints,
                     unresolved=unresolved, renamed=renamed)


def retrieval_query(question: str, history: list[dict] | None = None) -> str:
    """뜻으로 찾기(임베딩)에 쓸 질문 — 지시어·생략 후속 질문이면 앞 사용자 질문을 붙인다(최대 3단계, 키워드 복원과 같은 규칙).

    "휴대폰 신분증 앱 얘기 나왔어?" → "그거 누가 말했어?" → "그 답변은?" 에서 원래 주제를 잃지 않게(Codex 검토).
    """
    parts, q, hist = [question], question, list(history or [])
    for _ in range(3):
        if not (_ANAPHOR.search(q) or not _terms(q)):
            break
        idx = next((k for k in range(len(hist) - 1, -1, -1)
                    if hist[k].get("role") == "user" and hist[k].get("content")), None)
        if idx is None:
            break
        q = hist[idx]["content"]
        parts.insert(0, q)
        hist = hist[:idx]
    return " ".join(parts)


def resolve_agenda_ranges(agendas: list[dict], subtitles: list[dict]) -> list[AgendaRange]:
    """번호형 앵커만 사용하며 누락된 안건은 인접 앵커 사이로 추정한다."""
    anchored = {}
    for chapter in _anchor_agendas(agendas, subtitles):
        match = re.fullmatch(r"(\d+)\.\s+.+", chapter["label"])
        sec = _seconds(chapter.get("seconds"))
        if match and sec is not None:
            anchored.setdefault(int(match[1]), sec)
    if not anchored:
        return []
    end = _end(subtitles)
    times = sorted(set(anchored.values()))
    result = []
    for agenda in agendas:
        num = int(agenda["order_num"])
        lo = anchored.get(num)
        estimated = lo is None
        if estimated:
            lo = max((t for n, t in anchored.items() if n < num), default=0)
            hi = min((t for n, t in anchored.items() if n > num), default=end)
        else:
            hi = next((t for t in times if t > lo), end)
        result.append(AgendaRange(num, agenda.get("title") or "", lo, max(lo, hi), estimated))
    return result


def _contains(sec: float | None, lo: float, hi: float, end: float) -> bool:
    return sec is not None and lo <= sec and (sec < hi or sec == hi == end)


def build_meeting_context(*, subtitles: list[dict], meeting: dict | None,
                          summary_row: dict | None, agendas: list[dict], question: str,
                          history: list[dict] | None = None,
                          max_chars: int = MAX_CONTEXT_CHARS,
                          roster: Iterable[str] = (),
                          semantic_hits: list[dict] | None = None,
                          semantic_min: float = 0.40,
                          semantic_band: float = 0.06) -> ContextBundle:
    """점수순으로 예산을 배정한 뒤 시간순으로 조립하며 출처는 포함된 행만 낸다.

    교집합이 비면 단계적으로 완화한다: strict(시간∧명시 안건∧발언자 턴) → no_agenda → speaker_near(턴 또는 ±120초)
    → keyword(검색어만) → hint_range(제목 짐작 안건 구간) → 표본. 완화했으면 [검색 안내]로 모델에 사실대로 알린다.

    semantic_hits(뜻으로 찾기 결과 조각 [{start_time, end_time, similarity}])가 있으면 그 조각의 행도 적중 후보가 된다 —
    문턱(semantic_min) 이상이고 최고점과 semantic_band 안인 조각만. 점수는 키워드 점수에 더한다(두 쪽이 겹치면 더 위로).
    검색어가 없는 질문(발언자만·개요)에는 쓰지 않는다.
    """
    if max_chars < 0:
        raise ValueError("max_chars는 0 이상이어야 합니다")
    meeting, summary_row = meeting or {}, summary_row or {}
    speakers = list(dict.fromkeys(s["speaker"] for s in subtitles if s.get("speaker")))[:60]
    end = max(_end(subtitles), _seconds(meeting.get("duration_seconds")) or 0)
    plan = parse_question(question, known_speakers={s["speaker"] for s in subtitles if s.get("speaker")},
                          agendas=agendas, duration=end or None, history=history, roster=roster)
    ranges = resolve_agenda_ranges(agendas, subtitles)
    explicit_ranges = [r for r in ranges if r.order_num in plan.agenda_explicit]
    hint_ranges = [r for r in ranges if r.order_num in plan.agenda_hint]
    live_only = bool(subtitles) and all(s.get("kind") == "live" for s in subtitles)
    unlabelled = not any(s.get("speaker") for s in subtitles)
    header = ("=== 회의 정보 ===\n"
              f"제목: {str(meeting.get('title') or '미확인')[:160]}\n일시: {str(meeting.get('meeting_date') or '미확인')[:40]}\n"
              f"위원회: {str(meeting.get('committee') or '미확인')[:80]}\n길이: {_hms(end)}\n"
              "=== 발언자 목록 ===\n" + (", ".join(speakers)[:400] or "미확인") + "\n=== 안건 ===\n")
    by_num = {r.order_num: r for r in ranges}
    for agenda in agendas:
        r = by_num.get(int(agenda["order_num"]))
        marker = f"[{_hms(r.lo)} 상정]" if r and not r.estimated else "(구간 미확인)"
        header += f"{agenda['order_num']}. {agenda.get('title') or ''} {marker}\n"
    header = header[:1000].rstrip()
    summary_cap = 2500 if plan.intent & {"agenda", "conclusion"} else (
        4000 if "overview" in plan.intent else 1200)
    summaries = sorted(summary_row.get("agenda_summaries") or [],
                       key=lambda a: a.get("order_num") not in plan.agenda_nums)
    summary_parts = [f"{a.get('order_num')}. {a.get('title') or ''}: {a.get('summary') or ''}"
                     for a in summaries]
    if not plan.agenda_nums:
        summary_parts.insert(0, summary_row.get("summary_text") or "")
    else:
        summary_parts.append(summary_row.get("summary_text") or "")
    for key, label in (("key_decisions", "주요 결정"), ("action_items", "후속 조치")):
        summary_parts.extend(f"{label}: {item}" for item in summary_row.get(key) or [])
    summary = "\n".join(p for p in summary_parts if p)
    summary = ("=== 회의 요약 ===\n" + summary)[:summary_cap] if summary else ""

    # ── 행별 특징 ──
    n = len(subtitles)
    texts = [_compact(s.get("text") or "") for s in subtitles]
    raws = [s.get("text") or "" for s in subtitles]
    labels = [s.get("speaker") or "" for s in subtitles]
    times = [_seconds(s.get("start_time")) for s in subtitles]
    matches = [[term for term in plan.terms if _compact(term) in t] for t in texts]
    df = Counter(term for row in matches for term in row)
    named = [_label_name(labels[i]) in plan.names for i in range(n)]
    called = [any(re.search(re.escape(name) + r"(?:의원|위원)", texts[i]) for name in plan.names) for i in range(n)]
    mentioned = [any(name in texts[i] for name in plan.names) for i in range(n)]
    decision = [bool(_DECISION.search(texts[i])) for i in range(n)]
    in_explicit = [any(_contains(times[i], r.lo, r.hi, end) for r in explicit_ranges) for i in range(n)]
    in_hint = [any(_contains(times[i], r.lo, r.hi, end) for r in hint_ranges) for i in range(n)]
    in_time = [any(_contains(times[i], lo, hi, end) for lo, hi in plan.time_ranges) for i in range(n)]
    time_ok = [not plan.time_ranges or in_time[i] for i in range(n)]
    exp_ok = [not explicit_ranges or in_explicit[i] for i in range(n)]
    term_hit = [bool(m) for m in matches]
    vec_score = [0.0] * n
    if semantic_hits and plan.terms:
        good = [h for h in semantic_hits if float(h.get("similarity") or 0) >= semantic_min]
        if good:
            best = max(float(h["similarity"]) for h in good)
            for h in good:
                sim = float(h["similarity"])
                if sim < best - semantic_band:
                    continue
                sc = 2 + 4 * (sim - semantic_min) / max(best - semantic_min, 1e-6)
                lo, hi = float(h.get("start_time") or 0), float(h.get("end_time") or 0)
                for i in range(n):
                    if times[i] is not None and lo <= times[i] <= hi:
                        vec_score[i] = max(vec_score[i], sc)
    vec_hit = [v > 0 for v in vec_score]
    found = [term_hit[i] or vec_hit[i] for i in range(n)]
    conclusion = "conclusion" in plan.intent
    rel = []
    for i in range(n):
        r = sum(1 + math.log(n / (1 + df[t])) for t in matches[i]) + (len(matches[i]) >= 2)
        r += 3 * named[i] + 1.5 * mentioned[i] + 2 * (conclusion and decision[i])
        if r > 0:
            r += 1 * in_hint[i] + 1 * in_explicit[i] + 1 * in_time[i]
        rel.append(r)
    lines = [f"[{_hms(times[i]) if times[i] is not None else '시각 미확인'}] "
             f"{labels[i] or '화자 미확인'}: {raws[i]}" for i in range(n)]
    names_set = set(plan.names)

    def speaker_turns(allow: list[bool]) -> list[list[int]]:
        turns: list[list[int]] = []
        last_stop = 0
        for i in range(n):
            if i < last_stop or not allow[i] or not (named[i] or called[i]):
                continue
            stop, rows = i, []
            # 공무원을 물으면("김기덕 팀장한테 누가 물어봤어?") 그 답변을 부른 바로 앞 의원 질의부터 — 누가 물었는지가 빠졌다
            if not (set(labels[i].split()) & _MEMBER_TOKENS) and labels[i]:
                back = i
                while back > max(last_stop, i - 8) and allow[back - 1] and not (set(labels[back - 1].split()) & _MEMBER_TOKENS) \
                        and (times[back - 1] is None or times[i] is None or times[i] - times[back - 1] <= 180):
                    back -= 1
                if back > last_stop and allow[back - 1] and (set(labels[back - 1].split()) & _MEMBER_TOKENS) \
                        and not _is_chair_speaker(labels[back - 1]):
                    rows = list(range(back - 1, i))
            while stop < n:
                if stop > i:
                    if not allow[stop]:
                        break
                    if unlabelled and (times[i] is None or times[stop] is None or times[stop] > times[i] + 90):
                        break
                    lab = labels[stop]
                    if (set(lab.split()) & _MEMBER_TOKENS) and _label_name(lab) not in names_set:
                        # 위원장의 짧은 끼어들기("답변해 주세요")에서는 끊지 않는다 — 뒤따르는 답변이 버려졌다
                        short_chair = (_is_chair_speaker(lab) and len(raws[stop]) < 80
                                       and not _SUMMON_RE.search(raws[stop]) and not _TURN_END_RE.search(raws[stop]))
                        if not short_chair:
                            break
                rows.append(stop)
                stop += 1
            last_stop = max(i + 1, stop)
            turns.append(rows)
        return turns

    def pieces_of(turns: list[list[int]]) -> list[list[int]]:
        # 긴 턴은 1,500자 조각 여러 개로 — 뒤쪽 조각의 키워드 일치가 버려지지 않게(Codex 검토 2026-09-14)
        out: list[list[int]] = []
        for rows in turns:
            piece: list[int] = []
            chars = 0
            for j in rows:
                if piece and chars + len(lines[j]) + 1 > 1500:
                    out.append(piece)
                    piece, chars = [], 0
                piece.append(j)
                chars += len(lines[j]) + 1
            if piece:
                out.append(piece)
        return out

    def windows(rows: list[int], allow: list[bool], score: list[float]) -> list[tuple[float, list[int]]]:
        return [(score[i], [j for j in range(max(0, i - 2), min(n, i + 6)) if allow[j]]) for i in rows]

    near = [False] * n
    if plan.names:
        anchors_t = [times[i] for i in range(n) if (named[i] or called[i]) and times[i] is not None]
        for i in range(n):
            if times[i] is not None and any(abs(times[i] - t) <= 120 for t in anchors_t):
                near[i] = True

    levels: list[str] = ["strict"]
    if explicit_ranges and (plan.terms or plan.names):
        levels.append("no_agenda")      # 찾을 것(검색어·발언자)이 있을 때만 안건 조건을 푼다
    if plan.names and plan.terms:
        levels += ["speaker_near", "keyword", "speaker_only"]
    if hint_ranges:
        levels.append("hint_range")

    level, mode = "sample", "overview" if "overview" in plan.intent else "no_hits"
    candidates: list[tuple[float, list[int]]] = []
    row_score = [0.0] * n
    allow = [True] * n
    hit_rows: list[int] = []
    for lv in levels:
        allow = [time_ok[i] and exp_ok[i] for i in range(n)] if lv == "strict" else list(time_ok)
        if lv == "hint_range":
            allow = [time_ok[i] and in_hint[i] for i in range(n)]
            score = [2 + 2 * decision[i] if allow[i] else 0 for i in range(n)]
            hit_rows = [i for i in range(n) if allow[i]]
            if hit_rows:
                row_score, candidates, level, mode = score, windows(hit_rows, allow, score), lv, "range"
                break
            continue
        if plan.names and lv in ("strict", "no_agenda", "speaker_only"):
            ps = pieces_of(speaker_turns(allow))
            if plan.terms and lv != "speaker_only":
                ps = [p for p in ps if any(found[j] for j in p)]
            if ps:
                row_score = [rel[i] + vec_score[i] if allow[i] else 0 for i in range(n)]
                candidates = [(max(rel[j] + vec_score[j] for j in p) + 3 * any(named[j] for j in p), p) for p in ps]
                hit_rows = sorted({j for p in ps for j in p if rel[j] > 0})
                level, mode = lv, "speaker"
                break
            continue
        if lv == "speaker_near":
            turn_rows = {j for t in speaker_turns(allow) for j in t}
            hit_rows = [i for i in range(n) if allow[i] and found[i] and (i in turn_rows or near[i])]
        elif lv == "keyword":
            hit_rows = [i for i in range(n) if allow[i] and found[i]]
        elif not plan.terms and (explicit_ranges or plan.time_ranges):
            # 검색어·발언자 없이 명시 안건·시간만 — 그 구간 전체가 대상(결정 문구 가점). "1번 안건"이 다른 안건의 가결로 새지 않게(Codex 검토)
            score = [2 + 2 * decision[i] if allow[i] else 0 for i in range(n)]
            hit_rows = [i for i in range(n) if allow[i]]
            if hit_rows:
                row_score, candidates, level, mode = score, windows(hit_rows, allow, score), lv, "range"
                break
            continue
        elif plan.terms or conclusion:
            hit_rows = [i for i in range(n) if allow[i] and (rel[i] > 0 or vec_hit[i])]
        else:
            hit_rows = []
        if hit_rows:
            row_score = [rel[i] + vec_score[i] + 1.5 * near[i] if allow[i] and (rel[i] > 0 or vec_hit[i]) else 0
                         for i in range(n)]
            candidates = windows(hit_rows, allow, row_score)
            level = lv
            mode = "hits" if any(rel[i] > 0 for i in hit_rows) else "semantic"
            break
    if level == "sample":
        hit_rows = []
        allow = [True] * n
        row_score = [0.0] * n
        # 끝점도 포함하는 등간격 표본. 선택 우선순위도 양 끝에서 번갈아 준다.
        # 개요 질문은 요약이 없을 수 있어 40곳에서 뽑아 넓힌다(8줄·1,800자로 "회의를 요약해 줘"에 답하던 문제). 일치 없음은 8곳 그대로.
        k = 40 if mode == "overview" else 8
        sample = sorted({round(i * (n - 1) / (k - 1)) for i in range(k)}) if n > 1 else ([0] if subtitles else [])
        while sample:
            candidates.append((0, [sample.pop()]))
            if sample:
                candidates.append((0, [sample.pop(0)]))

    # ── [검색 안내] — 완화·표본·복원·이름 보정을 모델에 사실대로 알린다 ──
    guide: list[str] = []
    who = "·".join(plan.names)
    shown_terms = "'" + "'·'".join([t for t in plan.terms if len(t) >= 2][:3]) + "'" if plan.terms else ""
    for raw, canon in plan.renamed.items():
        guide.append(f"질문의 '{raw}'는 발언자 '{canon}'(으)로 읽었다.")
    if plan.unresolved:
        guide.append("'" + "'·'".join(plan.unresolved) + "'는 이 회의 발언자·위원 명단에 없다(이름이 틀렸을 수 있다).")
    if plan.from_history:
        guide.append("앞선 질문의 조건을 이어받아 찾았다.")
    if level == "no_agenda":
        guide.append("지정한 안건 구간에는 일치가 없어 회의 전체에서 찾았다.")
    elif level == "speaker_near":
        guide.append(f"{who}의 발언 턴에는 {shown_terms} 일치가 없어 앞뒤 2분의 발언까지 넓혔다. 발언자 표기대로 누가 말했는지 답하라.")
    elif level == "keyword" and plan.names:
        guide.append(f"{who}의 발언에는 {shown_terms} 일치가 없다. 아래는 다른 화자의 발언이다 — {who}이(가) 말했다고 답하지 마라.")
    elif level == "speaker_only":
        guide.append(f"{shown_terms} 일치가 없어 {who}의 발언 전체에서 골랐다. 질문한 내용이 없으면 없다고 답하라.")
    if mode == "semantic":
        guide.append("질문 낱말이 그대로 나오는 자막은 없어 뜻이 비슷한 구간을 골랐다. 질문과 실제로 관련 있는 발언만 근거로 답하라.")
    elif level == "hint_range":
        guide.append("질문 낱말과 일치하는 자막이 없어 제목이 비슷한 안건 구간을 발췌했다.")
    elif mode == "no_hits":
        guide.append("질문 낱말과 일치하는 자막이 없다. 아래 자막은 회의 전체에서 고르게 뽑은 표본이며 무관할 수 있다. "
                     "회의 정보·요약으로도 답할 수 없으면 관련 발언을 찾지 못했다고 답하라.")
    guide_text = ("[검색 안내] " + " ".join(guide))[:400] + "\n" if guide else ""
    notice = {"no_hits": _SAMPLE_NOTICE, "overview": _OVERVIEW_NOTICE}.get(mode, _NOTICE)
    notice += " 실시간 자막이라 화자가 확인되지 않았다." if live_only else ""

    # 아주 작은 예산에서도 안내를 우선 보존하고 나머지 고정 블록을 줄인다.
    fixed_room = max(0, max_chars - len(notice) - len("\n=== 자막 발췌 ===\n") - 2)
    guide_text = guide_text[:fixed_room]
    header = header[:max(0, fixed_room - len(guide_text))]
    summary = summary[:max(0, fixed_room - len(guide_text) - len(header) - 1)]
    prefix = header + ("\n" + summary if summary else "") + "\n=== 자막 발췌 ===\n" + guide_text
    budget = max(0, max_chars - len(prefix) - len(notice) - 1)

    # ── 예산 배정: 점수순, 동점이면 15분 구간을 번갈아(이른 발언만 채우지 않게) ──
    def bucket(i: int) -> int:
        return int(times[i] // 900) if times[i] is not None else -1

    ordered = sorted(candidates, key=lambda c: (-c[0], c[1][0] if c[1] else 0))
    seen: Counter = Counter()
    keyed = []
    for sc, idx in ordered:
        b = bucket(idx[0]) if idx else -1
        keyed.append(((-sc, seen[(sc, b)], idx[0] if idx else 0), idx))
        seen[(sc, b)] += 1
    keyed.sort(key=lambda k: k[0])
    chosen: set[int] = set()
    buckets: Counter = Counter()
    used = 0
    capped = mode != "speaker"

    def take(indices: list[int], with_cap: bool) -> bool:
        nonlocal used
        new = [i for i in indices if i not in chosen]
        if not new:
            return True
        costs: Counter = Counter()
        for i in new:
            costs[bucket(i)] += len(lines[i]) + 1
        joins = any(i - 1 in chosen or i + 1 in chosen for i in new)
        cost = sum(costs.values()) + (0 if joins else len(_SEPARATOR) + 80)
        if used + cost > budget:
            return True
        if with_cap and any(buckets[b] + c > budget * .4 for b, c in costs.items()):
            return False
        chosen.update(new)
        buckets.update(costs)
        used += cost
        return True

    skipped = [idx for _, idx in keyed if not take(idx, capped)]
    for idx in skipped:  # 2차: 한 곳에 몰린 주제 — 남은 예산이 있으면 40% 상한을 풀어 준다
        take(idx, False)

    # ── 넓히기: 적중 창을 한 줄씩 넓혀 예산을 채운다(발언자 모드 제외 — 생중계 90초 규칙 유지) ──
    if mode in ("hits", "range", "overview") and chosen:
        grp: list[list[int]] = []
        for i in sorted(chosen):
            if grp and i == grp[-1][-1] + 1:
                grp[-1].append(i)
            else:
                grp.append([i])
        grp.sort(key=lambda g: -max(row_score[j] for j in g))
        bounds = [[g[0], g[-1], g[0], g[-1]] for g in grp]
        grew = True
        while grew and used < budget * .95:
            grew = False
            for b in bounds:
                for side in (-1, 1):
                    j = b[0] - 1 if side < 0 else b[1] + 1
                    if j < 0 or j >= n or j in chosen or not allow[j]:
                        continue
                    if abs(j - (b[2] if side < 0 else b[3])) > 25:
                        continue
                    cost = len(lines[j]) + 1
                    if used + cost > budget:
                        continue
                    chosen.add(j)
                    used += cost
                    grew = True
                    if side < 0:
                        b[0] = j
                    else:
                        b[1] = j
                if used >= budget * .95:
                    break

    # 겹치는 창은 선택된 행 집합으로 병합하되 화자 턴은 별도 블록으로 유지한다.
    groups: list[list[int]] = []
    for i in sorted(chosen):
        if groups and i == groups[-1][-1] + 1 and not (
                mode == "speaker" and sum(len(lines[j]) + 1 for j in groups[-1]) + len(lines[i]) + 1 > 1500):
            groups[-1].append(i)
        else:
            groups.append([i])

    def render(group: list[int]) -> str:
        tags = [f"[안건 {r.order_num} 구간{'(추정)' if r.estimated else ''}]"
                for r in ranges if any(_contains(times[i], r.lo, r.hi, end) for i in group)]
        return ("\n".join(tags) + "\n" if tags else "") + "\n".join(lines[i] for i in group)

    def assemble() -> str:
        # 이어지는 그룹(긴 턴을 1,500자 조각으로 나눈 것) 사이에는 (중략) 을 넣지 않는다 — 빠진 것이 없다
        parts: list[str] = []
        for k, g in enumerate(groups):
            if k and g[0] == groups[k - 1][-1] + 1:
                parts.append("\n" + render(g))
            else:
                parts.append((_SEPARATOR if k else "") + render(g))
        return prefix + "".join(parts) + "\n" + notice

    text = assemble()
    while groups and len(text) > max_chars:
        groups.remove(min(groups, key=lambda g: max(row_score[i] for i in g)))
        text = assemble()
    if len(text) > max_chars:
        text = notice[:max_chars]
    included = {i for g in groups for i in g}
    sources = [{"meeting_id": meeting.get("id"), "meeting_title": meeting.get("title"),
                "start_time": subtitles[i]["start_time"],
                "text_snippet": (subtitles[i].get("text") or "")[:80], "source_type": "subtitle"}
               for i in sorted(included, key=lambda i: (-row_score[i], i))
               if times[i] is not None and row_score[i] > 0][:5]
    return ContextBundle(text, sources, speakers, {
        "hits": len(hit_rows), "excerpt_count": len(groups), "chars": len(text),
        "covered_last_quarter": any(times[i] is not None and times[i] >= end * .75 for i in included),
        "no_hits": mode in ("no_hits", "overview"), "intent": sorted(plan.intent),
        "estimated_agenda": any(r.estimated for r in ranges), "live_only": live_only,
        "level": level, "mode": mode, "relaxed": level not in ("strict", "sample"),
        "names": plan.names, "unresolved": plan.unresolved, "restored": plan.from_history,
        "terms": plan.terms[:8], "semantic_rows": sum(vec_hit),
    })
