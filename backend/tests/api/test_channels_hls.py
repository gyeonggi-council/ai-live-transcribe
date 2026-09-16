"""채널 HLS 깊은 재생목록 라우트 — 접속 직후 '자막 동기화 준비 중' 멈춤 제거 (2026-09-08).

서버가 보관한 세그먼트가 원본 창보다 깊으면 깊은 재생목록을, 아니면 원본으로 302.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient


def _window(entries, origin_window=6.0):
    return (origin_window, 10.0, entries)


def test_playlist_redirects_to_origin_when_buffer_is_shallow(client: TestClient):
    with patch("app.api.channels.get_channel_stt_service") as svc:
        svc.return_value.get_hls_window.return_value = _window([(1, 2.0, "u")])
        res = client.get("/api/channels/ch14/hls/playlist.m3u8", follow_redirects=False)
    assert res.status_code == 302
    origin = "https://stream01.cdn.gov-ntruss.com/live/ch14/playlist.m3u8"
    assert res.headers["location"] == origin


def test_playlist_served_from_buffer_when_deep(client: TestClient):
    entries = [(s, 2.0, f"https://cdn/m_{s}.ts") for s in range(100, 120)]
    with patch("app.api.channels.get_channel_stt_service") as svc:
        svc.return_value.get_hls_window.return_value = _window(entries)
        res = client.get("/api/channels/ch14/hls/playlist.m3u8")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/vnd.apple.mpegurl")
    assert "#EXT-X-MEDIA-SEQUENCE:100" in res.text
    assert "\n100.ts\n" in res.text
    assert "\n119.ts\n" in res.text
    assert "https://cdn" not in res.text  # URI 는 전부 상대경로 (hls.js sn 별 URI 고정)


def test_playlist_carries_segment_clock_as_pdt(client: TestClient):
    """보관분에 자막 시계가 있으면 세그먼트마다 PDT 로 — 브라우저가 영상 위치를 자막 시계로 바로 읽는다."""
    entries = [(s, 2.0, f"https://cdn/m_{s}.ts", 1000.0 + 2 * (s - 100)) for s in range(100, 120)]
    with patch("app.api.channels.get_channel_stt_service") as svc:
        svc.return_value.get_hls_window.return_value = _window(entries)
        res = client.get("/api/channels/ch14/hls/playlist.m3u8")
    assert res.status_code == 200
    assert "#EXT-X-PROGRAM-DATE-TIME:2000-01-01T00:16:40.000Z\n#EXTINF:2.000,\n100.ts" in res.text


def test_segment_served_from_buffer_or_404(client: TestClient):
    with patch("app.api.channels.get_channel_stt_service") as svc:
        svc.return_value.get_hls_window.return_value = _window([])
        svc.return_value.get_hls_segment.side_effect = (
            lambda ch, seq: b"\x47ts" if seq == 100 else None
        )
        ok = client.get("/api/channels/ch14/hls/100.ts")
        missing = client.get("/api/channels/ch14/hls/101.ts")
    assert ok.status_code == 200 and ok.content == b"\x47ts"
    assert ok.headers["content-type"] == "video/MP2T"
    assert missing.status_code == 404


def test_newest_segments_redirect_to_cdn_and_older_come_from_buffer(client: TestClient):
    """재생목록 URI 는 전부 {seq}.ts 로 고정하고, 트래픽 분산은 여기서 302 로 한다."""
    entries = [(s, 2.0, f"https://cdn/m_{s}.ts") for s in range(100, 120)]
    with patch("app.api.channels.get_channel_stt_service") as svc:
        svc.return_value.get_hls_window.return_value = _window(entries)
        svc.return_value.get_hls_segment.side_effect = lambda ch, seq: b"\x47old"
        newest = client.get("/api/channels/ch14/hls/119.ts", follow_redirects=False)
        edge = client.get("/api/channels/ch14/hls/116.ts", follow_redirects=False)
        older = client.get("/api/channels/ch14/hls/115.ts", follow_redirects=False)
    assert newest.status_code == 302 and newest.headers["location"] == "https://cdn/m_119.ts"
    assert edge.status_code == 302 and edge.headers["location"] == "https://cdn/m_116.ts"
    assert older.status_code == 200 and older.content == b"\x47old"


def test_playlist_404_for_unknown_channel_or_empty_stream(client: TestClient):
    res = client.get("/api/channels/nope/hls/playlist.m3u8", follow_redirects=False)
    assert res.status_code == 404
    with patch("app.api.channels.get_channel_stt_service") as svc:
        svc.return_value.get_hls_window.return_value = (None, None, [])
        res = client.get("/api/channels/chT1/hls/playlist.m3u8", follow_redirects=False)
        assert res.status_code == 404
