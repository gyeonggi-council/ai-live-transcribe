# -*- coding: utf-8 -*-
"""위원회 명부(이름+역할) 로더 — 단일 진실 소스.

신뢰원천 data/committee_rosters.json(GGC 스크레이프) 우선, 없으면 councilors
테이블(committees[].role) 폴백. VOD 텍스트 화자귀속(vod_stt_service)과 라이브
교정 화자 피기백(live_corrector)이 같은 명부를 보게 한다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _norm(x: str) -> str:
    return (x or "").replace(" ", "")


def load_committee_with_roles(supabase: Any, committee: str | None) -> list[dict]:
    """위원회 명부 [{name, role}] 반환. 위원회 미상/로드 실패 시 [] (fail-soft)."""
    if not committee:
        return []

    # 1) 신뢰원천 JSON (이름+직책)
    try:
        p = Path(__file__).resolve().parents[2] / "data" / "committee_rosters.json"
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            for cname, cinfo in data.items():
                if _norm(cname) == _norm(committee):
                    members = cinfo.get("members") or []
                    out = [
                        {"name": mm["name"], "role": mm.get("role") or "위원"}
                        for mm in members if mm.get("name")
                    ]
                    if out:
                        return out
    except Exception as e:
        logger.debug("committee_rosters.json 로드 스킵: %s", e)

    # 2) 폴백: councilors DB (committees[].role)
    try:
        from app.services.councilor_sync import CouncilorSyncService

        svc = CouncilorSyncService(supabase)
        rows = svc.get_by_committee(committee)
        out = []
        for r in rows:
            role = "위원"
            for c in (r.get("committees") or []):
                if isinstance(c, dict) and _norm(c.get("name")) == _norm(committee):
                    role = c.get("role") or "위원"
                    break
            if r.get("name"):
                out.append({"name": r["name"], "role": role})
        if not out:
            # 3) 본회의처럼 상임위 명부에 없는 회의 — 전체 활성 의원(역할 '의원').
            # glossary_service._committee_councilor_names 와 같은 규칙. 이게 없어서 393회 본회의
            # 라이브·VOD 화자 라벨이 의원 0건이었다(2026-09-08 실측: 2·3차 위원 일치율 0%).
            # 의장·부의장은 DB 에 역할이 없으므로 committee_rosters.json 의 "본회의" 항목(1 경로)이 맡는다.
            out = [{"name": r["name"], "role": "의원"} for r in svc.get_all_active() if r.get("name")]
        return out
    except Exception as e:
        logger.warning("위원회 명부(역할) 로드 실패: %s", e)
        return []
