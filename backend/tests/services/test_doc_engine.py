"""문서 엔진 호출의 **요청 모양**을 못 박는다 (2026-09-16).

지금까지 doc_engine 자체를 재는 테스트가 없어서, 필드 이름이 하나 틀려도 목킹된 테스트는 전부 초록이었다.
"""
from __future__ import annotations

import base64
from unittest.mock import patch

import pytest

from app.services import doc_engine as de


class _Resp:
    def __init__(self, status=200, content=b"PK\x03\x04", headers=None, payload=None):
        self.status_code = status
        self.content = content
        self.headers = headers or {}
        self._payload = payload

    def json(self):
        return self._payload


@patch.object(de.settings, "ggc_doc_internal_url", "http://doc:8100")
@patch.object(de.settings, "ggc_doc_token", "tok")
def test_generate_sends_profile_and_layout_only_when_given():
    with patch("app.services.doc_engine.httpx.post", return_value=_Resp()) as post:
        de.generate_hwpx("# x", title="t")
        body = post.call_args.kwargs["json"]
        assert body == {"markdown": "# x", "title": "t"}
        assert post.call_args.kwargs["headers"]["x-doc-token"] == "tok"

    with patch("app.services.doc_engine.httpx.post", return_value=_Resp()) as post:
        de.generate_hwpx("# x", title="t", preset="보도자료",
                         profile={"tables": []}, layout={"left": 20})
        body = post.call_args.kwargs["json"]
        assert body["preset"] == "보도자료" and body["profile"] == {"tables": []} and body["layout"] == {"left": 20}


@patch.object(de.settings, "ggc_doc_internal_url", "http://doc:8100")
def test_extract_profile_requires_tables():
    with patch("app.services.doc_engine.httpx.post",
               return_value=_Resp(payload={"ok": True, "profile": {"tables": [{"table_index": 0}]}})):
        assert de.extract_profile(b"PK")["tables"][0]["table_index"] == 0
    with patch("app.services.doc_engine.httpx.post", return_value=_Resp(payload={"ok": True})):
        with pytest.raises(de.DocEngineError):
            de.extract_profile(b"PK")


@patch.object(de.settings, "ggc_doc_internal_url", "http://doc:8100")
def test_fill_sends_base64_template():
    with patch("app.services.doc_engine.httpx.post", return_value=_Resp()) as post:
        de.fill_hwpx(b"PK\x03\x04hwpx", title="표지", values={"건명": "가"},
                     edits=[{"blockIndex": 0, "newText": "나"}])
        body = post.call_args.kwargs["json"]
        assert base64.b64decode(body["template"]) == b"PK\x03\x04hwpx"
        assert body["values"] == {"건명": "가"} and body["edits"][0]["blockIndex"] == 0


def test_missing_url_is_503_not_502():
    # 설정 없음(사람이 고칠 것)과 연결 실패(엔진 장애)는 다른 이야기다
    with patch.object(de.settings, "ggc_doc_internal_url", ""):
        for call in (lambda: de.generate_hwpx("x", title="t"),
                     lambda: de.extract_profile(b"PK"),
                     lambda: de.fill_hwpx(b"PK", title="t", values={"a": "b"})):
            with pytest.raises(de.DocEngineError) as e:
                call()
            assert e.value.status_code == 503
