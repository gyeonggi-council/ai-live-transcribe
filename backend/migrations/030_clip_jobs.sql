-- 030: 발언영상 클립 워크벤치 — 클립 잡 영속화 + 초안 인덱스 시간 오프셋
--
-- 배경: 데스크톱 영상추출기(exe)를 웹으로 대체하면서 "7일 보관·재다운로드"가 요구됐다.
-- 기존 speakers.py 의 clip-jobs 는 인메모리(파드 재시작이면 소멸)라 이 테이블로 옮긴다.
--
-- 적용 순서: ★배포보다 먼저★ 적용하고, 적용 뒤 반드시
--   kubectl -n ggc-poc rollout restart deploy/ggc-live-transcribe-pgrst
-- (PostgREST 가 스키마를 캐시한다 — 028 교훈)

SET search_path = subtitle;

-- 초안(실시간 자막) 인덱스 → KMS VOD 시간축 보정. VOD시각 = 자막 start_time + 이 값.
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS clip_time_offset NUMERIC(8,2);
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS clip_time_offset_updated_at TIMESTAMPTZ;
COMMENT ON COLUMN meetings.clip_time_offset IS
  '초안(실시간 자막) 인덱스 → KMS VOD 시간축 보정(초). VOD시각 = 자막 start_time + 이 값. 회의당 1회 맞춤. 공식/AI 인덱스에는 쓰지 않는다';

CREATE TABLE IF NOT EXISTS clip_jobs (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  meeting_id       UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  owner_user_id    UUID REFERENCES users(id) ON DELETE SET NULL,
  owner_username   VARCHAR(50) NOT NULL,           -- quick-admin 등 users 에 없는 주체 + 표시용
  label            VARCHAR(120) NOT NULL DEFAULT '클립',
  speaker_name     VARCHAR(100),
  source_kind      VARCHAR(16) NOT NULL CHECK (source_kind IN ('official','ai','live','manual')),
  segments         JSONB NOT NULL,                  -- [{"start":..,"end":..}] 여유·병합 적용 후, VOD 시간축
  pad_before       NUMERIC(6,2) NOT NULL DEFAULT 0,
  pad_after        NUMERIC(6,2) NOT NULL DEFAULT 0,
  merge            BOOLEAN NOT NULL DEFAULT true,
  with_srt         BOOLEAN NOT NULL DEFAULT true,
  time_offset      NUMERIC(8,2) NOT NULL DEFAULT 0, -- 잡 생성 시점의 오프셋(감사·SRT 재계산용)
  vod_url          TEXT NOT NULL,                   -- 생성 시점의 회의 vod_url 스냅샷
  total_seconds    NUMERIC(10,2) NOT NULL,
  status           VARCHAR(12) NOT NULL DEFAULT 'queued'
                   CHECK (status IN ('queued','running','done','failed','cancelled','expired')),
  attempts         SMALLINT NOT NULL DEFAULT 0,
  progress         REAL NOT NULL DEFAULT 0,
  current_segment  INT,
  error            TEXT,
  files            JSONB NOT NULL DEFAULT '[]'::jsonb,  -- [{"name":"…mp4","kind":"mp4|srt","bytes":N}]
  bytes_total      BIGINT NOT NULL DEFAULT 0,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at       TIMESTAMPTZ,
  finished_at      TIMESTAMPTZ,
  expires_at       TIMESTAMPTZ NOT NULL DEFAULT now() + interval '7 days',
  evicted_at       TIMESTAMPTZ,
  evicted_reason   VARCHAR(16) CHECK (evicted_reason IN ('ttl','capacity','manual','restart'))
);

CREATE INDEX IF NOT EXISTS idx_clip_jobs_owner_created ON clip_jobs (owner_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_clip_jobs_meeting       ON clip_jobs (meeting_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_clip_jobs_active        ON clip_jobs (created_at) WHERE status IN ('queued','running');
CREATE INDEX IF NOT EXISTS idx_clip_jobs_done_expires  ON clip_jobs (expires_at) WHERE status = 'done';

COMMENT ON TABLE clip_jobs IS
  '발언영상 클립 추출 잡. 파일은 PVC /app/clips/jobs/<id>/ 에 있고 보존은 7일 AND 바이트 상한(오래된 것부터). 파일 삭제 시 status=expired + evicted_reason';

-- superuser 로 만든 객체의 소유권을 전용 롤로 (템플릿 규약)
DO $ownership$
DECLARE r RECORD;
BEGIN
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'subtitle' AND tablename = 'clip_jobs' LOOP
    EXECUTE format('ALTER TABLE subtitle.%I OWNER TO ggc_subtitle', r.tablename);
  END LOOP;
END
$ownership$;
