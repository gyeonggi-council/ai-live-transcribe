-- Phase 11C: 속기록 수정 이력 테이블
-- @TASK P11C-T1 - 속기록 수정 이력 DB 마이그레이션

CREATE TABLE IF NOT EXISTS stenography_edit_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  line_id UUID NOT NULL,
  editor_id UUID,
  editor_name VARCHAR(100) NOT NULL,
  field_changed VARCHAR(20) NOT NULL CHECK (field_changed IN ('text', 'speaker', 'start_ms', 'end_ms', 'paragraph')),
  old_value TEXT,
  new_value TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_steno_hist_line ON stenography_edit_history(line_id);
CREATE INDEX IF NOT EXISTS idx_steno_hist_created ON stenography_edit_history(created_at DESC);
