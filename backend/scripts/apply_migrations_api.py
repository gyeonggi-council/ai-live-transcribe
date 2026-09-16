"""Supabase Management API로 마이그레이션 SQL을 적용한다 (Personal Access Token 사용).

풀러/psycopg 인증 문제와 브라우저 자동화를 우회한다. SQL 에디터가 쓰는 것과 동일한
Management API 엔드포인트로 DDL을 실행한다.

토큰은 명령/출력에 노출하지 않도록 환경변수 SUPABASE_ACCESS_TOKEN(또는 backend/.env)에서 읽는다.

사용 (backend 디렉터리):
  1) backend/.env 에 한 줄 추가:  SUPABASE_ACCESS_TOKEN=sbp_xxxxxxxx
  2) python scripts/apply_migrations_api.py 018 019
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

import httpx  # noqa: E402

# settings(pydantic, extra=forbid)를 거치지 않고 .env를 직접 파싱한다.
# (PAT를 .env에 두면 Settings()가 extra_forbidden으로 실패하므로 의존하지 않음)
MIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations")
ENV_PATH = os.path.join(os.path.dirname(MIG_DIR), ".env")
API = "https://api.supabase.com/v1/projects/{ref}/database/query"


def _env(key: str) -> str | None:
    v = os.environ.get(key)
    if v:
        return v
    if os.path.exists(ENV_PATH):
        for line in open(ENV_PATH, encoding="utf-8"):
            if line.strip().startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _ref() -> str:
    m = re.search(r"https://([a-z0-9]+)\.supabase\.", _env("SUPABASE_URL") or "")
    if not m:
        raise SystemExit("SUPABASE_URL에서 프로젝트 ref를 찾을 수 없습니다.")
    return m.group(1)


def _token() -> str:
    tok = _env("SUPABASE_ACCESS_TOKEN")
    if not tok:
        raise SystemExit("SUPABASE_ACCESS_TOKEN이 없습니다. backend/.env에 추가하세요.")
    return tok


def _find_migration(num: str) -> str:
    for fn in os.listdir(MIG_DIR):
        if fn.startswith(num) and fn.endswith(".sql"):
            return os.path.join(MIG_DIR, fn)
    raise FileNotFoundError(f"migration {num} not found")


def _run_sql(ref: str, token: str, sql: str) -> tuple[int, str]:
    resp = httpx.post(
        API.format(ref=ref),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"query": sql},
        timeout=60.0,
    )
    return resp.status_code, resp.text


def main() -> int:
    nums = sys.argv[1:] or ["018", "019"]
    ref = _ref()
    token = _token()
    print(f"[mgmt-api] project={ref}  migrations={nums}")

    for num in nums:
        path = _find_migration(num)
        sql = open(path, encoding="utf-8").read()
        status, body = _run_sql(ref, token, sql)
        ok = 200 <= status < 300
        print(f"  {'✓' if ok else '✗'} {os.path.basename(path)} → HTTP {status}")
        if not ok:
            print(f"    {body[:400]}")
            return 2

    # 검증
    status, body = _run_sql(
        ref, token,
        "select to_regclass('public.councilor_voiceprints') as tbl, "
        "(select count(*) from information_schema.columns "
        " where table_name='councilor_voiceprints' and column_name='is_chair') as has_chair",
    )
    print(f"\n[verify] HTTP {status}: {body[:200]}")
    return 0 if 200 <= status < 300 else 2


if __name__ == "__main__":
    raise SystemExit(main())
