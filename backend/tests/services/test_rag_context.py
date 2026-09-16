"""DB와 앱 초기화 없이 회의 컨텍스트 선택 계약을 검증한다."""
import importlib
import re
import sys
import types
from collections import Counter
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(scope="module")
def rag():
    """기존 services 패키지의 DB 관련 초기화만 격리하고 실제 모듈을 읽는다."""
    services = Path(__file__).resolve().parents[2] / "app" / "services"
    package = types.ModuleType("app.services")
    package.__path__ = [str(services)]
    with patch.dict(sys.modules):
        for name in tuple(sys.modules):
            if name == "app.services" or name.startswith("app.services."):
                del sys.modules[name]
        sys.modules["app.services"] = package
        return importlib.import_module("app.services.rag_context")


def row(sec, text="일반 발언", speaker=None, kind="ai"):
    return {"id": str(sec), "start_time": sec, "end_time": None if sec is None else sec + 5,
            "text": text, "speaker": speaker, "kind": kind}


def build(rag, subtitles, question, **kwargs):
    return rag.build_meeting_context(
        subtitles=subtitles, question=question,
        meeting=kwargs.pop("meeting", {"id": "meeting-1", "title": "검증 회의"}),
        summary_row=kwargs.pop("summary_row", None), agendas=kwargs.pop("agendas", []), **kwargs)


def parse(rag, question, **kwargs):
    return rag.parse_question(question, known_speakers=kwargs.pop("known_speakers", set()),
                              agendas=kwargs.pop("agendas", []),
                              duration=kwargs.pop("duration", 10800), **kwargs)


def stamp(sec):
    sec = int(sec)
    return f"[{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}]"


def test_late_unique_hit_and_sources(rag):
    subs = [row(i * 7, "가" * 80) for i in range(1500)]
    subs[1399]["text"] = "수소버스" + "가" * 76
    result = build(rag, subs, "수소버스")
    assert stamp(subs[1399]["start_time"]) in result.text
    assert result.sources[0]["start_time"] == subs[1399]["start_time"]
    assert result.sources[0]["meeting_title"] == "검증 회의"
    assert result.stats["covered_last_quarter"]
    assert len(result.text) <= 12000
    assert len(result.sources) <= 5
    for source in result.sources:
        assert any(line.startswith(stamp(source["start_time"]) + " ")
                   and source["text_snippet"] in line for line in result.text.splitlines())
        assert len(source["text_snippet"]) <= 80


@pytest.mark.parametrize("question", [
    "김태희 의원이 무엇을 질의했나", "김태희 의원의 질의", "김태희 의원님", "김태희의원님",
])
def test_member_particles(rag, question):
    plan = parse(rag, question)
    assert plan.names == ["김태희"]
    assert "speaker" in plan.intent


def test_terms_and_known_labels(rag):
    plan = parse(rag, "예산 삭감 얘기 나왔나")
    assert {"예산", "삭감"} <= set(plan.terms)
    terms = parse(rag, "정의 회의 처리 관리 예산을").terms
    assert {"정의", "처리", "관리", "예산을", "예산"} <= set(terms)
    assert "정" not in terms and "회" not in terms
    assert all(2 <= len(t) <= 20 for t in terms)
    assert len(terms) == len(set(terms))
    assert parse(rag, "박상현은?", known_speakers={"박상현 위원"}).names == ["박상현"]
    assert parse(rag, "위원장은?", known_speakers={"위원장 박상현"}).names == []


@pytest.mark.parametrize("question", ["2번 안건 결론은", "두 번째 안건", "의사일정 제2항"])
def test_agenda_number(rag, question):
    plan = parse(rag, question)
    assert plan.agenda_nums == [2]
    assert {"agenda", "conclusion"} <= plan.intent


@pytest.mark.parametrize(("question", "expected"), [
    ("1시간 20분쯤", (4500, 5100)), ("01:20:00", (4500, 5100)),
    ("80분 이후", (4800, 10800)), ("후반에", (8100, 10800)),
    ("초반", (0, 2700)), ("중반", (2700, 8100)), ("마지막", (8100, 10800)),
])
def test_elapsed_time(rag, question, expected):
    assert parse(rag, question).time_ranges == [expected]


def test_clock_and_title_stem(rag):
    assert parse(rag, "오후 2시 20분 회의").time_ranges == []
    agendas = [{"order_num": 2, "title": "수소버스 지원 조례안"}]
    assert parse(rag, "수소버스는?", agendas=agendas).agenda_nums == [2]


def test_history_only_previous_user_and_no_override(rag):
    history = [{"role": "user", "content": "2번 안건"},
               {"role": "assistant", "content": "이전 설명"},
               {"role": "user", "content": "김태희 의원 질의"},
               {"role": "assistant", "content": "박상현 의원 답변"}]
    plan = parse(rag, "그 답변에 뭐라고 했나", history=history)
    assert plan.names == ["김태희"] and plan.from_history
    assert not plan.agenda_nums
    assert parse(rag, "그 의원은?", history=history).names == ["김태희"]
    explicit = parse(rag, "그 답변 80분 이후", history=history)
    assert not explicit.from_history and not explicit.names
    assert not parse(rag, "수소버스 예산", history=history).from_history
    restored = parse(rag, "그 결과는?", history=[{"role": "user", "content": "2번 안건 80분 이후"}])
    assert restored.agenda_nums == [2] and restored.time_ranges == [(4800, 10800)]


def test_speaker_turn_includes_answers_stops_at_other_member(rag):
    subs = [row(0, "첫 질의", "김태희 위원"), row(10, "집행부 첫 답변", "홍길동 국장"),
            row(20, "추가 질의", "김태희 위원"), row(30, "집행부 두 번째 답변", "홍길동 국장"),
            row(40, "마지막 질의", "김태희 위원"), row(50, "집행부 세 번째 답변", "홍길동 국장"),
            row(60, "다른 의원 시작", "박상현 위원"), row(70, "다른 답변", "홍길동 국장")]
    result = build(rag, subs, "김태희 의원 질의")
    assert all(text in result.text for text in ("집행부 첫 답변", "집행부 두 번째 답변", "집행부 세 번째 답변"))
    excerpt = result.text.split("=== 자막 발췌 ===\n")[1]
    assert "다른 의원 시작" not in excerpt and "다른 답변" not in excerpt
    assert len(excerpt.split("\n위 자막")[0]) <= 1500


def test_live_call_has_90_second_limit(rag):
    subs = [row(0, "이전 발언", kind="live"), row(100, "김태희 의원님 질의하세요", kind="live"),
            row(150, "집행부 답변", kind="live"), row(190, "90초 경계 답변", kind="live"),
            row(191, "범위 밖 발언", kind="live")]
    result = build(rag, subs, "김태희 의원님")
    assert "집행부 답변" in result.text and "90초 경계 답변" in result.text
    assert "범위 밖 발언" not in result.text and "이전 발언" not in result.text
    assert result.stats["live_only"]
    assert "실시간 자막이라 화자가 확인되지 않았다" in result.text


def test_real_agenda_anchors_and_grouped_introduction(rag):
    agendas = [{"order_num": 1, "title": "수소버스 구매 지원의 건"},
               {"order_num": 2, "title": "학교급식 안전 점검의 건"}]
    subs = [row(120, "수소버스 구매 지원의 건과 학교급식 안전 점검의 건을 일괄 상정합니다"),
            row(130, "김태희 의원입니다"), row(500, "산회")]
    ranges = rag.resolve_agenda_ranges(agendas, subs)
    assert [(r.order_num, r.lo, r.hi, r.estimated) for r in ranges] == [
        (1, 120, 505, False), (2, 120, 505, False)]
    assert rag.resolve_agenda_ranges(agendas, [row(0, "일반 발언")]) == []


def test_missing_agenda_is_estimated_without_uniform_split(rag, monkeypatch):
    agendas = [{"order_num": n, "title": f"안건 제목 {n}"} for n in (1, 2, 3)]
    monkeypatch.setattr(rag, "_anchor_agendas", lambda a, s: [
        {"label": "1. 안건 제목 1", "seconds": 100},
        {"label": "제안설명(김태희 의원)", "seconds": 130},
        {"label": "3. 안건 제목 3", "seconds": 900},
    ])
    ranges = rag.resolve_agenda_ranges(agendas, [row(1000)])
    assert [(r.lo, r.hi, r.estimated) for r in ranges] == [
        (100, 900, False), (100, 900, True), (900, 1005, False)]


@pytest.mark.parametrize(("question", "limit"), [
    ("전체 요약", 4000), ("2번 안건 결론", 2500), ("김태희 의원 질의", 1200),
])
def test_summary_header_budgets(rag, question, limit):
    summary = {"summary_text": "전체요약" * 2000,
               "agenda_summaries": [{"order_num": 1, "title": "첫째", "summary": "가" * 6000},
                                    {"order_num": 2, "title": "둘째", "summary": "해당안건" * 2000}]}
    result = build(rag, [row(0, "질의", "김태희 위원")], question, summary_row=summary,
                   meeting={"title": "회의" * 1000, "committee": "위원회" * 1000})
    header, tail = result.text.split("=== 회의 요약 ===\n")
    summary_block = "=== 회의 요약 ===\n" + tail.split("\n=== 자막 발췌 ===")[0]
    assert len(header.rstrip()) <= 1000 and len(summary_block) <= limit
    assert all(label in header for label in ("=== 회의 정보 ===", "=== 발언자 목록 ===", "=== 안건 ==="))
    if "2번" in question:
        assert "해당안건" in summary_block
    assert len(result.text) <= 12000


def test_no_hits_samples_last_quarter_and_does_not_mutate(rag):
    subs = [row(i * 10, "가" * 80) for i in range(1500)]
    before = deepcopy(subs)
    result = build(rag, subs, "없는단어")
    assert result.stats["no_hits"] and result.stats["covered_last_quarter"]
    assert stamp(subs[-1]["start_time"]) in result.text
    assert subs == before


def test_bucket_cap_and_combined_filters(rag):
    subs = [row(i * 7, "예산 " + "가" * 80) for i in range(1500)]
    result = build(rag, subs, "예산")
    costs = Counter()
    for line in result.text.splitlines():
        m = re.match(r"\[(\d+):(\d+):(\d+)\] ", line)
        if m:
            seconds = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])
            costs[seconds // 900] += len(line) + 1
    prefix = result.text.split("=== 자막 발췌 ===\n")[0] + "=== 자막 발췌 ===\n"
    notice = result.text.rsplit("\n", 1)[1]
    excerpt_budget = 12000 - len(prefix) - len(notice) - 1
    assert len(costs) >= 3 and max(costs.values()) <= excerpt_budget * .4
    combined = build(rag, [row(0, "앞 질문", "김태희 위원"),
                           row(4800, "뒤 질문", "김태희 위원")], "김태희 의원 80분 이후")
    assert "뒤 질문" in combined.text and "앞 질문" not in combined.text


@pytest.mark.parametrize("budget", [0, 1, 100, 500, 12000])
def test_empty_unknown_times_and_small_budgets(rag, budget):
    result = build(rag, [row(None, "시각 없음"), row(9000, "후반 발언")], "없는단어",
                   max_chars=budget)
    assert len(result.text) <= budget and result.stats["chars"] == len(result.text)
    assert all(source["start_time"] is not None for source in result.sources)
    assert build(rag, [], "전체 요약", max_chars=budget).sources == []


def test_rare_late_match_outranks_common_early_matches(rag):
    subs = [row(i * 7, "예산 " + "가" * 80) for i in range(1500)]
    subs[1400]["text"] = "예산 수소버스 특별 검토"
    result = build(rag, subs, "예산 수소버스")
    assert result.sources[0]["start_time"] == subs[1400]["start_time"]
    assert "예산 수소버스 특별 검토" in result.text


def test_entire_roster_and_turn_cap(rag):
    subs = [row(i * 10, "가" * 100, "김태희 위원" if i % 2 == 0 else "홍길동 국장")
            for i in range(30)]
    subs += [row(1000 + i * 10, "다른 질의", f"의원{i} 위원") for i in range(70)]
    result = build(rag, subs, "김태희 의원")
    excerpt = result.text.split("=== 자막 발췌 ===\n")[1].split("\n위 자막")[0]
    # 긴 턴은 1,500자 조각으로 이어 담는다(2026-09-14 수정) — 조각 하나가 1,500자를 넘지 않고, 다른 의원 턴은 들어오지 않는다
    assert result.stats["excerpt_count"] == 3 and len(excerpt) <= 3 * 1500 + 200  # 조각 3개, 각 ≤1,500
    assert "(중략)" not in excerpt
    assert len(result.speakers) == 60
    assert result.speakers[:3] == ["김태희 위원", "홍길동 국장", "의원0 위원"]
    assert "다른 질의" not in excerpt


def test_agenda_filters_with_time_and_exposes_estimate(rag, monkeypatch):
    agendas = [{"order_num": 1, "title": "첫째"}, {"order_num": 2, "title": "둘째"},
               {"order_num": 3, "title": "셋째"}]
    monkeypatch.setattr(rag, "_anchor_agendas", lambda a, s: [
        {"label": "1. 첫째", "seconds": 0}, {"label": "3. 셋째", "seconds": 7000}])
    subs = [row(0, "앞부분", "김태희 위원"), row(4800, "선택된 안건의 답변", "김태희 위원"),
            row(8000, "다음 안건", "김태희 위원")]
    result = build(rag, subs, "김태희 의원 2번 안건 80분 이후", agendas=agendas)
    assert result.stats["hits"] == 1 and result.stats["estimated_agenda"]
    assert "앞부분" not in result.text and "다음 안건" not in result.text
    assert result.sources[0]["start_time"] == 4800
    assert "[안건 2 구간(추정)]" in result.text
    plan = parse(rag, "김태희 의원 2번 안건 80분 이후", agendas=agendas)
    assert {"speaker", "agenda", "time"} <= plan.intent


def test_long_speaker_turn_keeps_late_keyword(rag):
    """같은 의원의 긴 연속 발언(>1,500자)에서 뒤쪽 키워드 일치가 버려지지 않는다(Codex 검토 P2)."""
    subs = [row(i * 10, "일반 발언 " + "가" * 120, speaker="김태희 위원") for i in range(20)]
    subs[16]["text"] = "예산 삭감 문제를 짚겠습니다 " + "나" * 100
    result = build(rag, subs, "김태희 의원이 예산 삭감에 대해 뭐라고 했나")
    assert stamp(subs[16]["start_time"]) in result.text
    assert any(src["start_time"] == subs[16]["start_time"] for src in result.sources)


# ─────────────────────────────────────────────────────────────────────────────
# 2026-09-15 담당자 신고 재현 — "이자형 의원이 모바일 공무원증 얘기를 했는데 AI 가 못 찾는다"
# 운영 회의(제393회 제1차 의회운영위원회) 모양: 5시간 · 안건 5 제목에 '공무원' · 04:28 에 질의·답변 · 위원장 끼어들기
# ─────────────────────────────────────────────────────────────────────────────
AGENDA5 = "경기도의회 공무원 공무국외출장규칙 일부개정규칙안"
AGENDAS = [{"order_num": 2, "title": "수소버스 보급 지원 조례안"},
           {"order_num": 5, "title": AGENDA5},
           {"order_num": 6, "title": "경기도의회 의정자문단 구성·운영 조례안"}]
LABELS = ["장한별 위원장", "김태희 위원", "이자형 위원", "진용국 사무처장", "김기덕 AI의정혁신팀장"]
MOBILE = [
    (16092, "이자형 위원", "모바일 공무원증 어플은 다운 받으셨습니까?"),
    (16097, "진용국 사무처장", "저는 아직 모바일 공무원증 어플도 서류가 준비가 덜 된 걸로 알고 있습니다."),
    (16106, "이자형 위원", "그러면 모바일 공무원증에 등록된 경기도의회 조직 정보는 확인해 보신 적이 없으시겠네요?"),
    (16110, "장한별 위원장", "네, 답변해 주세요."),
    (16133, "진용국 사무처장", "지금 모바일 공무원증에 등록된 경기도의회 조직 정보를 살펴보면 부서명이 예전 그대로입니다."),
    (16170, "이자형 위원", "조직 개편이 있을 때 모바일 공무원증 조직 정보를 어느 부서에서 변경을 요청합니까?"),
    (16187, "진용국 사무처장", "현재 모바일 공무원증 관련 조직 정보 관리는 인사과로 알고 있습니다."),
    (16209, "이자형 위원", "보통 모바일 공무원증은 어떤 때 사용하십니까?"),
]


@pytest.fixture
def production_like(rag, monkeypatch):
    monkeypatch.setattr(rag, "_anchor_agendas", lambda a, s: [
        {"label": f"5. {AGENDA5}", "seconds": 300}, {"label": "6. 경기도의회 의정자문단 구성·운영 조례안", "seconds": 1500}])
    subs = []
    for k in range(1500):
        sec = k * 12
        if 16080 <= sec <= 16220:
            continue
        text = "일반 발언 " + "가" * 60
        if 300 <= sec < 1500 and k % 3 == 0:
            text = "경기도의회 공무원 국외출장 여비 규정을 정비합니다 " + "나" * 30   # 안건 5 구간의 '공무원' 행
        subs.append(row(sec, text, LABELS[k % len(LABELS)]))
    subs += [row(sec, text, spk) for sec, spk, text in MOBILE]
    return sorted(subs, key=lambda s: s["start_time"])


def excerpt_of(result):
    return result.text.split("=== 자막 발췌 ===\n", 1)[1]


def test_production_question_finds_mobile_id_turn(rag, production_like):
    q = "이자형의원이 발언한 것중에 모바일 공무원증은 없어?"
    plan = parse(rag, q, known_speakers=set(LABELS), agendas=AGENDAS)
    assert plan.agenda_nums == [] and plan.names == ["이자형"]
    assert {"모바일", "공무원증"} <= set(plan.terms)
    assert not {"것중", "것중에", "없어", "발언한", "이자형의원이"} & set(plan.terms)
    result = build(rag, production_like, q, agendas=AGENDAS)
    ex = excerpt_of(result)
    assert stamp(16092) in ex and stamp(16209) in ex
    assert ex.count("모바일") >= 4
    assert "지금 모바일 공무원증에 등록된" in ex      # 위원장 끼어들기 뒤의 답변도 같은 턴
    assert "국외출장 여비" not in ex                  # 안건 5 구간으로 새지 않는다
    assert result.stats["level"] == "strict" and result.stats["mode"] == "speaker"
    assert "[검색 안내]" not in result.text
    assert result.sources and all(16000 < s["start_time"] < 16300 for s in result.sources)


def test_topic_only_is_not_an_agenda_question_and_fills_budget(rag, production_like):
    plan = parse(rag, "모바일 공무원증", known_speakers=set(LABELS), agendas=AGENDAS)
    assert plan.agenda_nums == [] and "agenda" not in plan.intent
    result = build(rag, production_like, "모바일 공무원증", agendas=AGENDAS)
    ex = excerpt_of(result)
    assert result.stats["mode"] == "hits" and result.stats["hits"] == len(MOBILE) - 1
    assert "국외출장 여비" not in ex
    assert ex.count("모바일") >= 7
    assert len(result.text) > 4000                    # 적중 창을 넓혀 예산을 쓴다(예전 2,208자)


def test_name_typo_resolves_to_meeting_speaker(rag, production_like):
    plan = parse(rag, "이자영 의원이 모바일 공무원증 얘기했어?", known_speakers=set(LABELS), agendas=AGENDAS)
    assert plan.names == ["이자형"] and plan.renamed == {"이자영": "이자형"}
    only_roster = parse(rag, "이자영 의원 발언", roster=["이자형", "전자영"])
    assert only_roster.names == ["이자형"]
    result = build(rag, production_like, "이자영 의원이 모바일 공무원증 얘기했어?", agendas=AGENDAS)
    assert "'이자영'는 발언자 '이자형'" in result.text and stamp(16092) in result.text
    unknown = parse(rag, "홍길순 의원 발언", known_speakers=set(LABELS), roster=["이자형"])
    assert unknown.names == [] and unknown.unresolved == ["홍길순"] and "홍길순" in unknown.terms


def test_other_speaker_only_falls_to_keyword_with_notice(rag):
    subs = [row(0, "모바일 공무원증 도입 현황을 묻겠습니다", "김태희 위원"), row(10, "답변드리겠습니다", "홍길동 국장"),
            row(2000, "다른 이야기입니다", "이자형 위원"), row(2010, "네 알겠습니다", "홍길동 국장")]
    result = build(rag, subs, "이자형 위원 모바일 공무원증")
    assert result.stats["level"] == "keyword"
    assert "모바일 공무원증 도입 현황" in result.text
    assert "이자형의 발언에는" in result.text and "말했다고 답하지 마라" in result.text


def test_explicit_agenda_relaxes_only_when_empty(rag, production_like):
    result = build(rag, production_like, "이자형 의원 5번 안건 모바일 공무원증", agendas=AGENDAS)
    assert result.stats["level"] == "no_agenda" and stamp(16092) in result.text
    assert "지정한 안건 구간에는 일치가 없어" in result.text


def test_generic_title_words_do_not_pick_agendas(rag):
    assert parse(rag, "모바일 공무원증은?", agendas=AGENDAS).agenda_nums == []
    assert parse(rag, "경기도의회 공무원 얘기", agendas=AGENDAS).agenda_nums == []
    assert parse(rag, "공무국외출장규칙 결과는?", agendas=AGENDAS).agenda_nums == [5]
    assert parse(rag, "국외출장 규칙은?", agendas=AGENDAS).agenda_nums == [5]
    assert parse(rag, "수소버스보급 조례", agendas=AGENDAS).agenda_nums == [2]
    hint = parse(rag, "수소버스는?", agendas=AGENDAS)
    assert hint.agenda_nums == [2] and hint.agenda_hint == [2] and "conclusion" not in hint.intent


def test_no_fake_names_from_committee_or_staff_words(rag):
    assert parse(rag, "의회운영위원회 결과").names == []
    assert parse(rag, "수석전문위원 검토보고").names == []


def test_follow_up_chain_restores_terms(rag):
    h1 = [{"role": "user", "content": "모바일 공무원증 얘기 나왔어?"}, {"role": "assistant", "content": "네"}]
    p1 = parse(rag, "그거 누가 말했어?", history=h1)
    assert {"모바일", "공무원증"} <= set(p1.terms) and p1.from_history
    h2 = h1 + [{"role": "user", "content": "그거 누가 말했어?"}, {"role": "assistant", "content": "이자형 위원"}]
    assert {"모바일", "공무원증"} <= set(parse(rag, "그 사람은 뭐라고 했어?", history=h2).terms)
    own = parse(rag, "그럼 예산은?", history=h1)
    assert "예산" in own.terms and "모바일" not in own.terms and not own.from_history
    ell = parse(rag, "그래서 결론은?", history=[{"role": "user", "content": "5번 안건 결과는?"}])
    assert ell.agenda_nums == [5] and ell.from_history


def test_particles_and_chat_words(rag):
    plan = parse(rag, "혹시 의원한테 공무원증이랑 사무처로 넘어간 예산만 알려줘")
    assert {"공무원증", "사무처", "예산"} <= set(plan.terms)
    assert not {"의원", "혹시", "알려줘", "의원한테"} & set(plan.terms)
    assert plan.names == []                                  # '혹시 의원' 을 이름으로 읽지 않는다
    assert parse(rag, "예산만 의원한테 물어봤어").names == []
    assert parse(rag, "김기덕 팀장이 뭐라고 답했어?", known_speakers={"김기덕 AI의정혁신팀장"}).terms == []


def test_no_hits_has_no_sources_and_says_so(rag, production_like):
    result = build(rag, production_like, "블록체인 얘기 있었어?", agendas=AGENDAS)
    assert result.stats["mode"] == "no_hits" and result.sources == []
    assert "회의 정보·요약으로도 답할 수 없으면 관련 발언을 찾지 못했다고 답하라" in result.text
    assert result.text.rsplit("\n", 1)[1].startswith("위 자막은 질문과 일치하는 구간이 없어")


def test_official_label_variants_are_one_person_but_members_are_not(rag):
    labels = {"진용국 사무처장", "진용복 의회사무처장", "김태희 위원", "김부희 과장"}
    assert {"진용국", "진용복"} <= set(parse(rag, "진용국 사무처장 답변", known_speakers=labels).names)
    assert parse(rag, "김태희 위원 질의", known_speakers=labels).names == ["김태희"]


def test_speaker_only_fallback_when_terms_never_match(rag, production_like):
    result = build(rag, production_like, "김기덕 팀장 블록체인 답변", agendas=AGENDAS)
    assert result.stats["level"] == "speaker_only" and "김기덕 AI의정혁신팀장" in excerpt_of(result)
    assert "김기덕의 발언 전체에서" in result.text


def test_agenda_number_only_stays_in_that_agenda(rag, monkeypatch):
    """번호만 물으면 그 구간 자체 — 결정 문구가 없다고 다른 안건의 가결로 새지 않는다(Codex 검토 2026-09-15)."""
    agendas = [{"order_num": 1, "title": "첫째"}, {"order_num": 2, "title": "둘째"}]
    monkeypatch.setattr(rag, "_anchor_agendas", lambda a, s: [
        {"label": "1. 첫째", "seconds": 0}, {"label": "2. 둘째", "seconds": 100}])
    subs = [row(10, "첫째 안건 설명입니다"), row(20, "질의 없습니다"), row(110, "둘째 안건 원안대로 가결되었음을 선포합니다")]
    result = build(rag, subs, "1번 안건", agendas=agendas)
    assert result.stats["level"] == "strict" and result.stats["mode"] == "range"
    assert "첫째 안건 설명" in result.text and "가결되었음" not in excerpt_of(result)


def test_follow_up_keeps_title_agenda_hint(rag):
    history = [{"role": "user", "content": "수소버스는?"}, {"role": "assistant", "content": "…"}]
    plan = parse(rag, "그 결과는?", agendas=AGENDAS, history=history)
    assert plan.agenda_nums == [2] and plan.agenda_hint == [2] and plan.from_history


def test_semantic_hits_find_paraphrase_without_keyword(rag, production_like):
    """낱말이 하나도 겹치지 않는 질문 — 뜻으로 찾은 조각이 적중이 되고 [검색 안내]로 알린다."""
    hits = [{"start_time": 16090, "end_time": 16215, "similarity": 0.51},
            {"start_time": 900, "end_time": 960, "similarity": 0.42},      # 최고점과 0.06 넘게 차이 — 버림
            {"start_time": 3000, "end_time": 3100, "similarity": 0.33}]    # 문턱 미만 — 버림
    result = build(rag, production_like, "휴대폰 신분증 앱 얘기", agendas=AGENDAS, semantic_hits=hits)
    ex = excerpt_of(result)
    assert result.stats["mode"] == "semantic" and stamp(16092) in ex
    assert stamp(900) not in ex and stamp(3000) not in ex
    assert "뜻이 비슷한 구간" in result.text
    none = build(rag, production_like, "휴대폰 신분증 앱 얘기", agendas=AGENDAS,
                 semantic_hits=[{"start_time": 16090, "end_time": 16215, "similarity": 0.33}])
    assert none.stats["mode"] == "no_hits"


def test_semantic_rows_respect_speaker_turns(rag, production_like):
    hits = [{"start_time": 16090, "end_time": 16215, "similarity": 0.5}, {"start_time": 2000, "end_time": 2100, "similarity": 0.5}]
    result = build(rag, production_like, "이자형 위원 휴대폰 신분증 앱 질의", agendas=AGENDAS, semantic_hits=hits)
    assert result.stats["mode"] == "speaker" and stamp(16092) in result.text


def test_semantic_ignored_for_speaker_only_or_overview(rag, production_like):
    hits = [{"start_time": 0, "end_time": 99999, "similarity": 0.9}]
    assert build(rag, production_like, "이 회의를 요약해 줘", agendas=AGENDAS, semantic_hits=hits).stats["semantic_rows"] == 0
    assert build(rag, production_like, "이자형 위원 질의", agendas=AGENDAS, semantic_hits=hits).stats["semantic_rows"] == 0


def test_retrieval_query_adds_previous_question_for_follow_ups(rag):
    h = [{"role": "user", "content": "모바일 공무원증 얘기 나왔어?"}, {"role": "assistant", "content": "네"}]
    assert rag.retrieval_query("그거 누가 말했어?", h) == "모바일 공무원증 얘기 나왔어? 그거 누가 말했어?"
    assert rag.retrieval_query("예산 삭감은?", h) == "예산 삭감은?"
    assert rag.retrieval_query("예산 삭감은?") == "예산 삭감은?"
    h2 = [{"role": "user", "content": "휴대폰 신분증 앱 얘기 나왔어?"}, {"role": "assistant", "content": "네"},
          {"role": "user", "content": "그거 누가 말했어?"}, {"role": "assistant", "content": "이자형 위원"}]
    assert rag.retrieval_query("그 답변은?", h2) == "휴대폰 신분증 앱 얘기 나왔어? 그거 누가 말했어? 그 답변은?"
