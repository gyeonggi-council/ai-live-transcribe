"""HLS 플레이리스트 파서

m3u8 플레이리스트에서 TS 세그먼트 URL을 추출하고,
새로 추가된 세그먼트만 필터링합니다.

마스터 플레이리스트 (#EXT-X-STREAM-INF) 감지 시
첫 번째 미디어 플레이리스트로 자동 리다이렉트합니다.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import httpx

logger = logging.getLogger(__name__)

# 미디어 재생목록이 이만큼 연속 그대로면 마스터를 다시 읽는다. 폴링 1초 · 세그먼트 2초라
# 정상 방송에서는 같은 목록이 2~3번 이어질 뿐이고, 6번(≈6초)이면 스트림이 멈췄거나 청크리스트가 바뀐 것이다.
# 15 → 6 (2026-09-14): 영상 지연 목표를 13~18초로 내리면 시청자가 15초 정체 안에 재생목록 엣지에 닿아 스톨이 보인다.
STALE_POLLS_BEFORE_REFRESH = 6


class HlsPlaylistParser:
    """m3u8 플레이리스트를 파싱하여 세그먼트 URL을 추출합니다.

    - 마스터 플레이리스트 → 미디어 플레이리스트 자동 해석
    - 상대 경로 → 절대 URL 변환
    - 이미 처리한 세그먼트 추적 (중복 방지)
    """

    def __init__(self) -> None:
        self._seen_segments: set[str] = set()
        self._client = httpx.AsyncClient(timeout=10.0)
        self._media_playlist_url: str | None = None
        # 재생목록 깊이 계측 — 프런트 영상 지연 목표(liveSyncDuration)가 이 창보다
        # 깊으면 접속 직후 톱업 일시정지가 그 차이만큼 발동한다. 그 근거 숫자.
        self.target_duration: float | None = None
        self.segment_count: int = 0
        self.window_seconds: float | None = None
        self._window_logged = False
        # 마지막 파싱의 URL → (미디어 시퀀스, 길이초). 세그먼트 보관(링 버퍼)이 재생목록을
        # 다시 만들 때 필요한 두 값 — get_new_segments 의 반환값은 URL 뿐이라 여기서 찾는다.
        self.entries: dict[str, tuple[int, float]] = {}
        # 청크리스트 교체 감지 — 같은 미디어 재생목록이 연속 몇 번 "새 세그먼트 없음" 이었나.
        # Wowza 가 정회·재개 때 스트림을 다시 열면 마스터가 새 chunklist_w… 를 가리키는데 옛 청크리스트도
        # 200 으로 옛 내용을 계속 주므로 한 번 해석한 URL 만 읽으면 영원히 눈치를 못 챈다
        # (2026-09-14 운영위: 11:21 재개 뒤 26분간 자막·서버 재생목록이 멈췄다). 그래서 정체가 이어지면 마스터를 다시 읽는다.
        self._stale_polls = 0
        self._last_seq_seen: int | None = None

    async def fetch_segments(self, playlist_url: str) -> list[str]:
        """m3u8 URL을 다운로드하여 세그먼트 URL 목록을 반환합니다.

        마스터 플레이리스트인 경우 첫 번째 미디어 플레이리스트를 따라갑니다.
        미디어 재생목록이 STALE_POLLS_BEFORE_REFRESH 번 연속 그대로면(정체) 마스터를 다시 읽어
        청크리스트가 바뀌었는지 확인한다 — 바뀌었으면 새 URL 로 갈아탄다.
        """
        if self._media_playlist_url is not None and self._stale_polls >= STALE_POLLS_BEFORE_REFRESH:
            await self._refresh_media_playlist(playlist_url)

        # 이미 미디어 플레이리스트 URL을 알고 있으면 바로 사용
        url = self._media_playlist_url or playlist_url

        response = await self._client.get(url)
        response.raise_for_status()
        text = response.text

        # 마스터 플레이리스트 감지 (#EXT-X-STREAM-INF 존재)
        if "#EXT-X-STREAM-INF" in text and self._media_playlist_url is None:
            media_url = self._extract_media_playlist(text, url)
            if media_url:
                logger.info("Master playlist detected, using media: %s", media_url)
                self._media_playlist_url = media_url
                # 미디어 플레이리스트 다시 fetch
                response = await self._client.get(media_url)
                response.raise_for_status()
                text = response.text

        segments = self._parse_segments(text, self._media_playlist_url or playlist_url)
        self._track_progress(segments)
        return segments

    def _track_progress(self, segments: list[str]) -> None:
        """재생목록이 앞으로 가는지 본다 — 마지막 세그먼트의 미디어 시퀀스가 그대로면 정체 1회."""
        last_seq = self.entries[segments[-1]][0] if segments else None
        if last_seq is not None and last_seq == self._last_seq_seen:
            self._stale_polls += 1
        else:
            self._stale_polls = 0
        self._last_seq_seen = last_seq

    async def _refresh_media_playlist(self, playlist_url: str) -> None:
        """마스터를 다시 읽어 청크리스트가 바뀌었으면 갈아탄다. 마스터 조회 실패는 무시(다음 폴링에 재시도)."""
        self._stale_polls = 0
        try:
            response = await self._client.get(playlist_url)
            response.raise_for_status()
            text = response.text
        except Exception as e:  # noqa: BLE001 — 폴링 루프를 죽이지 않는다
            logger.debug("master playlist refresh failed (%s): %s", playlist_url, e)
            return
        if "#EXT-X-STREAM-INF" not in text:
            return
        media_url = self._extract_media_playlist(text, playlist_url)
        if media_url and media_url != self._media_playlist_url:
            logger.warning(
                "HLS chunklist rotated after %d stale polls: %s -> %s",
                STALE_POLLS_BEFORE_REFRESH, self._media_playlist_url, media_url,
            )
            self._media_playlist_url = media_url
            self._last_seq_seen = None

    def _extract_media_playlist(self, text: str, base_url: str) -> str | None:
        """마스터 플레이리스트에서 첫 번째 미디어 플레이리스트 URL을 추출합니다."""
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # 첫 번째 비주석 라인이 미디어 플레이리스트
            return urljoin(base_url, line)
        return None

    def _parse_segments(self, text: str, base_url: str) -> list[str]:
        """미디어 플레이리스트 텍스트에서 세그먼트 URL을 추출합니다."""
        segments: list[str] = []
        durations: list[float] = []
        entries: dict[str, tuple[int, float]] = {}
        target: float | None = None
        seq = 0
        last_dur = 0.0
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                if line.startswith("#EXT-X-TARGETDURATION:"):
                    try:
                        target = float(line.split(":", 1)[1])
                    except ValueError:
                        pass
                elif line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
                    try:
                        seq = int(line.split(":", 1)[1])
                    except ValueError:
                        pass
                elif line.startswith("#EXTINF:"):
                    try:
                        last_dur = float(line[8:].split(",", 1)[0])
                        durations.append(last_dur)
                    except ValueError:
                        pass
                continue
            # .ts 세그먼트만 필터링
            absolute_url = urljoin(base_url, line)
            segments.append(absolute_url)
            entries[absolute_url] = (seq, last_dur)
            seq += 1

        self.target_duration = target
        self.segment_count = len(segments)
        self.window_seconds = round(sum(durations), 1) if durations else None
        self.entries = entries
        if segments and not self._window_logged:
            self._window_logged = True
            logger.info(
                "HLS playlist window: target=%ss segments=%d window=%ss (%s)",
                target, len(segments), self.window_seconds, base_url,
            )
        return segments

    def get_new_segments(self, all_segments: list[str]) -> list[str]:
        """이전에 처리하지 않은 새 세그먼트만 반환합니다."""
        new_segments = [s for s in all_segments if s not in self._seen_segments]
        self._seen_segments.update(new_segments)
        return new_segments

    def reset(self) -> None:
        """추적 상태를 초기화합니다."""
        self._seen_segments.clear()
        self._media_playlist_url = None
        self.target_duration = None
        self.segment_count = 0
        self.window_seconds = None
        self._window_logged = False
        self.entries = {}
        self._stale_polls = 0
        self._last_seq_seen = None

    async def close(self) -> None:
        """HTTP 클라이언트를 종료합니다."""
        await self._client.aclose()


_ADTS_RATES = (96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000, 7350)


def _is_adts(es: bytes | bytearray, k: int) -> bool:
    return es[k] == 0xFF and (es[k + 1] & 0xF6) == 0xF0


def ts_audio_seconds(data: bytes) -> float | None:
    """MPEG-TS 세그먼트에 든 AAC(ADTS) 오디오 길이(초) = 프레임 수 × 1024 / 표본율.

    ffmpeg 가 이 세그먼트에서 디코딩해 내놓는 샘플 수와 같다. 재생목록 EXTINF 는 '2.0' 으로 반올림돼
    실제(1.95~2.04초)와 달라서, 이어 더하면 자막 시계와 영상 위치가 벌어진다 (2026-09-11 ch60 실측).
    세그먼트 경계에 걸친 프레임은 머리가 있는 쪽에서 센다. AAC/ADTS 가 아니면 None (호출자는 EXTINF).
    """
    pmt_pid = audio_pid = None
    es = bytearray()
    for i in range(0, len(data) - 187, 188):
        if data[i] != 0x47:
            continue
        pid = ((data[i + 1] & 0x1F) << 8) | data[i + 2]
        afc = (data[i + 3] >> 4) & 3
        p, end = i + 4, i + 188
        if afc & 2:
            p += 1 + data[p]
        if not afc & 1 or p >= end:
            continue
        pusi = data[i + 1] & 0x40
        if pid == audio_pid:
            if pusi:  # PES 머리: 00 00 01 sid len(2) flags(2) hdr_len(1)
                if data[p:p + 3] != b"\x00\x00\x01":
                    continue
                p += 9 + data[p + 8]
            es += data[p:end]
        elif pusi and audio_pid is None and (pid == 0 or pid == pmt_pid):
            s = p + 1 + data[p]  # pointer_field 뒤 섹션 머리
            sec_end = min(end, s + 3 + (((data[s + 1] & 0x0F) << 8) | data[s + 2]) - 4)  # CRC 제외
            if pid == 0:  # PAT → 첫 프로그램의 PMT PID
                for j in range(s + 8, sec_end - 3, 4):
                    if (data[j] << 8) | data[j + 1]:
                        pmt_pid = ((data[j + 2] & 0x1F) << 8) | data[j + 3]
                        break
            else:  # PMT → stream_type 0x0F(AAC ADTS) 의 PID
                j = s + 12 + (((data[s + 10] & 0x0F) << 8) | data[s + 11])
                while j + 5 <= sec_end:
                    if data[j] == 0x0F:
                        audio_pid = ((data[j + 1] & 0x1F) << 8) | data[j + 2]
                        break
                    j += 5 + (((data[j + 3] & 0x0F) << 8) | data[j + 4])
    samples, rate, k, n = 0, 0, 0, len(es)
    while k + 7 <= n:
        flen = ((es[k + 3] & 0x03) << 11) | (es[k + 4] << 3) | (es[k + 5] >> 5) if _is_adts(es, k) else 0
        # 앞 세그먼트에서 넘어온 프레임 꼬리 속 가짜 동기어를 피하려고 다음 머리까지 확인한다
        if flen < 7 or (k + flen + 2 <= n and not _is_adts(es, k + flen)):
            k += 1
            continue
        sf = (es[k + 2] >> 2) & 0x0F
        rate = _ADTS_RATES[sf] if sf < len(_ADTS_RATES) else 0
        samples += 1024 * ((es[k + 6] & 0x03) + 1)
        k += flen
    return samples / rate if samples and rate else None


# 재생목록 PDT 의 기준일 — PDT = 이 날짜 + 세그먼트 첫 음성의 자막 시계(초). 프런트 liveSync.ts
# HLS_CLOCK_EPOCH_MS 와 같은 값이어야 한다. 0(1970)은 hls.js 가 '없음' 으로 볼 수 있어 피했다.
HLS_CLOCK_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)


def _program_date_time(clock: float) -> str:
    return (HLS_CLOCK_EPOCH + timedelta(seconds=clock)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def render_playlist(entries: list[tuple], target_duration: float | None) -> str:
    """서버 보관 세그먼트로 '깊은' 미디어 재생목록을 만든다.

    entries: (seq, 길이초, 원본 URL[, 자막 시계]) — 자막 시계가 있으면 세그먼트마다 PDT 로 싣는다.
    브라우저는 hls.js `playingDate` 로 '지금 영상이 보여주는 자막 시계' 를 추정 없이 읽고, 그 시계가
    자막 start_time 에 닿는 순간 자막을 띄운다 (2026-09-11 — 예전엔 재생 지연 추정 + 고정 3초로 역산했다).

    원본 CDN 재생목록은 6초(2초×3개)뿐이라 브라우저가 20초 전에서 시작할 수 없고 부족분을
    일시정지로 벌었다(접속 직후 ≈14초 멈춤). 서버는 전사용으로 세그먼트를 이미 받고 있으니
    그 보관분(40초)을 재생목록으로 내주면 접속 즉시 20초 전에서 재생이 시작된다.

    URI 는 **전부** 상대경로 `{seq}.ts` 다. hls.js 는 재생목록을 다시 받을 때 같은 번호(sn)의
    URI 가 바뀌면 `media sequence mismatch` 로 재생목록을 거부한다 — "최신 몇 개는 CDN 절대 URL"
    로 섞었더니 세그먼트가 나이 들며 주소가 바뀌어 영상이 통째로 죽었다(2026-09-08 ch13 실측).
    "정상 재생 트래픽은 CDN 이 진다" 는 api/channels.py 의 `/hls/{seq}.ts` 가 최신 몇 개를
    CDN 으로 302 해서 지킨다.
    """
    lines = ["#EXTM3U", "#EXT-X-VERSION:3"]
    if not entries:
        return "\n".join(lines) + "\n"
    td = max(1, math.ceil(target_duration or max(e[1] for e in entries)))
    lines += [f"#EXT-X-TARGETDURATION:{td}", f"#EXT-X-MEDIA-SEQUENCE:{entries[0][0]}"]
    for seq, dur, _url, *clock in entries:
        if clock and clock[0] is not None:
            lines.append(f"#EXT-X-PROGRAM-DATE-TIME:{_program_date_time(clock[0])}")
        lines.append(f"#EXTINF:{dur:.3f},")
        lines.append(f"{seq}.ts")
    return "\n".join(lines) + "\n"
