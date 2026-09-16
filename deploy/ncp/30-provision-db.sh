#!/usr/bin/env bash
# =============================================================================
#  30 · poc-db 프로비저닝 (poc-db 에서 sudo 로 실행 — poc-app 점프 경유)
#
#    NORM="sed -e 1s/^\xef\xbb\xbf// -e s/\r$//"
#    DB="$SSH -J ncloud@<poc-app 공인 IP>"
#    cat deploy/ncp/30-provision-db.sh deploy/ncp/sql/V1__provision.sql 는 따로 보내지 말고,
#    저장소 루트에서:
#      $NORM deploy/ncp/30-provision-db.sh | $DB ncloud@<poc-db 사설 IP> 'cat > /tmp/transcribe-30.sh'
#      $NORM deploy/ncp/sql/V1__provision.sql | $DB ncloud@<poc-db 사설 IP> 'cat > /tmp/transcribe-V1.sql'
#      $DB ncloud@<poc-db 사설 IP> 'sudo -n bash /tmp/transcribe-30.sh < /dev/null' < /dev/null
#
#  하는 일 (전부 멱등):
#    1. /root/poc-db-credentials.txt 에서 GGC_SUBTITLE_PASSWORD 재사용 (없으면 생성·추가)
#       — 02-poc-db-postgres.sh 의 "파일이 비밀번호 정본" 규칙과 동일한 구조다
#    2. V1__provision.sql 실행 (롤·subtitle 스키마·extensions·subtitle_stage)
#    3. pg_hba.conf 에 ggc_subtitle 경로가 없으면 추가 + reload
# =============================================================================
set -euo pipefail

CRED_FILE="/root/poc-db-credentials.txt"
SQL_FILE="/tmp/transcribe-V1.sql"

log()  { printf '\n[30] %s\n' "$*"; }
fail() { printf '\n[30] [중단] %s\n' "$*"; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "sudo 로 실행해야 한다."
[ -f "$SQL_FILE" ]   || fail "$SQL_FILE 이 없다. V1__provision.sql 을 먼저 전송할 것."
command -v psql >/dev/null || fail "psql 이 없다. poc-db 가 맞는지 확인할 것."

# ── 1. 비밀번호 정본 ─────────────────────────────────────────────────────────
log "비밀번호 정본 확인 ($CRED_FILE)"
touch "$CRED_FILE"; chmod 600 "$CRED_FILE"
SUBTITLE_PW="$(sed -n 's/^GGC_SUBTITLE_PASSWORD=//p' "$CRED_FILE" | head -1)"
if [ -n "$SUBTITLE_PW" ]; then
  echo "  기존 값 재사용 (파일과 DB 를 ALTER ROLE 로 동기화한다)"
else
  log "GGC_SUBTITLE_PASSWORD 신규 생성"
  SUBTITLE_PW="$(openssl rand -hex 24)"
  printf 'GGC_SUBTITLE_PASSWORD=%s\n' "$SUBTITLE_PW" >> "$CRED_FILE"
  echo "  $CRED_FILE 에 추가했다 (600)."
fi

# ── 2. DDL 실행 ──────────────────────────────────────────────────────────────
log "V1__provision.sql 실행"
sudo -u postgres psql -v ON_ERROR_STOP=1 -v subtitle_password="$SUBTITLE_PW" -d postgres -f "$SQL_FILE"
unset SUBTITLE_PW

# ── 3. pg_hba 경로 ───────────────────────────────────────────────────────────
# 02 가 만든 규칙이 특정 롤/DB 한정일 수 있다. all-all 규칙이 없으면 전용 행을 추가한다.
HBA="$(sudo -u postgres psql -tAc 'SHOW hba_file')"
log "pg_hba 확인 ($HBA)"
if grep -E '^host\s+all\s+all\s+10\.10\.11\.0/24' "$HBA" >/dev/null; then
  echo "  all-all 규칙이 이미 ${GGC_APP_SUBNET:?GGC_APP_SUBNET 가 필요하다 (예: 10.x.x.0/24)} 를 허용한다 — 추가 불필요"
else
  CHANGED=0
  if ! grep -E '^host\s+(ggcpoc|all)\s+(ggc_subtitle|all)\s+10\.10\.11\.0/24' "$HBA" >/dev/null; then
    echo 'host    ggcpoc          ggc_subtitle    ${GGC_APP_SUBNET:?GGC_APP_SUBNET 가 필요하다 (예: 10.x.x.0/24)}           scram-sha-256' >> "$HBA"; CHANGED=1
  fi
  if ! grep -E '^host\s+(subtitle_stage|all)\s+(ggc_subtitle|all)\s+10\.10\.11\.0/24' "$HBA" >/dev/null; then
    echo 'host    subtitle_stage  ggc_subtitle    ${GGC_APP_SUBNET:?GGC_APP_SUBNET 가 필요하다 (예: 10.x.x.0/24)}           scram-sha-256' >> "$HBA"; CHANGED=1
  fi
  if [ "$CHANGED" -eq 1 ]; then
    sudo -u postgres psql -tAc 'SELECT pg_reload_conf()' >/dev/null
    echo "  ggc_subtitle 전용 행 추가 + reload 완료"
  else
    echo "  전용 행이 이미 있다 — 변경 없음"
  fi
fi

# ── 4. 확인 ──────────────────────────────────────────────────────────────────
log "결과 확인"
sudo -u postgres psql -d ggcpoc -tAc \
  "SELECT 'role='  || count(*) FROM pg_roles    WHERE rolname='ggc_subtitle'
   UNION ALL SELECT 'schema='|| count(*) FROM pg_namespace WHERE nspname='subtitle'
   UNION ALL SELECT 'ext_schema='|| count(*) FROM pg_namespace WHERE nspname='extensions'" | sed 's/^/  /'
sudo -u postgres psql -tAc "SELECT 'stage_db=' || count(*) FROM pg_database WHERE datname='subtitle_stage'" | sed 's/^/  /'

log "완료 — 비밀번호는 $CRED_FILE 에만 있다. 채팅·로그·Git 에 옮기지 말 것."
echo "  다음: poc-app 에서 31-import-data.sh (Supabase 덤프 → 반입)"
