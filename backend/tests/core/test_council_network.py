# -*- coding: utf-8 -*-
"""의회망 판정 (2026-09-11) — 대역 표기 파서 · 접속 IP 를 어느 헤더에서 읽는가.

실제 대역 값은 저장소에 두지 않는다 — 여기 숫자는 문서용 예시 대역(TEST-NET, RFC 5737)이다.
"""

from starlette.requests import Request

from app.core.council_network import (
    client_ip,
    is_council_ip,
    is_login_required_ip,
    parse_ranges,
    parse_site_labels,
    site_label,
)

SPEC = "192.0.2.146-158, 198.51.100.102, 198.51.100.162, 203.0.113.0/30, 203.0.113.138-203.0.113.142"


def _req(headers: dict[str, str], host: str = "10.42.0.21") -> Request:
    return Request({
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (host, 12345),
    })


class TestParseRanges:
    def test_forms(self):
        r = parse_ranges(SPEC)
        assert len(r) == 5

    def test_last_octet_range_inclusive(self):
        assert is_council_ip("192.0.2.146", SPEC) and is_council_ip("192.0.2.158", SPEC)
        assert not is_council_ip("192.0.2.145", SPEC) and not is_council_ip("192.0.2.159", SPEC)

    def test_single_cidr_and_full_range(self):
        assert is_council_ip("198.51.100.102", SPEC) and not is_council_ip("198.51.100.103", SPEC)
        assert is_council_ip("203.0.113.3", SPEC) and not is_council_ip("203.0.113.4", SPEC)
        assert is_council_ip("203.0.113.140", SPEC) and not is_council_ip("203.0.113.137", SPEC)

    def test_bad_items_are_skipped_not_fatal(self):
        assert parse_ranges("nope, 1.2.3.4-2, 1.2.3.300, 192.0.2.1") == [(3221225985, 3221225985)]

    def test_empty_spec_means_nobody(self):
        assert not is_council_ip("192.0.2.150", "")
        assert not is_council_ip("", SPEC) and not is_council_ip("not-an-ip", SPEC)


class TestClientIp:
    def test_x_real_ip_wins(self):
        """Traefik 이 덮어쓰는 값 — 방문자가 보낸 XFF 첫 항목보다 우선한다."""
        assert client_ip(_req({"X-Real-IP": "198.51.100.7", "X-Forwarded-For": "192.0.2.150, 198.51.100.7"})) == "198.51.100.7"

    def test_xff_last_not_first(self):
        """XFF 첫 항목은 방문자가 쓸 수 있는 자리다(옛 ai.py 방식의 구멍)."""
        assert client_ip(_req({"X-Forwarded-For": "192.0.2.150, 198.51.100.7"})) == "198.51.100.7"

    def test_socket_fallback(self):
        assert client_ip(_req({})) == "10.42.0.21"


LABELS = "무선인터넷=192.0.2.146-158; 의회사무처(직원)=198.51.100.102,198.51.100.162; 의원=203.0.113.130-134,203.0.113.138-142"


class TestSiteLabel:
    """접속 통계의 접속처 이름표(2026-09-16) — IP 대신 이 이름만 저장한다."""

    def test_each_group(self):
        assert site_label("192.0.2.150", LABELS) == "무선인터넷"
        assert site_label("198.51.100.162", LABELS) == "의회사무처(직원)"
        assert site_label("203.0.113.133", LABELS) == "의원"
        assert site_label("203.0.113.140", LABELS) == "의원"   # 한 이름에 대역 둘

    def test_unknown_is_outside(self):
        assert site_label("8.8.8.8", LABELS) == "외부"
        assert site_label("203.0.113.136", LABELS) == "외부"   # 두 대역 사이 구멍

    def test_empty_or_broken_spec_is_outside(self):
        assert site_label("192.0.2.150", "") == "외부"
        assert site_label("", LABELS) == "외부"
        assert site_label("not-an-ip", LABELS) == "외부"
        assert parse_site_labels("이름표없음; =192.0.2.1; 빈대역=") == []

    def test_first_match_wins(self):
        spec = "먼저=192.0.2.0/24; 나중=192.0.2.150"
        assert site_label("192.0.2.150", spec) == "먼저"


class TestLoginRequired:
    """의회사무처 직원 PC 대역 — 막지 않고 앱 로그인을 요구한다(2026-09-16). 판정만 서버가 한다."""

    SPEC = "198.51.100.102, 198.51.100.162"

    def test_in_range(self):
        assert is_login_required_ip("198.51.100.102", self.SPEC)
        assert is_login_required_ip("198.51.100.162", self.SPEC)

    def test_out_of_range(self):
        assert not is_login_required_ip("198.51.100.103", self.SPEC)
        assert not is_login_required_ip("192.0.2.150", self.SPEC)

    def test_empty_spec_asks_nobody(self):
        assert not is_login_required_ip("198.51.100.102", "")
        assert not is_login_required_ip("", self.SPEC)
