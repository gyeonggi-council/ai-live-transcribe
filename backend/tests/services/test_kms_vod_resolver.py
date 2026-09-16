"""kms_vod_resolver 유닛 테스트."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.kms_vod_resolver import (
    VodNotConvertedError,
    normalize_vod_download_url,
    resolve_kms_vod_metadata,
)

KMS_VIEWER_URL = "https://kms.ggc.go.kr/caster/player/vodViewer.do?midx=138194"


def test_normalize_hls_definst_to_direct_mp4():
    """KMS HLS(_definst_/.../X.mp4/playlist.m3u8) → 직접 MP4(/mp4//...X.mp4)."""
    hls = (
        "https://kms.ggc.go.kr/vod/_definst_//mp4media2/gyoyukgihoek/"
        "20260422_gyoyukgihoek.mp4/playlist.m3u8"
    )
    assert normalize_vod_download_url(hls) == (
        "https://kms.ggc.go.kr/mp4//mp4media2/gyoyukgihoek/20260422_gyoyukgihoek.mp4"
    )


def test_normalize_hls_chunklist_variant():
    hls = (
        "https://kms.ggc.go.kr/vod/_definst_/mp4media2/bokji/20260422_bokji.mp4/chunklist.m3u8"
    )
    assert normalize_vod_download_url(hls) == (
        "https://kms.ggc.go.kr/mp4//mp4media2/bokji/20260422_bokji.mp4"
    )


def test_normalize_passthrough_direct_mp4_and_others():
    # 이미 직접 MP4면 그대로
    mp4 = "https://kms.ggc.go.kr/mp4//mp4media2/yegyeol/20260512_x.mp4"
    assert normalize_vod_download_url(mp4) == mp4
    # KMS HLS가 아닌 URL은 그대로
    other = "https://example.com/video.mp4"
    assert normalize_vod_download_url(other) == other
    assert normalize_vod_download_url("") == ""


@pytest.mark.asyncio
async def test_raises_vod_not_converted_when_page_has_title_but_no_mp4():
    """페이지에 vodtitle은 있는데 mp4file이 없으면 = 아직 변환 미완료."""
    # 방송 직후 KMS 페이지: 제목은 있으나 mp4file 변수 미생성
    html = (
        '<html><head></head><body><script>'
        'var vodtitle = "제392회 경기도의회 제1차 본회의 [2026.07.07]";'
        'var total_frame = 0*1000;'
        '</script></body></html>' + " " * 600  # len>=500 (에러페이지 오탐 방지)
    )
    with patch(
        "app.services.kms_vod_resolver._fetch_kms_page",
        new=AsyncMock(return_value=html),
    ):
        with pytest.raises(VodNotConvertedError):
            await resolve_kms_vod_metadata(KMS_VIEWER_URL)


@pytest.mark.asyncio
async def test_vod_not_converted_is_value_error_subclass():
    """기존 except ValueError 호출자 하위호환 — VodNotConvertedError ⊂ ValueError."""
    assert issubclass(VodNotConvertedError, ValueError)
