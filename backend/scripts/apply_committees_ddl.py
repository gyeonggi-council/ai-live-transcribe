"""DATABASE_URL(psycopg)로 councilors 확장 컬럼 DDL을 직접 적용.

Management API PAT가 없을 때 사용. 비밀번호는 출력하지 않는다.
"""
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.stdout.reconfigure(encoding="utf-8")

ENV = Path(__file__).resolve().parent.parent / ".env"


def env(key):
    if os.environ.get(key):
        return os.environ[key]
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


url = env("DATABASE_URL")
if not url:
    raise SystemExit("DATABASE_URL 없음")
p = urlparse(url)
print(f"host={p.hostname} port={p.port} db={p.path.lstrip('/')} user={p.username}")

DDL = """
ALTER TABLE councilors ADD COLUMN IF NOT EXISTS committees JSONB DEFAULT '[]'::jsonb;
ALTER TABLE councilors ADD COLUMN IF NOT EXISTS mi_code VARCHAR(50);
ALTER TABLE councilors ADD COLUMN IF NOT EXISTS synced_at TIMESTAMPTZ;
ALTER TABLE councilors ADD COLUMN IF NOT EXISTS profile_image_url TEXT;
ALTER TABLE councilors ADD COLUMN IF NOT EXISTS office_number VARCHAR(50);
"""

conninfo = url if "sslmode=" in url else (url + ("&" if "?" in url else "?") + "sslmode=require")

try:
    import psycopg
except ImportError:
    raise SystemExit("psycopg 미설치")

if "--apply" not in sys.argv:
    print("(dry-run — 연결만 테스트. 적용하려면 --apply)")
    try:
        with psycopg.connect(conninfo, connect_timeout=15) as conn:
            with conn.cursor() as cur:
                cur.execute("select column_name from information_schema.columns where table_name='councilors' order by 1")
                cols = [r[0] for r in cur.fetchall()]
        print("연결 성공. 현재 councilors 컬럼:", cols)
    except Exception as e:
        print("연결 실패:", repr(e)[:300])
    raise SystemExit(0)

with psycopg.connect(conninfo, connect_timeout=20) as conn:
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("select column_name from information_schema.columns where table_name='councilors' order by 1")
        cols = [r[0] for r in cur.fetchall()]
print("DDL 적용 완료. councilors 컬럼:", cols)
