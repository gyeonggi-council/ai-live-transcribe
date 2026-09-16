-- 020_ai_final_and_concurrency.sql
-- AI 최종본 구분 + 라인 낙관적 동시성

-- 최종본 종류 구분: 'manual'(속기사 수기) | 'ai_final'(AI 생성 최종본)
ALTER TABLE stenography_records
  ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'manual';

-- 생성 설정/모델/소요시간 등 메타 기록 (선택)
ALTER TABLE stenography_records
  ADD COLUMN IF NOT EXISTS source_meta jsonb;

-- 라인 낙관적 동시성 + 최종 수정자
ALTER TABLE stenography_lines
  ADD COLUMN IF NOT EXISTS version int NOT NULL DEFAULT 1;
ALTER TABLE stenography_lines
  ADD COLUMN IF NOT EXISTS updated_by text;

-- 회의별 최종본 빠른 조회
CREATE INDEX IF NOT EXISTS idx_steno_records_meeting_kind
  ON stenography_records (meeting_id, kind);
