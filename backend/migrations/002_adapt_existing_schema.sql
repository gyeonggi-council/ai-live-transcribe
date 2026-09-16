-- =============================================================================
-- 002_adapt_existing_schema.sql
-- 기존 Supabase 테이블과 우리 스키마 통합 마이그레이션
-- =============================================================================
-- ⚠️ 실행 전: Supabase 대시보드 > SQL Editor에서 실행
-- ⚠️ 기존 테이블(video_sessions, subtitles 등)의 데이터를 보존합니다
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Extensions
-- -----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- -----------------------------------------------------------------------------
-- 2. Functions
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- -----------------------------------------------------------------------------
-- 3. 기존 subtitles 테이블 → subtitles_legacy 로 이름 변경
--    (기존 715개 자막 데이터 보존)
-- -----------------------------------------------------------------------------
DO $$
BEGIN
  -- 기존 subtitles 테이블이 있고, meeting_id 컬럼이 없으면 (= 구 스키마)
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'subtitles'
  ) AND NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'subtitles' AND column_name = 'meeting_id'
  ) THEN
    -- Realtime publication에서 제거 (에러 방지)
    BEGIN
      ALTER PUBLICATION supabase_realtime DROP TABLE subtitles;
    EXCEPTION WHEN OTHERS THEN
      NULL; -- publication에 없으면 무시
    END;

    ALTER TABLE subtitles RENAME TO subtitles_legacy;
    RAISE NOTICE '기존 subtitles → subtitles_legacy 이름 변경 완료';
  END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 4. meetings 테이블 생성
-- -----------------------------------------------------------------------------
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

-- -----------------------------------------------------------------------------
-- 5. subtitles 테이블 생성 (새 스키마)
-- -----------------------------------------------------------------------------
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

-- -----------------------------------------------------------------------------
-- 6. councilors 테이블 생성
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS councilors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(100) NOT NULL,
  party VARCHAR(100),
  district VARCHAR(200),
  term INT,
  is_active BOOLEAN DEFAULT true
);

COMMENT ON TABLE councilors IS '의원 명단';

-- -----------------------------------------------------------------------------
-- 7. dictionary 테이블 생성
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dictionary (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  wrong_text VARCHAR(200) NOT NULL,
  correct_text VARCHAR(200) NOT NULL,
  category VARCHAR(50),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(wrong_text)
);

COMMENT ON TABLE dictionary IS '용어 교정 사전';

-- -----------------------------------------------------------------------------
-- 8. Indexes
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_meetings_status ON meetings(status);
CREATE INDEX IF NOT EXISTS idx_meetings_date ON meetings(meeting_date DESC);
CREATE INDEX IF NOT EXISTS idx_subtitles_meeting_time ON subtitles(meeting_id, start_time);
CREATE INDEX IF NOT EXISTS idx_subtitles_text_search ON subtitles
  USING GIN (to_tsvector('simple', text));
CREATE INDEX IF NOT EXISTS idx_subtitles_text_trgm ON subtitles
  USING GIN (text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_councilors_name ON councilors(name);
CREATE INDEX IF NOT EXISTS idx_councilors_active ON councilors(is_active) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_dictionary_wrong ON dictionary(wrong_text);
CREATE INDEX IF NOT EXISTS idx_dictionary_category ON dictionary(category);

-- -----------------------------------------------------------------------------
-- 9. Triggers
-- -----------------------------------------------------------------------------
DROP TRIGGER IF EXISTS meetings_updated_at ON meetings;
CREATE TRIGGER meetings_updated_at
  BEFORE UPDATE ON meetings
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- -----------------------------------------------------------------------------
-- 10. Supabase Realtime
-- -----------------------------------------------------------------------------
ALTER PUBLICATION supabase_realtime ADD TABLE subtitles;

-- -----------------------------------------------------------------------------
-- 11. RLS 비활성화 (MVP - 내부 사용)
-- -----------------------------------------------------------------------------
ALTER TABLE meetings DISABLE ROW LEVEL SECURITY;
ALTER TABLE subtitles DISABLE ROW LEVEL SECURITY;
ALTER TABLE councilors DISABLE ROW LEVEL SECURITY;
ALTER TABLE dictionary DISABLE ROW LEVEL SECURITY;

-- -----------------------------------------------------------------------------
-- 12. 테스트용 샘플 데이터
-- -----------------------------------------------------------------------------
INSERT INTO meetings (title, meeting_date, status, vod_url, duration_seconds)
VALUES
  ('제365회 경기도의회 본회의', '2026-01-15', 'ended',
   'https://example.com/vod/365.mp4', 7200),
  ('제366회 경기도의회 상임위원회', '2026-01-22', 'ended',
   'https://example.com/vod/366.mp4', 5400),
  ('제367회 경기도의회 본회의', '2026-02-05', 'live',
   NULL, NULL)
ON CONFLICT DO NOTHING;

-- 샘플 자막 (첫 번째 회의)
DO $$
DECLARE
  meeting_uuid UUID;
BEGIN
  SELECT id INTO meeting_uuid FROM meetings WHERE title LIKE '%365%' LIMIT 1;
  IF meeting_uuid IS NOT NULL THEN
    INSERT INTO subtitles (meeting_id, start_time, end_time, text, speaker, confidence)
    VALUES
      (meeting_uuid, 0.0, 3.5, '의장 김철수입니다. 제365회 경기도의회 본회의를 시작하겠습니다.', '김철수', 0.95),
      (meeting_uuid, 3.5, 8.2, '오늘 안건은 2026년도 경기도 예산안 심의입니다.', '김철수', 0.92),
      (meeting_uuid, 8.2, 14.0, '먼저 기획재정위원회 위원장의 심사보고를 듣겠습니다.', '김철수', 0.94),
      (meeting_uuid, 14.0, 20.5, '위원장님 나오셔서 보고해 주시기 바랍니다.', '김철수', 0.91),
      (meeting_uuid, 20.5, 28.0, '기획재정위원회 위원장 박영희입니다. 예산안 심사 결과를 보고드리겠습니다.', '박영희', 0.93)
    ON CONFLICT DO NOTHING;
  END IF;
END $$;

-- =============================================================================
-- 마이그레이션 완료
-- 결과 확인: SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';
-- =============================================================================
