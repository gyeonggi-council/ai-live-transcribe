-- =============================================================================
-- 003_bills.sql - 의안 관리 테이블
-- =============================================================================
-- ⚠️ 실행 전: Supabase 대시보드 > SQL Editor에서 실행
-- =============================================================================

-- @TASK P5-T4.1 - bills 테이블 마이그레이션
-- @SPEC docs/planning/

-- =============================================================================
-- 1. bills (의안)
-- =============================================================================
CREATE TABLE IF NOT EXISTS bills (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  bill_number VARCHAR(50) NOT NULL,          -- 의안번호 (예: "제2026-123호")
  title VARCHAR(500) NOT NULL,                -- 의안명
  proposer VARCHAR(200),                      -- 제안자
  committee VARCHAR(200),                     -- 소관 위원회
  status VARCHAR(50) DEFAULT 'received'
    CHECK (status IN ('received', 'reviewing', 'decided', 'promulgated')),
  proposed_date DATE,                         -- 제안일
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE bills IS '의안 (경기도의회 의안 정보)';
COMMENT ON COLUMN bills.id IS '고유 식별자';
COMMENT ON COLUMN bills.bill_number IS '의안번호 (예: 제2026-123호)';
COMMENT ON COLUMN bills.title IS '의안명';
COMMENT ON COLUMN bills.proposer IS '제안자';
COMMENT ON COLUMN bills.committee IS '소관 위원회';
COMMENT ON COLUMN bills.status IS '상태: received(접수), reviewing(심사중), decided(의결), promulgated(공포)';
COMMENT ON COLUMN bills.proposed_date IS '제안일';
COMMENT ON COLUMN bills.created_at IS '생성 시각';
COMMENT ON COLUMN bills.updated_at IS '수정 시각';

-- =============================================================================
-- 2. bill_mentions (의안-회의록 연결)
-- =============================================================================
CREATE TABLE IF NOT EXISTS bill_mentions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  bill_id UUID NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
  meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  subtitle_id UUID REFERENCES subtitles(id) ON DELETE SET NULL,  -- 선택: 특정 자막 구간
  start_time FLOAT,                           -- 언급 시작 시간 (초)
  end_time FLOAT,                             -- 언급 종료 시간 (초)
  note TEXT,                                  -- 메모
  created_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE bill_mentions IS '의안-회의록 연결 (어느 회의에서 의안이 논의되었는지)';
COMMENT ON COLUMN bill_mentions.id IS '고유 식별자';
COMMENT ON COLUMN bill_mentions.bill_id IS '의안 FK';
COMMENT ON COLUMN bill_mentions.meeting_id IS '회의 FK';
COMMENT ON COLUMN bill_mentions.subtitle_id IS '자막 FK (선택)';
COMMENT ON COLUMN bill_mentions.start_time IS '언급 시작 시간 (초)';
COMMENT ON COLUMN bill_mentions.end_time IS '언급 종료 시간 (초)';
COMMENT ON COLUMN bill_mentions.note IS '메모';
COMMENT ON COLUMN bill_mentions.created_at IS '생성 시각';

-- =============================================================================
-- 3. Indexes
-- =============================================================================

-- bills 인덱스
CREATE INDEX IF NOT EXISTS idx_bills_number ON bills(bill_number);
CREATE INDEX IF NOT EXISTS idx_bills_committee ON bills(committee);
CREATE INDEX IF NOT EXISTS idx_bills_status ON bills(status);
CREATE INDEX IF NOT EXISTS idx_bills_proposed_date ON bills(proposed_date DESC);

-- bill_mentions 인덱스
CREATE INDEX IF NOT EXISTS idx_bill_mentions_bill ON bill_mentions(bill_id);
CREATE INDEX IF NOT EXISTS idx_bill_mentions_meeting ON bill_mentions(meeting_id);
CREATE INDEX IF NOT EXISTS idx_bill_mentions_subtitle ON bill_mentions(subtitle_id);

-- =============================================================================
-- 4. Triggers
-- =============================================================================

-- bills 테이블의 updated_at 자동 업데이트 트리거
DROP TRIGGER IF EXISTS bills_updated_at ON bills;
CREATE TRIGGER bills_updated_at
  BEFORE UPDATE ON bills
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- =============================================================================
-- 5. RLS 비활성화 (MVP - 내부 사용)
-- =============================================================================
ALTER TABLE bills DISABLE ROW LEVEL SECURITY;
ALTER TABLE bill_mentions DISABLE ROW LEVEL SECURITY;

-- =============================================================================
-- 마이그레이션 완료
-- 결과 확인: SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name;
-- =============================================================================
