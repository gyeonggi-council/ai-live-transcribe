-- =============================================================================
-- 007_dictionary_created_by.sql
-- 사전 테이블에 created_by 컬럼 추가 (사용자 교정 추적용)
-- =============================================================================

ALTER TABLE dictionary ADD COLUMN IF NOT EXISTS created_by VARCHAR(100);

COMMENT ON COLUMN dictionary.created_by IS '등록자 (사용자 교정 시 기록)';
