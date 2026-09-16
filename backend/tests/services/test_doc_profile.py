"""서식 프로필을 우리 표에 맞추는 순수 함수들 (2026-09-16).

kordoc 의 표 매칭은 rows·cols 가 정확히 같아야 하고 anchor_text 가 있으면 첫 셀 글자까지 같아야 한다.
어긋나면 **오류가 아니라 조용히 미적용**이라(200 이고 파일도 멀쩡하다) 테스트로 못 박아 둔다.
"""
from __future__ import annotations

from app.services import doc_profile as dp
from app.services import meeting_documents as md


def _profile() -> dict:
    return {
        "schema_version": "0.3.0",
        "tables": [
            {"table_index": 0, "rows": 1, "cols": 1, "anchor_text": "운영위업무보고모니터링26914",
             "col_widths_hwpunit": ["53294"], "cells": [{"row": 0, "col": 0, "used_border_fills": {"1": {}}}]},
            {"table_index": 1, "rows": 3, "cols": 2, "anchor_text": "의원명", "anchor_row": "의원명|질의내용",
             "col_widths_hwpunit": ["6126", "26485"],
             "cells": [{"row": r, "col": c, "used_border_fills": {str(r): {}}}
                       for r in range(3) for c in range(2)]},
        ],
    }


def test_strip_anchors_removes_both_anchor_keys():
    out = dp.strip_anchors(_profile())
    assert all("anchor_text" not in t and "anchor_row" not in t for t in out["tables"])
    # 원본은 그대로 — 캐시에 담긴 프로필을 망가뜨리면 다음 문서가 조용히 달라진다
    assert _profile()["tables"][0]["anchor_text"]


def test_fit_rows_grows_by_cloning_last_body_row():
    out = dp.fit_rows(_profile(), 1, 6)
    t = out["tables"][1]
    assert t["rows"] == 6
    assert {c["row"] for c in t["cells"]} == {0, 1, 2, 3, 4, 5}
    # 늘린 행은 마지막 본문 행(2)의 서식을 그대로 물려받는다
    grown = [c for c in t["cells"] if c["row"] == 5]
    assert len(grown) == 2 and all(c["used_border_fills"] == {"2": {}} for c in grown)
    # 열 너비는 서식 값 그대로여야 한다 — 이것이 "보기 좋게"의 절반이다
    assert t["col_widths_hwpunit"] == ["6126", "26485"]
    # 다른 표(제목 상자)는 건드리지 않는다
    assert out["tables"][0]["rows"] == 1


def test_fit_rows_shrinks_and_keeps_header_row():
    t = dp.fit_rows(_profile(), 1, 2)["tables"][1]
    assert t["rows"] == 2 and {c["row"] for c in t["cells"]} == {0, 1}


def test_fit_rows_ignores_unknown_table_and_bad_rows():
    assert dp.fit_rows(_profile(), 9, 5)["tables"][1]["rows"] == 3
    assert dp.fit_rows(_profile(), 1, 0)["tables"][1]["rows"] == 3


def test_body_rows_counts_last_table_only():
    text, _ = md.monitoring_markdown(
        {"committee": "의회운영위원회", "meeting_date": "2026-09-14"}, [],
        [{"member": "이자형", "question": "질의", "answer": "답변", "department": "인사과",
          "departments": ["인사과"]}], None)
    # 제목 표(1행)는 세지 않고 본표만 — 머리 행 + 본문 1행 = 2
    assert md.body_rows(text) == 2


def test_cover_fill_values_and_title():
    values, edits, title = md.cover_fill({"name": "문승호", "summary": "렌탈 현황", "request_text": "업체명·금액"})
    assert values == {"건명": "렌탈 현황", "내용": "업체명·금액"}
    assert edits == [{"blockIndex": 0, "newText": "【 문승호 의원 】"}]
    assert title == "[표지] 문승호 의원 요구자료(렌탈 현황)"


def test_form_bytes_reads_real_templates():
    # 서식이 이미지 안(app/data/forms)에 있어야 한다 — backend/data 는 컨테이너에 없다
    for kind in ("monitoring", "datareq_list", "datareq_cover"):
        raw = dp.form_bytes(kind)
        assert raw and raw[:2] == b"PK", kind
    assert dp.form_bytes("없는서식") is None
