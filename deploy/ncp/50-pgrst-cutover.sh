#!/usr/bin/env bash
# =============================================================================
#  50 · PostgREST 브리지 배포 + Supabase 클라우드 절단 (poc-app 에서 실행, sudo 불필요)
#
#    stdin 1줄: poc-db ggc_subtitle 비밀번호 (로컬 래퍼 run-50 이 점프로 취득해 파이프)
#
#  ⚠ 실행 순서 계약: 반드시 "직전"에 run-31b-local.sh(최종 데이터 동기화)를 돌린 뒤 실행할 것.
#    절단 후 앱 쓰기는 poc-db 로 가므로, 절단 후에 31b 를 돌리면 새 데이터가 지워진다.
#
#  하는 일 (멱등):
#    1. Secret ggc-live-transcribe-pgrst 적용 — PGRST_DB_URI + PGRST_JWT_SECRET(있으면 보존)
#    2. SUPABASE_KEY = {role:"ggc_subtitle"} HS256 JWT 민팅(python3 stdlib) →
#       runtime Secret 의 SUPABASE_URL/KEY 를 클러스터 내부 브리지로 교체
#    3. 브리지 매니페스트 apply(/tmp/ggc-transcribe-src.tgz 의 k8s/) → 스모크
#    4. api 재기동 → 파드 경유 스모크
#  롤백: SUPABASE_URL/KEY 를 클라우드 값으로 원복(25b)하고 api 재기동.
# =============================================================================
set -euo pipefail

NS="ggc-poc"
BRIDGE_URL="http://ggc-live-transcribe-pgrst:8080"
TARBALL="/tmp/ggc-transcribe-src.tgz"
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

log()  { printf '\n[50] %s\n' "$*"; }
fail() { printf '\n[50] [중단] %s\n' "$*"; exit 1; }

IFS= read -r DBPW || true
[ -n "${DBPW:-}" ] || fail "stdin 1행(poc-db ggc_subtitle 비밀번호)이 비어 있다."

get_secret() { kubectl -n "$NS" get secret "$1" -o jsonpath="{.data.$2}" 2>/dev/null | base64 -d 2>/dev/null || true; }

# ── 1. 브리지 Secret ─────────────────────────────────────────────────────────
JWT_SECRET="$(get_secret ggc-live-transcribe-pgrst PGRST_JWT_SECRET)"
if [ -n "$JWT_SECRET" ]; then
  log "PGRST_JWT_SECRET 보존"
else
  log "PGRST_JWT_SECRET 신규 생성"
  JWT_SECRET="$(openssl rand -hex 32)"
fi
DB_URI="postgresql://ggc_subtitle:${DBPW}@${GGC_DB_HOST:?GGC_DB_HOST 가 필요하다}:5432/ggcpoc"
umask 077
kubectl -n "$NS" create secret generic ggc-live-transcribe-pgrst \
  --from-literal=PGRST_DB_URI="$DB_URI" \
  --from-literal=PGRST_JWT_SECRET="$JWT_SECRET" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
unset DBPW DB_URI
echo "  Secret ggc-live-transcribe-pgrst 적용"

# ── 2. SUPABASE_KEY(브리지용 JWT) 민팅 + runtime Secret 교체 ─────────────────
log "브리지용 JWT 민팅 (role=ggc_subtitle, 만료 10년)"
BRIDGE_KEY="$(JWT_SECRET="$JWT_SECRET" python3 - <<'PY'
import base64, hashlib, hmac, json, os, time
def b64u(b): return base64.urlsafe_b64encode(b).rstrip(b"=")
secret = os.environ["JWT_SECRET"].encode()
h = b64u(json.dumps({"alg":"HS256","typ":"JWT"},separators=(",",":")).encode())
p = b64u(json.dumps({"role":"ggc_subtitle","iss":"ggc-poc","exp":int(time.time())+315360000},separators=(",",":")).encode())
sig = b64u(hmac.new(secret, h+b"."+p, hashlib.sha256).digest())
print((h+b"."+p+b"."+sig).decode())
PY
)"
[ -n "$BRIDGE_KEY" ] || fail "JWT 민팅 실패"

# 클라우드 원복용으로 현재 값 키 이름에 백업(값은 Secret 안에만 존재)
OLD_URL="$(get_secret ggc-live-transcribe-runtime SUPABASE_URL)"
OLD_KEY="$(get_secret ggc-live-transcribe-runtime SUPABASE_KEY)"
BACKUP_ARGS=()
case "$OLD_URL" in
  http://ggc-live-transcribe-pgrst*) echo "  이미 브리지를 보고 있다 — 클라우드 백업 생략" ;;
  "") ;;
  *) BACKUP_ARGS=( "{\"stringData\":{\"SUPABASE_URL_CLOUD_BACKUP\":\"$OLD_URL\"}}" )
     kubectl -n "$NS" patch secret ggc-live-transcribe-runtime -p "${BACKUP_ARGS[0]}" >/dev/null
     P=$(printf '{"stringData":{"SUPABASE_KEY_CLOUD_BACKUP":"%s"}}' "$OLD_KEY")
     kubectl -n "$NS" patch secret ggc-live-transcribe-runtime -p "$P" >/dev/null
     echo "  클라우드 URL/KEY 를 *_CLOUD_BACKUP 키로 보존(롤백용)" ;;
esac
P=$(printf '{"stringData":{"SUPABASE_URL":"%s","SUPABASE_KEY":"%s"}}' "$BRIDGE_URL" "$BRIDGE_KEY")
kubectl -n "$NS" patch secret ggc-live-transcribe-runtime -p "$P" >/dev/null
unset OLD_KEY P
echo "  runtime Secret: SUPABASE_URL=$BRIDGE_URL (KEY 는 브리지 JWT 로 교체)"

# ── 3. 브리지 배포 ───────────────────────────────────────────────────────────
SRC_DIR=$(mktemp -d /var/tmp/ggc-pgrst-XXXXXX)
trap 'rm -rf "$SRC_DIR"' EXIT
[ -f "$TARBALL" ] || fail "$TARBALL 이 없다. 10-sync-source.sh 를 먼저 실행할 것."
tar -xzf "$TARBALL" -C "$SRC_DIR" k8s
find "$SRC_DIR/k8s" -type f -name '*.yaml' -print0 | xargs -0 -r sed -i -e '1s/^\xEF\xBB\xBF//' -e 's/\r$//'
[ -f "$SRC_DIR/k8s/ggc-live-transcribe-pgrst.yaml" ] || fail "pgrst 매니페스트가 타르볼에 없다."
log "브리지 apply + 롤아웃"
kubectl apply -f "$SRC_DIR/k8s/ggc-live-transcribe-pgrst.yaml"
kubectl -n "$NS" rollout restart deploy/ggc-live-transcribe-pgrst >/dev/null 2>&1 || true
kubectl -n "$NS" rollout status deploy/ggc-live-transcribe-pgrst --timeout=180s

log "브리지 스모크 (api 파드에서 curl — 임시 파드 불필요)"
SMOKE=$(kubectl -n "$NS" exec deploy/ggc-live-transcribe-api -- \
  sh -c "curl -s -o /dev/null -w '%{http_code}' --max-time 15 \
    -H 'apikey: $BRIDGE_KEY' -H 'Authorization: Bearer $BRIDGE_KEY' \
    '$BRIDGE_URL/rest/v1/subtitles?select=id&limit=1'" 2>/dev/null | tr -dc '0-9' | tail -c 3)
if [ "$SMOKE" != "200" ]; then
  echo "  --- pgrst 로그 ---"
  kubectl -n "$NS" logs deploy/ggc-live-transcribe-pgrst -c postgrest --tail=8 2>/dev/null | sed 's/^/    /'
  fail "브리지 스모크 '$SMOKE' (200 이어야 함)"
fi
echo "  브리지 경유 subtitles 조회 200"
unset BRIDGE_KEY JWT_SECRET

# ── 4. api 절단 재기동 ───────────────────────────────────────────────────────
log "api 재기동 (이 순간부터 클라우드 이탈)"
kubectl -n "$NS" rollout restart deploy/ggc-live-transcribe-api
kubectl -n "$NS" rollout status deploy/ggc-live-transcribe-api --timeout=300s
IP=$(kubectl -n "$NS" get pods -l app.kubernetes.io/name=ggc-live-transcribe-api -o jsonpath='{.items[0].status.podIP}')
for path in "/api/meetings?limit=1" "/api/meetings/ch1/subtitles?limit=1"; do
  C=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "http://$IP:8000$path")
  echo "  GET $path -> $C"
done

log "완료 — Supabase 클라우드가 런타임 경로에서 제거됐다."
echo "  다음: EXPECT_BRIDGE=1 bash /tmp/transcribe-40.sh (확장 검증) + 방송일 실채널 E2E"
echo "  롤백: runtime Secret 의 *_CLOUD_BACKUP 값으로 SUPABASE_URL/KEY 원복 후 api 재기동"
