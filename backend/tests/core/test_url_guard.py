"""SSRF 가드 (2026-09-16)

이 기능은 "관리자가 준 주소를 **서버가 대신** 받아오는" 것이라, 가드가 없으면
클러스터 내부를 훑는 도구가 된다(같은 망에 poc-db·PostgREST 브리지가 있다).
바깥 네트워크를 쓰지 않고 DNS 해석만 가로채 검사한다.
"""

import socket

import pytest

from app.core.url_guard import UnsafeUrlError, assert_safe_url


def _fake_dns(monkeypatch, ip: str):
    def getaddrinfo(host, port, *args, **kwargs):
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (ip, port))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


@pytest.mark.parametrize(
    "ip,why",
    [
        ("169.254.169.254", "클라우드 메타데이터"),
        ("127.0.0.1", "루프백"),
        ("10.0.12.6", "사설망(같은 망의 DB 서버)"),
        ("172.16.0.5", "사설망"),
        ("192.168.0.1", "사설망"),
        ("100.64.0.1", "CGNAT"),
        ("0.0.0.0", "unspecified"),
        ("::1", "IPv6 루프백"),
        ("::ffff:10.0.0.1", "IPv4-mapped 우회"),
        ("fd00::1", "IPv6 사설"),
    ],
)
def test_internal_addresses_are_rejected(monkeypatch, ip, why):
    _fake_dns(monkeypatch, ip)
    with pytest.raises(UnsafeUrlError):
        assert_safe_url("https://target.example/live")


def test_public_address_passes(monkeypatch):
    # ★203.0.113.x(문서용 TEST-NET)는 파이썬 3.12 에서 is_private 이라 여기 쓰면 안 된다.
    _fake_dns(monkeypatch, "93.184.216.34")
    assert assert_safe_url("https://council.example/live") == "https://council.example/live"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "gopher://target.example/",
        "ftp://target.example/",
        "data:text/html,<b>x</b>",
    ],
)
def test_non_http_schemes_are_rejected(url):
    with pytest.raises(UnsafeUrlError):
        assert_safe_url(url)


@pytest.mark.parametrize("port", [22, 5432, 6379, 8080, 1935, 9090])
def test_non_web_ports_are_rejected(monkeypatch, port):
    """내부 포트 스캐너로 쓰이지 않게 80·443 만 연다."""
    _fake_dns(monkeypatch, "93.184.216.34")
    with pytest.raises(UnsafeUrlError):
        assert_safe_url(f"https://target.example:{port}/x")


def test_userinfo_cannot_spoof_host(monkeypatch):
    """`https://safe.example@169.254.169.254/` 는 실제로 뒤쪽 호스트로 간다."""
    _fake_dns(monkeypatch, "169.254.169.254")
    with pytest.raises(UnsafeUrlError):
        assert_safe_url("https://safe.example@metadata.example/latest/meta-data/")


def test_unresolvable_host_is_rejected(monkeypatch):
    def boom(*a, **k):
        raise socket.gaierror("nope")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    with pytest.raises(UnsafeUrlError):
        assert_safe_url("https://does-not-exist.invalid/")
