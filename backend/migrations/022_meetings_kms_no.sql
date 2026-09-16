-- 022: meetings.kms_no — 경기도의회 홈페이지(KMS 최근회의영상) 목록 번호
--
-- 의회 홈페이지의 영상 목록 번호(예: 4438)를 저장해 우리 회의 목록을
-- 의회 홈페이지와 같은 번호순으로 정렬·표시한다.
-- NULL 허용(생중계 스텁 등 KMS 미매칭 회의), 정렬 인덱스 추가.

ALTER TABLE meetings ADD COLUMN IF NOT EXISTS kms_no INTEGER;

CREATE INDEX IF NOT EXISTS idx_meetings_kms_no
    ON meetings (kms_no DESC NULLS LAST);

COMMENT ON COLUMN meetings.kms_no IS '경기도의회 홈페이지(KMS) 최근회의영상 목록 번호 — 정렬·대조용';
