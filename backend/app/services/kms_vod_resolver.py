"""KMS VOD URL → MP4 직접 재생 URL 변환 및 메타데이터 추출 서비스

경기도의회 KMS(kms.ggc.go.kr) VOD 뷰어 페이지에서
직접 재생 가능한 MP4 URL과 메타데이터(제목, 날짜, 영상 길이)를 추출합니다.

사용자 URL 예시:
  https://kms.ggc.go.kr/caster/player/vodViewer.do?midx=137982

페이지 내 JS에서 추출:
  var mp4file = "/mp4media2/gihoek/20251222_gihoek.mp4";
  var vodtitle = "제389회 경기도의회 제1차 본회의 [2025.01.08]";
  var total_frame = 3600*1000;
"""

import re
import logging
from datetime import date
from urllib.parse import urlparse

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class VodNotConvertedError(ValueError):
    """KMS가 아직 이 영상을 MP4로 변환하지 않은 상태(방송 직후 수 시간 지연).

    ValueError 하위이므로 기존에 `except ValueError`/`except Exception`로
    잡던 호출자는 그대로 동작한다. 일괄 등록기는 이 예외만 따로 잡아
    '영상 변환 전이라도 회기·제목을 먼저 등록'하는 데 쓴다.
    """


# 기관 영상관리시스템 주소. 기본값은 경기도의회 KMS 라 동작이 바뀌지 않는다.
# 다른 기관은 KMS_BASE_URL 로 바꾸고, 그 시스템이 없으면 비운다(관련 기능이 통째로 꺼진다).
KMS_HOST = settings.kms_base_url.rstrip("/")
KMS_VOD_VIEWER_PATTERN = f"{urlparse(KMS_HOST).hostname or ''}/caster/player/vodViewer.do"

# ★2026-07-21 경기도 보안정책 변경: 특정 비브라우저 UA(curl 등)의 KMS 요청이
#   차단 페이지(text/html)로 대체되고, mp4 직접 전송은 연결당 ~300KB/s로
#   쉐이핑된다. 서버측 KMS 요청은 이 브라우저형 헤더를 표준으로 사용할 것.
#   (대용량 다운로드는 parallel_download 16-병렬로 쉐이핑 회피,
#    브라우저 재생은 프론트 Mp4Player가 HLS로 자동 전환)
KMS_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": f"{KMS_HOST}/",
}
# Anonymous VOD 등록 허용 도메인 (경기도의회 공식 KMS 호스트만)
ALLOWED_VOD_HOSTS = frozenset({urlparse(KMS_HOST).hostname or ""})
ALLOWED_VOD_SCHEMES = frozenset({"https"})
MP4FILE_REGEX = re.compile(r'var\s+mp4file\s*=\s*"([^"]+)"')
VODTITLE_REGEX = re.compile(r'var\s+vodtitle\s*=\s*"([^"]+)"')
TOTAL_FRAME_REGEX = re.compile(r'var\s+total_frame\s*=\s*(\d+)\s*\*\s*1000')
DATE_PATTERN_REGEX = re.compile(r'\[(\d{4})\.(\d{2})\.(\d{2})\]')


def is_kms_vod_url(url: str) -> bool:
    """KMS VOD 뷰어 URL인지 확인합니다."""
    return KMS_VOD_VIEWER_PATTERN in url


# KMS HLS 스트리밍 URL(_definst_/<...>.mp4/playlist.m3u8) 에서 .mp4 경로 추출
_KMS_HLS_DEFINST_RE = re.compile(r"_definst_/(.+?\.mp4)(?:/|$)")


def normalize_vod_download_url(url: str) -> str:
    """다운로드용 VOD URL을 직접 MP4 URL로 정규화합니다.

    KMS는 같은 영상을 (a) 직접 MP4(``/mp4//mp4media2/.../X.mp4``)와
    (b) HLS 재생목록(``/vod/_definst_//mp4media2/.../X.mp4/playlist.m3u8``)으로 모두 제공한다.
    동기화 경로 등에서 vod_url이 HLS(.m3u8)로 저장되면, 다운로더가 152바이트짜리 재생목록을
    받아 '파일이 너무 작다'며 실패한다. HLS URL이면 같은 경로의 직접 MP4 URL로 변환한다.

    HLS가 아니면(이미 직접 MP4거나 KMS가 아니면) 원본을 그대로 반환한다.
    """
    if not url:
        return url
    m = _KMS_HLS_DEFINST_RE.search(url)
    if not m:
        return url
    mp4_path = m.group(1)  # 예: "/mp4media2/.../X.mp4" 또는 "mp4media2/.../X.mp4"
    if not mp4_path.startswith("/"):
        mp4_path = "/" + mp4_path
    # 기존 직접 MP4와 동일 포맷(``/mp4/`` + 선행 슬래시 경로 → ``/mp4//mp4media2...``)
    return f"{KMS_HOST}/mp4/{mp4_path}"


def is_allowed_vod_source(url: str) -> bool:
    """익명 VOD 등록을 허용할 소스 URL인지 검증합니다.

    - 스킴은 https 고정 (http 거부)
    - 호스트는 ALLOWED_VOD_HOSTS 정확 일치 (urlparse.hostname 사용 →
      userinfo 주입 `https://evil@kms.ggc.go.kr/...` 형태 차단)
    - 경로는 체크하지 않음 (KMS 내부 어느 경로든 허용)
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in ALLOWED_VOD_SCHEMES:
        return False

    # hostname은 userinfo와 포트를 제외한 순수 호스트명만 반환합니다.
    # 예: "https://a@kms.ggc.go.kr:443/" -> hostname="kms.ggc.go.kr"
    host = (parsed.hostname or "").lower()
    return host in ALLOWED_VOD_HOSTS


def _title_from_url(url: str) -> str:
    """URL 경로에서 파일명 기반 제목을 생성합니다."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if path:
        filename = path.split("/")[-1]
        name = filename.rsplit(".", 1)[0] if "." in filename else filename
        return name
    return "VOD"


async def _fetch_kms_page(page_url: str) -> str:
    """KMS 페이지 HTML을 가져옵니다."""
    async with httpx.AsyncClient(timeout=10.0, headers=KMS_BROWSER_HEADERS) as client:
        response = await client.get(page_url)
        response.raise_for_status()
    return response.text


async def resolve_kms_vod_metadata(page_url: str) -> dict:
    """KMS VOD 뷰어 URL에서 메타데이터를 추출합니다.

    KMS URL이 아니면 URL 기반 최소 메타데이터를 반환합니다.

    Args:
        page_url: KMS vodViewer.do URL 또는 일반 URL

    Returns:
        dict: title, meeting_date (ISO), vod_url, duration_seconds

    Raises:
        ValueError: KMS 페이지에서 MP4 경로를 찾을 수 없을 때
    """
    if not is_kms_vod_url(page_url):
        return {
            "title": _title_from_url(page_url),
            "meeting_date": date.today().isoformat(),
            "vod_url": page_url,
            "duration_seconds": None,
        }

    html = await _fetch_kms_page(page_url)

    # MP4 URL (필수)
    mp4_match = MP4FILE_REGEX.search(html)
    if not mp4_match:
        # KMS 에러 페이지 감지 (EUC-KR 인코딩, 짧은 HTML, 접근 차단 메시지)
        if "charset=euc-kr" in html.lower() or len(html) < 500:
            raise ValueError(
                f"KMS 서버가 이 영상의 접근을 거부했습니다: {page_url}"
            )
        # 페이지는 정상(vodtitle 존재)인데 mp4file이 없으면 = 아직 VOD(MP4) 변환 미완료.
        # 방송 종료 직후에는 KMS가 라이브 DVR 스트림만 제공하고 endPos=0 상태로 둔다.
        if VODTITLE_REGEX.search(html):
            raise VodNotConvertedError(
                "이 영상은 아직 KMS에서 VOD(MP4) 변환이 완료되지 않았습니다(방송 직후에는 "
                f"몇 시간 걸릴 수 있음). 잠시 후 다시 시도해 주세요: {page_url}"
            )
        raise ValueError(
            f"KMS 페이지에서 MP4 파일 경로를 찾을 수 없습니다: {page_url}"
        )
    mp4file = mp4_match.group(1)
    vod_url = f"{KMS_HOST}/mp4/{mp4file}"

    # 제목 (선택)
    title = None
    title_match = VODTITLE_REGEX.search(html)
    if title_match:
        title = title_match.group(1)

    # 제목에서 날짜 추출 (선택)
    meeting_date = None
    if title:
        date_match = DATE_PATTERN_REGEX.search(title)
        if date_match:
            y, m, d = date_match.groups()
            meeting_date = f"{y}-{m}-{d}"

    # 영상 길이 (선택)
    duration_seconds = None
    duration_match = TOTAL_FRAME_REGEX.search(html)
    if duration_match:
        duration_seconds = int(duration_match.group(1))

    # 폴백
    if not title:
        title = _title_from_url(page_url)
    if not meeting_date:
        meeting_date = date.today().isoformat()

    logger.info(
        "KMS VOD metadata: %s -> title=%s, date=%s, url=%s, duration=%s",
        page_url, title, meeting_date, vod_url, duration_seconds,
    )
    return {
        "title": title,
        "meeting_date": meeting_date,
        "vod_url": vod_url,
        "duration_seconds": duration_seconds,
    }


async def resolve_kms_vod_url(page_url: str) -> str:
    """KMS VOD 뷰어 URL에서 직접 재생 가능한 MP4 URL을 추출합니다.

    KMS URL이 아니면 원본 URL을 그대로 반환합니다.
    내부적으로 resolve_kms_vod_metadata()를 호출합니다.

    Args:
        page_url: KMS vodViewer.do URL 또는 일반 URL

    Returns:
        직접 재생 가능한 MP4 URL

    Raises:
        ValueError: KMS 페이지에서 MP4 경로를 찾을 수 없을 때
    """
    metadata = await resolve_kms_vod_metadata(page_url)
    return metadata["vod_url"]
