"""문서 엔진(ggc_doc = kordoc)과 말을 섞는 **유일한** 곳 (2026-09-15 · 2026-09-16 확장).

서비스 공통 규칙: 서비스가 만드는 문서는 HWPX 가 기본이고, HWPX 는 ggc_doc 으로 만든다(경기천년체 강제·여백 20/20/0).
주소·토큰은 k8s env `GGC_DOC_INTERNAL_URL`·`GGC_DOC_TOKEN`(Secret ggc-doc-runtime/DOC_TOKEN). 비어 있으면 503.

통로가 셋이다 —
  generate_hwpx  마크다운(표·HTML 표 rowspan 포함) → HWPX. `profile` 을 함께 주면 원본 서식의 표
                 테두리·음영·열 너비가 재현된다.
  extract_profile 서식 HWPX → 표 서식 프로필(JSON). 서식은 우리가 보관하고, 엔진은 뽑아만 준다.
  fill_hwpx      서식 HWPX 파일 자체에 값만 채운다(요구자료 표지). **엔진이 글꼴·여백을 건드리지 않는다** —
                 원본 보존이 목적이기 때문이다.
"""
from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import settings


class DocEngineError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _base() -> str:
    url = (settings.ggc_doc_internal_url or "").strip().rstrip("/")
    if not url:
        raise DocEngineError(503, "문서 엔진이 설정되지 않았습니다(GGC_DOC_INTERNAL_URL)")
    return url


def _headers(content_type: str | None = None) -> dict[str, str]:
    h: dict[str, str] = {}
    if content_type:
        h["content-type"] = content_type
    if settings.ggc_doc_token:
        h["x-doc-token"] = settings.ggc_doc_token
    return h


def _post(path: str, *, timeout: float, **kw) -> httpx.Response:
    url = f"{_base()}{path}"   # 설정 없음(503)은 연결 실패(502)와 다른 이야기라 try 밖에서 먼저 낸다
    try:
        return httpx.post(url, timeout=timeout, **kw)
    except Exception as e:  # 연결 실패·시간 초과
        raise DocEngineError(502, f"문서 엔진에 닿지 않습니다({type(e).__name__})") from e


def _check(r: httpx.Response, what: str) -> None:
    if r.status_code == 413:
        raise DocEngineError(413, "문서가 너무 큽니다.")
    if r.status_code != 200:
        raise DocEngineError(502, f"문서 엔진 오류({what} HTTP {r.status_code})")


def _disposition(r: httpx.Response, title: str) -> str:
    return r.headers.get("content-disposition") or f"attachment; filename*=UTF-8''{quote(title + '.hwpx')}"


def generate_hwpx(
    markdown: str,
    *,
    title: str,
    preset: str | None = None,
    profile: dict[str, Any] | None = None,
    layout: dict[str, float] | None = None,
    timeout: float = 90.0,
) -> tuple[bytes, str]:
    """마크다운 → (HWPX 바이트, content-disposition).

    `profile` 은 `extract_profile` 로 뽑은 서식 프로필이다 — 표의 테두리·음영·열 너비를 그대로 입힌다.
    `layout` 을 주지 않으면 엔진 기본값(좌우 20 · 상하 20 · 머리말꼬리말 0)이 적용된다.
    """
    body: dict = {"markdown": markdown, "title": title}
    if preset:
        body["preset"] = preset
    if profile:
        body["profile"] = profile
    if layout:
        body["layout"] = layout
    r = _post("/generate", json=body, headers=_headers("application/json"), timeout=timeout)
    _check(r, "generate")
    return r.content, _disposition(r, title)


def extract_profile(template: bytes, *, timeout: float = 60.0) -> dict[str, Any]:
    """서식 HWPX → 표 서식 프로필. 실패하면 DocEngineError — 부르는 쪽이 프로필 없이 진행한다."""
    r = _post("/profile", content=template, headers=_headers("application/octet-stream"), timeout=timeout)
    _check(r, "profile")
    data = r.json()
    profile = data.get("profile") if isinstance(data, dict) else None
    if not isinstance(profile, dict) or not isinstance(profile.get("tables"), list):
        raise DocEngineError(502, "문서 엔진이 서식 프로필을 돌려주지 않았습니다.")
    return profile


def fill_hwpx(
    template: bytes,
    *,
    title: str,
    values: dict[str, Any] | None = None,
    edits: list[dict[str, Any]] | None = None,
    timeout: float = 90.0,
) -> tuple[bytes, str]:
    """서식 HWPX 파일에 값만 채운다 → (HWPX 바이트, content-disposition).

    values = 라벨-값 매칭 · edits = 블록·셀 좌표 지정. 둘 다 주면 좌표 먼저, 라벨이 나중이다.
    """
    if not values and not edits:
        raise DocEngineError(502, "채울 값이 없습니다.")
    body: dict = {"template": base64.b64encode(template).decode("ascii"), "title": title}
    if values:
        body["values"] = values
    if edits:
        body["edits"] = edits
    r = _post("/fill", json=body, headers=_headers("application/json"), timeout=timeout)
    _check(r, "fill")
    return r.content, _disposition(r, title)
