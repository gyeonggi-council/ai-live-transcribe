-- 037: 회의 시각 기준점(clock anchor) — 자막 시계(초) ↔ 실제 시각(벽시계)
--
-- 배경: 영상 위와 VOD 에 "이 장면이 실제로 몇 시였나"를 띄우려면 기준점이 필요하다.
--       그런데 자막 start_time 은 **수신된 오디오 초**라서, 정회로 방송이 끊긴 구간을
--       양쪽(자막·녹음) 모두 건너뛴다. 그래서 "회의 시작 시각 + 경과 초"로 계산하면
--       정회 한 번에 그 길이만큼 통째로 틀어진다(1시간 정회 = 1시간 오차).
--
--       세션이 시작될 때와 끊겼다 이어질 때마다 (그 순간의 자막 시계, 그 순간의 실제 시각)을
--       한 줄 남겨 두면, 구간별 선형 매핑으로 정확히 되돌릴 수 있다.
--       live_recorder 의 `.sessions`(clock↔byte) 사이드카와 같은 구조다.
--
-- 적용 순서: ★배포보다 먼저★ 적용하고, 적용 뒤 반드시
--   kubectl -n ggc-poc rollout restart deploy/ggc-live-transcribe-pgrst
-- (PostgREST 가 스키마를 캐시한다 — 028·030 교훈)

SET search_path = subtitle;

CREATE TABLE IF NOT EXISTS meeting_clock_anchors (
  id          BIGSERIAL PRIMARY KEY,
  meeting_id  UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  clock_sec   NUMERIC(10,2) NOT NULL,   -- 자막 start_time 과 같은 시계(수신된 오디오 초)
  wall_at     TIMESTAMPTZ NOT NULL,     -- 그 시계 지점의 실제 시각
  source      VARCHAR(16) NOT NULL DEFAULT 'live'
              CHECK (source IN ('live', 'manual')),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_meeting_clock_anchors_meeting
  ON meeting_clock_anchors(meeting_id, clock_sec);

COMMENT ON TABLE meeting_clock_anchors IS
  '회의 시각 기준점 — (자막 시계, 실제 시각) 쌍. 라이브 STT 가 세션 시작·정회 재개마다 한 줄 남긴다. 실제시각 = 기준점.wall_at + (자막시계 − 기준점.clock_sec)';
COMMENT ON COLUMN meeting_clock_anchors.clock_sec IS
  '자막 start_time 과 같은 시계(수신된 오디오 초). 정회 구간은 건너뛰므로 벽시계 경과와 다르다';
COMMENT ON COLUMN meeting_clock_anchors.wall_at IS
  '그 시계 지점의 실제 시각. 디코더가 재생목록 엣지보다 뒤처진 만큼(edge_lag)을 빼서 기록한다';
COMMENT ON COLUMN meeting_clock_anchors.source IS
  'live = 라이브 STT 가 자동 기록 / manual = 사람이 보정. 자막 created_at 으로 뒤늦게 추정한 값은 저장하지 않는다(응답에서만 estimated 로 표시)';

-- ── 소유권 이전 — PostgREST 가 ggc_subtitle 로 접속한다 (029 교훈) ──────────
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ggc_subtitle') THEN
    EXECUTE 'ALTER TABLE subtitle.meeting_clock_anchors OWNER TO ggc_subtitle';
    EXECUTE 'ALTER SEQUENCE subtitle.meeting_clock_anchors_id_seq OWNER TO ggc_subtitle';
  END IF;
END $$;
