"""의정포털 권한 매핑 테스트.

QR 자동 등록이 어떤 권한을 주는지가 곧 이 서비스의 접근통제다.
특히 admin 은 AI 자막 생성(회의당 약 $0.4)을 실행할 수 있어 자동 부여를 막아야 한다.
"""

import logging

from app.services.portal_role import (
    DEFAULT_ROLE,
    NEVER_AUTO_GRANTED,
    PORTAL_ROLE_MAP,
    map_portal_role,
)


class TestKnownRoles:
    def test_councilor_becomes_staff(self):
        """의원은 시청·검색만 — 자막 편집 권한이 아니다."""
        assert map_portal_role("ROLE_COUNCILOR") == "staff"

    def test_general_user_becomes_staff(self):
        assert map_portal_role("ROLE_USER") == "staff"

    def test_map_never_grants_privileged_roles(self):
        """매핑표에 실수로 높은 권한이 들어가는 것을 막는 구조 검사."""
        assert not set(PORTAL_ROLE_MAP.values()) & NEVER_AUTO_GRANTED


class TestUnknownRoles:
    def test_unmapped_role_falls_back(self, caplog):
        """상류 명세에 role 값이 열거돼 있지 않다 — 미상 값은 반드시 나온다."""
        with caplog.at_level(logging.WARNING):
            assert map_portal_role("ROLE_BRAND_NEW") == DEFAULT_ROLE
        assert "ROLE_BRAND_NEW" in caplog.text, "매핑표를 넓히려면 로그에 값이 남아야 한다"

    def test_empty_role_falls_back(self):
        assert map_portal_role("") == DEFAULT_ROLE
        assert map_portal_role(None) == DEFAULT_ROLE

    def test_whitespace_is_trimmed(self):
        assert map_portal_role("  ROLE_COUNCILOR  ") == "staff"


class TestPrivilegeGuard:
    def test_privileged_mapping_is_demoted(self, monkeypatch, caplog):
        """매핑표가 오염돼도 admin 이 자동 부여되지 않는다."""
        monkeypatch.setitem(PORTAL_ROLE_MAP, "ROLE_EVIL", "admin")
        with caplog.at_level(logging.ERROR):
            assert map_portal_role("ROLE_EVIL") == DEFAULT_ROLE
        assert "자동 부여 금지" in caplog.text
