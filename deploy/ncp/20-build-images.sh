#!/usr/bin/env bash
# =============================================================================
#  20 · 이미지 빌드 (poc-app 에서 sudo 로 실행)
#
#    $NORM deploy/ncp/20-build-images.sh | $SSH $APP 'cat > /tmp/transcribe-20.sh'
#    $SSH $APP 'sudo -n bash /tmp/transcribe-20.sh < /dev/null' < /dev/null
#
#  ⚠ 'bash -s' 로 넘기지 말 것 — apt-get install 이 stdin 으로 스크립트 뒷부분을 먹는다.
#
#  인프라 정본 07-build-image.sh 의 복제·개명판이다. 다른 점:
#    · 이미지가 2개다 (api = backend/, web = frontend/)
#    · 태그 파일이 /var/lib/ggc-poc/transcribe-current-tag 다 —
#      문서 허브의 current-tag 와 반드시 분리한다(섞이면 B 가 A 의 태그로 뜬다)
#  재실행 안전성: podman 은 없을 때만 설치, 같은 소스 해시 이미지는 빌드 생략,
#  이미지 tar 는 이미지별 최근 3개 보관(롤백 안전망).
# =============================================================================
set -euo pipefail

TARBALL="/tmp/ggc-transcribe-src.tgz"
IMG_DIR="/var/lib/ggc-poc/images"
TAG_FILE="/var/lib/ggc-poc/transcribe-current-tag"
API_IMAGE_NAME="localhost/ggc-live-transcribe-api"
WEB_IMAGE_NAME="localhost/ggc-live-transcribe-web"
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

log()  { printf '\n[20] %s\n' "$*"; }
fail() { printf '\n[20] [중단] %s\n' "$*"; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "sudo 로 실행해야 한다."
[ -f "$TARBALL" ]    || fail "$TARBALL 이 없다. 먼저 10-sync-source.sh 를 실행할 것."

# ── 0. 자원 점검 ─────────────────────────────────────────────────────────────
log "자원 점검"
DISK_AVAIL_GB=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
MEM_AVAIL_MB=$(free -m | awk '/^Mem:/{print $7}')
echo "  디스크 여유 ${DISK_AVAIL_GB} GiB · 메모리 가용 ${MEM_AVAIL_MB} MB · CPU $(nproc)"
[ "$DISK_AVAIL_GB" -ge 10 ] || fail "디스크 여유가 10 GiB 미만이다. 이미지 tar 정리 후 재시도할 것."
[ "$MEM_AVAIL_MB" -ge 2000 ] || fail "가용 메모리가 2 GB 미만이다. Next 빌드가 실패한다."

# ── 1. podman ────────────────────────────────────────────────────────────────
# docker 를 설치하지 말 것 — iptables FORWARD DROP 으로 flannel 이 끊긴다(정본 07 주석 참조).
if command -v podman >/dev/null 2>&1; then
  log "podman 이미 설치됨 ($(podman --version))"
else
  log "podman 설치"
  export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a
  apt-get update -qq
  apt-get install -y -qq podman
  echo "  $(podman --version)"
fi

# ── 2. 아웃바운드 사전 점검 ──────────────────────────────────────────────────
log "아웃바운드 점검"
getent hosts registry.npmjs.org >/dev/null || fail "DNS 실패 — acg-poc-app 아웃바운드 UDP 53 확인"
NPM_CODE=$(curl -s -m 20 -o /dev/null -w '%{http_code}' https://registry.npmjs.org/next || true)
[ "$NPM_CODE" = "200" ] || fail "registry.npmjs.org HTTP '$NPM_CODE' — 아웃바운드 TCP 443 확인"
GH_CODE=$(curl -s -m 20 -o /dev/null -w '%{http_code}' -L https://github.com/BtbN/FFmpeg-Builds/releases || true)
[ "$GH_CODE" = "200" ] || echo "  [주의] github.com HTTP '$GH_CODE' — ffmpeg 정적 바이너리 다운로드가 실패할 수 있다"

# ── 3. 소스 전개 ─────────────────────────────────────────────────────────────
SRC_SHA8=$(sha256sum "$TARBALL" | cut -c1-8)
TAG="${IMAGE_TAG:-$(date +%Y%m%d-%H%M)-$SRC_SHA8}"
log "소스 해시 $SRC_SHA8 · 태그 $TAG"

WORK=$(mktemp -d /var/tmp/ggc-transcribe-build-XXXXXX)
trap 'rm -rf "$WORK"' EXIT
tar -xzf "$TARBALL" -C "$WORK"
[ -d "$WORK/backend" ]  || fail "타르볼에 backend/ 가 없다."
[ -d "$WORK/frontend" ] || fail "타르볼에 frontend/ 가 없다."

# k8s/·deploy/ 만 정규화한다. backend/·frontend/ 소스는 건드리지 않는다 —
# 내용 해시가 바뀌면 podman 레이어 캐시가 깨진다. (Dockerfile 은 LF 로 관리된다)
log "BOM/CRLF 정규화 (k8s/ · deploy/ 만)"
find "$WORK/k8s" "$WORK/deploy" -type f \( -name '*.yaml' -o -name '*.yml' -o -name '*.sh' -o -name '*.sql' \) \
     -print0 | xargs -0 -r sed -i -e '1s/^\xEF\xBB\xBF//' -e 's/\r$//'

# ── 4. 빌드 ──────────────────────────────────────────────────────────────────
# 같은 소스 해시의 이미지가 "두 개 모두 같은 태그로" 있을 때만 생략한다.
# 한쪽만 있을 때 생략하면 태그 파일과 실재 이미지가 어긋나 배포가 깨진다.
EXISTING_API=$(k3s ctr -n k8s.io images ls -q 2>/dev/null | grep "^$API_IMAGE_NAME:.*-$SRC_SHA8$" | head -1 || true)
EXISTING_WEB=$(k3s ctr -n k8s.io images ls -q 2>/dev/null | grep "^$WEB_IMAGE_NAME:.*-$SRC_SHA8$" | head -1 || true)
if [ -n "$EXISTING_API" ] && [ -n "$EXISTING_WEB" ] && [ "${EXISTING_API#*:}" = "${EXISTING_WEB#*:}" ]; then
  TAG="${EXISTING_API#*:}"
  log "동일 소스의 이미지 쌍이 이미 있다 — 빌드를 건너뛴다 (태그 $TAG)"
  mkdir -p "$(dirname "$TAG_FILE")"
  printf '%s' "$TAG" > "$TAG_FILE"
  echo "  현재 태그를 $TAG_FILE 에 기록했다."
  exit 0
fi

# --network=host: 브리지를 만들지 않아 iptables 무개입 + systemd-resolved 스텁 DNS 문제 회피.
build_one() {
  local name="$1" ctx="$2" file="$3" short="$4"
  local image="$name:$TAG"
  log "$short 빌드 (수 분 소요)"
  podman build --network=host --pull=missing -f "$file" -t "$image" "$ctx"

  mkdir -p "$IMG_DIR"
  local tarpath="$IMG_DIR/${name##*/}-$TAG.tar"
  log "$short 내보내기 -> $tarpath"
  # docker-archive 고정 — oci-archive 는 무명 참조로 등록돼 파드가 안 뜬다(정본 07 주석 참조).
  podman save --format docker-archive -o "$tarpath" "$image"
  k3s ctr -n k8s.io images import "$tarpath"
  k3s ctr -n k8s.io images ls | grep "$image" >/dev/null || fail "$short: ctr 에 이미지가 보이지 않는다."
  k3s crictl images | grep "${name##*/}" >/dev/null    || fail "$short: crictl 에 이미지가 보이지 않는다(kubelet 이 못 본다)."
  echo "  $short: ctr · crictl 양쪽에서 확인됨"
}

build_one "$API_IMAGE_NAME" "$WORK/backend"  "$WORK/backend/Dockerfile"  "api"
build_one "$WEB_IMAGE_NAME" "$WORK/frontend" "$WORK/frontend/Dockerfile" "web"

# ── 5. 정리 ──────────────────────────────────────────────────────────────────
# 2026-08-18 디스크 사고 교훈: 루트 50GB 에 tar(백업)+containerd(가동)+podman(캐시)이
# 3중으로 쌓여 DiskPressure→전 파드 축출이 두 번 발생했다.
#  · tar 보존은 2세대로 축소 (롤백 안전망 유지 + 용량 절반)
#  · 빌드 완료 후 podman 쪽 앱 이미지 태그는 제거(containerd·tar 에 이미 있음).
#    베이스 이미지는 남겨 다음 빌드 캐시로 쓴다.
#  · ⚠ `crictl rmi --prune` 은 절대 금지 — 축출 등으로 파드가 없으면 "미사용" 판정이
#    현행 이미지까지 지워, 레지스트리 없는 이 구성에서 전 서비스가 ErrImagePull 이 된다
#    (2026-08-18 실제 발생, tar 재import 로 복구).
log "이미지 tar 정리 (2세대 보존)"
for base in ggc-live-transcribe-api ggc-live-transcribe-web; do
  ls -1t "$IMG_DIR"/$base-*.tar 2>/dev/null | tail -n +3 | while read -r old; do
    echo "  삭제 $old"; rm -f "$old"
  done
done

log "podman 앱 이미지 정리 (베이스 캐시는 보존)"
podman rmi "$API_IMAGE_NAME:$TAG" "$WEB_IMAGE_NAME:$TAG" >/dev/null 2>&1 || true
podman images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null \
  | grep -E '^localhost/ggc-live-transcribe' | xargs -r podman rmi -f >/dev/null 2>&1 || true
podman image prune -f >/dev/null 2>&1 || true

mkdir -p "$(dirname "$TAG_FILE")"
printf '%s' "$TAG" > "$TAG_FILE"

log "완료"
echo "  api: $API_IMAGE_NAME:$TAG"
echo "  web: $WEB_IMAGE_NAME:$TAG"
echo "  태그를 $TAG_FILE 에 기록했다. 35-deploy.sh 가 이 값을 읽는다."
