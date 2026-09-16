-- =============================================================================
-- 001_initial.sql
-- 경기도의회 실시간 자막 서비스 - 초기 데이터베이스 마이그레이션
-- =============================================================================
-- 실행 방법: Supabase 대시보드 > SQL Editor에서 실행
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Extensions
-- -----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- -----------------------------------------------------------------------------
-- 2. Functions
-- -----------------------------------------------------------------------------

-- updated_at 자동 업데이트 트리거 함수
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- -----------------------------------------------------------------------------
-- 3. Tables
-- -----------------------------------------------------------------------------

-- 3.1 meetings (회의)
CREATE TABLE IF NOT EXISTS meetings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title VARCHAR(255) NOT NULL,
  meeting_date DATE NOT NULL,
  stream_url TEXT,
  vod_url TEXT,
  status VARCHAR(20) DEFAULT 'scheduled'
    CHECK (status IN ('scheduled', 'live', 'processing', 'ended')),
  duration_seconds INT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE meetings IS '회의 정보';
COMMENT ON COLUMN meetings.id IS '고유 식별자';
COMMENT ON COLUMN meetings.title IS '회의 제목';
COMMENT ON COLUMN meetings.meeting_date IS '회의 날짜';
COMMENT ON COLUMN meetings.stream_url IS '실시간 스트림 URL';
COMMENT ON COLUMN meetings.vod_url IS 'VOD URL';
COMMENT ON COLUMN meetings.status IS '회의 상태 (scheduled, live, processing, ended)';
COMMENT ON COLUMN meetings.duration_seconds IS '총 재생 시간 (초)';
COMMENT ON COLUMN meetings.created_at IS '생성 시각';
COMMENT ON COLUMN meetings.updated_at IS '수정 시각';

-- 3.2 subtitles (자막)
CREATE TABLE IF NOT EXISTS subtitles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  start_time FLOAT NOT NULL,
  end_time FLOAT NOT NULL,
  text TEXT NOT NULL,
  speaker VARCHAR(100),
  confidence FLOAT CHECK (confidence >= 0 AND confidence <= 1),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE subtitles IS '자막 정보';
COMMENT ON COLUMN subtitles.id IS '고유 식별자';
COMMENT ON COLUMN subtitles.meeting_id IS '회의 FK';
COMMENT ON COLUMN subtitles.start_time IS '시작 시간 (초)';
COMMENT ON COLUMN subtitles.end_time IS '종료 시간 (초)';
COMMENT ON COLUMN subtitles.text IS '자막 텍스트';
COMMENT ON COLUMN subtitles.speaker IS '화자 (선택)';
COMMENT ON COLUMN subtitles.confidence IS '인식 신뢰도 (0~1)';
COMMENT ON COLUMN subtitles.created_at IS '생성 시각';

-- 3.3 councilors (의원 명단)
CREATE TABLE IF NOT EXISTS councilors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(100) NOT NULL,
  party VARCHAR(100),
  district VARCHAR(200),
  term INT,
  is_active BOOLEAN DEFAULT true
);

COMMENT ON TABLE councilors IS '의원 명단';
COMMENT ON COLUMN councilors.id IS '고유 식별자';
COMMENT ON COLUMN councilors.name IS '의원 이름';
COMMENT ON COLUMN councilors.party IS '소속 정당';
COMMENT ON COLUMN councilors.district IS '지역구';
COMMENT ON COLUMN councilors.term IS '대수 (예: 11)';
COMMENT ON COLUMN councilors.is_active IS '현역 여부';

-- 3.4 dictionary (용어 사전)
CREATE TABLE IF NOT EXISTS dictionary (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  wrong_text VARCHAR(200) NOT NULL,
  correct_text VARCHAR(200) NOT NULL,
  category VARCHAR(50),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(wrong_text)
);

COMMENT ON TABLE dictionary IS '용어 교정 사전';
COMMENT ON COLUMN dictionary.id IS '고유 식별자';
COMMENT ON COLUMN dictionary.wrong_text IS '잘못 인식되는 텍스트';
COMMENT ON COLUMN dictionary.correct_text IS '올바른 텍스트';
COMMENT ON COLUMN dictionary.category IS '분류 (councilor, term, etc.)';
COMMENT ON COLUMN dictionary.created_at IS '생성 시각';

-- -----------------------------------------------------------------------------
-- 4. Indexes
-- -----------------------------------------------------------------------------

-- meetings 인덱스
CREATE INDEX IF NOT EXISTS idx_meetings_status ON meetings(status);
CREATE INDEX IF NOT EXISTS idx_meetings_date ON meetings(meeting_date DESC);

-- subtitles 인덱스
CREATE INDEX IF NOT EXISTS idx_subtitles_meeting_time ON subtitles(meeting_id, start_time);

-- Full-Text Search 인덱스 (한국어 - 'simple' 설정은 형태소 분석 없이 공백 기준 토큰화)
CREATE INDEX IF NOT EXISTS idx_subtitles_text_search ON subtitles
  USING GIN (to_tsvector('simple', text));

-- trigram 인덱스 (부분 문자열 검색)
CREATE INDEX IF NOT EXISTS idx_subtitles_text_trgm ON subtitles
  USING GIN (text gin_trgm_ops);

-- councilors 인덱스
CREATE INDEX IF NOT EXISTS idx_councilors_name ON councilors(name);
CREATE INDEX IF NOT EXISTS idx_councilors_active ON councilors(is_active) WHERE is_active = true;

-- dictionary 인덱스
CREATE INDEX IF NOT EXISTS idx_dictionary_wrong ON dictionary(wrong_text);
CREATE INDEX IF NOT EXISTS idx_dictionary_category ON dictionary(category);

-- -----------------------------------------------------------------------------
-- 5. Triggers
-- -----------------------------------------------------------------------------

-- meetings 테이블의 updated_at 자동 업데이트 트리거
DROP TRIGGER IF EXISTS meetings_updated_at ON meetings;
CREATE TRIGGER meetings_updated_at
  BEFORE UPDATE ON meetings
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- -----------------------------------------------------------------------------
-- 6. Supabase Realtime 설정
-- -----------------------------------------------------------------------------

-- subtitles 테이블에 Realtime 활성화 (자막 실시간 푸시용)
ALTER PUBLICATION supabase_realtime ADD TABLE subtitles;

-- -----------------------------------------------------------------------------
-- 7. Row Level Security (RLS) - MVP에서는 비활성화
-- -----------------------------------------------------------------------------

-- MVP: RLS 비활성화 (내부 사용)
ALTER TABLE meetings DISABLE ROW LEVEL SECURITY;
ALTER TABLE subtitles DISABLE ROW LEVEL SECURITY;
ALTER TABLE councilors DISABLE ROW LEVEL SECURITY;
ALTER TABLE dictionary DISABLE ROW LEVEL SECURITY;

-- =============================================================================
-- 마이그레이션 완료
-- =============================================================================
