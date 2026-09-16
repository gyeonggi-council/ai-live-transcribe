-- 019: councilor_voiceprints.is_chair — 위원회 위원장 지정
--
-- 상임위 회의는 위원장이 회의 내내 발언(상시 화자)하므로, 실시간 화자 식별에서
-- 위원장 voiceprint를 항상 diarize known_speaker slot 1에 고정한다.
-- 동기화 데이터에 역할 정보가 없어(전부 "위원") 관리자가 위원회별로 1명을 위원장으로 지정한다.

ALTER TABLE councilor_voiceprints
  ADD COLUMN IF NOT EXISTS is_chair BOOLEAN NOT NULL DEFAULT false;

-- 위원회별 위원장 조회 인덱스
CREATE INDEX IF NOT EXISTS idx_voiceprints_chair
  ON councilor_voiceprints(committee, is_chair);

COMMENT ON COLUMN councilor_voiceprints.is_chair IS
  '위원회 위원장 여부. true면 실시간 diarize known-speaker에 항상 포함(상시 화자).';
