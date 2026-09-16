"""의회 서식(HWPX)에서 뽑은 **표 서식**을 우리가 만드는 표에 맞춰 입히는 곳 (2026-09-16).

담당자 신고: "문서를 보기 좋게. 지금은 전혀 그렇게 안 나온다."
마크다운만 보내면 표가 kordoc 기본 서식(단일 실선·기본 열 너비·음영 없음)으로 나온다.
kordoc 에는 원본 HWPX 에서 표의 테두리·음영·열 너비·셀 글꼴만 뽑는 `hwpxToProfile` 이 있어
(우리 쪽 통로는 `doc_engine.extract_profile`) 그 프로필을 생성 요청에 함께 주면 같은 모양이 된다.

**그대로는 안 붙는다** — kordoc 의 매칭 규칙이 까다롭다(`gen-profile.ts` takeProfile 실측):

1. 프로필의 `rows`·`cols` 가 만드는 표와 **정확히** 같아야 한다. 서식의 본표는 빈 줄까지 9행인데
   우리 표의 행 수는 회의마다 다르다 → `fit_rows` 로 행 수를 맞춘다(마지막 본문 행의 서식을 복제).
2. 프로필에 `anchor_text` 가 있으면 **첫 셀 글자까지** 같아야 한다. 우리 제목에는 그 회의의 날짜가
   들어가 서식과 다르다 → `strip_anchors` 로 앵커를 지워 등장 순번(table_index) 매칭으로 떨어뜨린다.

프로필을 못 얻으면 `None` 을 돌려주고 **프로필 없이 생성**한다 — 모양은 예전과 같지만 문서는 나온다.
"""
from __future__ import annotations

import copy
import hashlib
import logging
from pathlib import Path
from typing import Any

from app.services.doc_engine import DocEngineError, extract_profile

logger = logging.getLogger(__name__)

# ⚠ backend/data 가 아니라 backend/app/data — Dockerfile 이 app/ 과 migrations/ 만 복사한다.
FORMS_DIR = Path(__file__).resolve().parent.parent / "data" / "forms"

FORM_FILES = {
    "monitoring": "monitoring.hwpx",        # [서식1] 운영위 모니터링(업무보고)
    "datareq_list": "datareq_list.hwpx",    # [서식2] 운영위 자료요구 목록
    "datareq_cover": "datareq_cover.hwpx",  # [서식3] 운영위 의원 요구자료(표지)
}

# 파일 해시 → 프로필. 서식은 배포 사이에 안 바뀌므로 프로세스 수명 캐시로 충분하다.
_cache: dict[str, dict[str, Any]] = {}


def form_bytes(kind: str) -> bytes | None:
    """서식 원본 바이트. 이미지에 파일이 없으면 None(문서 생성은 계속된다)."""
    name = FORM_FILES.get(kind)
    if not name:
        return None
    path = FORMS_DIR / name
    try:
        return path.read_bytes()
    except OSError:
        logger.warning("doc form missing: %s", path)
        return None


def strip_anchors(profile: dict[str, Any]) -> dict[str, Any]:
    """앵커(첫 셀 글자·첫 행 지문)를 지운다 — 남으면 글자가 다른 우리 표에 안 붙는다."""
    out = copy.deepcopy(profile)
    for table in out.get("tables") or []:
        table.pop("anchor_text", None)
        table.pop("anchor_row", None)
    return out


def fit_rows(profile: dict[str, Any], table_index: int, rows: int) -> dict[str, Any]:
    """한 표의 행 수를 실제 행 수로 맞춘다.

    남는 행은 버리고, 모자라는 행은 **마지막 본문 행의 셀 서식을 복제**해 채운다
    (서식의 본문 행은 전부 같은 모양이라 복제가 곧 재현이다).
    """
    if rows < 1:
        return profile
    out = copy.deepcopy(profile)
    for table in out.get("tables") or []:
        if int(table.get("table_index", -1)) != table_index:
            continue
        old = int(table.get("rows") or 0)
        cells = list(table.get("cells") or [])
        table["rows"] = rows
        if old == rows or old < 2 or not cells:
            continue
        last = max(int(c.get("row") or 0) for c in cells)
        template_row = [c for c in cells if int(c.get("row") or 0) == last]
        kept = [c for c in cells if int(c.get("row") or 0) < rows]
        for r in range(old, rows):
            for cell in template_row:
                clone = copy.deepcopy(cell)
                clone["row"] = r
                kept.append(clone)
        table["cells"] = kept
    return out


def _raw_profile(kind: str) -> dict[str, Any] | None:
    raw = form_bytes(kind)
    if not raw:
        return None
    key = hashlib.sha256(raw).hexdigest()
    if key in _cache:
        return _cache[key]
    try:
        profile = extract_profile(raw)
    except DocEngineError as e:
        logger.warning("doc profile extract failed (%s): %s", kind, e.detail)
        return None
    except Exception:  # noqa: BLE001 — 문서 만들기가 이것 때문에 죽으면 안 된다
        logger.warning("doc profile extract failed (%s)", kind, exc_info=True)
        return None
    _cache[key] = profile
    return profile


def profile_for(kind: str, *, body_rows: int) -> dict[str, Any] | None:
    """`kind` 서식의 표 서식을, 본표가 `body_rows` 행(머리 행 포함)일 때 쓸 모양으로 돌려준다.

    서식은 [제목표(1×1), 본표] 두 개다 — 제목표는 행 수가 1로 고정이고 본표만 맞춘다.
    """
    profile = _raw_profile(kind)
    if not profile:
        return None
    return fit_rows(strip_anchors(profile), 1, body_rows)


def clear_cache() -> None:
    """테스트용."""
    _cache.clear()
