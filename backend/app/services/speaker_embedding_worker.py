"""화자 임베딩 워커 — 서브프로세스 전용 (`python <이 파일> --pcm … --windows … --out …`).

부모(API 프로세스)에서 직접 onnxruntime 을 올리지 않는 이유:
  ① 세션 아레나가 부모 힙에 남지 않는다(3Gi 상한). ② sherpa-onnx 가 GIL 을 놓든 말든 라이브 STT
  이벤트루프를 막지 않는다. ③ `os.nice` 로 라이브 채널 CPU 를 우선한다.
앱 패키지를 import 하지 않는다 — 평가 스크립트가 파드 /tmp 에서 파일 경로로 그대로 실행한다.

입력: 16kHz mono s16le PCM 파일 + 창 JSON [[start_sec, end_sec], …]
출력: float32 .npy (n, dim). 정규화는 호출측(speaker_voice_fusion)이 한다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

RATE = 16000


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcm", required=True)
    ap.add_argument("--windows", required=True, help="JSON 파일: [[start,end], ...] (초)")
    ap.add_argument("--out", required=True, help=".npy 출력 경로")
    ap.add_argument("--model", required=True)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--nice", type=int, default=10)
    args = ap.parse_args(argv)

    try:
        os.nice(args.nice)
    except Exception:
        pass
    import sherpa_onnx  # 워커에서만 import — 부모 프로세스는 이 의존성을 모른다

    cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=args.model, num_threads=args.threads, debug=False, provider="cpu"
    )
    ext = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
    with open(args.windows, encoding="utf-8") as f:
        wins = json.load(f)
    pcm = np.memmap(args.pcm, dtype=np.int16, mode="r")
    out = np.zeros((len(wins), ext.dim), dtype=np.float32)
    n_total = len(pcm)
    for i, (st, en) in enumerate(wins):
        a, b = max(0, int(st * RATE)), min(n_total, int(en * RATE))
        if b - a < RATE // 2:  # 0.5초 미만은 임베딩 불가 — 0 벡터(호출측이 걸러낸다)
            continue
        x = np.asarray(pcm[a:b], dtype=np.float32) / 32768.0
        s = ext.create_stream()
        s.accept_waveform(sample_rate=RATE, waveform=x)
        s.input_finished()
        out[i] = np.asarray(ext.compute(s), dtype=np.float32)
    np.save(args.out, out)
    print(f"embedded {len(wins)} windows dim {ext.dim}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
