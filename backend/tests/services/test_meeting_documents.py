"""부서별 회의 문서(services/meeting_documents · api/meeting_documents, 2026-09-15)."""
import io
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_supabase
from app.main import app
from app.services import meeting_documents as md

MEETING = {"id": "m1", "title": "제393회 제1차 의회운영위원회 [2026-09-14]", "meeting_date": "2026-09-14",
           "committee": "의회운영위원회", "status": "ended"}


def test_short_forms():
    assert md.councilor_short("장한별") == "장한별 (민,수원4)"
    assert md.councilor_short("없는사람") == "없는사람"
    assert md.district_short("광주시 제3선거구") == "광주3" and md.district_short("비례대표") == "비례"
    assert md.committee_short("의회운영위원회") == "운영위" and md.committee_short("여성가족평생교육위원회") == "여가교위"


@pytest.mark.parametrize(("label", "dept"), [
    ("진용국 사무처장", "의회사무처"), ("사무처장 진용복", "의회사무처"), ("진용복 의회사무처장", "의회사무처"),
    ("김기덕 AI의정혁신팀장", "AI의정혁신팀"), ("양승호 인사과장", "인사과"), ("의정국장 박호순", "의정국"),
    ("정준선 수석전문위원", "전문위원실"), ("이은호 언론협력담당관", "언론협력담당관"), ("대변인 김철수", "대변인"),
    ("이자형 위원", None), ("장한별 위원장", None), ("화자 3", None), ("김기덕 팀장", None),
])
def test_department_of_label(label, dept):
    assert md.department_of_label(label) == dept


def test_normalize_department():
    known = ["의회사무처", "인사과", "소통협치관"]
    assert md.normalize_department("의회 사무처", known) == "의회사무처"
    assert md.normalize_department("소통협치관, 의회 사무처", known) == "소통협치관"
    assert md.normalize_department(None, known) == "미분류"
    assert md.normalize_department("교육청", known) == "교육청"


def row(sec, speaker, text):
    return {"id": str(sec), "start_time": sec, "speaker": speaker, "text": text}


def test_member_turns_keep_short_chair_and_close_on_summon():
    subs = [row(0, "장한별 위원장", "다음은 이자형 위원님 질의해 주십시오."),
            row(10, "이자형 위원", "모바일 공무원증 조직 정보가 틀립니다"), row(20, "장한별 위원장", "네, 답변해 주세요."),
            row(30, "진용국 사무처장", "확인하겠습니다"), row(40, "장한별 위원장", "김태희 위원님 질의해 주십시오."),
            row(50, "김태희 위원", "짧은 인사"), row(60, "이자형 위원", "추가 질의입니다 " + "가" * 30),
            row(70, "양승호 인사과장", "인사과 소관입니다")]
    turns = md.member_turns(subs)
    assert [t["member"] for t in turns] == ["이자형", "이자형"]      # 김태희 턴은 답변도 없고 짧아 뺀다
    assert [r["text"] for r in turns[0]["rows"]][-1] == "확인하겠습니다"  # 짧은 끼어들기 뒤 답변 포함


ITEMS = [
    {"member": "이자형", "question": "○ 조직 정보 현행화 요청", "answer": "○ 확인 후 정정", "answerer": "진용국 사무처장",
     "departments": ["의회사무처"], "department": "의회사무처", "start_time": 10},
    {"member": "이자형", "question": "○ 변경 요청 부서 <문의>", "answer": "○ 인사과 소관", "answerer": "양승호 인사과장",
     "departments": ["인사과"], "department": "인사과", "start_time": 60},
    {"member": "김태희", "question": "○ 렌탈 현황", "answer": "", "answerer": "",
     "departments": ["의회사무처", "총무과"], "department": "의회사무처, 총무과", "start_time": 90},
]


def test_monitoring_markdown_rowspan_escape_and_department_filter():
    text, title = md.monitoring_markdown(MEETING, [], ITEMS, None)
    # 제목은 문단(#)이 아니라 1×1 표다 — 서식이 그렇고, 그래야 서식 프로필의 제목 상자가 붙는다
    assert text.startswith("<table>\n<tr><td>운영위 모니터링('26.9.14)</td></tr>\n</table>")
    assert "#" not in text.split("<table>")[0]
    assert 'rowspan="2">이자형<br>(민,광주3)' in text and "&lt;문의&gt;" in text
    assert title == "260914 운영위 모니터링(회의)"
    only, t2 = md.monitoring_markdown(MEETING, [{"title": "업무보고의 건"}], ITEMS, "인사과")
    assert "업무보고 모니터링" in only and "조직 정보 현행화" not in only and t2.endswith("_인사과")
    with pytest.raises(md.NoDataError):
        md.monitoring_markdown(MEETING, [], ITEMS, "없는부서")


REQS = [
    {"id": "r1", "start_time": 5, "councilor_name": "문승호", "summary": "정수기·커피머신 렌탈 계약 현황 자료",
     "request_text": "렌탈 계약 업체명·금액·종료 시기", "department": "의회 사무처", "status": "detected"},
    {"id": "r2", "start_time": 9, "councilor_name": "신미숙", "summary": "소통협치관 관련 자료", "department": "소통협치관",
     "status": "confirmed"},
    {"id": "r3", "start_time": 12, "councilor_name": "김태희", "summary": "기각된 요구", "department": None, "status": "dismissed"},
]


def test_datareq_list_and_cover():
    rows = md.datareq_rows(REQS, ["의회사무처", "소통협치관"], None)
    assert [r["id"] for r in rows] == ["r1", "r2"]                    # 기각 제외, 시간순
    text, title = md.datareq_list_markdown(MEETING, [], rows, None)
    assert "<th>제출여부</th>" in text and "문승호<br>(민,성남1)" in text and title == "260914 운영위 자료요구 목록"
    only = md.datareq_rows(REQS, ["의회사무처", "소통협치관"], "소통협치관")
    assert [r["id"] for r in only] == ["r2"]
    cover, ctitle = md.cover_markdown(rows[0])
    assert cover.startswith("# 【 문승호 의원 】") and "□ 위 자료는 붙임과 같습니다." in cover and "담당사무관" in cover
    assert ctitle == "[표지] 문승호 의원 요구자료(정수기·커피머신 렌탈 계약 현황 자료)"
    z = zipfile.ZipFile(io.BytesIO(md.zip_bytes([("a.hwpx", b"1"), ("a.hwpx", b"2")])))
    assert sorted(z.namelist()) == ["a (2).hwpx", "a.hwpx"]


@pytest.mark.asyncio
async def test_press_drops_quotes_not_in_subtitles():
    subs = [row(0, "이자형 위원", "모바일 공무원증 조직 정보를 현행화해야 합니다 그래야 의원들이 편합니다")]
    fake = AsyncMock(return_value={"title": "운영위, 업무보고 청취", "subtitles": ["부제"], "lead": "리드", "paragraphs": ["본문"],
                                   "quote": {"speaker": "이자형 위원", "text": "지어낸 말"}})
    md._daily.clear()
    with patch("app.services.summary_service._call_openai_json", fake):
        text, title = await md.press_release(MEETING, {"summary_text": "요약"}, subs)
    assert "지어낸 말" not in text and "# 운영위, 업무보고 청취" in text and "AI 초안" in text
    assert title == "260914 운영위 보도자료(초안)"
    with pytest.raises(md.NoDataError):
        await md.press_release(MEETING, {}, subs)


# ── API ────────────────────────────────────────────────────────────────────────
def _ctx(**over):
    base = {"meeting": MEETING, "subs": [row(10, "이자형 위원", "질의"), row(20, "진용국 사무처장", "답변")], "agendas": [],
            "requests": REQS, "staff_titles": {}, "summary": {"summary_text": "요약"}, "departments": ["의회사무처", "소통협치관"],
            "fingerprint": "fp"}
    base.update(over)
    return base


@pytest.fixture
def client():
    app.dependency_overrides[get_supabase] = lambda: MagicMock()
    yield TestClient(app)
    app.dependency_overrides.clear()


COUNCIL = patch("app.core.auth_middleware.is_council", return_value=True)


def test_api_options_and_monitoring_hwpx(client):
    with COUNCIL, patch("app.api.meeting_documents._load", return_value=_ctx()), \
            patch("app.services.meeting_documents.extract_monitoring", AsyncMock(return_value=ITEMS)), \
            patch("app.api.meeting_documents.generate_hwpx", return_value=(b"HWPX", "attachment; filename*=UTF-8''x.hwpx")) as gen:
        opt = client.get("/api/meetings/m1/documents/options").json()
        assert opt["departments"] == ["의회사무처", "소통협치관"] and len(opt["material_requests"]) == 2
        r = client.post("/api/meetings/m1/documents/monitoring?department=인사과")
        assert r.status_code == 200 and r.content == b"HWPX"
        assert r.headers["content-disposition"] == "attachment; filename*=UTF-8''x.hwpx"
        assert "양승호" not in gen.call_args.args[0] and "인사과 소관" in gen.call_args.args[0]
        preview = client.post("/api/meetings/m1/documents/monitoring?format=json").json()
        assert len(preview["rows"]) == 3


def test_api_cover_bundle_is_zip_and_single_is_hwpx(client):
    with COUNCIL, patch("app.api.meeting_documents._load", return_value=_ctx()), \
            patch("app.api.meeting_documents.generate_hwpx", return_value=(b"H", "cd")):
        z = client.post("/api/meetings/m1/documents/datareq-cover?department=의회사무처")
        assert z.headers["content-type"] == "application/zip"
        assert len(zipfile.ZipFile(io.BytesIO(z.content)).namelist()) == 1
        one = client.post("/api/meetings/m1/documents/datareq-cover?request_id=r2")
        assert one.status_code == 200 and one.content == b"H"


def test_api_errors(client):
    with COUNCIL, patch("app.api.meeting_documents._load", return_value=_ctx(requests=[])):
        assert client.post("/api/meetings/m1/documents/datareq-list").status_code == 409
        assert client.post("/api/meetings/m1/documents/nope").status_code == 404
    with COUNCIL, patch("app.api.meeting_documents._load", return_value=_ctx()), \
            patch.object(md.settings, "ggc_doc_internal_url", ""):
        r = client.post("/api/meetings/m1/documents/datareq-list")
        assert r.status_code == 503 and "문서 엔진" in r.json()["detail"]


def test_api_requires_login_or_council(client):
    with patch("app.core.auth_middleware.is_council", return_value=False):
        assert client.get("/api/meetings/m1/documents/options").status_code in (401, 403)


def test_multi_answerer_item_shows_in_each_department():
    only, _ = md.monitoring_markdown(MEETING, [], ITEMS, "총무과")
    assert "렌탈 현황" in only and "조직 정보" not in only


def test_label_departments_merge_rare_asr_variant():
    subs = [row(i, "박호순 의정국장", "답변") for i in range(12)] + [row(99, "박호순 의장국장", "답변"), row(100, "양승호 인사과장", "답")]
    known, canon = md.label_departments(subs)
    assert known[0] == "의정국" and canon["의장국"] == "의정국" and "의장국" not in known and "인사과" in known


@pytest.mark.asyncio
async def test_extract_splits_answerers_and_canonicalizes():
    subs = [row(0, "이자형 위원", "질의 " + "가" * 50), row(10, "박호순 의정국장", "답변"), row(20, "이민재 총무과장", "보충")]
    subs += [row(100 + i, "박호순 의정국장", "추가") for i in range(10)]
    fake = AsyncMock(return_value={"items": [{"turn": 0, "question": "○ 질의", "answer": "○ 답", "answerer": "이민재 총무과장, 박호순 의장국장"}]})
    md._extract_cache.clear()
    md._daily.clear()
    with patch("app.services.summary_service._call_openai_json", fake):
        items = await md.extract_monitoring(subs, "fp", "mX")
    assert items[0]["departments"] == ["총무과", "의정국"]


@pytest.mark.asyncio
async def test_long_turn_is_split_not_truncated():
    subs = [row(0, "이자형 위원", "질의 " + "가" * 6200), row(10, "진용국 사무처장", "마지막 답변입니다")]
    seen = []

    async def fake(system, user, **kw):
        seen.append(user)
        return {"items": [{"turn": 0, "question": "○ 질의", "answer": "○ 답", "answerer": "진용국 사무처장"}]}

    md._extract_cache.clear()
    md._daily.clear()
    with patch("app.services.summary_service._call_openai_json", side_effect=fake):
        await md.extract_monitoring(subs, "fp-long", "mL")
    assert any("마지막 답변입니다" in u for u in seen)
    assert all(len(u) <= 6000 + 200 for u in seen) and len(seen) >= 2


@pytest.mark.asyncio
async def test_concurrent_requests_extract_once():
    import asyncio as aio

    subs = [row(0, "이자형 위원", "질의 " + "가" * 50), row(10, "진용국 사무처장", "답변")]
    calls = 0

    async def fake(system, user, **kw):
        nonlocal calls
        calls += 1
        await aio.sleep(0.05)
        return {"items": [{"turn": 0, "question": "○ 질의", "answer": "○ 답", "answerer": "진용국 사무처장"}]}

    md._extract_cache.clear()
    md._daily.clear()
    with patch("app.services.summary_service._call_openai_json", side_effect=fake):
        a, b = await aio.gather(md.extract_monitoring(subs, "fp-c", "mC"), md.extract_monitoring(subs, "fp-c", "mC"))
    assert calls == 1 and a == b and sum(md._daily.values()) == 1


def test_quote_must_come_from_that_speaker():
    subs = [row(0, "이자형 위원", "모바일 공무원증 조직 정보를"), row(5, "이자형 위원", "현행화해야 합니다"),
            row(10, "김태희 위원", "예산을 삭감하면 안 됩니다")]
    assert md.quote_in_speaker({"speaker": "이자형 위원", "text": "조직 정보를 현행화해야"}, subs)       # 이어진 두 행에 걸친 문장
    assert not md.quote_in_speaker({"speaker": "이자형 위원", "text": "예산을 삭감하면 안 됩니다"}, subs)  # 남의 말
    assert not md.quote_in_speaker({"speaker": "", "text": "예산을 삭감하면"}, subs)


def test_roster_falls_back_to_db_when_json_missing(tmp_path, monkeypatch):
    from unittest.mock import MagicMock as MM

    monkeypatch.setattr(md, "_roster_cache", None)
    monkeypatch.setattr(md, "Path", lambda *_a, **_k: tmp_path / "x" / "y" / "z.py")   # JSON 이 없는 컨테이너
    db = MM()
    db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MM(
        data=[{"name": "장한별", "party": "더불어민주당", "district": "수원시 제4선거구"}])
    with patch("app.core.database.get_supabase", return_value=db):
        assert md.councilor_short("장한별") == "장한별 (민,수원4)"
    monkeypatch.setattr(md, "_roster_cache", None)
