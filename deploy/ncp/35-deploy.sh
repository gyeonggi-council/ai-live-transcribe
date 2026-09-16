#!/usr/bin/env bash
# =============================================================================
#  35 · 배포 (poc-app 에서 실행. sudo 불필요 — kubeconfig 가 644 다)
#
#    $NORM deploy/ncp/35-deploy.sh | $SSH $APP 'cat > /tmp/transcribe-35.sh'
#    $SSH $APP 'bash /tmp/transcribe-35.sh < /dev/null' < /dev/null            # 1단계: 워크로드만
#    $SSH $APP 'EXPOSE=1 bash /tmp/transcribe-35.sh < /dev/null' < /dev/null   # 2단계: Ingress 포함
#
#  환경변수:
#    IMAGE_TAG    특정 태그로 배포 (기본: 20 이 기록한 /var/lib/ggc-poc/transcribe-current-tag)
#    EXPOSE=1     Ingress 까지 apply — ⚠ ACG 가 허용하는 모든 출발지에 공개된다.
#                 검증(40-verify)이 전 항목 PASS 인 뒤에만 쓸 것 (2단계 노출 원칙)
#    DB_BACKEND   supabase | postgres — 지정하면 매니페스트 값을 덮어쓴다 (컷오버·롤백용)
#
#  불변식: TLS 인증서·기존 Secret 은 여기서 만들지도 재생성하지도 않는다.
#          (인증서는 문서 허브 08 이 부트스트랩한 클러스터 공유 자원이다)
# =============================================================================
set -euo pipefail

NS="ggc-poc"
API_IMAGE_NAME="localhost/ggc-live-transcribe-api"
WEB_IMAGE_NAME="localhost/ggc-live-transcribe-web"
TAG_FILE="/var/lib/ggc-poc/transcribe-current-tag"
TARBALL="/tmp/ggc-transcribe-src.tgz"
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

log()  { printf '\n[35] %s\n' "$*"; }
fail() { printf '\n[35] [중단] %s\n' "$*"; exit 1; }

# ── 0. 매니페스트 전개 ───────────────────────────────────────────────────────
SRC_DIR=$(mktemp -d /var/tmp/ggc-transcribe-deploy-XXXXXX)
trap 'rm -rf "$SRC_DIR"' EXIT
[ -f "$TARBALL" ] || fail "$TARBALL 이 없다. 10-sync-source.sh 를 먼저 실행할 것."
tar -xzf "$TARBALL" -C "$SRC_DIR" k8s
find "$SRC_DIR/k8s" -type f -name '*.yaml' -print0 \
  | xargs -0 -r sed -i -e '1s/^\xEF\xBB\xBF//' -e 's/\r$//'
MAIN="$SRC_DIR/k8s/ggc-live-transcribe.yaml"
INGRESS="$SRC_DIR/k8s/ggc-live-transcribe-ingress.yaml"
[ -f "$MAIN" ]    || fail "$MAIN 이 없다."
[ -f "$INGRESS" ] || fail "$INGRESS 가 없다."

TAG="${IMAGE_TAG:-$(cat "$TAG_FILE" 2>/dev/null || true)}"
[ -n "$TAG" ] || fail "태그를 알 수 없다. 20-build-images.sh 를 먼저 실행하거나 IMAGE_TAG 를 지정할 것."

# ── 1. 선행 조건 검사 ────────────────────────────────────────────────────────
log "이미지 존재 확인 (태그 $TAG)"
for name in ggc-live-transcribe-api ggc-live-transcribe-web; do
  sudo -n k3s crictl images 2>/dev/null | grep "$name" | grep "$TAG" >/dev/null \
    || fail "이미지 $name:$TAG 가 노드에 없다. 20-build-images.sh 를 먼저 실행할 것."
done
echo "  확인됨"

kubectl -n "$NS" get secret ggc-live-transcribe-runtime >/dev/null 2>&1 \
  || fail "Secret ggc-live-transcribe-runtime 이 없다. 25-set-runtime-secret.sh 를 먼저 실행할 것."
kubectl -n "$NS" get secret openai-api >/dev/null 2>&1 \
  || fail "공유 Secret openai-api 가 없다 — 클러스터 상태를 확인할 것."

if [ "${DB_BACKEND:-}" = "postgres" ]; then
  kubectl -n "$NS" get secret ggc-live-transcribe-runtime -o jsonpath='{.data.DATABASE_URL}' 2>/dev/null | grep . >/dev/null \
    || fail "DB_BACKEND=postgres 인데 Secret 에 DATABASE_URL 이 없다. 25 를 --phase-b 로 재실행할 것."
fi

# ── 2. 렌더·적용 ─────────────────────────────────────────────────────────────
log "매니페스트 적용 (워크로드)"
RENDERED="$SRC_DIR/rendered.yaml"
sed -e "s|$API_IMAGE_NAME:REPLACE_WITH_GIT_SHA|$API_IMAGE_NAME:$TAG|g" \
    -e "s|$WEB_IMAGE_NAME:REPLACE_WITH_GIT_SHA|$WEB_IMAGE_NAME:$TAG|g" \
    "$MAIN" > "$RENDERED"
if [ -n "${DB_BACKEND:-}" ]; then
  case "$DB_BACKEND" in supabase|postgres) ;; *) fail "DB_BACKEND 는 supabase|postgres 만 허용" ;; esac
  sed -i "s|{ name: DB_BACKEND, value: \"[a-z]*\" }|{ name: DB_BACKEND, value: \"$DB_BACKEND\" }|" "$RENDERED"
  echo "  DB_BACKEND=$DB_BACKEND 로 덮어씀"
fi
# 공인 IP 는 저장소에 두지 않는다 — 배포 시점에 주입한다(2026-08-23).
sed -i "s|__PUBLIC_IP__|${GGC_PUBLIC_IP:?GGC_PUBLIC_IP 가 필요하다 (CORS_ORIGINS 주입용)}|g" "$RENDERED"
if grep '__PUBLIC_IP__' "$RENDERED" >/dev/null; then
  fail "공인 IP 치환이 안 된 항목이 있다."
fi
if grep 'REPLACE_WITH_GIT_SHA' "$RENDERED" >/dev/null; then
  fail "이미지 태그 치환이 안 된 항목이 있다."
fi
kubectl apply -f "$RENDERED"
kubectl -n "$NS" annotate deploy/ggc-live-transcribe-api deploy/ggc-live-transcribe-web deploy/ggc-live-transcribe-clipper \
  kubernetes.io/change-cause="deploy $TAG (DB_BACKEND=${DB_BACKEND:-manifest})" --overwrite >/dev/null

# ── 3. 롤아웃 ────────────────────────────────────────────────────────────────
# api 는 strategy: Recreate 라 구 파드 종료 → 신 파드 기동 순서다. 잠깐의 단절은 정상.
# clipper(자동 클립 작업자, 2026-09-10)는 api 와 같은 이미지다 — 종료 시 도는 잡을 queued 로 되돌린다.
for d in ggc-live-transcribe-api ggc-live-transcribe-web ggc-live-transcribe-clipper; do
  log "롤아웃 대기: $d (최대 300초)"
  if ! kubectl -n "$NS" rollout status "deploy/$d" --timeout=300s; then
    echo "  롤아웃 실패. 진단:"
    kubectl -n "$NS" get pods -l "app.kubernetes.io/name=$d" -o wide || true
    kubectl -n "$NS" describe deploy "$d" | tail -25 || true
    kubectl -n "$NS" logs "deploy/$d" --tail=50 || true
    exit 1
  fi
done

# ── 4. 노출 (2단계) ──────────────────────────────────────────────────────────
if [ "${EXPOSE:-0}" = "1" ]; then
  log "Ingress 적용 — 외부 노출"
  kubectl apply -f "$INGRESS"
  echo "  https://${GGC_PUBLIC_IP:-<공인 IP>}/transcribe (ACG 허용 출발지에서만 도달)"
else
  log "Ingress 는 적용하지 않았다 (1단계)"
  echo "  내부 검증: kubectl -n $NS port-forward svc/ggc-live-transcribe-web 13000:80"
  echo "  노출하려면: 40-verify 전 항목 PASS 확인 후 EXPOSE=1 bash /tmp/transcribe-35.sh"
fi

log "완료 — 다음: 40-verify-transcribe.sh"
