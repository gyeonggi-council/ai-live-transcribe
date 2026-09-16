-- =============================================================================
-- 009_councilors_expansion.sql
-- 의원정보 동기화를 위한 councilors 테이블 확장
-- =============================================================================

-- 새 컬럼 추가 (IF NOT EXISTS는 ALTER TABLE ADD COLUMN에서 지원)
DO $$
BEGIN
  -- mi_code: 경기도의회 고유 코드 (upsert 키)
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'councilors' AND column_name = 'mi_code'
  ) THEN
    ALTER TABLE councilors ADD COLUMN mi_code VARCHAR(50);
  END IF;

  -- profile_image_url: 프로필 사진 URL
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'councilors' AND column_name = 'profile_image_url'
  ) THEN
    ALTER TABLE councilors ADD COLUMN profile_image_url TEXT;
  END IF;

  -- committees: 소속 위원회 [{name, role}]
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'councilors' AND column_name = 'committees'
  ) THEN
    ALTER TABLE councilors ADD COLUMN committees JSONB DEFAULT '[]'::jsonb;
  END IF;

  -- office_number: 사무실 번호
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'councilors' AND column_name = 'office_number'
  ) THEN
    ALTER TABLE councilors ADD COLUMN office_number VARCHAR(50);
  END IF;

  -- synced_at: 마지막 동기화 시각
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'councilors' AND column_name = 'synced_at'
  ) THEN
    ALTER TABLE councilors ADD COLUMN synced_at TIMESTAMPTZ;
  END IF;

  -- created_at (기존 테이블에 없을 수 있음)
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'councilors' AND column_name = 'created_at'
  ) THEN
    ALTER TABLE councilors ADD COLUMN created_at TIMESTAMPTZ DEFAULT NOW();
  END IF;

  -- updated_at
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'councilors' AND column_name = 'updated_at'
  ) THEN
    ALTER TABLE councilors ADD COLUMN updated_at TIMESTAMPTZ DEFAULT NOW();
  END IF;
END $$;

-- mi_code UNIQUE INDEX
CREATE UNIQUE INDEX IF NOT EXISTS idx_councilors_mi_code
  ON councilors(mi_code)
  WHERE mi_code IS NOT NULL;

-- updated_at 자동 갱신 트리거
DROP TRIGGER IF EXISTS trg_councilors_updated_at ON councilors;
CREATE TRIGGER trg_councilors_updated_at
  BEFORE UPDATE ON councilors
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

COMMENT ON COLUMN councilors.mi_code IS '경기도의회 고유 코드 (동기화 키)';
COMMENT ON COLUMN councilors.profile_image_url IS '프로필 사진 URL';
COMMENT ON COLUMN councilors.committees IS '소속 위원회 [{name, role}]';
COMMENT ON COLUMN councilors.office_number IS '사무실 번호';
COMMENT ON COLUMN councilors.synced_at IS '마지막 동기화 시각';
