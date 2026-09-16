"""의정포털 권한 → 자막 서비스 권한 매핑.

QR 로그인으로 계정이 자동 생성될 때 어떤 권한을 줄지 정하는 곳이다.

★상류 명세에 role 값이 열거돼 있지 않다.
  openapi.json 은 예시로 `ROLE_USER` 하나만 보여주고, 실계정에서 `ROLE_COUNCILOR` 를
  확인했다(2026-08-22). 그래서 **관측된 값만** 매핑하고 미상 값은 안전한 기본값으로
  떨어뜨리며 경고 로그를 남긴다. 로그에 새 값이 잡히면 그때 표에 추가한다 —
  있을 법한 이름을 짐작해서 채우지 않는다.

★`admin` 은 자동으로 주지 않는다.
  admin 은 AI 자막 생성(회의당 약 $0.4)과 VOD 일괄 등록을 실행할 수 있어, 자동
  부여하면 OpenAI 예산이 통제를 벗어난다. 승격은 관리자 화면이나
  `deploy/ncp/run-61-set-role-local.sh` 로 사람이 한다.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: 의정포털 role 원문 → 이 서비스 role. 관측된 값만 넣는다.
PORTAL_ROLE_MAP: dict[str, str] = {
    "ROLE_COUNCILOR": "staff",  # 의원 — 시청·검색
    "ROLE_USER": "staff",  # 일반 직원
}

#: 매핑에 없는 값이 왔을 때의 권한. 가장 낮은 실사용 권한이어야 한다.
DEFAULT_ROLE = "staff"

#: 자동 부여를 금지하는 권한 — 사람이 승격시켜야만 얻는다.
NEVER_AUTO_GRANTED = frozenset({"admin", "meeting_manager", "stenographer", "committee_staff"})


def map_portal_role(portal_role: str | None) -> str:
    """의정포털 권한 문자열을 이 서비스 권한으로 옮긴다.

    미상 값은 DEFAULT_ROLE 로 떨어뜨리고 경고를 남긴다 — 그 로그가 매핑표를
    넓히는 유일한 근거다.
    """
    key = (portal_role or "").strip()
    if not key:
        logger.warning("포털 권한이 비어 있다 — %s 로 처리한다", DEFAULT_ROLE)
        return DEFAULT_ROLE

    mapped = PORTAL_ROLE_MAP.get(key)
    if mapped is None:
        logger.warning(
            "매핑에 없는 포털 권한 %r — %s 로 처리한다. 실제로 쓰이는 값이면 "
            "app/services/portal_role.py 의 PORTAL_ROLE_MAP 에 추가할 것",
            key,
            DEFAULT_ROLE,
        )
        return DEFAULT_ROLE

    if mapped in NEVER_AUTO_GRANTED:
        # 매핑표에 실수로 높은 권한을 적어도 여기서 막힌다.
        logger.error(
            "포털 권한 %r 이 자동 부여 금지 권한 %r 로 매핑돼 있다 — %s 로 강등한다",
            key,
            mapped,
            DEFAULT_ROLE,
        )
        return DEFAULT_ROLE

    return mapped
