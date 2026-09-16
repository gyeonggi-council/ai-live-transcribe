-- 025_stenography_records_base.sql
-- 속기록 레코드 기본 테이블 (초기 프로젝트에서 수동 생성됐던 테이블의 정식 마이그레이션)
-- 현 Supabase 프로젝트에 부재해 ai_final/회의록 미리보기 경로가 폴백으로만 동작 — 정식 생성.
-- 011(stenography_lines)과 020(kind/source_meta/version)이 이 테이블을 전제한다.

CREATE TABLE IF NOT EXISTS stenography_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id UUID NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    stenographer_name TEXT,
    status TEXT NOT NULL DEFAULT 'draft',  -- draft | submitted | approved
    file_path TEXT,
    filename TEXT,
    file_size BIGINT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_steno_records_meeting
  ON stenography_records (meeting_id);
