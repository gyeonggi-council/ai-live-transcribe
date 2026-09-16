-- 011_stenography_lines.sql
-- 속기록 라인 단위 테이블 (Professional Stenography Editor)
-- stenography_records → stenography_lines (1:N)

CREATE TABLE IF NOT EXISTS stenography_lines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id UUID NOT NULL REFERENCES stenography_records(id) ON DELETE CASCADE,
    sequence_no INT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    speaker VARCHAR(200),
    start_ms INT,
    end_ms INT,
    starts_new_paragraph BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Prevent duplicate sequence numbers per record
ALTER TABLE stenography_lines
ADD CONSTRAINT stenography_lines_record_id_sequence_no_unique
UNIQUE (record_id, sequence_no);

-- Fast lookups by record_id
CREATE INDEX IF NOT EXISTS idx_stenography_lines_record_id
ON stenography_lines(record_id);

-- Auto-update updated_at timestamp
DROP TRIGGER IF EXISTS trg_stenography_lines_updated_at ON stenography_lines;
CREATE TRIGGER trg_stenography_lines_updated_at
    BEFORE UPDATE ON stenography_lines
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

COMMENT ON TABLE stenography_lines IS '속기록 라인별 상세 정보 (화자, 타이밍, 텍스트)';
COMMENT ON COLUMN stenography_lines.record_id IS '속기록 레코드 FK';
COMMENT ON COLUMN stenography_lines.sequence_no IS '정렬 순서 (1부터, 갭 허용)';
COMMENT ON COLUMN stenography_lines.start_ms IS '시작 시간 (밀리초)';
COMMENT ON COLUMN stenography_lines.end_ms IS '종료 시간 (밀리초)';
COMMENT ON COLUMN stenography_lines.starts_new_paragraph IS '새 문단 시작 여부';
