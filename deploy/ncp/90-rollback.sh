#!/usr/bin/env bash
# =============================================================================
#  90 · 롤백 / 긴급 차단 (poc-app 에서 실행) — 정본 11-rollback.sh 의 복제·개명판
#
#    bash /tmp/transcribe-90.sh --tag <태그>   특정 이미지 태그로 두 Deployment 동시 복귀
#    bash /tmp/transcribe-90.sh --close        긴급: Ingress 만 제거해 외부 접근 차단 (수 초)
#    bash /tmp/transcribe-90.sh --purge        자막 리소스 전체 제거 (허브·인프라 무손상)
#    bash /tmp/transcribe-90.sh --list         배포 이력·보관 이미지 tar 목록
#
#  DB 롤백 (Phase B 에서 문제가 났을 때):
#    1) 25-set-runtime-secret.sh 로 SUPABASE_URL/KEY 가 Secret 에 있는지 확인
#    2) DB_BACKEND=supabase bash /tmp/transcribe-35.sh   ← 컷오버 전 상태로 복귀
#    Supabase 는 컷오버 freeze 시점 그대로 남아 있다(해지 전 2주 병행 원칙).
# =============================================================================
set -uo pipefail

NS="ggc-poc"
API="ggc-live-transcribe-api"
WEB="ggc-live-transcribe-web"
CLIPPER="ggc-live-transcribe-clipper"   # 자동 클립 작업자 — api 와 같은 이미지(2026-09-10)
IMG_DIR="/var/lib/ggc-poc/images"
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

log()  { printf '\n[90] %s\n' "$*"; }
fail() { printf '\n[90] [중단] %s\n' "$*"; exit 1; }

ensure_image() {
  # 이미지가 GC 됐으면 보관 tar 에서 되살린다 — 레지스트리 없는 구성의 유일한 안전망.
  local base="$1" tag="$2"
  if sudo -n k3s crictl images 2>/dev/null | grep "$base" | grep "$tag" >/dev/null; then
    echo "  이미지 $base:$tag 존재"; return 0
  fi
  local tarpath="$IMG_DIR/$base-$tag.tar"
  [ -f "$tarpath" ] || fail "이미지 $base:$tag 가 없고 $tarpath 도 없다. 재빌드가 필요하다."
  log "이미지 GC 감지 — tar 에서 재import: $tarpath"
  sudo -n k3s ctr -n k8s.io images import "$tarpath" || fail "재import 실패"
}

case "${1:---list}" in

  --list)
    log "배포 이력"
    for d in $API $WEB $CLIPPER; do
      echo "  -- $d"
      kubectl -n $NS rollout history deploy/$d 2>/dev/null | sed 's/^/  /' || echo "  (없음)"
      kubectl -n $NS get deploy $d -o jsonpath='  현재: {.spec.template.spec.containers[0].image}{"\n"}' 2>/dev/null || true
    done
    log "보관 중인 이미지 tar"
    ls -1t "$IMG_DIR"/ggc-live-transcribe-*.tar 2>/dev/null | sed 's/^/  /' || echo "  (없음)"
    ;;

  --tag)
    TAG="${2:-}"
    [ -n "$TAG" ] || fail "--tag <태그> 형식으로 줄 것. 후보는 --list 로 확인한다."
    ensure_image "$API" "$TAG"
    ensure_image "$WEB" "$TAG"
    log "두 Deployment 를 $TAG 로 교체 (api·web 은 같은 소스 태그로 움직여야 한다)"
    kubectl -n $NS set image deploy/$API api="localhost/$API:$TAG" || fail "api set image 실패"
    kubectl -n $NS set image deploy/$WEB web="localhost/$WEB:$TAG" || fail "web set image 실패"
    # clipper 는 없던 시절 태그로 되돌리면 그 이미지에 작업자 모듈이 없다 — 그때는 멈춰 둔다
    if kubectl -n $NS get deploy/$CLIPPER >/dev/null 2>&1; then
      kubectl -n $NS set image deploy/$CLIPPER clipper="localhost/$API:$TAG" || fail "clipper set image 실패"
    fi
    kubectl -n $NS annotate deploy/$API deploy/$WEB kubernetes.io/change-cause="rollback to $TAG" --overwrite >/dev/null
    kubectl -n $NS rollout status deploy/$API --timeout=180s
    kubectl -n $NS rollout status deploy/$WEB --timeout=180s
    if kubectl -n $NS get deploy/$CLIPPER >/dev/null 2>&1 && \
       ! kubectl -n $NS rollout status deploy/$CLIPPER --timeout=120s; then
      echo "  clipper 가 이 태그에서 뜨지 않는다(자동 클립 이전 태그일 수 있다) — 멈춰 둔다:"
      kubectl -n $NS scale deploy/$CLIPPER --replicas=0
    fi
    ;;

  --close)
    log "긴급 차단 — Ingress 제거 (앱·데이터는 살아 있다)"
    kubectl -n $NS delete ingress $API $WEB --ignore-not-found
    echo
    echo "  외부 접근이 끊겼다. 확인: curl -sk -o /dev/null -w '%{http_code}\\n' https://\${LB_IP}/transcribe/login  (404 면 성공)"
    echo "  복구: EXPOSE=1 bash /tmp/transcribe-35.sh"
    echo "  더 강하게: kubectl -n $NS scale deploy/$API deploy/$WEB deploy/$CLIPPER --replicas=0"
    echo "  자동 클립만 멈추기: kubectl -n $NS scale deploy/$CLIPPER --replicas=0"
    ;;

  --purge)
    log "자막 서비스 리소스 전체 제거 (PVC·Secret 은 명시할 때만 지운다)"
    kubectl -n $NS delete ingress $API $WEB --ignore-not-found
    kubectl -n $NS delete deploy $API $WEB $CLIPPER --ignore-not-found
    kubectl -n $NS delete svc $API $WEB --ignore-not-found
    kubectl -n $NS delete middleware ggc-live-transcribe-strip-prefix --ignore-not-found 2>/dev/null || true
    echo
    echo "  PVC(업로드 자산)·Secret 은 남겨 두었다. 완전 폐기 시에만:"
    echo "    kubectl -n $NS delete pvc ggc-live-transcribe-uploads"
    echo "    kubectl -n $NS delete secret ggc-live-transcribe-runtime"
    echo "  허브 무손상 확인: curl -sk -o /dev/null -w '%{http_code}\\n' https://\${LB_IP}/api/health  (200)"
    ;;

  *)
    sed -n '3,15p' "$0"
    exit 2
    ;;
esac
