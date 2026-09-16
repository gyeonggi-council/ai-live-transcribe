#!/usr/bin/env bash
# =============================================================================
#  10 · 소스 전송 (로컬 실행 — Git Bash, cwd = 저장소 루트 D:\ggc-services\ggc-ai-live-transcribe)
#
#    bash deploy/ncp/10-sync-source.sh
#
#  backend/ · frontend/ · k8s/ · deploy/ncp/ 를 재현 가능한 타르볼로 묶어 poc-app 으로 보낸다.
#  구조·안전장치는 인프라 쪽 동기화 스크립트를 복제·개명한 것이다:
#    1. 화이트리스트 — 저장소 루트를 통째로 tar 하지 않고 네 디렉터리만 열거
#    2. 목록 검사   — 비밀로 보이는 파일이 하나라도 섞이면 전송하지 않고 중단
# =============================================================================
set -euo pipefail

# 서버 주소는 저장소에 두지 않는다 — deploy/ncp/env.sh (gitignore) 에서 읽는다.
_ENVF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"
[ -f "$_ENVF" ] || { echo "[중단] $_ENVF 가 없다. deploy/ncp/env.sh.example 를 복사해 값을 채울 것."; exit 1; }
# shellcheck source=/dev/null
. "$_ENVF"

APP_HOST="${APP_HOST:-$GGC_APP_HOST}"
KEY="${KEY:-$GGC_SSH_KEY}"
SRC="$(pwd)"
TARBALL_REMOTE="/tmp/ggc-transcribe-src.tgz"

SSH="ssh -i $KEY -o BatchMode=yes -o StrictHostKeyChecking=no \
     -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
     -o ServerAliveInterval=30 -o ServerAliveCountMax=20"

log() { printf '\n[10] %s\n' "$*"; }

for d in backend frontend k8s deploy/ncp; do
  [ -d "$SRC/$d" ] || { echo "  [중단] $d/ 가 없다. cwd 가 저장소 루트인지 확인할 것."; exit 1; }
done

# GNU tar 여야 한다. Windows 기본 tar.exe(bsdtar)는 파일명을 CP949 로 기록해 서버에서 깨진다.
if ! tar --version 2>/dev/null | head -1 | grep "GNU tar" >/dev/null; then
  echo "  [중단] GNU tar 가 아니다. Git Bash 의 /usr/bin/tar 를 쓸 것."
  exit 1
fi

# CRLF 가드 — Windows 체크아웃(autocrlf)이 만든 CRLF .sh 가 이미지에 들어가면
# 컨테이너가 `env: 'sh\r': No such file or directory` 로 CrashLoop 한다(2026-08-18 실제 발생).
# .gitattributes 가 LF 를 강제하지만, attributes 이전에 체크아웃된 사본을 잡는 마지막 그물이다.
log "CRLF 혼입 검사 (*.sh)"
# ⚠ $'\r' 를 쓰지 말 것 — Git Bash 가 스크립트를 igncr 로 읽어 CR 이 소거되면 패턴이
#   빈 문자열이 되어 전 파일에 매치된다(거짓 양성, 2026-08-18 실측). awk 의 /\r$/ 는
#   백슬래시-r 을 awk 가 해석하므로 bash 단계에 CR 문자가 등장하지 않아 안전하다.
CRLF_HITS=$(find backend frontend k8s deploy/ncp -type f -name '*.sh' -print0 2>/dev/null \
  | xargs -0 -r awk '/\r$/ { print FILENAME; nextfile }' | sort -u)
if [ -n "$CRLF_HITS" ]; then
  echo "  [중단] CRLF 가 섞인 스크립트가 있다. 고치는 법:"
  echo "    git config core.autocrlf false && git ls-files -z | xargs -0 rm -f && git checkout -- ."
  echo "$CRLF_HITS" | head -10 | sed 's/^/    /'
  exit 1
fi
echo "  이상 없음"

log "타르볼 생성 (재현 가능 옵션 — 같은 소스면 같은 해시)"
TMPD="$(mktemp -d -t ggc-transcribe-src-XXXXXX)"
trap 'rm -rf "$TMPD"' EXIT
TB="$TMPD/src.tgz"

# ⚠ 제외 패턴에 './' 접두를 붙이지 말 것 — `-C "$SRC" backend` 열거 방식에서는 매치되지 않는다.
tar --sort=name --mtime='@0' --owner=0 --group=0 --numeric-owner -I 'gzip -n' \
    --exclude='frontend/node_modules' \
    --exclude='frontend/.next' \
    --exclude='backend/.venv' \
    --exclude='backend/__pycache__' \
    --exclude='*/__pycache__' \
    --exclude='*.pyc' \
    --exclude='backend/.pytest_cache' \
    --exclude='backend/htmlcov' \
    --exclude='*/.env' \
    --exclude='*/.env.*' \
    --exclude='*.log' \
    --exclude='.DS_Store' \
    --exclude='Thumbs.db' \
    -cf "$TB" -C "$SRC" backend frontend k8s deploy/ncp

log "비밀 파일 혼입 검사"
# grep -q 금지 — 첫 매치에서 파이프를 닫아 tar 를 SIGPIPE 로 죽이고 pipefail 이 오탐한다.
if tar -tzf "$TB" | grep -E '(^|/)(keys/|logs/|\.env$|\.env\.|.*\.pem$|.*\.key$|.*credentials.*|.*secret.*\.json$)' >/dev/null; then
  echo "  [중단] 타르볼에 비밀로 보이는 파일이 포함되었다. 전송하지 않는다:"
  tar -tzf "$TB" | grep -E '(^|/)(keys/|logs/|\.env$|\.env\.|.*\.pem$|.*\.key$|.*credentials.*|.*secret.*\.json$)' | head -20
  exit 1
fi
echo "  이상 없음 (파일 $(tar -tzf "$TB" | wc -l)개)"

SRC_SHA="$(sha256sum "$TB" | cut -d' ' -f1)"
SRC_SHA8="${SRC_SHA:0:8}"
log "전송  sha256=$SRC_SHA8…  크기 $(wc -c < "$TB") bytes"

$SSH "$APP_HOST" "cat > $TARBALL_REMOTE" < "$TB"

REMOTE_SHA="$($SSH "$APP_HOST" "sha256sum $TARBALL_REMOTE" < /dev/null | cut -d' ' -f1)"
if [ "$SRC_SHA" != "$REMOTE_SHA" ]; then
  echo "  [중단] 해시 불일치. 로컬=$SRC_SHA 원격=$REMOTE_SHA"
  exit 1
fi

log "완료 — 원격 해시 일치"
echo "  소스 해시(태그에 쓰인다): $SRC_SHA8"
echo
echo "  다음:"
echo "    \$NORM deploy/ncp/20-build-images.sh | \$SSH \$APP 'cat > /tmp/transcribe-20.sh'"
echo "    \$SSH \$APP 'sudo -n bash /tmp/transcribe-20.sh < /dev/null' < /dev/null"
