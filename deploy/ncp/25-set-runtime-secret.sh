#!/usr/bin/env bash
# =============================================================================
#  25 · 런타임 Secret 등록 (poc-app 에서 대화형으로 실행 — ssh -t 로 접속해 직접 실행)
#
#    ssh -t -i keys/ggc-poc ncloud@<poc-app 공인 IP> 'bash /tmp/transcribe-25.sh'
#
#  ⚠ 이 스크립트만 '< /dev/null' 규칙의 예외다(대화형 입력이 목적). 08b 와 같은 지위.
#     안에 stdin 을 먹는 apt-get/dpkg 가 없어 그 함정에 걸리지 않는다.
#
#  만드는 것: Secret ggc-live-transcribe-runtime (네임스페이스 ggc-poc)
#    SUPABASE_URL / SUPABASE_KEY : Phase A(하이브리드) 동안만. 컷오버 후 키에서 제거
#    JWT_SECRET_KEY              : 없을 때만 생성 — 재생성하면 전 사용자 세션이 무효가 된다
#    ADMIN_QUICK_PIN             : 프롬프트 입력
#    DATABASE_URL                : Phase B 에서만 (--phase-b 플래그)
#
#  불변식: 값은 화면·파일·로그 어디에도 남기지 않는다. read -s + 프로세스 환경만 쓴다.
#  OPENAI_API_KEY 는 여기 넣지 않는다 — 기존 openai-api Secret 을 매니페스트가 참조한다.
# =============================================================================
set -euo pipefail

NS="ggc-poc"
SECRET="ggc-live-transcribe-runtime"
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

log()  { printf '\n[25] %s\n' "$*"; }
fail() { printf '\n[25] [중단] %s\n' "$*"; exit 1; }

[ -t 0 ] || fail "TTY 가 없다. ssh -t 로 접속해 직접 실행할 것."

PHASE_B=0
[ "${1:-}" = "--phase-b" ] && PHASE_B=1

# 기존 값 보존 원칙: 이미 있는 키는 그대로 두고, 없는 키만 채운다.
get_existing() { kubectl -n "$NS" get secret "$SECRET" -o jsonpath="{.data.$1}" 2>/dev/null | base64 -d 2>/dev/null || true; }

JWT="$(get_existing JWT_SECRET_KEY)"
if [ -n "$JWT" ]; then
  log "JWT_SECRET_KEY 이미 있음 — 유지한다 (재생성하면 전 사용자가 로그아웃된다)"
else
  log "JWT_SECRET_KEY 신규 생성"
  JWT="$(openssl rand -base64 48 | tr -d '\n=' | tr '+/' '-_')"
fi

SUPA_URL="$(get_existing SUPABASE_URL)"
SUPA_KEY="$(get_existing SUPABASE_KEY)"
PIN="$(get_existing ADMIN_QUICK_PIN)"
DB_URL="$(get_existing DATABASE_URL)"

prompt_if_empty() {
  # $1=변수명 $2=프롬프트 $3=현재값. 안내는 전부 /dev/tty 로 — stdout 은 반환값 전용이다.
  local cur="$3"
  if [ -n "$cur" ]; then
    printf '  %s: 기존 값 있음 — 유지하려면 그냥 Enter\n' "$1" > /dev/tty
  fi
  printf '  %s 입력: ' "$2" > /dev/tty
  local v; IFS= read -rs v < /dev/tty; echo > /dev/tty
  if [ -n "$v" ]; then printf '%s' "$v"; else printf '%s' "$cur"; fi
}

SUPA_URL="$(prompt_if_empty SUPABASE_URL 'SUPABASE_URL (https://<ref>.supabase.co)' "$SUPA_URL")"
SUPA_KEY="$(prompt_if_empty SUPABASE_KEY 'SUPABASE_KEY (service role key)' "$SUPA_KEY")"
PIN="$(prompt_if_empty ADMIN_QUICK_PIN 'ADMIN_QUICK_PIN' "$PIN")"
if [ "$PHASE_B" -eq 1 ]; then
  DB_URL="$(prompt_if_empty DATABASE_URL 'DATABASE_URL (postgresql://ggc_subtitle:...@<poc-db 사설 IP>:5432/ggcpoc)' "$DB_URL")"
  [ -n "$DB_URL" ] || fail "Phase B 에는 DATABASE_URL 이 필수다."
fi

[ -n "$SUPA_URL" ] || fail "SUPABASE_URL 이 비어 있다 (Phase A 에는 필수)."
[ -n "$SUPA_KEY" ] || fail "SUPABASE_KEY 가 비어 있다 (Phase A 에는 필수)."
[ -n "$PIN" ]      || fail "ADMIN_QUICK_PIN 이 비어 있다."

log "Secret $SECRET 적용"
ARGS=(
  --from-literal=JWT_SECRET_KEY="$JWT"
  --from-literal=SUPABASE_URL="$SUPA_URL"
  --from-literal=SUPABASE_KEY="$SUPA_KEY"
  --from-literal=ADMIN_QUICK_PIN="$PIN"
)
[ -n "$DB_URL" ] && ARGS+=( --from-literal=DATABASE_URL="$DB_URL" )

umask 077
kubectl -n "$NS" create secret generic "$SECRET" "${ARGS[@]}" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
umask 022
unset JWT SUPA_URL SUPA_KEY PIN DB_URL

log "완료 — 키 목록(값은 출력하지 않는다):"
kubectl -n "$NS" get secret "$SECRET" -o jsonpath='{.data}' | tr ',' '\n' | sed 's/:.*//; s/[{}"]//g; s/^/  /'
echo
echo "  다음: 35-deploy.sh (Deployment·Service 적용)"
