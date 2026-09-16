-- Phase: anonymous VOD registration — dedup safeguard
-- vod_url 기준 중복 회의 방지. NULL 은 허용 (실시간/예정 회의).
--
-- ⚠ 적용 전 확인:
--   SELECT vod_url, COUNT(*)
--   FROM meetings
--   WHERE vod_url IS NOT NULL
--   GROUP BY vod_url
--   HAVING COUNT(*) > 1;
-- 중복 행이 있으면 이 마이그레이션이 실패합니다. 먼저 수동 정리하세요.
--
-- @TASK anonymous-vod-registration

CREATE UNIQUE INDEX IF NOT EXISTS uniq_meetings_vod_url
  ON meetings(vod_url)
  WHERE vod_url IS NOT NULL;

COMMENT ON INDEX uniq_meetings_vod_url IS
  '동일 vod_url 중복 등록 방지 (partial: NULL 허용)';
