"""OpenAI STT 스모크 테스트 — 실시간 전사(경로 A) + 화자 구분(경로 B) 실측 검증.

실제 한국어 회의 영상(기본: 국회 영상회의록 짧은 클립)에서 ffmpeg로 PCM을 추출해
- 경로 A: Realtime transcription WebSocket(gpt-realtime-whisper)에 스트리밍 → delta/completed 수신
- 경로 B: gpt-4o-transcribe-diarize 배치 → segments[].speaker(화자 구분) 수신
둘 다 실제 OpenAI API로 호출하여 조직 계정 접근 권한과 한국어 품질을 한 번에 확인한다.

사용법 (backend 디렉터리에서):
    python scripts/verify_openai_stt.py
    python scripts/verify_openai_stt.py <영상_URL> --seconds 30
    python scripts/verify_openai_stt.py --model gpt-4o-transcribe   # 실시간 모델 교체 테스트

필요: ffmpeg, OPENAI_API_KEY(.env), openai/websockets 패키지. (네트워크/요금 발생)
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import os
import subprocess
import sys
import time
import wave

# backend 패키지 import 가능하도록 경로 보정 (cwd 무관 — 이 파일 기준 backend 루트)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Windows 콘솔(cp949)에서 이모지/한글 출력 시 UnicodeEncodeError 방지
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

from app.core.config import settings  # noqa: E402

# 검증 완료된 테스트 영상 (국회 영상회의록, HTTP 200/CORS 확인). 짧은 발언 클립.
DEFAULT_URL = (
    "https://m.webcast.go.kr/vod/_definst_/FULL/2024/bokji/"
    "DKP332241704_01_202408280920.mp4/playlist.m3u8"
)
RATE = 24000  # OpenAI Realtime은 24kHz PCM16만 지원


def extract_pcm(url: str, seconds: int, offset: float = 0.0) -> bytes:
    """ffmpeg로 영상 URL에서 24kHz mono PCM16 raw를 추출한다 (HLS/MP4 모두 ffmpeg가 처리)."""
    print(f"[ffmpeg] {url} 에서 offset={offset}s, {seconds}초 추출 중...")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if offset and offset > 0:
        cmd += ["-ss", str(offset)]
    cmd += [
        "-i", url, "-t", str(seconds),
        "-vn", "-ac", "1", "-ar", str(RATE), "-f", "s16le", "pipe:1",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 실패: {proc.stderr.decode('utf-8', 'ignore')[:500]}")
    pcm = proc.stdout
    print(f"[ffmpeg] PCM {len(pcm):,} bytes (~{len(pcm) / (RATE * 2):.1f}s)")
    return pcm


def pcm_to_wav(pcm: bytes, rate: int = RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


# ─── 경로 B: 화자 구분 (배치) ────────────────────────────────────────────

def test_diarize(pcm: bytes) -> bool:
    from openai import OpenAI

    print("\n" + "=" * 60)
    print("[경로 B] gpt-4o-transcribe-diarize 배치 화자 구분 테스트")
    print("=" * 60)
    client = OpenAI(api_key=settings.openai_api_key)
    wav = pcm_to_wav(pcm)
    try:
        resp = client.audio.transcriptions.create(
            model=settings.diarize_model,
            file=("clip.wav", io.BytesIO(wav), "audio/wav"),
            response_format="diarized_json",
            chunking_strategy="auto",
            language="ko",
        )
    except Exception as e:
        print(f"  ❌ FAIL: {type(e).__name__}: {e}")
        return False

    segments = getattr(resp, "segments", None)
    if segments is None and isinstance(resp, dict):
        segments = resp.get("segments")
    if not segments:
        print(f"  ⚠️  세그먼트 없음. raw={resp}")
        return False

    speakers = set()
    for seg in segments:
        spk = getattr(seg, "speaker", None) or (seg.get("speaker") if isinstance(seg, dict) else None)
        text = getattr(seg, "text", None) or (seg.get("text") if isinstance(seg, dict) else "")
        start = getattr(seg, "start", None) or (seg.get("start") if isinstance(seg, dict) else 0)
        end = getattr(seg, "end", None) or (seg.get("end") if isinstance(seg, dict) else 0)
        speakers.add(spk)
        print(f"  [{spk}] {start:.1f}-{end:.1f}s  {text}")
    print(f"  ✅ PASS: {len(segments)} segments, 화자 {sorted(str(s) for s in speakers)}")
    return True


# ─── 실명 화자 식별 (known_speaker_references) ──────────────────────────

def test_known_speaker(pcm: bytes) -> bool:
    """첫 8초를 화자 참조로 등록해 diarize가 그 이름을 반환하는지 검증."""
    from openai import OpenAI

    print("\n" + "=" * 60)
    print("[실명 식별] known_speaker_references 테스트")
    print("=" * 60)
    client = OpenAI(api_key=settings.openai_api_key)

    ref_bytes = pcm[: RATE * 2 * 8]  # 첫 8초
    ref_wav = pcm_to_wav(ref_bytes)
    ref_url = "data:audio/wav;base64," + base64.b64encode(ref_wav).decode("ascii")
    full_wav = pcm_to_wav(pcm)
    try:
        resp = client.audio.transcriptions.create(
            model=settings.diarize_model,
            file=("clip.wav", io.BytesIO(full_wav), "audio/wav"),
            response_format="diarized_json",
            chunking_strategy="auto",
            language="ko",
            extra_body={
                "known_speaker_names": ["위원장"],
                "known_speaker_references": [ref_url],
            },
        )
    except Exception as e:
        print(f"  ❌ FAIL: {type(e).__name__}: {e}")
        return False

    segments = getattr(resp, "segments", None) or []
    speakers = set()
    for seg in segments:
        spk = getattr(seg, "speaker", None) or (seg.get("speaker") if isinstance(seg, dict) else None)
        text = getattr(seg, "text", None) or (seg.get("text") if isinstance(seg, dict) else "")
        speakers.add(spk)
        print(f"  [{spk}] {text}")
    matched = "위원장" in {str(s) for s in speakers}
    print(f"  {'✅ PASS' if matched else '⚠️ 참조 화자 미매칭'}: 화자={sorted(str(s) for s in speakers)}")
    return matched


# ─── cue 정규식 실측 (실제 자막에서 호명/집행부 단서 추출) ───────────────

def test_cue_scan(pcm: bytes) -> bool:
    """실제 회의 자막을 diarize로 받아 cue tracker 정규식이 무엇을 추출하는지 점검."""
    from openai import OpenAI
    from app.services.speaker_cue_tracker import (
        _MEMBER_RE, _OFFICIAL_RE, _SELFINTRO_RE, _TURN_CONTEXT,
    )

    print("\n" + "=" * 60)
    print("[cue 스캔] 실제 자막에서 호명/자기소개/집행부 단서 추출")
    print("=" * 60)
    client = OpenAI(api_key=settings.openai_api_key)
    wav = pcm_to_wav(pcm)
    try:
        resp = client.audio.transcriptions.create(
            model=settings.diarize_model, file=("c.wav", io.BytesIO(wav), "audio/wav"),
            response_format="diarized_json", chunking_strategy="auto", language="ko",
        )
    except Exception as e:
        print(f"  ❌ FAIL: {e}")
        return False
    segments = getattr(resp, "segments", None) or []
    members, officials, selfintros = [], [], []
    for seg in segments:
        txt = (getattr(seg, "text", None) or "").strip()
        if not txt:
            continue
        has_ctx = any(k in txt for k in _TURN_CONTEXT) or bool(_SELFINTRO_RE.search(txt))
        if has_ctx:
            members += _MEMBER_RE.findall(txt)
        selfintros += [m for m in _SELFINTRO_RE.findall(txt)]
        officials += [m[0] if isinstance(m, tuple) else m for m in _OFFICIAL_RE.findall(txt)]
        print(f"  · {txt[:80]}")
    print(f"  → 호명/위원 후보: {members}")
    print(f"  → 자기소개: {selfintros}")
    print(f"  → 집행부 직책: {officials}")
    return True


# ─── 경로 A: 실시간 전사 (WebSocket) ─────────────────────────────────────

async def test_realtime(pcm: bytes, model: str) -> bool:
    import websockets

    print("\n" + "=" * 60)
    print(f"[경로 A] Realtime transcription WS 테스트 (model={model})")
    print("=" * 60)

    url = settings.openai_realtime_ws_url
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}  # GA: OpenAI-Beta 없음

    finals: list[str] = []
    interims = 0
    got_session = False

    try:
        async with websockets.connect(url, additional_headers=headers, max_size=None) as ws:
            await ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "type": "transcription",
                    "audio": {"input": {
                        "format": {"type": "audio/pcm", "rate": RATE},
                        "transcription": {"model": model, "language": "ko"},
                        "turn_detection": None,
                    }},
                },
            }))

            async def receiver() -> None:
                nonlocal interims, got_session
                async for raw in ws:
                    ev = json.loads(raw)
                    t = ev.get("type", "")
                    if t == "session.updated":
                        got_session = True
                        print("  · session.updated (세션 수용됨)")
                    elif t == "conversation.item.input_audio_transcription.delta":
                        interims += 1
                    elif t == "conversation.item.input_audio_transcription.completed":
                        txt = (ev.get("transcript") or "").strip()
                        if txt:
                            finals.append(txt)
                            print(f"  · [final] {txt}")
                    elif t in ("error", "conversation.item.input_audio_transcription.failed"):
                        print(f"  ❌ 서버 에러: {json.dumps(ev.get('error', ev), ensure_ascii=False)[:300]}")

            recv_task = asyncio.create_task(receiver())

            # PCM을 0.2초 청크로 4배속 전송, ~3초마다 commit
            chunk = int(RATE * 2 * 0.2)
            sent = 0
            for i in range(0, len(pcm), chunk):
                await ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(pcm[i:i + chunk]).decode("ascii"),
                }))
                sent += 1
                if sent % 15 == 0:  # ~3초마다 commit
                    await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                await asyncio.sleep(0.05)
            await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))

            # 마지막 전사 수신 대기
            await asyncio.sleep(8.0)
            recv_task.cancel()
    except Exception as e:
        print(f"  ❌ FAIL: {type(e).__name__}: {e}")
        return False

    ok = len(finals) > 0
    print(f"  {'✅ PASS' if ok else '❌ FAIL'}: interim {interims}건, final {len(finals)}건"
          f"{', session.updated' if got_session else ''}")
    return ok


# ─── main ────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?", default=DEFAULT_URL)
    ap.add_argument("--seconds", type=int, default=30)
    ap.add_argument("--offset", type=float, default=0.0, help="소스 시작 오프셋(초)")
    ap.add_argument("--cue-scan", action="store_true", help="실제 자막에서 cue 정규식 추출 점검")
    ap.add_argument("--model", default=settings.openai_realtime_stt_model,
                    help="실시간 전사 모델 (기본: settings)")
    ap.add_argument("--skip-realtime", action="store_true")
    ap.add_argument("--skip-diarize", action="store_true")
    ap.add_argument("--known-speaker", action="store_true",
                    help="실명 식별(known_speaker_references) 추가 검증")
    args = ap.parse_args()

    if not settings.openai_api_key:
        print("❌ OPENAI_API_KEY 미설정 (.env 확인)")
        return 1

    t0 = time.time()
    pcm = extract_pcm(args.url, args.seconds, args.offset)

    results = {}
    if not args.skip_diarize:
        results["diarize"] = test_diarize(pcm)
    if args.cue_scan:
        results["cue_scan"] = test_cue_scan(pcm)
    if args.known_speaker:
        results["known_speaker"] = test_known_speaker(pcm)
    if not args.skip_realtime:
        results["realtime"] = asyncio.run(test_realtime(pcm, args.model))

    print("\n" + "=" * 60)
    print(f"결과 ({time.time() - t0:.1f}s): " +
          ", ".join(f"{k}={'PASS' if v else 'FAIL'}" for k, v in results.items()))
    print("=" * 60)
    return 0 if all(results.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
