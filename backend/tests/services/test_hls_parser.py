"""HlsPlaylistParser — 재생목록 깊이 계측 (TARGETDURATION · 세그먼트 수 · 창 합계).

영상 지연 목표(프런트 liveSyncDuration)가 원본 재생목록 깊이보다 깊으면 접속 직후
톱업 일시정지가 발동한다. 그 근거 숫자를 서버가 재서 stt_status 로 내보낸다.
"""

import pytest

from app.services.hls_parser import HlsPlaylistParser

MEDIA = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:4
#EXT-X-MEDIA-SEQUENCE:100
#EXTINF:4.000,
seg100.ts
#EXTINF:3.960,
seg101.ts
#EXTINF:4.040,
seg102.ts
"""


def test_parse_segments_records_window_metrics():
    p = HlsPlaylistParser()
    segs = p._parse_segments(MEDIA, "https://cdn.example/live/ch14/playlist.m3u8")
    assert segs == [
        "https://cdn.example/live/ch14/seg100.ts",
        "https://cdn.example/live/ch14/seg101.ts",
        "https://cdn.example/live/ch14/seg102.ts",
    ]
    assert p.target_duration == 4.0
    assert p.segment_count == 3
    assert p.window_seconds == 12.0


def test_window_metrics_default_none_before_parse():
    p = HlsPlaylistParser()
    assert p.target_duration is None
    assert p.segment_count == 0
    assert p.window_seconds is None


def test_reset_clears_window_metrics():
    p = HlsPlaylistParser()
    p._parse_segments(MEDIA, "https://cdn.example/p.m3u8")
    p.reset()
    assert p.window_seconds is None
    assert p.segment_count == 0


# ─── 세그먼트 보관·깊은 재생목록 (2026-09-08 접속 멈춤 제거) ─────────────────

from app.services.hls_parser import render_playlist  # noqa: E402


def test_parse_segments_records_seq_and_duration_per_url():
    p = HlsPlaylistParser()
    p._parse_segments(MEDIA, "https://cdn.example/live/ch14/playlist.m3u8")
    assert p.entries["https://cdn.example/live/ch14/seg100.ts"] == (100, 4.0)
    assert p.entries["https://cdn.example/live/ch14/seg102.ts"] == (102, 4.04)


def test_render_playlist_uses_relative_uri_for_every_segment():
    entries = [
        (seq, 2.0, f"https://cdn.example/live/ch7/media_{seq}.ts") for seq in range(100, 110)
    ]
    text = render_playlist(entries, target_duration=10)
    lines = text.splitlines()
    assert lines[0] == "#EXTM3U"
    assert "#EXT-X-TARGETDURATION:10" in lines
    assert "#EXT-X-MEDIA-SEQUENCE:100" in lines
    uris = [ln for ln in lines if ln and not ln.startswith("#")]
    assert uris == [f"{s}.ts" for s in range(100, 110)]
    assert "cdn.example" not in text  # CDN 분산은 /hls/{seq}.ts 라우트의 302 가 한다
    assert lines.count("#EXTINF:2.000,") == 10
    assert not text.endswith("#EXT-X-ENDLIST")  # 라이브


def test_render_playlist_keeps_uri_stable_across_reloads():
    """hls.js 는 같은 sn 의 URI 가 재생목록 갱신 사이에 바뀌면 media sequence mismatch 로
    재생목록을 거부한다(2026-09-08 ch13 실측). 창이 3개 전진해도 같은 seq 는 같은 줄이어야 한다."""

    def uri_of(text: str) -> dict[int, str]:
        lines = text.splitlines()
        start = int(next(ln for ln in lines if ln.startswith("#EXT-X-MEDIA-SEQUENCE:")).split(":")[1])
        uris = [ln for ln in lines if ln and not ln.startswith("#")]
        return {start + i: u for i, u in enumerate(uris)}

    mk = lambda lo: [(s, 2.0, f"https://cdn.example/live/ch7/media_{s}.ts") for s in range(lo, lo + 20)]
    first, second = uri_of(render_playlist(mk(100), 10)), uri_of(render_playlist(mk(103), 10))
    for seq in set(first) & set(second):
        assert first[seq] == second[seq]


def test_render_playlist_target_duration_ceils_and_floors_at_1():
    text = render_playlist([(1, 2.5, "u")], target_duration=None)
    assert "#EXT-X-TARGETDURATION:3" in text


def test_render_playlist_writes_segment_clock_as_pdt():
    """세그먼트 첫 음성의 자막 시계를 PDT(2000-01-01 + 초)로 싣는다 — 프런트가 playingDate 로 읽는다."""
    text = render_playlist([(5, 2.0, "u", 12.5), (6, 2.0, "u", 14.52), (7, 2.0, "u", None)], 10)
    lines = text.splitlines()
    i = lines.index("#EXT-X-PROGRAM-DATE-TIME:2000-01-01T00:00:12.500Z")
    assert lines[i + 1:i + 3] == ["#EXTINF:2.000,", "5.ts"]  # 태그는 자기 세그먼트 바로 앞
    assert "#EXT-X-PROGRAM-DATE-TIME:2000-01-01T00:00:14.520Z" in lines
    assert text.count("PROGRAM-DATE-TIME") == 2  # 시계가 없는 세그먼트는 태그 없음


# ─── 세그먼트 실제 음성 길이 (EXTINF '2.0' 반올림 대신 AAC 프레임 수) ────────────

from app.services.hls_parser import ts_audio_seconds  # noqa: E402

AUDIO_PID = 0x101


def _ts_packets(pid: int, payload: bytes) -> bytes:
    """payload 를 188바이트 TS 패킷들로 (첫 패킷 PUSI, 마지막은 적응 필드로 채움)."""
    out = b""
    first = True
    while payload or first:
        body, payload = payload[:184], payload[184:]
        b1 = (0x40 if first else 0) | (pid >> 8)
        if len(body) == 184:
            out += bytes([0x47, b1, pid & 0xFF, 0x10]) + body
        else:
            stuff = 184 - len(body)
            af = bytes([stuff - 1]) + (b"\x00" + b"\xff" * (stuff - 2) if stuff >= 2 else b"")
            out += bytes([0x47, b1, pid & 0xFF, 0x30]) + af + body
        first = False
    return out


def _adts(sf_index: int = 4, payload: bytes = b"\x00" * 20) -> bytes:
    flen = 7 + len(payload)
    return bytes([
        0xFF, 0xF1, 0x40 | (sf_index << 2), 0x80 | ((flen >> 11) & 0x03),
        (flen >> 3) & 0xFF, ((flen & 0x07) << 5) | 0x1F, 0xFC,
    ]) + payload


def _segment(es: bytes) -> bytes:
    pat = b"\x00" + bytes([0x00, 0xB0, 13, 0x00, 0x01, 0xC1, 0x00, 0x00, 0x00, 0x01, 0xF0, 0x00]) + b"\x00" * 4
    pmt = b"\x00" + bytes([0x02, 0xB0, 18, 0x00, 0x01, 0xC1, 0x00, 0x00, 0xE1, 0x00, 0xF0, 0x00,
                           0x0F, 0xE0 | (AUDIO_PID >> 8), AUDIO_PID & 0xFF, 0xF0, 0x00]) + b"\x00" * 4
    pes = b"\x00\x00\x01\xC0" + len(es).to_bytes(2, "big") + b"\x80\x80\x05" + b"\x21\x00\x01\x00\x01" + es
    return _ts_packets(0, pat) + _ts_packets(0x1000, pmt) + _ts_packets(AUDIO_PID, pes)


def test_ts_audio_seconds_counts_aac_frames():
    """44.1kHz AAC 프레임 10개 = 10×1024/44100 초 (ch60 원본이 44.1kHz, 세그먼트당 84/87프레임)."""
    assert ts_audio_seconds(_segment(b"".join(_adts() for _ in range(10)))) == pytest.approx(10 * 1024 / 44100)


def test_ts_audio_seconds_counts_frame_split_across_segments_once():
    """세그먼트 경계에 걸친 프레임은 머리가 있는 쪽에서 한 번만 센다 — 이어 더해도 벌어지지 않는다."""
    frames = [_adts() for _ in range(16)]
    a = b"".join(frames[:10]) + frames[10][:15]
    b = frames[10][15:] + b"".join(frames[11:])
    total = ts_audio_seconds(_segment(a)) + ts_audio_seconds(_segment(b))
    assert total == pytest.approx(16 * 1024 / 44100)


def test_ts_audio_seconds_none_for_non_ts():
    assert ts_audio_seconds(b"not a transport stream") is None


# ── 청크리스트 교체 감지 (2026-09-14 운영위 정회·재개 뒤 26분 정체) ─────────────────
MASTER_A = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1219744\nchunklist_wA.m3u8\n"
MASTER_B = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1219744\nchunklist_wB.m3u8\n"
MEDIA_A = "#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:846\n#EXTINF:2.0,\n846.ts\n#EXTINF:2.0,\n847.ts\n"
MEDIA_B = "#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:1600\n#EXTINF:2.0,\n1600.ts\n#EXTINF:2.0,\n1601.ts\n"


class _FakeResp:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    """URL → 응답 본문. master 는 호출마다 바뀔 수 있다(list). 호출 URL 을 기록한다."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[str] = []

    async def get(self, url: str):
        self.calls.append(url)
        body = self.routes[url]
        if isinstance(body, list):
            return _FakeResp(body.pop(0) if len(body) > 1 else body[0])
        return _FakeResp(body)


@pytest.mark.asyncio
async def test_rotated_chunklist_is_picked_up_after_stale_polls():
    from app.services import hls_parser as hp

    master = "https://cdn/live/ch1/playlist.m3u8"
    client = _FakeClient(
        {
            master: [MASTER_A, MASTER_B],  # 첫 해석은 A, 그 뒤 재개로 B
            "https://cdn/live/ch1/chunklist_wA.m3u8": MEDIA_A,  # 옛 청크리스트 — 200 이지만 영원히 그대로
            "https://cdn/live/ch1/chunklist_wB.m3u8": MEDIA_B,
        }
    )
    p = HlsPlaylistParser()
    p._client = client
    first = await p.fetch_segments(master)
    assert first[-1].endswith("847.ts")
    # 정체 — 같은 목록이 STALE_POLLS_BEFORE_REFRESH 번 이어진다
    for _ in range(hp.STALE_POLLS_BEFORE_REFRESH):
        await p.fetch_segments(master)
    assert p._stale_polls == hp.STALE_POLLS_BEFORE_REFRESH
    assert client.calls.count(master) == 1  # 아직 마스터를 다시 안 읽었다
    # 다음 폴링에서 마스터를 다시 읽고 B 로 갈아탄다
    rotated = await p.fetch_segments(master)
    assert client.calls.count(master) == 2
    assert p._media_playlist_url.endswith("chunklist_wB.m3u8")
    assert rotated[-1].endswith("1601.ts")
    assert p.get_new_segments(rotated) == rotated  # 새 세그먼트로 인식된다


@pytest.mark.asyncio
async def test_progressing_playlist_never_refreshes_master():
    from app.services import hls_parser as hp

    master = "https://cdn/live/ch1/playlist.m3u8"
    medias = [
        f"#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:{n}\n#EXTINF:2.0,\n{n}.ts\n" for n in range(100, 100 + hp.STALE_POLLS_BEFORE_REFRESH * 2)
    ]
    client = _FakeClient({master: MASTER_A, "https://cdn/live/ch1/chunklist_wA.m3u8": medias})
    p = HlsPlaylistParser()
    p._client = client
    for _ in range(hp.STALE_POLLS_BEFORE_REFRESH * 2 - 1):
        await p.fetch_segments(master)
    assert client.calls.count(master) == 1
    assert p._stale_polls == 0


@pytest.mark.asyncio
async def test_same_chunklist_after_refresh_keeps_polling_quietly():
    from app.services import hls_parser as hp

    master = "https://cdn/live/ch1/playlist.m3u8"
    client = _FakeClient({master: MASTER_A, "https://cdn/live/ch1/chunklist_wA.m3u8": MEDIA_A})
    p = HlsPlaylistParser()
    p._client = client
    for _ in range(hp.STALE_POLLS_BEFORE_REFRESH + 2):
        await p.fetch_segments(master)
    # 스트림이 그냥 멈춘 경우(정회): 마스터를 다시 읽지만 URL 이 같으니 그대로, 카운터는 다시 센다
    assert client.calls.count(master) == 2
    assert p._media_playlist_url.endswith("chunklist_wA.m3u8")
