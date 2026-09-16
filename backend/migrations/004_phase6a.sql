-- Phase 6A: 회의관리 확장 + 교정 고도화 + 회의록 상태관리
-- 실행일: 2026-02-11

-- =============================================================================
-- 1. meetings 테이블 확장
-- =============================================================================
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS meeting_type VARCHAR(50);
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS committee VARCHAR(200);
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS transcript_status VARCHAR(50) DEFAULT 'draft'
  CHECK (transcript_status IN ('draft', 'reviewing', 'final'));

-- =============================================================================
-- 2. meeting_participants: 회의 참석 의원
-- =============================================================================
CREATE TABLE IF NOT EXISTS meeting_participants (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  councilor_id VARCHAR(100) NOT NULL,
  name VARCHAR(200),
  role VARCHAR(100),
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(meeting_id, councilor_id)
);

CREATE INDEX IF NOT EXISTS idx_meeting_participants_meeting_id
  ON meeting_participants(meeting_id);

-- =============================================================================
-- 3. meeting_agendas: 회의 안건
-- =============================================================================
CREATE TABLE IF NOT EXISTS meeting_agendas (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  order_num INT NOT NULL,
  title VARCHAR(500) NOT NULL,
  description TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_meeting_agendas_meeting_id
  ON meeting_agendas(meeting_id);

-- =============================================================================
-- 4. subtitle_history: 자막 변경 이력
-- =============================================================================
CREATE TABLE IF NOT EXISTS subtitle_history (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  subtitle_id UUID NOT NULL REFERENCES subtitles(id) ON DELETE CASCADE,
  field_name VARCHAR(50) NOT NULL,
  old_value TEXT,
  new_value TEXT,
  changed_by VARCHAR(200),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_subtitle_history_subtitle_id
  ON subtitle_history(subtitle_id);

-- =============================================================================
-- 5. transcript_publications: 회의록 확정/공개 이력
-- =============================================================================
CREATE TABLE IF NOT EXISTS transcript_publications (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  status VARCHAR(50) NOT NULL CHECK (status IN ('draft', 'reviewing', 'final')),
  published_by VARCHAR(200),
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_transcript_publications_meeting_id
  ON transcript_publications(meeting_id);
