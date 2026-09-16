#!/usr/bin/env sh
# 백엔드 시작 스크립트
#
# 컨테이너 CMD/플랫폼 Start Command로 지정 시 $PORT 전개가 보장됨.
# 로컬/OCI/NCP에서 동일하게 동작 (PORT 미지정 시 8000 기본).

set -e

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

echo "[start] Launching uvicorn on ${HOST}:${PORT}"

exec uvicorn app.main:app \
    --host "${HOST}" \
    --port "${PORT}" \
    --workers 1 \
    --proxy-headers \
    --forwarded-allow-ips '*'
