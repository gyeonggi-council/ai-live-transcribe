-- =============================================================================
-- 006_missing_tables.sql
-- 누락된 테이블 일괄 생성 (003_bills + 004_phase6a + 005_phase7 통합)
-- 실행: Supabase Dashboard > SQL Editor
-- =============================================================================

-- =============================================================================
-- 1. bills (의안)
-- =============================================================================
CREATE TABLE IF NOT EXISTS bills (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  bill_number VARCHAR(50) NOT NULL,
  title VARCHAR(500) NOT NULL,
  proposer VARCHAR(200),
  committee VARCHAR(200),
  status VARCHAR(50) DEFAULT 'received'
    CHECK (status IN ('received', 'reviewing', 'decided', 'promulgated')),
  proposed_date DATE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- 2. bill_mentions (의안-회의록 연결)
-- =============================================================================
CREATE TABLE IF NOT EXISTS bill_mentions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  bill_id UUID NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
  meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  subtitle_id UUID REFERENCES subtitles(id) ON DELETE SET NULL,
  start_time FLOAT,
  end_time FLOAT,
  note TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- 3. meetings 테이블 확장 (Phase 6A)
-- =============================================================================
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS meeting_type VARCHAR(50);
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS committee VARCHAR(200);
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS transcript_status VARCHAR(50) DEFAULT 'draft';
-- CHECK constraint는 IF NOT EXISTS 미지원이므로 DO 블록 사용
DO $$ BEGIN
  ALTER TABLE meetings ADD CONSTRAINT meetings_transcript_status_check
    CHECK (transcript_status IN ('draft', 'reviewing', 'final'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- =============================================================================
-- 4. meeting_participants (회의 참석 의원)
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

-- =============================================================================
-- 5. meeting_agendas (회의 안건)
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

-- =============================================================================
-- 6. subtitle_history (자막 변경 이력)
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

-- =============================================================================
-- 7. transcript_publications (회의록 확정/공개 이력)
-- =============================================================================
CREATE TABLE IF NOT EXISTS transcript_publications (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  status VARCHAR(50) NOT NULL CHECK (status IN ('draft', 'reviewing', 'final')),
  published_by VARCHAR(200),
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================================================
-- 8. subtitles 확장 - verification_status (Phase 7)
-- =============================================================================
ALTER TABLE subtitles ADD COLUMN IF NOT EXISTS verification_status VARCHAR(20) DEFAULT 'unverified';
DO $$ BEGIN
  ALTER TABLE subtitles ADD CONSTRAINT subtitles_verification_status_check
    CHECK (verification_status IN ('unverified', 'verified', 'flagged'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- =============================================================================
-- 9. meeting_summaries (AI 회의 요약)
-- =============================================================================
CREATE TABLE IF NOT EXISTS meeting_summaries (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  summary_text TEXT NOT NULL,
  agenda_summaries JSONB,
  key_decisions JSONB,
  action_items JSONB,
  model_used VARCHAR(100),
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(meeting_id)
);

-- =============================================================================
-- 10. Indexes
-- =============================================================================
CREATE INDEX IF NOT EXISTS idx_bills_number ON bills(bill_number);
CREATE INDEX IF NOT EXISTS idx_bills_committee ON bills(committee);
CREATE INDEX IF NOT EXISTS idx_bills_status ON bills(status);
CREATE INDEX IF NOT EXISTS idx_bills_proposed_date ON bills(proposed_date DESC);
CREATE INDEX IF NOT EXISTS idx_bill_mentions_bill ON bill_mentions(bill_id);
CREATE INDEX IF NOT EXISTS idx_bill_mentions_meeting ON bill_mentions(meeting_id);
CREATE INDEX IF NOT EXISTS idx_meeting_participants_meeting_id ON meeting_participants(meeting_id);
CREATE INDEX IF NOT EXISTS idx_meeting_agendas_meeting_id ON meeting_agendas(meeting_id);
CREATE INDEX IF NOT EXISTS idx_subtitle_history_subtitle_id ON subtitle_history(subtitle_id);
CREATE INDEX IF NOT EXISTS idx_transcript_publications_meeting_id ON transcript_publications(meeting_id);
CREATE INDEX IF NOT EXISTS idx_subtitles_meeting_verification ON subtitles(meeting_id, verification_status);
CREATE INDEX IF NOT EXISTS idx_meeting_summaries_meeting_id ON meeting_summaries(meeting_id);

-- =============================================================================
-- 11. Triggers
-- =============================================================================
DROP TRIGGER IF EXISTS bills_updated_at ON bills;
CREATE TRIGGER bills_updated_at
  BEFORE UPDATE ON bills
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

DROP TRIGGER IF EXISTS meeting_summaries_updated_at ON meeting_summaries;
CREATE TRIGGER meeting_summaries_updated_at
  BEFORE UPDATE ON meeting_summaries
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- =============================================================================
-- 12. RLS 비활성화 (MVP - 내부 사용)
-- =============================================================================
ALTER TABLE bills DISABLE ROW LEVEL SECURITY;
ALTER TABLE bill_mentions DISABLE ROW LEVEL SECURITY;
ALTER TABLE meeting_participants DISABLE ROW LEVEL SECURITY;
ALTER TABLE meeting_agendas DISABLE ROW LEVEL SECURITY;
ALTER TABLE subtitle_history DISABLE ROW LEVEL SECURITY;
ALTER TABLE transcript_publications DISABLE ROW LEVEL SECURITY;
ALTER TABLE meeting_summaries DISABLE ROW LEVEL SECURITY;
