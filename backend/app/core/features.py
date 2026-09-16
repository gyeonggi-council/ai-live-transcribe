"""기능 스위치 — "설정이 비면 그 기능은 꺼진다" 를 한 곳에서 판정한다 (2026-09-16)

다른 의회가 이 서비스를 띄우면 경기도의회 전용 외부 시스템(KMS·의정캘린더·의원명부 API·
의정포털 앱 QR 로그인)은 존재하지 않는다. 그 주소를 비워 두면 해당 기능만 조용히 꺼지고
**자막·검색·요약·화자·클립은 그대로 돈다.**

화면 표시(`/api/config`)와 실제 동작(각 루프)이 **같은 함수**를 읽는다 —
따로 판정하면 "켜져 있다고 나오는데 안 도는" 상태가 생긴다.
"""

from __future__ import annotations

from app.core.config import settings


def org_name() -> str:
    return settings.org_name or "의회"


def kms_base_url() -> str:
    return (settings.kms_base_url or "").rstrip("/")


def kms_enabled() -> bool:
    """다시보기(VOD) 자동 등록·속기록·안건·클립의 원본 시스템."""
    return bool(kms_base_url())


def schedule_sync_enabled() -> bool:
    """의사일정(의정캘린더) 수집."""
    return bool(settings.council_calendar_url) and settings.assembly_schedule_sync_interval_minutes > 0


def roster_sync_enabled() -> bool:
    """의원 명부 동기화. 꺼지면 자막은 나오지만 화자 이름이 안 붙는다."""
    return bool(settings.councilor_api_base_url)


def qr_login_enabled() -> bool:
    """의정포털 앱 QR 로그인."""
    return bool(settings.ggc_login_base_url)


def onair_api_enabled() -> bool:
    """기관 생중계 상태 API(`ggc` 제공자)."""
    return bool(settings.council_onair_api_url)


def snapshot() -> dict:
    """공개 설정 응답과 관리자 화면이 함께 읽는 한 벌."""
    return {
        "org_name": org_name(),
        "features": {
            "kms": kms_enabled(),
            "schedule_sync": schedule_sync_enabled(),
            "roster_sync": roster_sync_enabled(),
            "qr_login": qr_login_enabled(),
            "onair_api": onair_api_enabled(),
        },
        "kms_base_url": kms_base_url(),
    }
