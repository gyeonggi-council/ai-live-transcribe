"""외부 URL 을 가져올 때의 안전 가드 (SSRF 방어) — 2026-09-16

생중계 페이지 자동 탐지가 "관리자가 준 주소를 서버가 대신 받아오는" 기능이라,
가드가 없으면 **클러스터 내부를 훑는 도구**가 된다. 이 파드와 같은 망에
poc-db(PostgreSQL)·PostgREST 브리지·다른 서비스의 내부 포트가 전부 있다.

여기서 막는 것:
  · 스킴          http/https 만 (file:·gopher:·ftp:·data: 거부)
  · 포트          80·443 만 (:22·:5432·:6379·:8080 거부 — 내부 포트 스캔 차단)
  · 목적지 IP     DNS 해석 뒤 **모든** A/AAAA 를 검사. 사설·루프백·링크로컬
                  (클라우드 메타데이터 169.254.169.254 포함)·CGNAT·멀티캐스트 거부
  · 리다이렉트    자동 추종 금지. 최대 3홉, **매 홉마다 전부 다시 검사**
  · 크기          기본 2MB 에서 끊는다(Content-Length 를 믿지 않고 실제로 센다)
  · 동시성        프로세스 전역 2개

한계(명시): 검사 직후 DNS 가 바뀌는 rebinding 까지는 막지 못한다. 완전 차단은
검사한 IP 로 직접 연결해야 하는데, 이 기능은 **관리자 전용**이라 거기까지 가지 않았다.
위협 모델이 바뀌면 이 문단부터 다시 읽을 것.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = ("http", "https")
ALLOWED_PORTS = (80, 443)
MAX_REDIRECTS = 3

_semaphore = asyncio.Semaphore(2)


class UnsafeUrlError(ValueError):
    """가드에 걸린 주소. 사용자에게 사유를 그대로 보여 준다."""


@dataclass
class FetchResult:
    url: str                 # 최종 도달한 주소
    status_code: int
    text: str
    content_type: str
    truncated: bool = False
    insecure: bool = False   # 인증서 검증 없이 받아왔다 — 호출자가 경고로 알려야 한다


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_private or ip.is_loopback or ip.is_link_local:
        return True          # 169.254.0.0/16 = 링크로컬 = 클라우드 메타데이터
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True
    if isinstance(ip, ipaddress.IPv4Address):
        if ip in ipaddress.ip_network("100.64.0.0/10"):   # CGNAT
            return True
    else:
        # ::ffff:10.0.0.1 같은 IPv4-mapped 우회를 편다
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None:
            return _is_blocked_ip(mapped)
        if ip.is_site_local:
            return True
    return False


def assert_safe_url(url: str) -> str:
    """스킴·포트·목적지 IP 를 검사하고 정규화한 주소를 돌려준다. 걸리면 UnsafeUrlError."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"http/https 주소만 됩니다 (받은 값: {scheme or '없음'})")

    # ★ netloc 이 아니라 hostname 을 쓴다 — `https://evil@real.example/` 같은
    #   userinfo 주입으로 호스트 검사를 속이는 수법을 막는다(kms_vod_resolver 와 같은 관행).
    host = parsed.hostname
    if not host:
        raise UnsafeUrlError("주소에 호스트가 없습니다")

    port = parsed.port or (443 if scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise UnsafeUrlError(f"80·443 포트만 됩니다 (받은 값: {port})")

    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"주소를 찾을 수 없습니다: {host}") from exc

    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            raise UnsafeUrlError(
                f"내부망 주소로는 접속하지 않습니다 ({host} → {addr})"
            )
    return url


async def safe_fetch(
    url: str,
    *,
    max_bytes: int = 2_000_000,
    timeout: float = 8.0,
    connect_timeout: float = 3.0,
    headers: dict | None = None,
    allow_insecure_tls: bool = False,
) -> FetchResult:
    """가드를 통과한 주소만 받아온다. 리다이렉트는 손으로 따라가며 매번 재검사한다.

    `allow_insecure_tls` — 인증서 검증에 실패하면 **한 번만** 검증 없이 다시 받는다.
    국내 의회 사이트에 중간 인증서 체인이 빠진 곳이 흔해서다(경기도의회 생중계 사이트
    실측, 2026-09-16). 켜고 받은 결과는 `insecure=True` 로 표시되고, 호출자는 반드시
    사용자에게 "이 사이트의 인증서를 확인할 수 없었다" 고 알려야 한다.
    """
    try:
        return await _fetch_once(
            url, max_bytes=max_bytes, timeout=timeout,
            connect_timeout=connect_timeout, headers=headers, verify=True,
        )
    except httpx.ConnectError as exc:
        if not (allow_insecure_tls and "CERTIFICATE_VERIFY_FAILED" in str(exc)):
            raise
        logger.warning("인증서 검증 실패 — 검증 없이 재시도한다: %s", url)
        result = await _fetch_once(
            url, max_bytes=max_bytes, timeout=timeout,
            connect_timeout=connect_timeout, headers=headers, verify=False,
        )
        result.insecure = True
        return result


async def _fetch_once(
    url: str,
    *,
    max_bytes: int,
    timeout: float,
    connect_timeout: float,
    headers: dict | None,
    verify: bool,
) -> FetchResult:
    current = assert_safe_url(url)
    limits = httpx.Timeout(timeout, connect=connect_timeout)

    async with _semaphore:
        async with httpx.AsyncClient(
            timeout=limits,
            verify=verify,
            follow_redirects=False,          # ★자동 추종을 켜면 302 한 번으로 내부망에 닿는다
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
                ),
                **(headers or {}),
            },
        ) as client:
            for _ in range(MAX_REDIRECTS + 1):
                async with client.stream("GET", current) as resp:
                    if resp.is_redirect:
                        location = resp.headers.get("location", "")
                        if not location:
                            raise UnsafeUrlError("리다이렉트 주소가 비어 있습니다")
                        current = assert_safe_url(str(httpx.URL(current).join(location)))
                        continue

                    chunks: list[bytes] = []
                    total = 0
                    truncated = False
                    async for chunk in resp.aiter_bytes():
                        chunks.append(chunk)
                        total += len(chunk)
                        if total >= max_bytes:
                            truncated = True
                            break
                    body = b"".join(chunks)
                    return FetchResult(
                        url=current,
                        status_code=resp.status_code,
                        text=body.decode("utf-8", "replace"),
                        content_type=resp.headers.get("content-type", ""),
                        truncated=truncated,
                    )

    raise UnsafeUrlError(f"리다이렉트가 {MAX_REDIRECTS}회를 넘었습니다")
