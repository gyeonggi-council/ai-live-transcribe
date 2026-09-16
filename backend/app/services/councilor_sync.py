"""의원정보 동기화 서비스

경기도의회 API에서 의원 정보를 가져와 councilors 테이블에 동기화합니다.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from supabase import Client

logger = logging.getLogger(__name__)


def _norm_committee(name: str) -> str:
    """위원회명 비교용 정규화 — 공백 제거.

    meeting.committee와 councilor.committees[].name의 공백 표기 흔들림
    (예: '도시환경위원회' vs '도시환경 위원회')으로 명부가 빈 채 반환되어 라이브·VOD
    이름교정이 조용히 no-op 되는 것을 완화한다(이름 자체가 다르면 여전히 매칭 안 됨 — 안전).
    """
    return re.sub(r"\s+", "", name or "")

# 경기도의회 의원 정보 API
GGC_API_URL = (
    "https://www.ggc.go.kr/site/main/api/portaltoggc/"
    "ggcmemrecinfoview/onclick/"
)

# API 키 (공개 API)
GGC_API_KEY = "ggcmemrecinfoview"


class CouncilorSyncService:
    """의원정보 동기화 서비스"""

    def __init__(self, supabase: Client) -> None:
        self._supabase = supabase

    async def sync_from_api(self) -> dict[str, int]:
        """경기도의회 API에서 의원 정보를 가져와 DB에 동기화합니다.

        Returns:
            동기화 결과 {added, updated, deactivated}
        """
        try:
            raw_members = await self._fetch_members()
        except Exception as e:
            logger.error("의원 정보 API 호출 실패: %s", e)
            raise

        if not raw_members:
            logger.warning("API에서 의원 정보를 가져오지 못했습니다.")
            return {"added": 0, "updated": 0, "deactivated": 0}

        result = {"added": 0, "updated": 0, "deactivated": 0}
        now = datetime.now(timezone.utc).isoformat()
        synced_mi_codes: list[str] = []

        for member in raw_members:
            mi_code = str(member.get("MI_CODE", "")).strip()
            if not mi_code:
                continue

            synced_mi_codes.append(mi_code)
            row = self._map_member_to_row(member, now)

            # mi_code로 기존 레코드 조회
            existing = (
                self._supabase.table("councilors")
                .select("id, mi_code")
                .eq("mi_code", mi_code)
                .execute()
            )

            if existing.data:
                # 기존 레코드 업데이트
                self._supabase.table("councilors").update(row).eq(
                    "mi_code", mi_code
                ).execute()
                result["updated"] += 1
            else:
                # 새 레코드 삽입
                self._supabase.table("councilors").insert(row).execute()
                result["added"] += 1

        # API 응답에 없는 의원은 비활성화
        if synced_mi_codes:
            try:
                all_active = (
                    self._supabase.table("councilors")
                    .select("id, mi_code")
                    .eq("is_active", True)
                    .not_.is_("mi_code", "null")
                    .execute()
                )
                for row in all_active.data or []:
                    if row["mi_code"] and row["mi_code"] not in synced_mi_codes:
                        self._supabase.table("councilors").update(
                            {"is_active": False}
                        ).eq("id", row["id"]).execute()
                        result["deactivated"] += 1
            except Exception as e:
                logger.warning("비활성화 처리 중 오류: %s", e)

        logger.info(
            "의원 동기화 완료: 추가 %d, 수정 %d, 비활성화 %d",
            result["added"],
            result["updated"],
            result["deactivated"],
        )
        return result

    async def _fetch_members(self) -> list[dict[str, Any]]:
        """경기도의회 API에서 의원 목록을 가져옵니다."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                GGC_API_URL,
                params={"key": GGC_API_KEY},
            )
            response.raise_for_status()
            data = response.json()

        # API 응답 구조에 따라 파싱
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # {"list": [...]} 또는 {"data": [...]} 등
            for key in ("list", "data", "items", "result"):
                if key in data and isinstance(data[key], list):
                    return data[key]
        return []

    def _map_member_to_row(
        self, member: dict[str, Any], synced_at: str
    ) -> dict[str, Any]:
        """API 응답 객체를 DB 행으로 매핑합니다."""
        mi_code = str(member.get("MI_CODE", "")).strip()
        name = str(member.get("MI_NAME", "")).strip()
        party = str(member.get("MI_PARTY", "")).strip() or None
        district = str(member.get("MI_DISTRICT", "")).strip() or None

        # 프로필 이미지
        photo = member.get("MI_PHOTO", "") or member.get("PHOTO_URL", "")
        profile_image_url = str(photo).strip() or None
        if profile_image_url and not profile_image_url.startswith("http"):
            profile_image_url = f"https://www.ggc.go.kr{profile_image_url}"

        # 위원회 정보
        committees = []
        committee_str = str(member.get("MI_COMMITTEE", "")).strip()
        if committee_str:
            for c in committee_str.split(","):
                c = c.strip()
                if c:
                    committees.append({"name": c, "role": "위원"})

        office_number = str(member.get("MI_OFFICE", "")).strip() or None
        term = member.get("MI_TERM")
        if term is not None:
            try:
                term = int(term)
            except (ValueError, TypeError):
                term = None

        # 추가 필드
        name_english = str(member.get("MI_NAME_ENG", "")).strip() or None
        name_chinese = str(member.get("MI_NAME_CHN", "")).strip() or None
        district_detail = str(member.get("MI_DISTRICT_DETAIL", "")).strip() or None
        email = str(member.get("MI_EMAIL", "")).strip() or None
        fax = str(member.get("MI_FAX", "")).strip() or None

        return {
            "mi_code": mi_code,
            "name": name,
            "party": party,
            "district": district,
            "term": term,
            "is_active": True,
            "profile_image_url": profile_image_url,
            "committees": committees,
            "office_number": office_number,
            "synced_at": synced_at,
            "name_english": name_english,
            "name_chinese": name_chinese,
            "district_detail": district_detail,
            "email": email,
            "fax": fax,
        }

    def get_all_active(self) -> list[dict[str, Any]]:
        """현역 의원 목록을 조회합니다."""
        result = (
            self._supabase.table("councilors")
            .select("*")
            .eq("is_active", True)
            .order("name")
            .execute()
        )
        return result.data or []

    def get_by_committee(self, committee: str) -> list[dict[str, Any]]:
        """위원회별 의원 목록을 조회합니다.

        committees는 JSONB 배열([{"name": ...}, ...])이다. postgrest-py의
        .contains()에 list[dict]를 넘기면 PG 배열 리터럴을 만들려고 ','.join()을
        호출하다 'expected str instance, dict found'로 터진다(조용히 삼켜져 명부가
        빈 채로 폴백 → C-2/실명식별/글로서리가 통째로 no-op). 활성 의원은 소수라
        Python에서 포함 필터링하는 게 클라이언트 버전에 무관하게 안전하다.
        """
        if not committee:
            return []
        target = _norm_committee(committee)
        rows = (
            self._supabase.table("councilors")
            .select("*")
            .eq("is_active", True)
            .order("name")
            .execute()
            .data
            or []
        )

        def _in_committee(c: dict[str, Any]) -> bool:
            raw = c.get("committees")
            if not isinstance(raw, list):
                return False
            for item in raw:
                name = (
                    item.get("name") if isinstance(item, dict)
                    else item if isinstance(item, str)
                    else None
                )
                if name and _norm_committee(name) == target:
                    return True
            return False

        matched = [c for c in rows if _in_committee(c)]
        if not matched:
            # 회의는 위원회명을 갖는데 명부 0명 → 표기 불일치/미등록 가능. silent no-op 관측용.
            logger.debug("get_by_committee: '%s' 명부 0명 (위원회명 불일치 가능)", committee)
        return matched

    def search(self, query: str) -> list[dict[str, Any]]:
        """의원 이름/정당/지역구 검색"""
        result = (
            self._supabase.table("councilors")
            .select("*")
            .or_(
                f"name.ilike.%{query}%,"
                f"party.ilike.%{query}%,"
                f"district.ilike.%{query}%"
            )
            .order("name")
            .execute()
        )
        return result.data or []

    def get_by_id(self, councilor_id: str) -> dict[str, Any] | None:
        """의원 상세 조회"""
        result = (
            self._supabase.table("councilors")
            .select("*")
            .eq("id", councilor_id)
            .execute()
        )
        if result.data:
            return result.data[0]
        return None

    def get_by_names(self, names: list[str]) -> list[dict[str, Any]]:
        """이름 목록으로 의원 정보를 배치 조회합니다."""
        if not names:
            return []
        result = (
            self._supabase.table("councilors")
            .select("*")
            .in_("name", names)
            .execute()
        )
        return result.data or []

    def get_names_for_correction(self) -> list[str]:
        """AI 교정에 사용할 의원명 목록을 반환합니다."""
        result = (
            self._supabase.table("councilors")
            .select("name")
            .eq("is_active", True)
            .execute()
        )
        return [row["name"] for row in (result.data or []) if row.get("name")]

    def get_last_sync_time(self) -> str | None:
        """마지막 동기화 시각을 반환합니다."""
        result = (
            self._supabase.table("councilors")
            .select("synced_at")
            .not_.is_("synced_at", "null")
            .order("synced_at", desc=True)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0].get("synced_at")
        return None
