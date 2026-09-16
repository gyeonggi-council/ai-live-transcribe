#!/usr/bin/env bash
# =============================================================================
#  40 · 실시간 자막 서비스 검증 (poc-app 에서 실행)
#
#    $NORM deploy/ncp/40-verify-transcribe.sh | $SSH $APP 'cat > /tmp/transcribe-40.sh'
#    $SSH $APP 'bash /tmp/transcribe-40.sh < /dev/null' < /dev/null
#
#  09-verify-web.sh(문서 허브)의 복제·개명판. 09 를 대체하지 않는다 —
#  09 는 문서 허브, 이 스크립트는 자막 서비스의 별개 검증 주기다.
#  -e 를 쓰지 않는다. 실패해도 끝까지 확인하고 마지막에 PASS/FAIL 합계를 낸다.
#
#  Phase B(DB_BACKEND=postgres) 검증까지 하려면 환경변수를 준다:
#    EXPECT_DB_BACKEND=postgres bash /tmp/transcribe-40.sh
# =============================================================================
set -uo pipefail

NS="ggc-poc"
API="ggc-live-transcribe-api"
WEB="ggc-live-transcribe-web"
LB_IP="${LB_IP:-${GGC_LB_IP:?LB_IP 또는 GGC_LB_IP 가 필요하다}}"
NODEPORT_HTTPS="${NODEPORT_HTTPS:-30928}"
PUBLIC_IP="${PUBLIC_IP:-${GGC_PUBLIC_IP:?PUBLIC_IP 또는 GGC_PUBLIC_IP 가 필요하다}}"
EXPECT_DB_BACKEND="${EXPECT_DB_BACKEND:-supabase}"

PASS=0; FAIL=0
ok()    { echo -e "  \033[1;32mPASS\033[0m  $*"; PASS=$((PASS+1)); }
ng()    { echo -e "  \033[1;31mFAIL\033[0m  $*"; FAIL=$((FAIL+1)); }
skip()  { echo -e "  \033[1;33mSKIP\033[0m  $*"; }
head_() { echo -e "\n\033[1;36m$*\033[0m"; }

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

# -----------------------------------------------------------------------------
head_ "[1] 이미지"
for name in $API $WEB; do
  if sudo -n k3s crictl images 2>/dev/null | grep "$name" >/dev/null; then
    ok "$name 이미지가 kubelet 저장소에 있다"
  else
    ng "$name 이미지 없음 - 20-build-images.sh 를 실행할 것"
  fi
done

# -----------------------------------------------------------------------------
head_ "[2] Deployment 가용성"
for d in $API $WEB; do
  WANT=$(kubectl -n $NS get deploy $d -o jsonpath='{.spec.replicas}' 2>/dev/null)
  HAVE=$(kubectl -n $NS get deploy $d -o jsonpath='{.status.availableReplicas}' 2>/dev/null)
  if [ -n "$WANT" ] && [ "$WANT" = "${HAVE:-0}" ]; then
    echo "      $d: available $HAVE / desired $WANT · $(kubectl -n $NS get deploy $d -o jsonpath='{.spec.template.spec.containers[0].image}')"
    ok "$d 가용"
  else
    ng "$d 가용 레플리카 ${HAVE:-0} / 요구 ${WANT:-?}"
  fi
done

# -----------------------------------------------------------------------------
head_ "[3] 파드 상태·재시작"
API_POD=$(kubectl -n $NS get pods -l "app.kubernetes.io/name=$API" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
WEB_POD=$(kubectl -n $NS get pods -l "app.kubernetes.io/name=$WEB" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
for pod in $API_POD $WEB_POD; do
  [ -n "$pod" ] || { ng "파드를 찾을 수 없다"; continue; }
  PHASE=$(kubectl -n $NS get pod "$pod" -o jsonpath='{.status.phase}')
  RESTARTS=$(kubectl -n $NS get pod "$pod" -o jsonpath='{.status.containerStatuses[0].restartCount}')
  echo "      $pod  phase=$PHASE  restarts=$RESTARTS"
  [ "$PHASE" = "Running" ] && ok "$pod Running" || ng "$pod phase=$PHASE"
  if [ "${RESTARTS:-0}" -eq 0 ]; then ok "$pod 재시작 0회"; else
    ng "$pod 재시작 ${RESTARTS}회 - 이전 로그 확인"
    kubectl -n $NS logs "$pod" --previous --tail=20 2>/dev/null | sed 's/^/      /'
  fi
done

# -----------------------------------------------------------------------------
head_ "[4] G-NONROOT"
for d in $API $WEB; do
  UID_OUT=$(kubectl -n $NS exec "deploy/$d" -- id -u 2>/dev/null | tr -d '[:space:]')
  if [ -n "$UID_OUT" ] && [ "$UID_OUT" != "0" ]; then
    ok "$d 비루트 실행 (uid=$UID_OUT)"
  else
    ng "$d uid='$UID_OUT' (0 이거나 확인 불가)"
  fi
done

# -----------------------------------------------------------------------------
head_ "[5] ffmpeg (STT 전제조건)"
FFV=$(kubectl -n $NS exec "deploy/$API" -- ffmpeg -version 2>/dev/null | head -1)
if echo "$FFV" | grep -E '^ffmpeg version n9\.0' >/dev/null; then
  ok "ffmpeg 9.0 정적 바이너리 ($(echo "$FFV" | awk '{print $3}'))"
else
  ng "ffmpeg 확인 실패: '$FFV'"
fi

# -----------------------------------------------------------------------------
head_ "[5b] 자동 클립 작업자 (2026-09-10 — api 와 같은 이미지, cpu 1·mem 1Gi 한도)"
CLIPPER="ggc-live-transcribe-clipper"
if kubectl -n $NS get deploy $CLIPPER >/dev/null 2>&1; then
  C_IMG=$(kubectl -n $NS get deploy $CLIPPER -o jsonpath='{.spec.template.spec.containers[0].image}')
  A_IMG=$(kubectl -n $NS get deploy $API -o jsonpath='{.spec.template.spec.containers[0].image}')
  C_HAVE=$(kubectl -n $NS get deploy $CLIPPER -o jsonpath='{.status.availableReplicas}')
  C_LIM=$(kubectl -n $NS get deploy $CLIPPER -o jsonpath='{.spec.template.spec.containers[0].resources.limits.cpu}/{.spec.template.spec.containers[0].resources.limits.memory}')
  echo "      $CLIPPER: available ${C_HAVE:-0} · $C_IMG · limits $C_LIM"
  [ "$C_IMG" = "${A_IMG}" ] && ok "clipper 이미지 = api 이미지" || ng "clipper 이미지($C_IMG) ≠ api($A_IMG)"
  [ "${C_HAVE:-0}" = "1" ] && ok "clipper 가용" || ng "clipper 가용 레플리카 ${C_HAVE:-0}"
  [ "$C_LIM" = "1/1Gi" ] && ok "clipper 한도 cpu 1·mem 1Gi" || ng "clipper 한도가 $C_LIM — 서버 보호 한도가 풀렸다"
  if kubectl -n $NS logs deploy/$CLIPPER --tail=200 2>/dev/null | grep "자동 클립 작업자 시작" >/dev/null; then
    ok "clipper 기동 로그"
  else
    ng "clipper 기동 로그 없음 — kubectl -n $NS logs deploy/$CLIPPER"
  fi
else
  ng "$CLIPPER Deployment 없음"
fi

# -----------------------------------------------------------------------------
head_ "[6] Service 엔드포인트"
for s in $API $WEB; do
  EPS=$(kubectl -n $NS get endpointslice -l "kubernetes.io/service-name=$s" \
        -o jsonpath='{.items[*].endpoints[*].addresses[*]}' 2>/dev/null)
  [ -n "$EPS" ] && ok "$s 엔드포인트 존재 ($EPS)" || ng "$s 엔드포인트 비어 있음 - readiness 실패 또는 셀렉터 불일치"
done

# -----------------------------------------------------------------------------
head_ "[7] 파드 직결 / ClusterIP"
API_IP=$(kubectl -n $NS get pods -l "app.kubernetes.io/name=$API" -o jsonpath='{.items[0].status.podIP}' 2>/dev/null)
if [ -n "$API_IP" ]; then
  C=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://$API_IP:8000/health")
  [ "$C" = "200" ] && ok "api 파드 직결 /health 200" || ng "api 파드 직결 $C"
fi
WEB_IP=$(kubectl -n $NS get pods -l "app.kubernetes.io/name=$WEB" -o jsonpath='{.items[0].status.podIP}' 2>/dev/null)
if [ -n "$WEB_IP" ]; then
  C=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://$WEB_IP:3000/transcribe/login")
  [ "$C" = "200" ] && ok "web 파드 직결 /transcribe/login 200" || ng "web 파드 직결 $C"
fi
for s in $API $WEB; do
  CIP=$(kubectl -n $NS get svc $s -o jsonpath='{.spec.clusterIP}' 2>/dev/null)
  [ -n "$CIP" ] || { ng "$s ClusterIP 확인 불가"; continue; }
  case "$s" in
    $API) P="/health" ;; $WEB) P="/transcribe/login" ;;
  esac
  C=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://$CIP$P")
  [ "$C" = "200" ] && ok "$s ClusterIP 경유 200" || ng "$s ClusterIP 경유 $C"
done

# -----------------------------------------------------------------------------
head_ "[8] Ingress 라우트 (미노출 단계면 404 가 정상)"
if kubectl -n $NS get ingress $API >/dev/null 2>&1; then
  C=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "https://127.0.0.1:$NODEPORT_HTTPS/transcribe/health")
  [ "$C" = "200" ] && ok "NodePort /transcribe/health 200" || ng "NodePort /transcribe/health $C"
  C=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "https://$LB_IP/transcribe/login")
  [ "$C" = "200" ] && ok "klipper-lb /transcribe/login 200" || ng "klipper-lb /transcribe/login $C"

  # WebSocket 핸드셰이크 — Traefik 이 Upgrade 를 통과시키는지. 101 이면 성공.
  # --http1.1 필수: https 에서 h2 로 협상되면 Upgrade 헤더가 무효라 백엔드가 404 를 준다(검증 함정).
  WSC=$(curl -sk --http1.1 -o /dev/null -w '%{http_code}' --max-time 10 \
    -H 'Upgrade: websocket' -H 'Connection: Upgrade' \
    -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' -H 'Sec-WebSocket-Version: 13' \
    "https://$LB_IP/transcribe/ws/meetings/00000000-0000-0000-0000-000000000000/subtitles")
  [ "$WSC" = "101" ] && ok "WS 핸드셰이크 101" || ng "WS 핸드셰이크 $WSC (101 이어야 함)"

  # HTTP -> HTTPS
  R=$(curl -s -o /dev/null -w '%{http_code}|%{redirect_url}' --max-time 10 "http://$LB_IP/transcribe/login")
  case "$R" in
    30*https://*) ok "80 -> HTTPS 리다이렉트 ($R)" ;;
    *)            ng "리다이렉트되지 않는다: $R" ;;
  esac
else
  skip "Ingress 미적용 (1단계) - 노출 후 재검증할 것"
fi

# -----------------------------------------------------------------------------
head_ "[9] 인증 계약 (미인증 쓰기 차단)"
BASE_API="http://${API_IP:-127.0.0.1}:8000"
# POST /api/meetings 는 설계상 optional_auth(비로그인 허용, 도메인 화이트리스트)라 대상이 아니다.
# require_role("admin") 이 걸린 regenerate 로 인증 계약을 확인한다.
C=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -X POST "$BASE_API/api/meetings/00000000-0000-0000-0000-000000000000/regenerate")
case "$C" in
  401|403) ok "미인증 admin 쓰기 API $C" ;;
  *)       ng "미인증 admin 쓰기 API $C (401/403 이어야 함)" ;;
esac
C=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$BASE_API/api/channels")
[ "$C" = "200" ] && ok "공개 조회 API /api/channels 200" || ng "/api/channels $C"

# -----------------------------------------------------------------------------
head_ "[10] G-NOHSTS + 보안 헤더 (Ingress 있을 때만)"
if kubectl -n $NS get ingress $WEB >/dev/null 2>&1; then
  H=$(curl -ksI --max-time 10 "https://$LB_IP/transcribe/login")
  if echo "$H" | grep -i "strict-transport-security" >/dev/null; then
    ng "HSTS 가 켜져 있다 - 자체서명 구성에서 이 IP 전체가 브라우저에서 영구 차단된다. 즉시 제거할 것"
  else
    ok "HSTS 없음 (자체서명 구성에서 정상)"
  fi
  for h in "x-frame-options" "x-content-type-options"; do
    echo "$H" | grep -i "^$h" >/dev/null && ok "헤더 $h 존재" || ng "헤더 $h 없음"
  done
else
  skip "Ingress 미적용 - 헤더 검사는 노출 후"
fi

# -----------------------------------------------------------------------------
head_ "[11] 설정 주입 (값은 출력하지 않는다 — 길이만)"
if [ -n "$API_POD" ]; then
  DBB=$(kubectl -n $NS exec "$API_POD" -- printenv DB_BACKEND 2>/dev/null)
  [ "$DBB" = "$EXPECT_DB_BACKEND" ] && ok "DB_BACKEND=$DBB (기대값 일치)" || ng "DB_BACKEND='$DBB' (기대 $EXPECT_DB_BACKEND)"
  # 컷오버(2026-08-18) 전에는 false 가 필수였다 — Railway 가 같은 Supabase 를 봐서
  # 이중 STT·이중 과금이 났기 때문. 지금은 반대로 true 여야 정상이다: false 면 방송이
  # 열려도 자막이 안 나오고, 화면에 수동 시작 버튼이 없어 아무도 모른 채 끝난다.
  AUTO=$(kubectl -n $NS exec "$API_POD" -- printenv STT_AUTO_START 2>/dev/null)
  [ "$AUTO" = "true" ] && ok "STT_AUTO_START=true (방송 감지 시 자동 자막)" || ng "STT_AUTO_START='$AUTO' — 방송이 열려도 자막이 안 나온다!"
  # 동시 채널 상한 — 2026-07-21 사고(상한 8에서 슬롯 강탈)의 교훈값이 14다.
  CAP=$(kubectl -n $NS exec "$API_POD" -- printenv STT_MAX_CONCURRENT_CHANNELS 2>/dev/null)
  [ "${CAP:-0}" -ge 14 ] 2>/dev/null && ok "STT_MAX_CONCURRENT_CHANNELS=$CAP (상임위 13 + 본회의 커버)" \
    || ng "STT_MAX_CONCURRENT_CHANNELS='$CAP' — 상임위 다수 개회일에 일부 채널 자막 누락"
  for key in OPENAI_API_KEY JWT_SECRET_KEY; do
    LEN=$(kubectl -n $NS exec "$API_POD" -- sh -c "printenv $key | wc -c" 2>/dev/null | tr -d '[:space:]')
    [ "${LEN:-0}" -gt 1 ] && ok "$key 주입됨 (${LEN}바이트)" || ng "$key 가 비어 있다"
  done
  if [ "$EXPECT_DB_BACKEND" = "postgres" ]; then
    for key in SUPABASE_URL SUPABASE_KEY; do
      LEN=$(kubectl -n $NS exec "$API_POD" -- sh -c "printenv $key 2>/dev/null | wc -c" 2>/dev/null | tr -d '[:space:]')
      [ "${LEN:-0}" -le 1 ] && ok "$key 부재 (postgres 모드에서 정상)" || ng "$key 가 여전히 주입돼 있다 (${LEN}바이트)"
    done
    # G-DEPS: 파드 안에서 poc-db 실연결
    if kubectl -n $NS exec "$API_POD" -- python -c \
"import os,psycopg;c=psycopg.connect(os.environ['DATABASE_URL'],connect_timeout=5);print(c.execute('SELECT count(*) FROM subtitle.subtitles').fetchone()[0]);c.close()" \
       >/dev/null 2>&1; then
      ok "G-DEPS: 파드 -> poc-db subtitle.subtitles 조회 성공"
    else
      ng "G-DEPS: 파드에서 poc-db 연결 실패"
    fi
  fi
else
  ng "api 파드가 없어 설정 주입을 확인할 수 없다"
fi

# -----------------------------------------------------------------------------
if [ "${EXPECT_BRIDGE:-0}" = "1" ]; then
  head_ "[11b] PostgREST 브리지 (클라우드 절단 확인)"
  SURL=$(kubectl -n $NS exec "$API_POD" -- printenv SUPABASE_URL 2>/dev/null)
  case "$SURL" in
    http://ggc-live-transcribe-pgrst*) ok "SUPABASE_URL 이 클러스터 내부 브리지 ($SURL)" ;;
    *) ng "SUPABASE_URL='$SURL' — 아직 클라우드를 본다" ;;
  esac
  PW=$(kubectl -n $NS get deploy ggc-live-transcribe-pgrst -o jsonpath='{.status.availableReplicas}' 2>/dev/null)
  [ "${PW:-0}" -ge 1 ] && ok "pgrst 브리지 가용" || ng "pgrst 브리지 미가용"
  # api 파드에서 클라우드 도메인 참조가 남았는지 (env 전수)
  CLOUD=$(kubectl -n $NS exec "$API_POD" -- sh -c 'env | grep -c "supabase\.co"' 2>/dev/null | tr -d '[:space:]')
  [ "${CLOUD:-0}" = "0" ] && ok "api env 에 supabase.co 참조 0건" || ng "api env 에 supabase.co 참조 ${CLOUD}건 (백업 키 제외 확인 필요)"
fi

# -----------------------------------------------------------------------------
head_ "[12] G-HUB-ALIVE (문서 허브 무영향)"
C=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "https://$LB_IP/api/health")
[ "$C" = "200" ] && ok "문서 허브 /api/health 200 - 허브가 깨지지 않았다" || ng "문서 허브 /api/health $C"

# -----------------------------------------------------------------------------
head_ "[13] 최근 오류 로그 (api, 10분)"
if [ -n "$API_POD" ]; then
  ERRS=$(kubectl -n $NS logs "$API_POD" --since=10m 2>/dev/null | grep -Ei 'traceback|ffmpeg.*(not found|missing)|ECONNREFUSED|CRITICAL' | head -5)
  if [ -z "$ERRS" ]; then ok "최근 10분 치명 오류 없음"; else
    ng "오류 로그 발견:"; echo "$ERRS" | sed 's/^/      /'
  fi
fi

# -----------------------------------------------------------------------------
echo ""
echo "==============================================================="
echo " 결과  PASS: $PASS   FAIL: $FAIL   (기대 DB_BACKEND=$EXPECT_DB_BACKEND)"
echo "==============================================================="
[ "$FAIL" -eq 0 ]
