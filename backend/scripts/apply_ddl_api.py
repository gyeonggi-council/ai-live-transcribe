"""councilors 확장 컬럼만 Management API로 추가 (트리거 의존성 없는 안전 DDL)."""
import os
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
import httpx

ENV = Path(__file__).resolve().parent.parent / ".env"
API = "https://api.supabase.com/v1/projects/{ref}/database/query"

DDL = """
ALTER TABLE councilors ADD COLUMN IF NOT EXISTS committees JSONB DEFAULT '[]'::jsonb;
ALTER TABLE councilors ADD COLUMN IF NOT EXISTS mi_code VARCHAR(50);
ALTER TABLE councilors ADD COLUMN IF NOT EXISTS synced_at TIMESTAMPTZ;
ALTER TABLE councilors ADD COLUMN IF NOT EXISTS profile_image_url TEXT;
ALTER TABLE councilors ADD COLUMN IF NOT EXISTS office_number VARCHAR(50);
CREATE UNIQUE INDEX IF NOT EXISTS idx_councilors_mi_code ON councilors(mi_code) WHERE mi_code IS NOT NULL;
"""


def env(key):
    if os.environ.get(key):
        return os.environ[key]
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


ref = re.search(r"https://([a-z0-9]+)\.supabase\.", env("SUPABASE_URL") or "").group(1)
tok = env("SUPABASE_ACCESS_TOKEN")
if not tok:
    raise SystemExit("SUPABASE_ACCESS_TOKEN 없음")


def run(sql):
    r = httpx.post(
        API.format(ref=ref),
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        json={"query": sql}, timeout=60.0,
    )
    return r.status_code, r.text


st, body = run(DDL)
print(f"DDL HTTP {st}: {body[:200]}")
st2, body2 = run(
    "select column_name from information_schema.columns "
    "where table_name='councilors' and column_name in "
    "('committees','mi_code','synced_at') order by 1"
)
print(f"verify HTTP {st2}: {body2[:300]}")
