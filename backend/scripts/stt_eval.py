"""STT 정확도 평가 하네스 — 속기 회의록(ground truth) 대비 CER 측정 + 오류 마이닝.

같은 회의 영상을 세 엔진 중 하나로 재전사하고, 속기사 작성 회의록(fetch_kms_minutes.py
산출물)과 대조한다.

  --engine batch     운영 라이브 경로 재현 — 12초 창 배치 전사(live_batch_stt 와 같은 컷·prompt)
                     모델 gpt-4o-transcribe(현행) / gpt-transcribe(keywords 지원, 더 저렴)
  --engine live      스트리밍 gpt-live-transcribe — delay(minimal~xhigh)·keywords·prompt·languages.
                     실시간 속도로 송신해 **completed 지연(초)** 도 함께 잰다 (지연/정확도 교환 실험)
  --engine realtime  구 경로 A(gpt-realtime-whisper, 3초 commit) — 2026-08 평가와의 연속성용

측정:
- CER(문자 오류율): 공백·문장부호 제거 후 한글/숫자/영문만 비교 (한국어라 WER보다 적합)
- 치환 오류 상위 목록: 고유명사·용어 오인식 후보 (dictionary/stt_prompt 보강 소스)
- live 엔진: 턴별 (오디오 끝 → completed) 지연의 p50/p95, 첫 delta 까지의 지연
※ 속기록은 정제 문어체(간투사 제거 등)라 CER 절대값은 실제보다 높게 나온다 —
   개선 전/후 상대 비교가 목적. 런 간 변동이 ±2.5%p 라 한 구간 한 번으로 결론내지 말 것.

사용법 (backend 디렉터리에서):
    python scripts/fetch_kms_minutes.py 138285            # 참조 먼저 수집
    python scripts/stt_eval.py --midx 138285 --seconds 300 --offset 60 --engine batch
    python scripts/stt_eval.py --midx 138285 --engine batch --model gpt-transcribe --keywords-from-ref
    python scripts/stt_eval.py --midx 138285 --engine live --delay high --keywords-from-ref
    python scripts/stt_eval.py --midx 138285 --no-prompt  # 프롬프트 효과 분리 측정
    python scripts/stt_eval.py --midx 138285 --audio recordings/ch14_20260903.mp3  # 라이브 녹음으로
출력: backend/eval_data/eval_<midx>_<offset>s_<engine>_<model>_<tag>.json
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import difflib
import json
import os
import re
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

from app.core.config import settings  # noqa: E402
from verify_openai_stt import RATE, extract_pcm  # noqa: E402

EVAL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval_data")
VOD_VIEWER = "https://kms.ggc.go.kr/caster/player/vodViewer.do?midx={midx}"


# ─── 전사 (현행 라이브 경로 A 프로토콜) ─────────────────────────────────

async def transcribe_realtime(pcm: bytes, model: str, prompt: str) -> list[str]:
    import websockets

    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    transcription: dict = {"model": model, "language": "ko"}
    if prompt:
        transcription["prompt"] = prompt

    finals: list[str] = []
    async with websockets.connect(
        settings.openai_realtime_ws_url, additional_headers=headers, max_size=None
    ) as ws:
        await ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "type": "transcription",
                "audio": {"input": {
                    "format": {"type": "audio/pcm", "rate": RATE},
                    "transcription": transcription,
                    "turn_detection": None,
                }},
            },
        }))

        done = asyncio.Event()

        async def receiver() -> None:
            async for raw in ws:
                ev = json.loads(raw)
                t = ev.get("type", "")
                if t == "conversation.item.input_audio_transcription.completed":
                    txt = (ev.get("transcript") or "").strip()
                    if txt:
                        finals.append(txt)
                elif t == "error":
                    code = (ev.get("error") or {}).get("code", "")
                    if code != "input_audio_buffer_commit_empty":  # 종료 시 무해한 빈 commit
                        print(f"  [ws error] {json.dumps(ev.get('error', ev), ensure_ascii=False)[:200]}")

        recv_task = asyncio.create_task(receiver())
        chunk = int(RATE * 2 * 0.2)
        sent = 0
        for i in range(0, len(pcm), chunk):
            await ws.send(json.dumps({
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(pcm[i:i + chunk]).decode("ascii"),
            }))
            sent += 1
            if sent % 15 == 0:
                await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
            await asyncio.sleep(0.04)
        await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
        await asyncio.sleep(10.0)
        recv_task.cancel()
        done.set()
    return finals


# ─── 엔진 2: 운영 배치 경로 재현 (live_batch_stt 와 같은 창·컷·prompt) ────

async def transcribe_batch(
    pcm: bytes, model: str, prompt: str, keywords: list[str] | None, window_sec: float,
) -> tuple[list[str], dict]:
    """12초 창 배치 전사 — 운영 live_batch_stt 의 분절·prompt 규칙을 그대로 따른다.

    창 컷은 _find_quiet_cut(꼬리 2.5초 안 가장 조용한 0.3초 블록), 무음 창은 API 생략,
    prompt = 글로서리 + 직전 창 전사 꼬리(200자), 결과에서 프롬프트 에코(_strip_overlap) 제거.
    keywords 는 gpt-transcribe 만 받는다(extra_body) — 거부되면 자동으로 빼고 재시도.
    """
    from openai import AsyncOpenAI

    from app.services.live_batch_stt import _find_quiet_cut, _has_speech, _pcm_to_wav, _strip_overlap

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    byps = RATE * 2
    window_bytes = int(window_sec * byps) - (int(window_sec * byps) % 2)
    ctx_chars = settings.live_batch_context_chars

    finals: list[str] = []
    window_starts: list[float] = []  # finals[i] 가 나온 창의 시작(초, pcm 기준) — replay_live 타임스탬프용
    api_secs: list[float] = []
    prev_tail = ""
    pos = 0
    n_windows = n_silent = 0
    keywords_ok = bool(keywords)
    while pos < len(pcm):
        buf = pcm[pos:pos + window_bytes]
        cut = _find_quiet_cut(buf, RATE, window_sec) if len(buf) >= window_bytes else len(buf)
        chunk = buf[:cut] if 0 < cut <= len(buf) else buf
        win_start = pos / byps
        pos += len(chunk)
        n_windows += 1
        if not _has_speech(chunk, RATE):
            n_silent += 1
            continue
        parts = [p for p in (prompt, prev_tail) if p]
        kwargs: dict = {
            "model": model,
            "file": ("window.wav", _pcm_to_wav(chunk, RATE), "audio/wav"),
            "language": "ko",
        }
        if parts:
            kwargs["prompt"] = "\n".join(parts)
        if keywords_ok:
            kwargs["extra_body"] = {"keywords": keywords}
        t0 = time.time()
        try:
            res = await client.audio.transcriptions.create(**kwargs)
        except Exception as e:
            if keywords_ok and "keyword" in str(e).lower():
                print(f"  [batch] keywords 거부 — 빼고 계속: {str(e)[:120]}")
                keywords_ok = False
                kwargs.pop("extra_body", None)
                res = await client.audio.transcriptions.create(**kwargs)
            else:
                raise
        api_secs.append(time.time() - t0)
        text = (getattr(res, "text", "") or "").strip()
        text = _strip_overlap(prev_tail, text)
        if not text:
            continue
        prev_tail = text[-ctx_chars:]
        finals.append(text)
        window_starts.append(round(win_start, 2))
    stats = {
        "windows": n_windows, "silent_windows": n_silent, "api_calls": len(api_secs),
        "api_sec_p50": _pct(api_secs, 50), "api_sec_p95": _pct(api_secs, 95),
        "keywords_used": keywords_ok, "window_starts": window_starts,
    }
    print(f"  [batch] 창 {n_windows}(무음 {n_silent}) · API p50 {stats['api_sec_p50']}s p95 {stats['api_sec_p95']}s")
    return finals, stats


# ─── 엔진 3: 스트리밍 gpt-live-transcribe (지연·정확도 교환 실험) ─────────

async def transcribe_live(
    pcm: bytes, model: str, prompt: str, keywords: list[str] | None, delay: str,
    *, vad: str = "server_vad", commit_sec: float = 0.0, pace: bool = True,
) -> tuple[list[str], dict]:
    """gpt-live-transcribe 세션에 **실시간 속도**로 오디오를 보내며 completed 지연을 잰다.

    지연 정의: 그 턴의 마지막 오디오 바이트를 보낸 벽시계 → completed 수신 벽시계.
    (운영에서 자막이 '그 발화가 끝난 뒤' 몇 초 만에 확정되는가와 같은 뜻)
    vad=server_vad 면 서버가 턴을 자르고, none 이면 commit_sec 마다 수동 commit.
    """
    import websockets

    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    transcription: dict = {"model": model, "languages": ["ko"], "delay": delay}
    if prompt:
        transcription["prompt"] = prompt
    if keywords:
        transcription["keywords"] = keywords
    turn_detection = (
        {"type": "server_vad", "threshold": 0.5, "prefix_padding_ms": 300, "silence_duration_ms": 500}
        if vad == "server_vad" else None
    )

    finals: list[str] = []
    turn_lat: list[float] = []
    first_delta_lat: list[float] = []
    errors: list[str] = []
    # 턴 경계 추정: server_vad 는 speech_stopped 이벤트, none 은 commit 시각
    last_audio_end_wall: list[float] = [0.0]   # 최근 턴의 오디오 끝(벽시계)
    turn_started_wall: list[float | None] = [None]
    pending_first_delta: list[bool] = [True]

    async with websockets.connect(
        settings.openai_realtime_ws_url, additional_headers=headers, max_size=None
    ) as ws:
        await ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "type": "transcription",
                "audio": {"input": {
                    "format": {"type": "audio/pcm", "rate": RATE},
                    "transcription": transcription,
                    "turn_detection": turn_detection,
                }},
            },
        }))

        async def receiver() -> None:
            async for raw in ws:
                ev = json.loads(raw)
                t = ev.get("type", "")
                now = time.time()
                if t == "input_audio_buffer.speech_stopped":
                    last_audio_end_wall[0] = now
                elif t == "conversation.item.input_audio_transcription.delta":
                    if pending_first_delta[0] and turn_started_wall[0]:
                        first_delta_lat.append(now - turn_started_wall[0])
                        pending_first_delta[0] = False
                elif t == "conversation.item.input_audio_transcription.completed":
                    txt = (ev.get("transcript") or "").strip()
                    if txt:
                        finals.append(txt)
                        turn_lat.append(now - last_audio_end_wall[0])
                    pending_first_delta[0] = True
                    turn_started_wall[0] = now
                elif t == "error":
                    code = (ev.get("error") or {}).get("code", "")
                    if code != "input_audio_buffer_commit_empty":
                        errors.append(json.dumps(ev.get("error", ev), ensure_ascii=False)[:200])
                        print(f"  [ws error] {errors[-1]}")

        recv_task = asyncio.create_task(receiver())
        chunk_sec = 0.2
        chunk = int(RATE * 2 * chunk_sec)
        t_start = time.time()
        sent_sec = 0.0
        next_commit = commit_sec
        turn_started_wall[0] = t_start
        for i in range(0, len(pcm), chunk):
            await ws.send(json.dumps({
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(pcm[i:i + chunk]).decode("ascii"),
            }))
            sent_sec += chunk_sec
            if vad == "none":
                last_audio_end_wall[0] = time.time()
                if commit_sec > 0 and sent_sec >= next_commit:
                    await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                    next_commit += commit_sec
            if pace:
                # 실시간 페이싱 — 지연 측정이 목적이므로 오디오 시계보다 앞서 보내지 않는다
                ahead = sent_sec - (time.time() - t_start)
                if ahead > 0:
                    await asyncio.sleep(ahead)
        if vad == "none":
            last_audio_end_wall[0] = time.time()
        await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
        await asyncio.sleep(8.0)
        recv_task.cancel()
    stats = {
        "delay": delay, "vad": vad, "turns": len(finals),
        "turn_latency_p50": _pct(turn_lat, 50), "turn_latency_p95": _pct(turn_lat, 95),
        "first_delta_p50": _pct(first_delta_lat, 50),
        "errors": errors[:5],
    }
    print(f"  [live] 턴 {len(finals)} · completed 지연 p50 {stats['turn_latency_p50']}s p95 {stats['turn_latency_p95']}s")
    return finals, stats


async def transcribe_batch_live(
    pcm: bytes, model: str, prompt: str, keywords: list[str] | None, *,
    window: float, min_flush: float, pause_flush: float, prev_tail: str = "",
) -> tuple[list[str], dict]:
    """운영 라이브 경로 재현 — 창 분절을 `live_window_sim.LiveWindowSimulator`(조기 flush·in-flight 포함)로 한다.

    `transcribe_batch` 와 prompt(글로서리 + 직전 창 꼬리)·에코 제거(`_strip_overlap`)·keywords 처리는 같고 분할만 다르다.
    창 길이 실험(2026-09-14, docs/live-sync-eval-2026-09.md)의 도구 — 같은 오디오에 (12,6)·(8,6)·(8,4) 를 돌려 CER 을 비교한다.
    stats 에 시뮬 통계(평균/p95 창 · ready_lag p50/p95/p99 — 실제 API 왕복으로 계산) 와 에코 폐기 계수
    (`dup_dropped` 창 전체 폐기 · `overlap_trimmed_chars` 앞부분 절단 글자수) 를 싣는다. `prev_tail` 로 30분 청크를 이어 붙인다.
    """
    from openai import AsyncOpenAI

    from app.services.live_batch_stt import _pcm_to_wav, _strip_overlap
    from live_window_sim import LiveWindowSimulator

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    byps = RATE * 2
    ctx_chars = settings.live_batch_context_chars
    sim = LiveWindowSimulator(pcm, RATE, window=window, min_flush=min_flush, pause_flush=pause_flush)

    finals: list[str] = []
    window_starts: list[float] = []
    api_secs: list[float] = []
    dup_dropped = 0
    overlap_trimmed_chars = 0
    keywords_ok = bool(keywords)
    gen = sim.windows()
    try:
        win = next(gen)
        while True:
            parts = [p for p in (prompt, prev_tail) if p]
            kwargs: dict = {
                "model": model,
                "file": ("window.wav", _pcm_to_wav(win.pcm, RATE), "audio/wav"),
                "language": "ko",
            }
            if parts:
                kwargs["prompt"] = "\n".join(parts)
            if keywords_ok:
                kwargs["extra_body"] = {"keywords": keywords}
            t0 = time.time()
            try:
                res = await client.audio.transcriptions.create(**kwargs)
            except Exception as e:
                if keywords_ok and "keyword" in str(e).lower():
                    print(f"  [batch-live] keywords 거부 — 빼고 계속: {str(e)[:120]}")
                    keywords_ok = False
                    kwargs.pop("extra_body", None)
                    res = await client.audio.transcriptions.create(**kwargs)
                else:
                    raise
            api_sec = time.time() - t0
            api_secs.append(api_sec)
            raw = (getattr(res, "text", "") or "").strip()
            text = _strip_overlap(prev_tail, raw)
            if raw and not text:
                dup_dropped += 1
            elif raw and len(text) < len(raw):
                overlap_trimmed_chars += len(raw) - len(text)
            if text:
                prev_tail = text[-ctx_chars:]
                finals.append(text)
                window_starts.append(round(win.start_sec, 2))
            win = gen.send(api_sec)
    except StopIteration:
        pass
    stats = sim.stats()
    stats.update({
        "api_calls": len(api_secs),
        "api_sec_p50": _pct(api_secs, 50), "api_sec_p95": _pct(api_secs, 95),
        "keywords_used": keywords_ok, "window_starts": window_starts,
        "dup_dropped": dup_dropped, "overlap_trimmed_chars": overlap_trimmed_chars,
        "prev_tail": prev_tail,
    })
    print(
        f"  [batch-live w{window:g}/m{min_flush:g}] 창 {stats['windows']}(무음 {stats['silent_windows']}) · "
        f"평균 {stats['window_mean']}s p95 {stats['window_p95']}s · ready_lag p50 {stats['ready_lag_p50']} "
        f"p95 {stats['ready_lag_p95']} p99 {stats['ready_lag_p99']} · API p50 {stats['api_sec_p50']}s · "
        f"에코 폐기 {dup_dropped} 절단 {overlap_trimmed_chars}자"
    )
    return finals, stats


def _pct(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round(p / 100 * len(s) + 0.5)) - 1))
    return round(s[k], 2)


def load_audio(args: argparse.Namespace) -> bytes:
    """--audio 파일(mp3/wav/mp4 등, ffmpeg 가 읽는 것이면 됨)이 있으면 그것을, 없으면 KMS mp4."""
    if args.audio:
        return extract_pcm(args.audio, args.seconds, args.offset)
    raise ValueError("audio source required")


def keywords_from_ref(ref_doc: dict, limit: int = 60) -> list[str]:
    """속기록 화자 명단(+용어사전 정답)을 keywords 힌트로 — 운영의 DB 명부 시뮬레이션."""
    from app.services.dictionary import get_default_dictionary

    titles = {
        "위원", "위원장", "의원", "의장", "부의장", "부위원장", "간사", "국장", "과장", "실장",
        "본부장", "원장", "지사", "부지사", "교육감", "부교육감", "차관", "장관", "청장", "단장",
        "집행부", "속기사", "서기", "발언자",
    }
    seen: list[str] = []
    for sp in ref_doc.get("speakers", []):
        # "위원장 김회철" / "정성호 위원" / "집행부 OO국장" — 직함이 아닌 2~4자 한글 토큰이 이름
        for tok in str(sp).split():
            if tok in titles or not re.fullmatch(r"[가-힣]{2,4}", tok):
                continue
            if tok not in seen:
                seen.append(tok)
            break
    try:
        entries = getattr(get_default_dictionary(), "_entries", {})
        for e in list(entries.values())[:40]:
            correct = getattr(e, "correct_text", None) or getattr(e, "correct", None)
            if correct and correct not in seen:
                seen.append(str(correct))
    except Exception:
        pass
    return [k for k in seen if "<" not in k and ">" not in k and "\n" not in k][:limit]


# ─── 정규화·정렬·CER ────────────────────────────────────────────────────

def norm_strict(s: str) -> str:
    """CER용: 한글/숫자/영문만 (공백·문장부호 제거)."""
    return re.sub(r"[^가-힣0-9a-zA-Z]", "", s)


def norm_spaced(s: str) -> str:
    """마이닝용: 문장부호 제거, 공백 정규화 (어절 경계 유지)."""
    s = re.sub(r"[^가-힣 0-9a-zA-Z\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def find_reference_window(ref: str, hyp: str) -> tuple[int, int]:
    """정규화된 참조 전문에서 hyp와 가장 유사한 구간 [start,end)을 찾는다."""
    hl = len(hyp)
    win = int(hl * 1.35) + 50
    step = max(1, hl // 3)
    best = (0.0, 0)
    for start in range(0, max(1, len(ref) - hl // 2), step):
        seg = ref[start:start + win]
        r = difflib.SequenceMatcher(None, seg, hyp, autojunk=False).quick_ratio()
        if r > best[0]:
            best = (r, start)
    start = best[1]
    # 경계 정밀화: 최적 창 안에서 matching block 기반으로 앞뒤 트림
    seg = ref[start:start + win]
    sm = difflib.SequenceMatcher(None, seg, hyp, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size >= 3]
    if blocks:
        lo = start + blocks[0].a - blocks[0].b  # hyp 시작 이전 만큼 앞당김
        hi = start + blocks[-1].a + blocks[-1].size + (len(hyp) - (blocks[-1].b + blocks[-1].size))
        return max(0, lo), min(len(ref), hi)
    return start, min(len(ref), start + win)


def edit_ops(ref: str, hyp: str) -> tuple[int, list[tuple[str, str]]]:
    """SequenceMatcher opcode 기반 편집 비용과 치환쌍을 구한다 (근사 편집거리)."""
    sm = difflib.SequenceMatcher(None, ref, hyp, autojunk=False)
    cost = 0
    subs: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        cost += max(i2 - i1, j2 - j1)
        if tag == "replace":
            subs.append((ref[i1:i2], hyp[j1:j2]))
    return cost, subs


def mine_word_substitutions(ref_sp: str, hyp_sp: str) -> tuple[Counter, int]:
    """어절 단위 정렬로 치환 오류쌍(참조→가설)을 수집한다.

    띄어쓰기만 다른 쌍(발음 동일)은 CER에 영향이 없으므로 별도 카운트만 하고 제외.
    """
    rw, hw = ref_sp.split(), hyp_sp.split()
    sm = difflib.SequenceMatcher(None, rw, hw, autojunk=False)
    pairs: Counter = Counter()
    spacing_only = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace" and (i2 - i1) <= 3 and (j2 - j1) <= 3:
            r, h = " ".join(rw[i1:i2]), " ".join(hw[j1:j2])
            if norm_strict(r) == norm_strict(h):
                spacing_only += 1
                continue
            pairs[(r, h)] += 1
    return pairs, spacing_only


# ─── 후처리 (운영 라이브 경로와 동일 조건) ──────────────────────────────

def postprocess_finals(finals: list[str], args: argparse.Namespace) -> str:
    """운영 _emit_subtitle과 동일하게 dictionary.correct(사전+숫자변환)를 적용한다.

    --raw: 후처리 없이 원시 전사로 채점 (후처리 효과 분리 측정용)
    --extra-dict: 후보 교정쌍 JSON([{wrong,correct}])을 기본 사전 뒤에 추가 적용
    """
    if args.raw:
        return " ".join(finals)
    from app.services.dictionary import get_default_dictionary

    d = get_default_dictionary()
    extra: list[tuple[str, str]] = []
    if args.extra_dict:
        for e in json.load(open(args.extra_dict, encoding="utf-8")):
            extra.append((e["wrong"], e["correct"]))
    out = []
    for f in finals:
        c = d.correct(f)
        c = c if c.strip() else f
        for wrong, correct in extra:
            c = c.replace(wrong, correct)
        out.append(c)
    return " ".join(out)


# ─── main ────────────────────────────────────────────────────────────────

def load_ref_steno(path: str) -> dict:
    """mntsViewer 속기 txt(_fetch_steno.py 산출물)를 minutes JSON 과 같은 꼴로 — 본회의는
    captionDoc(midx)이 404 라 이 경로만 있다(2026-09-08 393회 2·3차 실측)."""
    from _steno_align import parse_steno

    items = parse_steno(open(path, encoding="utf-8").read())
    speakers: list[str] = []
    for name, _, _ in items:
        if name and name not in speakers:
            speakers.append(name)
    return {
        "title": os.path.basename(path),
        "utterances": [{"speaker": n or "", "text": s} for n, s, _ in items],
        "speakers": speakers,
    }


async def run(args: argparse.Namespace) -> dict:
    if args.ref_steno:
        ref_doc = load_ref_steno(args.ref_steno)
    else:
        ref_path = os.path.join(EVAL_DIR, f"minutes_{args.midx}.json")
        if not os.path.exists(ref_path):
            raise SystemExit(f"참조 없음: {ref_path} — 먼저 fetch_kms_minutes.py {args.midx} 실행")
        ref_doc = json.load(open(ref_path, encoding="utf-8"))
    ref_full = "\n".join(u["text"] for u in ref_doc["utterances"])

    if args.rescore:
        # 저장된 전사를 다른 후처리로 재채점 (API 호출 없음 — 런 변동 배제)
        saved = json.load(open(args.rescore, encoding="utf-8"))
        finals = saved["finals"]
        print(f"[rescore] {args.rescore} finals {len(finals)}건")
        hyp = postprocess_finals(finals, args)
        prompt = ""
        return score_and_report(args, ref_doc, ref_full, finals, hyp, prompt)

    if args.audio:
        pcm = extract_pcm(args.audio, args.seconds, args.offset)
    else:
        from app.services.kms_vod_resolver import resolve_kms_vod_url

        mp4_url = await resolve_kms_vod_url(VOD_VIEWER.format(midx=args.midx))
        print(f"[mp4] {mp4_url}")
        pcm = extract_pcm(mp4_url, args.seconds, args.offset)

    prompt = ""
    if args.meeting:
        # 운영 라이브 경로 재현 — live_batch_stt._glossary_prompts 와 같은 호출(글로서리 900자 캡).
        # build_stt_prompt(아래)는 다른 형식이라 "현행 재현" 이 아니다.
        from app.core.database import get_supabase_client
        from app.services.glossary_service import format_glossary_prompt, load_meeting_glossary

        terms = load_meeting_glossary(get_supabase_client(), args.meeting)
        prompt = format_glossary_prompt(terms, max_terms=200, max_chars=900)
        print(f"[prompt] 운영 글로서리 {len(prompt)}자 (용어 {len(terms)}개 중 캡 안에 든 것만)")
    elif not args.no_prompt:
        from app.services.stt_prompt import build_stt_prompt

        extra_names: list[str] = []
        if args.names_from_ref:
            # 운영에서는 DB 명부(roster)가 이 역할 — 여기서는 속기록 화자 명단으로 시뮬레이션
            seen = set()
            for sp in ref_doc.get("speakers", []):
                name = sp.split()[-1] if sp.split() else sp
                if name and name not in seen:
                    seen.add(name)
                    extra_names.append(name)
        try:
            prompt = build_stt_prompt(args.committee, extra_names=extra_names or None)
        except AttributeError:
            # 배포본 Settings 에 stt_domain_prompt_* 가 없던 시기(2026-09-03 이전 이미지) —
            # 운영 배치 경로가 쓰는 글로서리 형식으로 대체한다 (명부 + 사전 정답 용어).
            from app.services.glossary_service import format_glossary_prompt

            prompt = format_glossary_prompt(
                extra_names + keywords_from_ref(ref_doc), max_terms=200, max_chars=900
            )
            print("[prompt] build_stt_prompt 불가 → 글로서리 형식 대체")
        print(f"[prompt] {len(prompt)}자 (명부 {len(extra_names)}명 포함)" if extra_names else f"[prompt] {len(prompt)}자 (기본)")

    keywords = keywords_from_ref(ref_doc) if args.keywords_from_ref else None
    if keywords:
        print(f"[keywords] {len(keywords)}개: {', '.join(keywords[:8])}…")

    t0 = time.time()
    stats: dict = {}
    if args.engine == "batch" and (args.min_flush is not None or args.pause_flush is not None):
        finals, stats = await transcribe_batch_live(
            pcm, args.model, prompt, keywords, window=args.window,
            min_flush=args.min_flush if args.min_flush is not None else settings.live_batch_min_flush_seconds,
            pause_flush=args.pause_flush if args.pause_flush is not None else settings.live_batch_pause_flush_seconds,
        )
    elif args.engine == "batch":
        finals, stats = await transcribe_batch(pcm, args.model, prompt, keywords, args.window)
    elif args.engine == "live":
        finals, stats = await transcribe_live(
            pcm, args.model, prompt, keywords, args.delay,
            vad=args.vad, commit_sec=args.commit, pace=not args.no_pace,
        )
    else:
        finals = await transcribe_realtime(pcm, args.model, prompt)
    print(f"[전사:{args.engine}] final {len(finals)}건 ({time.time()-t0:.0f}s)")
    if not finals:
        raise SystemExit("전사 결과 없음")

    hyp = postprocess_finals(finals, args)
    return score_and_report(args, ref_doc, ref_full, finals, hyp, prompt, stats)


def score_and_report(
    args: argparse.Namespace,
    ref_doc: dict,
    ref_full: str,
    finals: list[str],
    hyp: str,
    prompt: str,
    stats: dict | None = None,
) -> dict:
    # 참조 구간 확정 (strict 정규화 기준)
    ref_strict_full = norm_strict(ref_full)
    hyp_strict = norm_strict(hyp)
    lo, hi = find_reference_window(ref_strict_full, hyp_strict)
    ref_strict = ref_strict_full[lo:hi]

    cost, _ = edit_ops(ref_strict, hyp_strict)
    cer = cost / max(1, len(ref_strict))

    # 어절 마이닝: 같은 구간을 spaced 버전에서 근사 추출 (비율로 위치 환산)
    ref_sp_full = norm_spaced(ref_full)
    scale = len(ref_sp_full) / max(1, len(ref_strict_full))
    ref_sp = ref_sp_full[int(lo * scale): int(hi * scale)]
    subs, spacing_only = mine_word_substitutions(ref_sp, norm_spaced(hyp))

    result = {
        "midx": args.midx,
        "title": ref_doc.get("title", ""),
        "engine": getattr(args, "engine", "realtime"),
        "model": args.model,
        "audio": getattr(args, "audio", None),
        "stats": stats or {},
        "prompt_chars": len(prompt),
        "offset": args.offset,
        "seconds": args.seconds,
        "ref_window": [lo, hi],
        "ref_chars": len(ref_strict),
        "hyp_chars": len(hyp_strict),
        "cer": round(cer, 4),
        "spacing_only_diffs": spacing_only,
        "top_substitutions": [
            {"ref": r, "hyp": h, "count": c}
            for (r, h), c in subs.most_common(args.top)
        ],
        "finals": finals,  # 오프라인 재채점(--rescore)용 원시 전사 전체
    }

    if args.rescore:
        tag = "rescore" + ("_extra" if args.extra_dict else "") + ("_raw" if args.raw else "")
    else:
        tag = "noprompt" if args.no_prompt else ("roster" if args.names_from_ref else "prompt")
        if getattr(args, "meeting", None):
            tag = "meeting"
        if getattr(args, "audio", None):
            tag += "_rec"  # 라이브 녹음(mp3) 오디오 — VOD mp4 와 구분
        if getattr(args, "keywords_from_ref", False):
            tag += "_kw"
        if getattr(args, "engine", "") == "live":
            tag += f"_{args.delay}"
        if args.raw:
            tag += "_raw"
        if getattr(args, "min_flush", None) is not None or getattr(args, "pause_flush", None) is not None:
            # 운영 규칙 재현(창 실험) — 조건이 파일명에 남아야 덮어쓰지 않는다 (Codex 지적, 2026-09-14)
            mf = args.min_flush if args.min_flush is not None else settings.live_batch_min_flush_seconds
            tag += f"_w{args.window:g}m{mf:g}"
    engine = getattr(args, "engine", "realtime")
    model_slug = re.sub(r"[^a-z0-9]+", "-", args.model.lower()).strip("-")
    out = os.path.join(EVAL_DIR, f"eval_{args.midx}_{int(args.offset)}s_{engine}_{model_slug}_{tag}.json")
    json.dump(result, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("\n" + "=" * 62)
    print(f"  midx={args.midx} offset={args.offset}s dur={args.seconds}s engine={engine} model={args.model} prompt={len(prompt)}자")
    if stats:
        print(f"  stats: {json.dumps(stats, ensure_ascii=False)}")
    print(f"  CER = {cer:.1%}  (ref {len(ref_strict)}자 vs hyp {len(hyp_strict)}자, 띄어쓰기만 차이 {spacing_only}건 제외)")
    print(f"  치환 오류 상위:")
    for (r, h), c in subs.most_common(15):
        print(f"    {c}× {r!r} → {h!r}")
    print(f"  저장: {out}")
    print("=" * 62)
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--midx", type=int, required=True)
    ap.add_argument("--seconds", type=int, default=300)
    ap.add_argument("--offset", type=float, default=0.0)
    ap.add_argument("--engine", choices=["realtime", "batch", "live"], default="batch",
                    help="batch=운영 배치 경로 재현(기본) · live=gpt-live-transcribe 스트리밍 · realtime=구 경로 A")
    ap.add_argument("--model", default=None,
                    help="기본: batch→settings.live_batch_model, live→gpt-live-transcribe, realtime→settings.openai_realtime_stt_model")
    ap.add_argument("--window", type=float, default=None, help="batch 창 길이(초, 기본 settings.live_batch_window_seconds)")
    ap.add_argument("--min-flush", type=float, default=None,
                    help="batch: 운영 규칙(조기 flush·in-flight) 재현 — 조기 flush 최소 버퍼(초). 이 값이나 --pause-flush 를 주면 live_window_sim 으로 분할")
    ap.add_argument("--pause-flush", type=float, default=None, help="batch: 조기 flush 꼬리 무음 길이(초, 기본 0.6)")
    ap.add_argument("--delay", choices=["minimal", "low", "medium", "high", "xhigh"], default="high",
                    help="live 엔진 delay — 클수록 문맥이 늘어 정확도↑ 지연↑")
    ap.add_argument("--vad", choices=["server_vad", "none"], default="server_vad",
                    help="live 턴 분절 — server_vad(자연 턴) / none(--commit 초마다 수동)")
    ap.add_argument("--commit", type=float, default=3.0, help="live --vad none 일 때 commit 주기(초)")
    ap.add_argument("--no-pace", action="store_true", help="live 실시간 페이싱 끄기(빨리 끝내기 — 지연 측정 무효)")
    ap.add_argument("--keywords-from-ref", action="store_true",
                    help="속기록 화자 명단+사전 정답을 keywords 힌트로 (gpt-transcribe·gpt-live-transcribe)")
    ap.add_argument("--audio", default=None,
                    help="KMS mp4 대신 이 오디오 파일(라이브 녹음 mp3 등)을 쓴다 — ffmpeg 가 읽는 형식")
    ap.add_argument("--committee", default=None, help="stt_prompt 명부 포함용 위원회명")
    ap.add_argument("--ref-steno", default=None,
                    help="참조를 minutes JSON 대신 _fetch_steno.py 의 속기 txt(mntsId)로 — 본회의는 captionDoc 이 404")
    ap.add_argument("--meeting", default=None,
                    help="이 회의 id 의 운영 글로서리(load_meeting_glossary, 900자)로 프롬프트 — 현행 라이브 경로 재현")
    ap.add_argument("--no-prompt", action="store_true", help="도메인 프롬프트 없이 측정 (효과 분리)")
    ap.add_argument("--names-from-ref", action="store_true",
                    help="속기록 화자 명단을 프롬프트에 주입 (운영의 DB 명부 시뮬레이션)")
    ap.add_argument("--raw", action="store_true", help="후처리(사전+숫자변환) 없이 원시 전사로 채점")
    ap.add_argument("--rescore", default=None, help="저장된 eval JSON의 finals를 재채점 (API 미호출)")
    ap.add_argument("--extra-dict", default=None, help="후보 교정쌍 JSON([{wrong,correct}]) 추가 적용")
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args()

    if args.model is None:
        args.model = {
            "batch": settings.live_batch_model,
            "live": "gpt-live-transcribe",
            "realtime": settings.openai_realtime_stt_model,
        }[args.engine]
    if args.window is None:
        args.window = settings.live_batch_window_seconds

    if not settings.openai_api_key and not args.rescore:
        print("OPENAI_API_KEY 미설정")
        return 1
    asyncio.run(run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
