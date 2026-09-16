-- =============================================================================
-- 005_phase7.sql
-- Phase 7: 자막 검증 + AI 요약 기능
-- 실행일: 2026-02-11
-- =============================================================================

-- =============================================================================
-- 1. subtitles 테이블 확장 - 자막 검증 상태 추가
-- =============================================================================
ALTER TABLE subtitles ADD COLUMN IF NOT EXISTS verification_status VARCHAR(20) DEFAULT 'unverified'
  CHECK (verification_status IN ('unverified', 'verified', 'flagged'));

COMMENT ON COLUMN subtitles.verification_status IS '자막 검증 상태 (unverified: 미검증, verified: 검증완료, flagged: 문제표시)';

-- subtitles 검증 상태 필터링용 인덱스
CREATE INDEX IF NOT EXISTS idx_subtitles_meeting_verification
  ON subtitles(meeting_id, verification_status);

-- =============================================================================
-- 2. meeting_summaries: 회의 AI 요약
-- =============================================================================
CREATE TABLE IF NOT EXISTS meeting_summaries (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  summary_text TEXT NOT NULL,                    -- 전체 요약 (2-3 문장)
  agenda_summaries JSONB,                        -- 안건별 요약 [{order_num, title, summary}]
  key_decisions JSONB,                           -- 핵심 결정사항 ["결정1", "결정2"]
  action_items JSONB,                            -- 후속 조치 ["조치1", "조치2"]
  model_used VARCHAR(100),                       -- 사용된 AI 모델 (e.g., "gpt-4o-mini")
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(meeting_id)                             -- 회의당 1개 요약만
);

COMMENT ON TABLE meeting_summaries IS '회의 AI 요약 (자동 생성된 요약, 결정사항, 후속조치)';
COMMENT ON COLUMN meeting_summaries.id IS '고유 식별자';
COMMENT ON COLUMN meeting_summaries.meeting_id IS '회의 FK';
COMMENT ON COLUMN meeting_summaries.summary_text IS '전체 회의 요약 (2-3 문장)';
COMMENT ON COLUMN meeting_summaries.agenda_summaries IS '안건별 요약 (JSONB 배열)';
COMMENT ON COLUMN meeting_summaries.key_decisions IS '핵심 결정사항 (JSONB 배열)';
COMMENT ON COLUMN meeting_summaries.action_items IS '후속 조치 사항 (JSONB 배열)';
COMMENT ON COLUMN meeting_summaries.model_used IS '사용된 AI 모델 명칭';
COMMENT ON COLUMN meeting_summaries.created_at IS '생성 시각';
COMMENT ON COLUMN meeting_summaries.updated_at IS '수정 시각';

-- =============================================================================
-- 3. Indexes
-- =============================================================================

-- meeting_summaries 조회 성능 최적화
CREATE INDEX IF NOT EXISTS idx_meeting_summaries_meeting_id
  ON meeting_summaries(meeting_id);

-- =============================================================================
-- 4. Triggers
-- =============================================================================

-- meeting_summaries 테이블의 updated_at 자동 업데이트 트리거
DROP TRIGGER IF EXISTS meeting_summaries_updated_at ON meeting_summaries;
CREATE TRIGGER meeting_summaries_updated_at
  BEFORE UPDATE ON meeting_summaries
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- =============================================================================
-- 5. RLS 비활성화 (MVP - 내부 사용)
-- =============================================================================
ALTER TABLE meeting_summaries DISABLE ROW LEVEL SECURITY;

-- =============================================================================
-- 마이그레이션 완료
-- 검증: SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name;
-- =============================================================================
