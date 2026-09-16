# Multi-stage Dockerfile — OCI Always Free (ARM Ampere) + AMD64 호환
#
# 빌드:
#   docker build -t ggc-backend .
#
# 실행 (docker-compose 추천):
#   docker run -p 8000:8000 --env-file .env ggc-backend
#
# 빌드 전략:
# - python:3.11-slim 베이스 (arm64/amd64 multi-arch 공식 이미지)
# - builder 스테이지에서 의존성 컴파일 → runtime은 경량 유지
# - non-root user(appuser)로 실행 → 보안
# - uploads/ 볼륨 마운트 지점 유지

# =============================================================================
# Builder stage
# =============================================================================
FROM python:3.11-slim AS builder

WORKDIR /build

# 빌드 의존성 (psycopg/pydantic 컴파일에 필요)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libpq-dev \
    curl \
    ca-certificates \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

# ffmpeg 9.0 정적 바이너리 (BtbN 고정 릴리스 태그 + sha256 검증) — 2026-09-08 8.1.2 → 9.0.1 (사용자 요청 "공식 최신")
# - apt ffmpeg(bookworm=5.1)로는 버전 요구를 못 맞추고 의존성 트리가 커서 정적 단일 바이너리를 쓴다
# - 태그를 latest 로 두지 않는 이유: 재빌드 시 바이너리가 바뀌면 STT 파이프라인 검증이 무효가 된다
#
# ★핀은 주기적으로 끊어진다 — BtbN 은 오래된 autobuild 릴리스를 지운다.
#   2026-08-31 빌드가 `curl: (22) 404` 로 죽었다(옛 핀 autobuild-2026-08-16-13-00 삭제됨).
#   증상이 "빌드 실패"라 원인이 멀어 보이지만 upstream 자산 소멸이 전부다.
#   갱신 방법: https://api.github.com/repos/BtbN/FFmpeg-Builds/releases?per_page=5 에서
#   최신 autobuild 태그와 linux64-gpl-9.0 자산명·digest(sha256) 세 값을 그대로 옮긴다.
#   **sha256 를 지우고 넘어가지 말 것** — 그러면 공급망 검증이 사라진다.
#   `latest` 태그의 n9.0-latest 자산은 매일 바뀌어 sha256 핀이 깨진다 — 날짜 autobuild 를 쓴다.
ARG FFMPEG_TAG=autobuild-2026-09-07-15-39
ARG FFMPEG_ASSET=ffmpeg-n9.0.1-27-g9b0578816c-linux64-gpl-9.0.tar.xz
ARG FFMPEG_SHA256=e414c137c7d6ed089c75d0887165f9a5fc1feb38bb6883f31d27fef0c00a03e4
RUN curl -fsSL -o /tmp/ffmpeg.tar.xz \
      "https://github.com/BtbN/FFmpeg-Builds/releases/download/${FFMPEG_TAG}/${FFMPEG_ASSET}" \
    && echo "${FFMPEG_SHA256}  /tmp/ffmpeg.tar.xz" | sha256sum -c - \
    && mkdir -p /opt/ffmpeg \
    && tar -xJf /tmp/ffmpeg.tar.xz -C /opt/ffmpeg --strip-components=1 \
    && rm /tmp/ffmpeg.tar.xz

# 화자 임베딩 모델 (VOD 음성 화자 융합, 2026-09-05) — 3D-Speaker CAM++ zh_en advanced (27MB, sherpa-onnx 배포본).
# ffmpeg 와 같은 규칙: 고정 URL + sha256 검증. 릴리스 자산이 사라지면 같은 이름의 파일을 구해 sha256 을
# 대조한다(값은 docs/speaker-accuracy-eval-2026-09.md 에도 있다). **sha256 을 지우고 넘어가지 말 것.**
# 모델을 바꾸면 config.py 의 voice_cos_* 임계값을 scripts/eval_voice_calibration.py 로 다시 보정한다.
ARG SPK_MODEL_URL=https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx
ARG SPK_MODEL_SHA256=aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2
RUN mkdir -p /opt/models \
    && curl -fsSL -o /opt/models/speaker.onnx "${SPK_MODEL_URL}" \
    && echo "${SPK_MODEL_SHA256}  /opt/models/speaker.onnx" | sha256sum -c -

# 얼굴 인식 모델 (영상 화면 → 의원 이름, 2026-09-16) — insightface v0.7 릴리스 buffalo_l 에서
# **두 파일만** 꺼낸다: det_10g.onnx(SCRFD 검출 17MB) · w600k_r50.onnx(ArcFace 임베딩 174MB).
# 같은 묶음의 1k3d68(3D 랜드마크 143MB)·2d106det·genderage 는 쓰지 않으므로 버린다.
#
# ffmpeg·화자 모델과 같은 규칙: 고정 URL + sha256 검증. 여기서는 **묶음과 꺼낸 파일 둘 다** 검증한다
# (묶음만 맞추면 압축 안이 바뀌었을 때 못 잡는다). **sha256 을 지우고 넘어가지 말 것.**
# 임계값은 이 모델 쌍 기준으로 보정돼 있다 — 모델을 바꾸면 config.py 의 face_cos_* 를
# docs/face-recognition-eval-2026-09.md 의 실측으로 다시 정한다.
# unzip 을 apt 로 들이지 않는 이유: 베이스가 python 이라 zipfile 로 꺼내면 의존성이 늘지 않는다.
ARG FACE_PACK_URL=https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip
ARG FACE_PACK_SHA256=80ffe37d8a5940d59a7384c201a2a38d4741f2f3c51eef46ebb28218a7b0ca2f
ARG FACE_DET_SHA256=5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91
ARG FACE_REC_SHA256=4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43
RUN curl -fsSL -o /tmp/buffalo_l.zip "${FACE_PACK_URL}" \
    && echo "${FACE_PACK_SHA256}  /tmp/buffalo_l.zip" | sha256sum -c - \
    && mkdir -p /opt/models/face \
    && python -c "import zipfile; z=zipfile.ZipFile('/tmp/buffalo_l.zip'); [open('/opt/models/face/'+n.split('/')[-1],'wb').write(z.read(n)) for n in z.namelist() if n.endswith(('det_10g.onnx','w600k_r50.onnx'))]" \
    && echo "${FACE_DET_SHA256}  /opt/models/face/det_10g.onnx" | sha256sum -c - \
    && echo "${FACE_REC_SHA256}  /opt/models/face/w600k_r50.onnx" | sha256sum -c - \
    && rm /tmp/buffalo_l.zip

# 의존성 먼저 설치 (캐시 레이어 분리)
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# =============================================================================
# Runtime stage
# =============================================================================
FROM python:3.11-slim AS runtime

# 런타임 의존성만 (psycopg용 libpq. ffmpeg 는 builder 의 정적 바이너리로 대체)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# non-root user — UID/GID 를 숫자로 고정한다.
# k8s runAsNonRoot 는 이름 USER 를 검증하지 못해 CreateContainerConfigError 가 난다(2026-08-15 실제 발생).
RUN groupadd -g 10001 appuser && useradd -u 10001 -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# builder에서 설치한 의존성 복사
COPY --from=builder /install /usr/local
COPY --from=builder /opt/ffmpeg/bin/ffmpeg /usr/local/bin/ffmpeg

# STT 파이프라인이 기대하는 메이저 버전인지 스모크 (실패 시 빌드가 여기서 죽는 것이 의도)
RUN ffmpeg -version | grep -E '^ffmpeg version n9\.0' >/dev/null

# 화자 임베딩 모델 + 런타임 스모크 — 모델이 로드되지 않으면 빌드가 여기서 죽는다
COPY --from=builder /opt/models /app/models
RUN python -c "import sherpa_onnx, numpy; e = sherpa_onnx.SpeakerEmbeddingExtractor(sherpa_onnx.SpeakerEmbeddingExtractorConfig(model='/app/models/speaker.onnx', num_threads=1, provider='cpu')); assert e.dim == 192, e.dim"

# 얼굴 모델 + 런타임 스모크 — 검출기 출력 9개(stride 3종 × score/bbox/kps)와 임베딩 512차원을
# 여기서 확인한다. 모델이 바뀌어 구조가 달라지면 배포가 아니라 **빌드가** 죽는 것이 의도다.
COPY --from=builder /opt/models/face /app/models/face
RUN python -c "\
import onnxruntime as ort, numpy as np, cv2; \
d = ort.InferenceSession('/app/models/face/det_10g.onnx', providers=['CPUExecutionProvider']); \
r = ort.InferenceSession('/app/models/face/w600k_r50.onnx', providers=['CPUExecutionProvider']); \
assert len(d.get_outputs()) == 9, len(d.get_outputs()); \
out = r.run(None, {r.get_inputs()[0].name: np.zeros((1,3,112,112), dtype=np.float32)})[0]; \
assert out.shape == (1,512), out.shape; \
print('face models ok', cv2.__version__, ort.__version__)"

# 앱 코드 + 시작 스크립트
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser migrations/ ./migrations/
COPY --chown=appuser:appuser start.sh ./start.sh
RUN chmod +x /app/start.sh

# uploads 디렉토리 (볼륨 마운트 지점)
RUN mkdir -p /app/uploads/agenda_files /app/uploads/stenography \
    && chown -R appuser:appuser /app/uploads

USER 10001

# 환경변수 기본값 (런타임에 override 권장)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

EXPOSE 8000

# 헬스체크 (Docker native healthcheck)
# ${PORT:-8000}: 외부 런타임이 PORT 주입 시 존중, 아니면 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f "http://localhost:${PORT:-8000}/health" || exit 1

# start.sh가 $PORT 전개 + uvicorn 기동 담당
CMD ["/app/start.sh"]
