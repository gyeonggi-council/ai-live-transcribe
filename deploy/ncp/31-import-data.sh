#!/usr/bin/env bash
# =============================================================================
#  31 · Supabase → poc-db 데이터 이관 (poc-app 에서 sudo + TTY 로 실행)
#
#    ssh -t -i keys/ggc-poc ncloud@<poc-app 공인 IP> 'sudo bash /tmp/transcribe-31.sh'
#
#  ⚠ 대화형 예외 스크립트다(08b·25 와 같은 지위) — 비밀번호를 TTY 로만 받는다.
#     값은 파일·히스토리·로그 어디에도 남기지 않는다. PGPASSWORD 프로세스 환경만 쓴다.
#
#  경로 설계 (CLAUDE.md 의 poc-db 격리 원칙과 정합):
#    Supabase(외부) --pg_dump--> poc-app(아웃바운드 가능) --psql--> poc-db <사설 IP>
#    poc-db 는 아웃바운드가 없지만 poc-app→poc-db 5432 는 허용된 유일 경로라
#    포트를 새로 열 것도, 파일을 poc-db 로 옮길 것도 없다.
#
#  절차 (재실행 = 전량 재이관, 멱등):
#    1. PGDG postgresql-client 확보 (Supabase 서버 버전 이상)
#    2. pg_dump -n public → /var/lib/ggc-poc/backups/ 보관(600) — 컷오버 증적 겸 백업
#    3. subtitle_stage: public 초기화 → 덤프 반입 → ALTER SCHEMA public RENAME TO subtitle
#       (본문에 "public." 문자열이 있을 수 있어 sed 치환은 금지 — 스키마 개명으로 처리)
#    4. ggcpoc: DROP SCHEMA subtitle CASCADE → stage 의 subtitle 스키마를 그대로 반입
#    5. 대사 리포트: 테이블별 행수 Supabase vs ggcpoc.subtitle 전수 비교
# =============================================================================
set -euo pipefail

DB_HOST="${GGC_DB_HOST:?GGC_DB_HOST 가 필요하다 (예: GGC_DB_HOST=10.x.x.x bash /tmp/transcribe-31.sh)}"
DB_ROLE="ggc_subtitle"
BACKUP_DIR="/var/lib/ggc-poc/backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
DUMP="$BACKUP_DIR/supabase-public-$STAMP.sql"
REPORT="$BACKUP_DIR/reconcile-$STAMP.txt"

log()  { printf '\n[31] %s\n' "$*"; }
fail() { printf '\n[31] [중단] %s\n' "$*"; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "sudo 로 실행해야 한다."
[ -t 0 ] || [ -e /dev/tty ] || fail "TTY 가 없다. ssh -t 로 접속할 것."

ask()  { printf '  %s: ' "$1" > /dev/tty; local v; IFS= read -r  v < /dev/tty; printf '%s' "${v:-$2}"; }
asks() { printf '  %s: ' "$1" > /dev/tty; local v; IFS= read -rs v < /dev/tty; echo > /dev/tty; printf '%s' "$v"; }

log "접속 정보 입력 (Supabase 대시보드 Database Settings 참조)"
echo "  * 직결 호스트(db.<ref>.supabase.co)가 IPv6 전용이면 session pooler 호스트를 쓸 것" > /dev/tty
echo "    (aws-0-<region>.pooler.supabase.com, 포트 5432, 사용자 postgres.<ref>)" > /dev/tty
SUPA_HOST="$(ask 'Supabase 호스트' '')";              [ -n "$SUPA_HOST" ] || fail "호스트가 비었다."
SUPA_PORT="$(ask 'Supabase 포트 [5432]' '5432')"
SUPA_USER="$(ask 'Supabase 사용자 [postgres]' 'postgres')"
SUPA_DB="$(ask 'Supabase DB [postgres]' 'postgres')"
SUPA_PW="$(asks 'Supabase 비밀번호')";                [ -n "$SUPA_PW" ] || fail "비밀번호가 비었다."
DBPW="$(asks "poc-db $DB_ROLE 비밀번호 (poc-db:/root/poc-db-credentials.txt 의 GGC_SUBTITLE_PASSWORD)")"
[ -n "$DBPW" ] || fail "poc-db 비밀번호가 비었다."

# ── 1. 클라이언트 확보 ───────────────────────────────────────────────────────
SUPA_VER="$(PGPASSWORD="$SUPA_PW" PGCONNECT_TIMEOUT=15 psql -h "$SUPA_HOST" -p "$SUPA_PORT" -U "$SUPA_USER" -d "$SUPA_DB" -tAc 'SHOW server_version' 2>/dev/null || true)"
if [ -z "$SUPA_VER" ]; then
  # 로컬에 psql 이 아예 없을 수 있다 — 먼저 최신 클라이언트를 깔고 재시도한다.
  SUPA_MAJOR=17
else
  SUPA_MAJOR="${SUPA_VER%%.*}"
fi
if ! command -v pg_dump >/dev/null || [ "$(pg_dump --version | grep -oE '[0-9]+' | head -1)" -lt "$SUPA_MAJOR" ]; then
  log "postgresql-client-$SUPA_MAJOR 설치 (PGDG)"
  export DEBIAN_FRONTEND=noninteractive
  if [ ! -f /etc/apt/sources.list.d/pgdg.list ]; then
    install -d /usr/share/postgresql-common/pgdg
    curl -fsS -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
      https://www.postgresql.org/media/keys/ACCC4CF8.asc
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo "$VERSION_CODENAME")-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list
  fi
  apt-get update -qq
  apt-get install -y -qq "postgresql-client-$SUPA_MAJOR"
fi
SUPA_VER="$(PGPASSWORD="$SUPA_PW" PGCONNECT_TIMEOUT=15 psql -h "$SUPA_HOST" -p "$SUPA_PORT" -U "$SUPA_USER" -d "$SUPA_DB" -tAc 'SHOW server_version')" \
  || fail "Supabase 접속 실패 — 호스트/자격 또는 IPv6 전용 여부(pooler 사용)를 확인할 것."
log "Supabase 서버 $SUPA_VER · 클라이언트 $(pg_dump --version | awk '{print $3}')"

PGPASSWORD="$DBPW" PGCONNECT_TIMEOUT=10 psql -h "$DB_HOST" -U "$DB_ROLE" -d subtitle_stage -tAc 'SELECT 1' >/dev/null \
  || fail "poc-db subtitle_stage 접속 실패 — 30-provision-db.sh 를 먼저 실행했는지, 비밀번호가 맞는지 확인할 것."

# ── 2. 덤프 (스키마+데이터 전부, 소유권·권한 제외) ──────────────────────────
mkdir -p "$BACKUP_DIR"; chmod 700 "$BACKUP_DIR"
log "pg_dump 시작 → $DUMP"
umask 077
PGPASSWORD="$SUPA_PW" pg_dump -h "$SUPA_HOST" -p "$SUPA_PORT" -U "$SUPA_USER" -d "$SUPA_DB" \
  -n public --no-owner --no-privileges --no-comments -f "$DUMP" \
  || fail "pg_dump 실패"
echo "  크기 $(du -h "$DUMP" | cut -f1) · 라인 $(wc -l < "$DUMP")"

# ── 3. 스테이지 반입 + 스키마 개명 ───────────────────────────────────────────
# 덤프에 CREATE SCHEMA public 이 있을 수도, 없을 수도 있어(공급자 구성에 따라 다름)
# public 을 미리 만들어 두고 "already exists" 만 무해 오류로 걸러낸다.
PSQL_STAGE=(psql -h "$DB_HOST" -U "$DB_ROLE" -d subtitle_stage -q)
RESTORE_ERR="$BACKUP_DIR/restore-errors-$STAMP.log"
log "subtitle_stage 초기화 후 반입"
PGPASSWORD="$DBPW" "${PSQL_STAGE[@]}" -v ON_ERROR_STOP=1 \
  -c 'DROP SCHEMA IF EXISTS subtitle CASCADE; DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;'
PGPASSWORD="$DBPW" "${PSQL_STAGE[@]}" -f "$DUMP" 2> "$RESTORE_ERR" || true
if grep 'ERROR' "$RESTORE_ERR" | grep -v 'already exists' >/dev/null; then
  echo "  반입 중 오류 (harmless 'already exists' 제외):"
  grep 'ERROR' "$RESTORE_ERR" | grep -v 'already exists' | head -10 | sed 's/^/    /'
  fail "스테이지 반입 실패 — $RESTORE_ERR 전체를 확인할 것."
fi
PGPASSWORD="$DBPW" "${PSQL_STAGE[@]}" -v ON_ERROR_STOP=1 \
  -c 'ALTER SCHEMA public RENAME TO subtitle; CREATE SCHEMA public;'

# ── 4. 본 반입 (ggcpoc.subtitle 전량 교체) ───────────────────────────────────
# subtitle 은 사용자 스키마라 pg_dump 가 CREATE SCHEMA subtitle 을 포함한다 —
# ggcpoc 쪽은 DROP 만 하고 생성은 덤프에 맡긴다(소유자 = 접속 롤 ggc_subtitle).
log "ggcpoc.subtitle 전량 재반입"
PGPASSWORD="$DBPW" psql -h "$DB_HOST" -U "$DB_ROLE" -d ggcpoc -v ON_ERROR_STOP=1 -q \
  -c 'DROP SCHEMA IF EXISTS subtitle CASCADE;'
PGPASSWORD="$DBPW" pg_dump -h "$DB_HOST" -U "$DB_ROLE" -d subtitle_stage -n subtitle --no-owner --no-privileges \
  | PGPASSWORD="$DBPW" psql -h "$DB_HOST" -U "$DB_ROLE" -d ggcpoc -v ON_ERROR_STOP=1 -q \
  || fail "본 반입 실패"

# ── 5. 대사 리포트 (행수 전수 비교 — 데이터 값은 담지 않는다) ────────────────
log "대사 리포트 생성 → $REPORT"
counts_of() {
  # $1=스키마. \gexec 로 테이블별 count 를 한 세션에서 실행한다 (탭 구분 "table<TAB>n").
  local schema="$1"; shift
  "$@" -tA -v ON_ERROR_STOP=1 <<SQL
SELECT format('SELECT %L || chr(9) || count(*) FROM %I.%I', tablename, schemaname, tablename)
FROM pg_tables WHERE schemaname = '$schema' ORDER BY tablename \\gexec
SQL
}
SUPA_COUNTS="$(PGPASSWORD="$SUPA_PW" counts_of public \
  psql -h "$SUPA_HOST" -p "$SUPA_PORT" -U "$SUPA_USER" -d "$SUPA_DB")" || fail "Supabase 행수 집계 실패"
LOCAL_COUNTS="$(PGPASSWORD="$DBPW" counts_of subtitle \
  psql -h "$DB_HOST" -U "$DB_ROLE" -d ggcpoc)" || fail "poc-db 행수 집계 실패"

MATCH_RC=0
{
  echo "# Supabase(public) vs poc-db ggcpoc(subtitle) 행수 대사 — $STAMP"
  printf '# table\tsupabase\tpocdb\tmatch\n'
  join -t "$(printf '\t')" -a1 -a2 -e '?' -o '0,1.2,2.2' \
       <(printf '%s\n' "$SUPA_COUNTS" | sort) <(printf '%s\n' "$LOCAL_COUNTS" | sort) \
  | awk -F'\t' '{m=($2==$3)?"OK":"MISMATCH"; print $0 "\t" m; if(m=="MISMATCH") bad++} END{ exit bad?1:0 }'
} > "$REPORT" || MATCH_RC=$?
chmod 600 "$REPORT"
cat "$REPORT"

unset SUPA_PW DBPW
if [ "$MATCH_RC" -ne 0 ]; then
  fail "행수 불일치가 있다. $REPORT 를 확인할 것 (라이브 쓰기 중이었다면 freeze 후 재실행)."
fi

log "완료 — 전 테이블 행수 일치"
echo "  백업: $DUMP (600) · 리포트: $REPORT"
echo "  subtitle_stage 는 컷오버까지 롤백 소스로 유지한다. 컷오버 후 DROP DATABASE subtitle_stage."
