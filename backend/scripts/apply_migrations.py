"""Supabase Postgres에 마이그레이션 SQL을 직접 적용한다 (psycopg).

Supabase REST 클라이언트는 DDL(CREATE/ALTER)을 못 하므로, settings.database_url(풀러)로
직접 연결해 지정한 마이그레이션 파일을 실행한다. 모든 마이그레이션은 멱등(IF NOT EXISTS).

사용 (backend 디렉터리): python scripts/apply_migrations.py 018 019
인자 없으면 기본으로 018, 019 적용.
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

from app.core.config import settings  # noqa: E402

MIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations")


def _split_statements(sql: str) -> list[str]:
    """`--` 라인 주석 제거 후 ';' 기준으로 문장 분리(문자열 내 ';' 없음 전제)."""
    lines = []
    for line in sql.splitlines():
        if line.strip().startswith("--"):
            continue
        lines.append(line)
    body = "\n".join(lines)
    return [s.strip() for s in body.split(";") if s.strip()]


def _find_migration(num: str) -> str:
    for fn in os.listdir(MIG_DIR):
        if fn.startswith(num) and fn.endswith(".sql"):
            return os.path.join(MIG_DIR, fn)
    raise FileNotFoundError(f"migration {num} not found in {MIG_DIR}")


def main() -> int:
    nums = sys.argv[1:] or ["018", "019"]

    url = settings.database_url
    if "localhost" in url or not url:
        print("❌ DATABASE_URL이 로컬 기본값입니다. Supabase 풀러 URL이 필요합니다.")
        return 1

    import psycopg

    conninfo = url
    print(f"[connect] {re.sub(r'://[^@]*@', '://***@', conninfo)}")
    try:
        conn = psycopg.connect(conninfo, autocommit=True, connect_timeout=20)
    except Exception as e:
        # SSL 요구 시 재시도
        if "sslmode" not in conninfo:
            try:
                sep = "&" if "?" in conninfo else "?"
                conn = psycopg.connect(conninfo + f"{sep}sslmode=require", autocommit=True, connect_timeout=20)
            except Exception as e2:
                print(f"❌ 연결 실패: {e2}")
                return 1
        else:
            print(f"❌ 연결 실패: {e}")
            return 1

    try:
        with conn.cursor() as cur:
            for num in nums:
                path = _find_migration(num)
                print(f"\n[apply] {os.path.basename(path)}")
                stmts = _split_statements(open(path, encoding="utf-8").read())
                for st in stmts:
                    cur.execute(st)
                    print(f"  ✓ {st.splitlines()[0][:70]}")

            # 검증
            print("\n[verify]")
            cur.execute("SELECT to_regclass('public.councilor_voiceprints')")
            tbl = cur.fetchone()[0]
            print(f"  councilor_voiceprints 테이블: {'존재' if tbl else '없음'}")
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='councilor_voiceprints' AND column_name='is_chair'"
            )
            col = cur.fetchone()
            print(f"  is_chair 컬럼: {'존재' if col else '없음'}")
            ok = bool(tbl) and bool(col)
    finally:
        conn.close()

    print(f"\n결과: {'✅ PASS' if ok else '❌ FAIL'}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
