# -*- coding: utf-8 -*-
"""의회망 판정 — 의회 건물 안 공인 IP 대역에서 온 비로그인 방문자에게 발언영상·AI 를 연다 (2026-09-11 담당자 요청).

대역 값은 **저장소에 두지 않는다**(poc-app 공인 IP 와 같은 원칙). 클러스터의 ConfigMap
`ggc-live-transcribe-council` 키 `COUNCIL_NETWORK_RANGES` → env → settings.council_network_ranges.
비어 있으면 아무도 의회망이 아니다(안전한 쪽으로 꺼진다).

표기: `192.0.2.146-158`(끝자리 범위) · `a.b.c.d-e.f.g.h` · CIDR `a.b.c.0/24` · 단일 주소. 쉼표로 잇는다.

접속 IP 의 전제 — Traefik 이 방문자 실제 주소를 넘긴다(인프라 `scripts/14-traefik-real-ip.yaml`, 2026-09-11 적용).
그 전에는 모든 요청이 `10.42.0.1`(klipper-lb MASQUERADE)로 보여 누구도 의회망으로 판정되지 않았다.
Traefik 은 방문자가 보낸 X-Forwarded-For·X-Real-IP 를 지우고 자기가 본 주소로 다시 쓴다
(위조 헤더로 실측 — 앱에는 실제 주소가 찍혔다). 그래서 X-Real-IP 를 먼저 믿고,
없으면 XFF 의 **마지막** 항목(가장 가까운 프록시가 붙인 값)을 쓴다. 첫 항목은 방문자가 쓸 수 있는 자리다.
"""

from __future__ import annotations

import ipaddress
import logging
from functools import lru_cache

from starlette.requests import HTTPConnection

from app.core.config import settings

logger = logging.getLogger(__name__)

Range = tuple[int, int]


def _v4(text: str) -> int:
    return int(ipaddress.IPv4Address(text.strip()))


def parse_ranges(spec: str) -> list[Range]:
    """'a.b.c.d-e, a.b.c.d/nn, a.b.c.d, a.b.c.d-e.f.g.h' → [(시작, 끝)] (정수, 양끝 포함). 틀린 항목은 버린다."""
    out: list[Range] = []
    for raw in (spec or "").split(","):
        item = raw.strip()
        if not item:
            continue
        try:
            if "/" in item:
                net = ipaddress.IPv4Network(item, strict=False)
                out.append((int(net.network_address), int(net.broadcast_address)))
            elif "-" in item:
                left, right = (p.strip() for p in item.split("-", 1))
                start = _v4(left)
                if "." in right:
                    end = _v4(right)
                else:                       # 끝자리만 쓴 범위: 192.0.2.146-158
                    last = int(right)
                    if not 0 <= last <= 255:
                        raise ValueError(item)
                    end = (start & 0xFFFFFF00) | last
                if end < start:
                    raise ValueError(item)
                out.append((start, end))
            else:
                ip = _v4(item)
                out.append((ip, ip))
        except ValueError:
            logger.warning("의회망 대역 표기를 읽지 못해 건너뜀: %r", item)
    return out


@lru_cache(maxsize=4)
def _ranges(spec: str) -> tuple[Range, ...]:
    return tuple(parse_ranges(spec))


def client_ip(conn: HTTPConnection) -> str:
    """방문자 IP — X-Real-IP → X-Forwarded-For 마지막 → 소켓 주소."""
    real = (conn.headers.get("x-real-ip") or "").strip()
    if real:
        return real
    xff = conn.headers.get("x-forwarded-for") or ""
    if xff.strip():
        return xff.split(",")[-1].strip()
    return conn.client.host if conn.client else ""


def is_council_ip(ip: str, spec: str | None = None) -> bool:
    ranges = _ranges(settings.council_network_ranges if spec is None else spec)
    if not ranges or not ip:
        return False
    try:
        n = _v4(ip)
    except ValueError:
        return False
    return any(a <= n <= b for a, b in ranges)


def is_council(conn: HTTPConnection) -> bool:
    return is_council_ip(client_ip(conn))


# ─── 로그인을 요구하는 대역 (2026-09-16 담당자 결정) ─────────────────────────
# 의회사무처 직원 PC 처럼 "그냥 보지 말고 모바일 의정지원서비스 앱으로 로그인해서 쓰라"고 할 곳.
# 2026-09-15 에는 Traefik 이 아예 막았는데(안내 화면 403), 막는 대신 **로그인 안내**로 바꾼 것이다.
# 값은 ConfigMap `ggc-live-transcribe-council` 의 키 LOGIN_REQUIRED_RANGES. 비면 아무에게도 요구하지 않는다.


def is_login_required_ip(ip: str, spec: str | None = None) -> bool:
    ranges = _ranges(settings.login_required_ranges if spec is None else spec)
    if not ranges or not ip:
        return False
    try:
        n = _v4(ip)
    except ValueError:
        return False
    return any(a <= n <= b for a, b in ranges)


def login_required(conn: HTTPConnection) -> bool:
    return is_login_required_ip(client_ip(conn))


# ─── 접속처 이름표 (접속 통계 전용, 2026-09-16 담당자 요청) ────────────────────
# 통계는 **IP 를 저장하지 않는다.** 요청이 들어온 순간 여기서 이름으로 바꾸고 이름만 남긴다.
# 값은 ConfigMap `ggc-live-transcribe-council` 의 키 COUNCIL_SITE_LABELS(대역과 같은 원칙 — 저장소에 두지 않는다).
# 표기: "무선인터넷=192.0.2.146-158; 사무처(직원)=198.51.100.102,198.51.100.162"
# 대역 표기는 COUNCIL_NETWORK_RANGES 와 같다(parse_ranges 재사용).

OUTSIDE_LABEL = "외부"


def parse_site_labels(spec: str) -> list[tuple[str, tuple[Range, ...]]]:
    """'이름=대역,대역; 이름=대역' → [(이름, ((시작,끝), …))]. 틀린 항목은 버린다(먼저 적은 이름이 이긴다)."""
    out: list[tuple[str, tuple[Range, ...]]] = []
    for raw in (spec or "").split(";"):
        item = raw.strip()
        if not item or "=" not in item:
            if item:
                logger.warning("접속처 이름표 표기를 읽지 못해 건너뜀: %r", item)
            continue
        label, _, ranges_spec = item.partition("=")
        label = label.strip()
        ranges = tuple(parse_ranges(ranges_spec))
        if not label or not ranges:
            logger.warning("접속처 이름표 표기를 읽지 못해 건너뜀: %r", item)
            continue
        out.append((label, ranges))
    return out


@lru_cache(maxsize=4)
def _site_labels(spec: str) -> tuple[tuple[str, tuple[Range, ...]], ...]:
    return tuple(parse_site_labels(spec))


def site_label(ip: str, spec: str | None = None) -> str:
    """IP → 접속처 이름. 등록된 대역이 없으면 '외부'."""
    labels = _site_labels(settings.council_site_labels if spec is None else spec)
    if not labels or not ip:
        return OUTSIDE_LABEL
    try:
        n = _v4(ip)
    except ValueError:
        return OUTSIDE_LABEL
    for label, ranges in labels:
        if any(a <= n <= b for a, b in ranges):
            return label
    return OUTSIDE_LABEL


def site_label_of(conn: HTTPConnection) -> str:
    return site_label(client_ip(conn))
