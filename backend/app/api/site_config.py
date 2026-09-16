"""공개 설정 — 기관 이름과 켜져 있는 기능 (2026-09-16)

프런트가 "이 기관은 QR 로그인이 있나 / 다시보기가 있나" 를 알아야 버튼을 감출 수 있다.
503 을 보여 주는 대신 아예 안 보여 주는 쪽이 낫다.

비밀은 담지 않는다 — 주소와 불리언뿐이라 비로그인에게 열어도 된다.
"""

from fastapi import APIRouter

from app.core import features

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
async def get_site_config() -> dict:
    return features.snapshot()
