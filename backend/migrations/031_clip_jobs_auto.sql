-- 031: 자동 클립 — AI 자막이 끝난 회의의 의원 발언 영상을 서버가 미리 잘라(720p 로 작게) 둔다
--
-- 배경(2026-09-10 사용자 결정): 설치형 추출기의 "확인 후 추출" 없이 의원 전원 영상을 받기만 하게.
-- 유튜브·휴대폰 공유용이라 원본(2.26Mbps)을 720p H.264 CRF28 로 줄인다(실측 원본의 17%).
-- 자동 잡은 api 파드가 아니라 별도 작업자 파드(ggc-live-transcribe-clipper, cpu 1·mem 1Gi)가 돌린다.
--
--   origin   manual = 사람이 워크벤치에서 요청(api 파드가 실행) · auto = 작업자가 만든 것(작업자가 실행)
--   compress true = 재인코딩(작게) · false = -c copy(원본 그대로, 수동 추출)
--
-- 적용 순서: ★배포보다 먼저★ 적용하고, 적용 뒤 반드시
--   kubectl -n ggc-poc rollout restart deploy/ggc-live-transcribe-pgrst
-- (PostgREST 가 스키마를 캐시한다 — 028 교훈. 컬럼 없이 새 코드가 뜨면 수동 추출까지 500 이 난다)

SET search_path = subtitle;

ALTER TABLE clip_jobs ADD COLUMN IF NOT EXISTS origin VARCHAR(10) NOT NULL DEFAULT 'manual'
  CHECK (origin IN ('manual', 'auto'));
ALTER TABLE clip_jobs ADD COLUMN IF NOT EXISTS compress BOOLEAN NOT NULL DEFAULT false;

-- 작업자: 가장 오래된 대기 자동 잡 · 스캔: 회의별 자동 잡 유무
CREATE INDEX IF NOT EXISTS idx_clip_jobs_origin_status ON clip_jobs (origin, status, created_at);
CREATE INDEX IF NOT EXISTS idx_clip_jobs_meeting_origin ON clip_jobs (meeting_id, origin);

COMMENT ON COLUMN clip_jobs.origin IS
  'manual=워크벤치에서 사람이 요청(api 파드 실행) · auto=AI 자막 완료 회의를 작업자 파드가 자동으로 자름(보관 3일·자동분 예산 안)';
COMMENT ON COLUMN clip_jobs.compress IS
  'true=720p H.264 CRF 재인코딩(공유용, 원본의 약 17%) · false=-c copy';
