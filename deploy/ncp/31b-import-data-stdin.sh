#!/usr/bin/env bash
# =============================================================================
#  31b · Supabase → poc-db 데이터 이관 — 비대화형 변형 (poc-app 에서 sudo 로 실행)
#
#  31(TTY 대화형)을 쓸 수 없는 환경(Claude Code `!` 실행)용 — 25b 와 같은 지위.
#  stdin 2줄: ① Supabase DB 비밀번호 ② poc-db ggc_subtitle 비밀번호.
#  값은 ssh stdin 으로만 흐르고 명령 인자·화면·파일 어디에도 남지 않는다.
#
#    printf '%s\n%s\n' "$SUPW" "$DBPW" | ssh ... 'sudo -n bash /tmp/transcribe-31b.sh'
#
#  접속 대상은 환경변수 SUPABASE_PROJECT_REF 로 준다. 직결 호스트가
#  IPv6 전용이라 닿지 않으면 session pooler(IPv4) 로 자동 폴백한다.
#  절차·재실행 안전성은 31 과 동일: 전량 재이관(멱등) + 행수 전수 대사.
# =============================================================================
set -euo pipefail

REF="${SUPABASE_PROJECT_REF:?SUPABASE_PROJECT_REF 가 필요하다}"
SUPA_DB="postgres"
DB_HOST="${GGC_DB_HOST:?GGC_DB_HOST 가 필요하다}"
DB_ROLE="ggc_subtitle"
BACKUP_DIR="/var/lib/ggc-poc/backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
DUMP="$BACKUP_DIR/supabase-public-$STAMP.sql"
REPORT="$BACKUP_DIR/reconcile-$STAMP.txt"

log()  { printf '\n[31b] %s\n' "$*"; }
fail() { printf '\n[31b] [중단] %s\n' "$*"; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "sudo 로 실행해야 한다."

IFS= read -r SUPA_PW || true
IFS= read -r DBPW    || true
[ -n "${SUPA_PW:-}" ] || fail "stdin 1행(Supabase DB 비밀번호)이 비어 있다."
[ -n "${DBPW:-}" ]    || fail "stdin 2행(poc-db $DB_ROLE 비밀번호)이 비어 있다."

# ── 1. 클라이언트 확보 (Supabase 는 PG 17) ───────────────────────────────────
if ! command -v pg_dump >/dev/null || [ "$(pg_dump --version | grep -oE '[0-9]+' | head -1)" -lt 17 ]; then
  log "postgresql-client-17 설치 (PGDG)"
  export DEBIAN_FRONTEND=noninteractive
  if [ ! -f /etc/apt/sources.list.d/pgdg.list ]; then
    install -d /usr/share/postgresql-common/pgdg
    curl -fsS -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
      https://www.postgresql.org/media/keys/ACCC4CF8.asc
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo "$VERSION_CODENAME")-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list
  fi
  apt-get update -qq
  apt-get install -y -qq postgresql-client-17
fi

# ── 2. Supabase 접속 경로 결정 ───────────────────────────────────────────────
# poc-app 아웃바운드 ACG 가 5432/6543 을 막고 있어(2026-08-18 실측) 기본 경로는
# 담당자 PC 를 릴레이로 쓰는 ssh -R 터널이다. 그 경우 호출 측이 SUPA_HOST/PORT/USER 를
# env 로 넘긴다 (예: 127.0.0.1:15432 + postgres.<ref>). env 없으면 종전 자동탐색.
try_conn() { # $1=host $2=port $3=user — 실패 시 psql 오류를 CONN_ERR 에 남긴다(비밀번호 미포함)
  CONN_ERR=$(PGPASSWORD="$SUPA_PW" PGCONNECT_TIMEOUT=12 psql -h "$1" -p "$2" -U "$3" -d "$SUPA_DB" -tAc 'SELECT 1' 2>&1 >/dev/null) || return 1
}
if [ -n "${SUPA_HOST:-}" ]; then
  SUPA_PORT="${SUPA_PORT:-5432}"; SUPA_USER="${SUPA_USER:-postgres.$REF}"
  log "지정 경로로 접속: $SUPA_HOST:$SUPA_PORT ($SUPA_USER)"
  try_conn "$SUPA_HOST" "$SUPA_PORT" "$SUPA_USER" \
    || { echo "  psql: $CONN_ERR"; fail "지정 경로 접속 실패 — 위 오류로 원인(테넌트/비밀번호/터널)을 가를 것"; }
else
  SUPA_HOST="db.$REF.supabase.co"; SUPA_PORT=5432; SUPA_USER="postgres"
  if try_conn "$SUPA_HOST" "$SUPA_PORT" "$SUPA_USER"; then
    log "직결 성공: $SUPA_HOST"
  else
    log "직결 실패 — session pooler(IPv4) 폴백"
    SUPA_USER="postgres.$REF"
    OK=""
    for h in aws-0-ap-northeast-2.pooler.supabase.com aws-1-ap-northeast-2.pooler.supabase.com; do
      if try_conn "$h" "$SUPA_PORT" "$SUPA_USER"; then SUPA_HOST="$h"; OK=1; break; fi
      echo "  [$h] psql: $CONN_ERR"
    done
    [ -n "$OK" ] || fail "pooler 접속 실패 — 위 오류 확인. 아웃바운드 5432 차단이면 ssh -R 터널 경로를 쓸 것(런북 참조)"
    log "pooler 접속 성공: $SUPA_HOST ($SUPA_USER)"
  fi
fi
SUPA_VER="$(PGPASSWORD="$SUPA_PW" psql -h "$SUPA_HOST" -p "$SUPA_PORT" -U "$SUPA_USER" -d "$SUPA_DB" -tAc 'SHOW server_version')"
echo "  Supabase 서버 $SUPA_VER · 클라이언트 $(pg_dump --version | awk '{print $3}')"

PGPASSWORD="$DBPW" PGCONNECT_TIMEOUT=10 psql -h "$DB_HOST" -U "$DB_ROLE" -d subtitle_stage -tAc 'SELECT 1' >/dev/null \
  || fail "poc-db subtitle_stage 접속 실패 — 30-provision 실행 여부·비밀번호 확인"

# ── 3. 덤프 ──────────────────────────────────────────────────────────────────
mkdir -p "$BACKUP_DIR"; chmod 700 "$BACKUP_DIR"
log "pg_dump → $DUMP"
umask 077
PGPASSWORD="$SUPA_PW" pg_dump -h "$SUPA_HOST" -p "$SUPA_PORT" -U "$SUPA_USER" -d "$SUPA_DB" \
  -n public --no-owner --no-privileges --no-comments -f "$DUMP" || fail "pg_dump 실패"
echo "  크기 $(du -h "$DUMP" | cut -f1) · 라인 $(wc -l < "$DUMP")"

# ── 4. 스테이지 반입 + 스키마 개명 (sed 치환 금지 — 본문 훼손 위험) ──────────
# 수용하는 오류(2026-08-18 실측 근거):
#  · transaction_timeout          — PG17 클라이언트 덤프의 SET, PG16 서버가 모름(동작 무영향)
#  · schema "auth" ...            — auth.users FK/트리거. Supabase 관리 스키마라 이관 대상 아님
#  · role "authenticated|anon|service_role|supabase_*" — Supabase 전용 롤 정책/권한. RLS 미사용
# 이 스킵으로 사라지는 것은 auth 연계 제약/정책뿐이며 데이터(COPY)는 영향받지 않는다.
# 자체 인증 전환(코드 트랙)이 이 전제를 이어받는다.
HARMLESS='already exists|transaction_timeout|schema "auth" does not exist|role "authenticated" does not exist|role "anon" does not exist|role "service_role" does not exist|role "supabase_'
check_restore_err() { # $1=오류파일 $2=단계명
  local real
  real=$(grep 'ERROR' "$1" | grep -Ev "$HARMLESS" || true)
  local skipped
  skipped=$(grep -c 'ERROR' "$1" || true)
  if [ -n "$real" ]; then
    echo "$real" | head -10 | sed 's/^/    /'
    fail "$2 실패 — $1 확인"
  fi
  echo "  $2: 실질 오류 0 (수용된 스킵 ${skipped}건 — auth 연계/전용 롤/PG17 SET)"
}

# 확장 배치 전략 (2026-08-18 최종 확정): "확장은 subtitle 스키마에 산다"
#  · Supabase 덤프는 public.gin_trgm_ops 등 한정 이름 → 스테이지 반입 동안은 public 에 필요.
#  · public→subtitle 개명이 확장을 자연스럽게 subtitle 로 옮긴다(이동 코드 불필요 —
#    ALTER 는 멤버 함수 소유권이 얽히면 실패한다는 것을 실측으로 배웠다).
#  · 최종 덤프는 subtitle.* 한정 이름 → ggcpoc 쪽도 확장이 subtitle 스키마에 있으면 일치.
#    매 재이관 때 DROP SCHEMA subtitle CASCADE 로 함께 지워지고 아래에서 재생성된다.
#  확장 3종은 신뢰(trusted)라 DB 소유자/CREATE 권한의 ggc_subtitle 로 생성 가능.
ext_stmt() { # $1=DB $2=SQL — 실패 무해(이미 그 상태면 no-op)
  PGPASSWORD="$DBPW" psql -h "$DB_HOST" -U "$DB_ROLE" -d "$1" -q -c "$2" 2>/dev/null || true
}
ensure_ext() { # $1=DB $2=스키마
  for e in '"uuid-ossp"' pg_trgm pgcrypto; do
    ext_stmt "$1" "CREATE EXTENSION IF NOT EXISTS $e WITH SCHEMA $2"
    ext_stmt "$1" "ALTER EXTENSION $e SET SCHEMA $2"
  done
}

PSQL_STAGE=(psql -h "$DB_HOST" -U "$DB_ROLE" -d subtitle_stage -q)
RESTORE_ERR="$BACKUP_DIR/restore-errors-$STAMP.log"
log "subtitle_stage 초기화 후 반입"
PGPASSWORD="$DBPW" "${PSQL_STAGE[@]}" -v ON_ERROR_STOP=1 \
  -c 'DROP SCHEMA IF EXISTS subtitle CASCADE; DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;'
ensure_ext subtitle_stage public
PGPASSWORD="$DBPW" "${PSQL_STAGE[@]}" -f "$DUMP" 2> "$RESTORE_ERR" || true
check_restore_err "$RESTORE_ERR" "스테이지 반입"
PGPASSWORD="$DBPW" "${PSQL_STAGE[@]}" -v ON_ERROR_STOP=1 \
  -c 'ALTER SCHEMA public RENAME TO subtitle; CREATE SCHEMA public;'

# ── 5. 본 반입 ───────────────────────────────────────────────────────────────
# 최종 반입도 PG17 클라이언트 pg_dump 의 SET 프리앰블(transaction_timeout)을 지나므로
# ON_ERROR_STOP 대신 동일한 오류파일+허용목록 검사를 쓴다.
log "ggcpoc.subtitle 전량 재반입"
PGPASSWORD="$DBPW" psql -h "$DB_HOST" -U "$DB_ROLE" -d ggcpoc -v ON_ERROR_STOP=1 -q \
  -c 'DROP SCHEMA IF EXISTS subtitle CASCADE; CREATE SCHEMA subtitle;'
# 덤프의 CREATE SCHEMA subtitle 은 'already exists' 로 무해 스킵된다.
# 확장을 먼저 심어야 덤프 안의 gin 인덱스(subtitle.gin_trgm_ops)가 성립한다.
ensure_ext ggcpoc subtitle
FINAL_ERR="$BACKUP_DIR/final-errors-$STAMP.log"
PGPASSWORD="$DBPW" pg_dump -h "$DB_HOST" -U "$DB_ROLE" -d subtitle_stage -n subtitle --no-owner --no-privileges \
  | PGPASSWORD="$DBPW" psql -h "$DB_HOST" -U "$DB_ROLE" -d ggcpoc -q 2> "$FINAL_ERR" || true
check_restore_err "$FINAL_ERR" "본 반입"

# ── 6. 대사 리포트 (행수 전수 비교, 데이터 값 미포함) ────────────────────────
log "대사 리포트 → $REPORT"
counts_of() {
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
  echo "# Supabase(public) vs ggcpoc(subtitle) 행수 대사 — $STAMP"
  printf '# table\tsupabase\tpocdb\tmatch\n'
  join -t "$(printf '\t')" -a1 -a2 -e '?' -o '0,1.2,2.2' \
       <(printf '%s\n' "$SUPA_COUNTS" | sort) <(printf '%s\n' "$LOCAL_COUNTS" | sort) \
  | awk -F'\t' '{
      if ($2==$3) m="OK";
      else if ($1=="site_visits") m="DRIFT-OK";  # 방문 카운터 — 이관 중 열린 브라우저가 계속 기록(2026-08-18 실측 2행). 콘텐츠 아님
      else { m="MISMATCH"; bad++ }
      print $0 "\t" m
    } END{ exit bad?1:0 }'
} > "$REPORT" || MATCH_RC=$?
chmod 600 "$REPORT"
cat "$REPORT"

unset SUPA_PW DBPW
if [ "$MATCH_RC" -ne 0 ]; then
  fail "행수 불일치 — $REPORT 확인 (라이브 쓰기 중이었다면 freeze 후 재실행)"
fi
log "완료 — 전 테이블 행수 일치. subtitle_stage 는 컷오버까지 롤백 소스로 유지."
