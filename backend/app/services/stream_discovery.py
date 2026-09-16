"""생중계 페이지 주소 → 채널 후보 자동 찾기 (2026-09-16)

다른 의회가 "우리 생중계 페이지는 여기입니다" 만 주면 영상 주소(m3u8)를 찾아 준다.

**실측으로 정한 한계** — 페이지에서 주소를 바로 꺼낼 수 있는 곳은 많지 않다.
방송이 꺼져 있으면 HTML 에 주소가 아예 없는 벤더가 대부분이다(서울시의회·대구시의회·
충남도의회·고양시의회·강북구의회·성남시의회에서 0건 확인, 2026-09-16).
반대로 경기도의회 페이지는 주소 규칙이 자바스크립트에 그대로 있다:

    function loadPlayerLive(ch, thid, ip) {
        var streamUrl = "https://" + ip + "/live/" + ch + "/playlist.m3u8";
    }

그래서 규칙 R2(문자열 결합 템플릿 환원)가 필요하다. 못 찾는 것이 정상적인 결과이며,
그때는 사용자에게 **무엇을 읽었는지**와 직접 입력 경로를 보여 준다.

이 모듈은 **관리자만** 부를 수 있고, 모든 외부 요청은 core/url_guard 를 통과한다.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from app.core.config import settings
from app.core.url_guard import UnsafeUrlError, safe_fetch

logger = logging.getLogger(__name__)

MAX_SCRIPTS = 5
MAX_SCRIPT_BYTES = 512 * 1024
MAX_CANDIDATES = 60
MAX_TEMPLATE_HOSTS = 4
MAX_TEMPLATE_SEGMENTS = 40
MAX_VERIFY = 8

_M3U8_RE = re.compile(r"""https?://[^\s"'<>\\)]+\.m3u8[^\s"'<>\\)]*""")
_SCRIPT_SRC_RE = re.compile(r"""<script[^>]+src=["']([^"']+)["']""", re.I)
_VIDEO_SRC_RE = re.compile(r"""<(?:video|source)[^>]+(?:src|data-src)=["']([^"']+)["']""", re.I)
_PLAYER_SRC_RE = re.compile(
    r"""(?:loadSource|setup\s*\(\s*\{[^}]*?\bfile)\s*[:(]\s*["']([^"']+)["']""", re.I
)
# 문자열 리터럴과 식별자가 `+` 로 이어진 자바스크립트 결합식
_CONCAT_RE = re.compile(
    r"""(?:(?:"[^"\n]*"|'[^'\n]*'|[A-Za-z_$][\w$.]*)\s*\+\s*)+(?:"[^"\n]*"|'[^'\n]*'|[A-Za-z_$][\w$.]*)"""
)
# 따옴표 종류마다 **따로** 훑는다. 하나의 정규식으로 `["']…["']` 를 쓰면
# onclick="loadPlayerLive('ch14','t1',…)" 전체가 큰따옴표 한 쌍으로 잡혀
# 정작 필요한 'ch14'·'stream01…' 이 통째로 묻힌다(실제로 그렇게 실패했다).
_DQ_LIT_RE = re.compile(r'"([^"\n]{1,200})"')
_SQ_LIT_RE = re.compile(r"'([^'\n]{1,200})'")
_HOSTLIKE_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}$", re.I)
_TOKENLIKE_RE = re.compile(r"^[A-Za-z]{1,6}[0-9]{1,4}$")


@dataclass
class ChannelCandidate:
    suggested_id: str
    name: str
    m3u8_url: str
    code: str = ""
    confidence: float = 0.5
    evidence: str = ""
    verified: bool | None = None       # None = 확인 안 함
    http_status: int | None = None


@dataclass
class DiscoveryResult:
    page_url: str
    vendor: str = "unknown"
    candidates: list[ChannelCandidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fetched: list[dict] = field(default_factory=list)   # 무엇을 읽었는지 — 사용자에게 근거로 보여 준다

    def to_dict(self) -> dict:
        return {
            "page_url": self.page_url,
            "vendor": self.vendor,
            "candidates": [c.__dict__ for c in self.candidates],
            "warnings": self.warnings,
            "fetched": self.fetched,
        }


def _registrable(host: str) -> str:
    """eTLD+1 근사 — `a.b.go.kr` 처럼 2단 접미사도 흔해 뒤 3조각까지 본다."""
    parts = (host or "").lower().split(".")
    if len(parts) <= 2:
        return host or ""
    if parts[-2] in {"go", "co", "or", "ne", "re", "pe", "ac"} and parts[-1] == "kr":
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _vendor_of(page_url: str, body: str) -> str:
    path = urlparse(page_url).path.lower()
    if "/onair/onair.do" in path:
        return "webpot"
    if "/cast/live" in path:
        return "cast-do"
    if "live_list.jsp" in path or "/live/" in path and path.endswith(".jsp"):
        return "jsp"
    if "wowza" in body.lower():
        return "wowza"
    return "unknown"


def _find_literal_m3u8(text: str, base: str) -> list[tuple[str, str]]:
    return [(m, "본문의 .m3u8 주소") for m in dict.fromkeys(_M3U8_RE.findall(text))]


def _find_player_src(text: str, base: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for rx, why in ((_VIDEO_SRC_RE, "<video> 태그"), (_PLAYER_SRC_RE, "플레이어 초기화")):
        for raw in rx.findall(text):
            if ".m3u8" in raw:
                out.append((urljoin(base, raw), why))
    return out


def _strip_js_comments(text: str) -> str:
    """자바스크립트 주석을 지운다 — 문자열 안의 `//` 는 건드리지 않는다.

    ★없으면 조용히 틀린다: 경기도의회 페이지에는 **주석 처리된 옛 주소**
      `//var streamUrl="http://<옛 IP>:1935/live/"+ch+"/playlist.m3u8";` 가 남아 있어,
      그대로 긁으면 지금 쓰지 않는 origin 으로 채널 후보 17개가 만들어진다(실측).
    """
    out: list[str] = []
    i, n = 0, len(text)
    quote = ""
    while i < n:
        c = text[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 2; continue
            if c == quote:
                quote = ""
            i += 1
            continue
        if c in "\"'`":
            quote = c; out.append(c); i += 1; continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        out.append(c); i += 1
    return "".join(out)


def _find_concat_templates(text: str) -> list[str]:
    """`"https://"+ip+"/live/"+ch+"/playlist.m3u8"` → `https://{0}/live/{1}/playlist.m3u8`"""
    templates: list[str] = []
    for expr in _CONCAT_RE.findall(_strip_js_comments(text)):
        parts = [p.strip() for p in expr.split("+")]
        literal = "".join(
            p[1:-1] for p in parts if len(p) >= 2 and p[0] in "\"'" and p[-1] == p[0]
        )
        if ".m3u8" not in literal:
            continue
        rebuilt: list[str] = []
        idx = 0
        for p in parts:
            if len(p) >= 2 and p[0] in "\"'" and p[-1] == p[0]:
                rebuilt.append(p[1:-1])
            else:
                rebuilt.append("{%d}" % idx)
                idx += 1
        tmpl = "".join(rebuilt)
        if "{0}" in tmpl and tmpl not in templates:
            templates.append(tmpl)
    return templates


def _expand_template(tmpl: str, text: str) -> list[tuple[str, str]]:
    """템플릿의 빈칸을 같은 문서의 문자열 리터럴로 채운다.

    `https://` 바로 뒤 칸은 호스트 후보로, 나머지는 경로 조각 후보(ch7 같은 토큰)로 본다.
    상한을 두는 이유: 상한이 없으면 리터럴 수백 개의 곱집합이 되어 수천 개 주소를 만든다.
    """
    literals = list(dict.fromkeys(
        _DQ_LIT_RE.findall(text) + _SQ_LIT_RE.findall(text)
    ))
    hosts = [s for s in literals if _HOSTLIKE_RE.match(s)][:MAX_TEMPLATE_HOSTS]
    tokens = [s for s in literals if _TOKENLIKE_RE.match(s)][:MAX_TEMPLATE_SEGMENTS]

    slots = sorted({int(m) for m in re.findall(r"\{(\d+)\}", tmpl)})
    if not slots:
        return []
    host_slot = slots[0] if re.search(r"https?://\{%d\}" % slots[0], tmpl) else None

    out: list[tuple[str, str]] = []
    host_values = hosts if host_slot is not None else [""]
    for host in host_values:
        token_slots = [s for s in slots if s != host_slot]
        if not token_slots:
            url = tmpl.replace("{%d}" % host_slot, host) if host_slot is not None else tmpl
            out.append((url, "자바스크립트 주소 규칙"))
            continue
        for token in tokens:
            url = tmpl
            if host_slot is not None:
                url = url.replace("{%d}" % host_slot, host)
            for s in token_slots:
                url = url.replace("{%d}" % s, token)
            if "{" not in url:
                out.append((url, f"자바스크립트 주소 규칙 ({token})"))
    return out


def _token_of(url: str) -> str:
    """주소에서 채널 토큰을 뽑는다 — `/live/ch7/playlist.m3u8` → `ch7`."""
    parts = [p for p in urlparse(url).path.split("/") if p]
    for p in reversed(parts):
        if _TOKENLIKE_RE.match(p):
            return p
    return parts[-2] if len(parts) >= 2 else (parts[0] if parts else "")


def _name_for_token(token: str, text: str) -> str:
    """토큰이 나오는 <a>/<option>/<li> 의 글자를 이름 후보로 쓴다."""
    if not token:
        return ""
    pattern = re.compile(
        r"""<(a|option|li|button)[^>]*%s[^>]*>\s*([^<>]{1,40}?)\s*</\1>""" % re.escape(token),
        re.I | re.S,
    )
    m = pattern.search(text)
    if m:
        name = re.sub(r"\s+", " ", m.group(2)).strip()
        # 숫자·기호만 있는 글자(전화번호 등)는 채널 이름이 아니다
        if name and re.search(r"[가-힣A-Za-z]", name) and not re.match(r"^[\d\s()\-.]+$", name):
            return name
    return ""


def _safe_id(token: str, used: set[str]) -> str:
    base = re.sub(r"[^A-Za-z0-9_-]", "", token)[:20] or "ch"
    candidate = base
    n = 2
    while candidate in used:
        suffix = str(n)
        candidate = base[: 20 - len(suffix)] + suffix
        n += 1
    used.add(candidate)
    return candidate


async def discover_channels(page_url: str) -> DiscoveryResult:
    """생중계 페이지에서 채널 후보를 찾는다. 못 찾아도 예외를 던지지 않는다."""
    result = DiscoveryResult(page_url=page_url)
    if not settings.discovery_enabled:
        result.warnings.append("자동 찾기가 꺼져 있습니다 (DISCOVERY_ENABLED=false)")
        return result

    try:
        page = await safe_fetch(
            page_url,
            max_bytes=settings.discovery_max_bytes,
            timeout=settings.discovery_timeout_seconds,
            allow_insecure_tls=True,
        )
    except UnsafeUrlError as exc:
        result.warnings.append(str(exc))
        return result
    except Exception as exc:                            # noqa: BLE001
        result.warnings.append(f"페이지를 읽지 못했습니다: {exc}")
        return result

    result.fetched.append({"url": page.url, "status": page.status_code, "bytes": len(page.text)})
    result.vendor = _vendor_of(page.url, page.text)
    if getattr(page, "insecure", False):
        result.warnings.append(
            "이 사이트의 보안 인증서를 확인할 수 없어 검증 없이 읽었습니다 "
            "(국내 의회 사이트에 흔한 인증서 체인 누락). 찾은 주소를 눈으로 확인한 뒤 등록하세요."
        )

    # R6 — 국회 웹캐스트는 전용 리졸버가 이미 있다
    if "assembly.webcast.go.kr" in urlparse(page.url).netloc:
        from app.services.assembly_stream_resolver import resolve_assembly_stream

        try:
            url = await resolve_assembly_stream(page.url)
            result.vendor = "assembly"
            result.candidates.append(
                ChannelCandidate("assembly", "국회 생중계", url, confidence=0.95,
                                 evidence="국회 웹캐스트 전용 해석기")
            )
            return result
        except Exception as exc:                        # noqa: BLE001
            result.warnings.append(f"국회 스트림 해석 실패: {exc}")

    documents: list[tuple[str, str]] = [(page.url, page.text)]

    # R3 — 같은 기관 도메인의 스크립트만 따라간다
    page_zone = _registrable(urlparse(page.url).hostname or "")
    script_urls: list[str] = []
    for raw in _SCRIPT_SRC_RE.findall(page.text):
        absolute = urljoin(page.url, raw)
        if _registrable(urlparse(absolute).hostname or "") != page_zone:
            continue
        if absolute not in script_urls:
            script_urls.append(absolute)
        if len(script_urls) >= MAX_SCRIPTS:
            break

    for url in script_urls:
        try:
            js = await safe_fetch(url, max_bytes=MAX_SCRIPT_BYTES,
                                  timeout=settings.discovery_timeout_seconds,
                                  allow_insecure_tls=True)
        except Exception as exc:                        # noqa: BLE001
            result.fetched.append({"url": url, "status": 0, "error": str(exc)})
            continue
        result.fetched.append({"url": js.url, "status": js.status_code, "bytes": len(js.text)})
        documents.append((js.url, js.text))

    # R1·R4·R2
    found: list[tuple[str, str, float]] = []
    for base, text in documents:
        for url, why in _find_literal_m3u8(text, base):
            found.append((url, why, 0.9))
        for url, why in _find_player_src(text, base):
            found.append((url, why, 0.6))
        for tmpl in _find_concat_templates(text):
            for url, why in _expand_template(tmpl, text):
                found.append((url, why, 0.7))

    seen: set[str] = set()
    used_ids: set[str] = set()
    for url, why, confidence in found:
        if url in seen or not url.startswith(("http://", "https://")):
            continue
        seen.add(url)
        token = _token_of(url)
        name = _name_for_token(token, page.text) or token or "채널"
        result.candidates.append(
            ChannelCandidate(
                suggested_id=_safe_id(token, used_ids),
                name=name,
                m3u8_url=url,
                confidence=confidence,
                evidence=why,
            )
        )
        if len(result.candidates) >= MAX_CANDIDATES:
            result.warnings.append(f"후보가 {MAX_CANDIDATES}개를 넘어 여기서 끊었습니다")
            break

    await _verify(result)
    # 재생목록이 확인된 것 → 신뢰도 높은 것 → https 순. 화면 맨 위가 고를 만한 것이어야 한다.
    result.candidates.sort(
        key=lambda c: (
            c.verified is not True,
            -c.confidence,
            not c.m3u8_url.startswith("https://"),
        )
    )

    if not result.candidates:
        result.warnings.append(
            "이 페이지에서 영상 주소를 찾지 못했습니다. "
            "대부분의 의회 생중계는 **방송 중일 때만** 영상 주소가 드러납니다 — "
            "회의 시간에 다시 시도하거나, 아래에 영상 주소(.m3u8)를 직접 붙여넣으세요."
        )
    return result


async def _verify(result: DiscoveryResult) -> None:
    """후보 앞부분을 실제로 받아 `#EXTM3U` 인지 본다.

    ★404·403 은 **탈락시키지 않는다.** 방송 전에는 살아 있는 주소도 404 를 준다(실측).
      등록은 되어야 하고, 화면에는 '응답 없음(방송 전일 수 있음)' 으로만 표시한다.
    """
    for candidate in result.candidates[:MAX_VERIFY]:
        try:
            res = await safe_fetch(candidate.m3u8_url, max_bytes=8192, timeout=3.0,
                                   allow_insecure_tls=True)
        except Exception:                               # noqa: BLE001
            candidate.verified = False
            continue
        candidate.http_status = res.status_code
        candidate.verified = res.text.lstrip().startswith("#EXTM3U")
        if candidate.verified:
            candidate.confidence = min(1.0, candidate.confidence + 0.2)
