-- 039: 채널을 코드 상수에서 DB 로 (다른 의회도 자기 채널을 등록할 수 있게)
--
-- 배경: 채널 18개(위원회명·HLS 주소·방송상태 코드)가 app/core/channels.py 에 박혀 있어
--       다른 의회는 개발자가 코드를 고치지 않으면 자막을 한 줄도 볼 수 없었다.
--       이 표와 /admin/channels 화면이 그 벽을 없앤다.
--
-- 번호가 033 이 아니라 039 인 이유: main 은 032 까지지만 병합 대기 중인 브랜치가
-- 이미 033~038 을 쓰고 있다(실측). 같은 번호를 두 번 쓰면 적용 순서가 갈린다.
--
-- ★ 적용 뒤 반드시: kubectl -n ggc-poc rollout restart deploy/ggc-live-transcribe-pgrst
--   PostgREST 가 스키마를 캐시하므로, 안 하면 새 표에 전부 404 가 난다.

-- ★이 두 줄이 없으면 조용히 틀린다 (ggc-services/CLAUDE.md 규약):
--   ① superuser 로 돌면 search_path 가 안 걸려 표가 public 에 생긴다.
--   ② superuser 가 만든 표는 소유자가 postgres 라 앱 롤이 접근하지 못한다 → 파일 끝에서 넘긴다.
SET search_path = subtitle;

CREATE TABLE IF NOT EXISTS channels (
  id              VARCHAR(20) PRIMARY KEY,
  name            TEXT        NOT NULL,
  code            TEXT,
  stream_url      TEXT        NOT NULL DEFAULT '',
  committee       TEXT,
  page_url        TEXT,
  status_provider TEXT        NOT NULL DEFAULT 'ggc',
  provider_config JSONB       NOT NULL DEFAULT '{}'::jsonb,
  manual_status   INT,
  manual_until    TIMESTAMPTZ,
  sort_order      INT         NOT NULL DEFAULT 1000,
  is_active       BOOLEAN     NOT NULL DEFAULT true,
  is_test         BOOLEAN     NOT NULL DEFAULT false,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- id 폭·모양을 여기서 막는다. meetings.channel_id 가 VARCHAR(20)(015)이라 넘치면
  -- 회의 생성이 실패하고, 그 예외 경로가 channel_id 를 meeting_id 로 반환해
  -- 자막이 존재하지 않는 회의에 저장된다(화면에 영원히 안 붙는다).
  -- 슬래시·공백을 허용하면 /api/channels/{id}/hls/playlist.m3u8 경로와 WS 룸 키도 깨진다.
  CONSTRAINT ck_channels_id_shape CHECK (id ~ '^[A-Za-z0-9_-]{1,20}$'),
  CONSTRAINT ck_channels_provider CHECK (status_provider IN ('ggc','probe','manual','schedule','none'))
);

-- code 는 비어 있을 수 있다(기관 중립 제공자). 값이 있을 때만 유일하다.
CREATE UNIQUE INDEX IF NOT EXISTS uq_channels_code
  ON channels(code) WHERE code IS NOT NULL AND code <> '';
CREATE INDEX IF NOT EXISTS idx_channels_active_sort ON channels(is_active, sort_order);

-- ── 시드: 지금 코드 상수와 같은 19행 ────────────────────────────────────────
-- ★committee 를 채우지 않는다. get_committee_for_channel() 이 `committee or name` 이라
--   지금 실질값은 name 이고, 여기에 다른 값을 넣으면 meetings.committee 가 바뀌어
--   roster_loader 가 committee_rosters.json 키와 못 맞춘다 → 명부가 비고
--   화자가 전부 "위원장" 으로 굳는다.
INSERT INTO channels (id, name, code, stream_url, sort_order, is_test, status_provider) VALUES
  ('ch14', '본회의', 'A011', 'https://stream01.cdn.gov-ntruss.com/live/ch14/playlist.m3u8', 10, false, 'ggc'),
  ('ch1', '의회운영위원회', 'C001', 'https://stream01.cdn.gov-ntruss.com/live/ch1/playlist.m3u8', 20, false, 'ggc'),
  ('ch3', '기획재정위원회', 'C105', 'https://stream02.cdn.gov-ntruss.com/live/ch3/playlist.m3u8', 30, false, 'ggc'),
  ('ch6', '경제노동위원회', 'C205', 'https://stream02.cdn.gov-ntruss.com/live/ch6/playlist.m3u8', 40, false, 'ggc'),
  ('ch7', '안전행정위원회', 'C301', 'https://stream02.cdn.gov-ntruss.com/live/ch7/playlist.m3u8', 50, false, 'ggc'),
  ('ch8', '문화체육관광위원회', 'C501', 'https://stream01.cdn.gov-ntruss.com/live/ch8/playlist.m3u8', 60, false, 'ggc'),
  ('ch15', '농정해양위원회', 'C601', 'https://stream01.cdn.gov-ntruss.com/live/ch15/playlist.m3u8', 70, false, 'ggc'),
  ('ch2', '보건복지위원회', 'C701', 'https://stream02.cdn.gov-ntruss.com/live/ch2/playlist.m3u8', 80, false, 'ggc'),
  ('ch12', '건설교통위원회', 'C807', 'https://stream01.cdn.gov-ntruss.com/live/ch12/playlist.m3u8', 90, false, 'ggc'),
  ('ch13', '도시환경위원회', 'C901', 'https://stream01.cdn.gov-ntruss.com/live/ch13/playlist.m3u8', 100, false, 'ggc'),
  ('ch16', '미래과학협력위원회', 'C9043', 'https://stream01.cdn.gov-ntruss.com/live/ch16/playlist.m3u8', 110, false, 'ggc'),
  ('ch11', '여성가족평생교육위원회', 'C905', 'https://stream01.cdn.gov-ntruss.com/live/ch11/playlist.m3u8', 120, false, 'ggc'),
  ('ch4', '교육기획위원회', 'C908', 'https://stream02.cdn.gov-ntruss.com/live/ch4/playlist.m3u8', 130, false, 'ggc'),
  ('ch5', '교육행정위원회', 'C909', 'https://stream01.cdn.gov-ntruss.com/live/ch5/playlist.m3u8', 140, false, 'ggc'),
  ('ch60', '경기도청 예산결산특별위원회', 'E020', 'https://stream01.cdn.gov-ntruss.com/live/ch60/playlist.m3u8', 150, false, 'ggc'),
  ('ch61', '경기도교육청 예산결산특별위원회', 'E030', 'https://stream01.cdn.gov-ntruss.com/live/ch61/playlist.m3u8', 160, false, 'ggc'),
  ('ch10', '행정사무조사', 'E040', 'https://stream01.cdn.gov-ntruss.com/live/ch10/playlist.m3u8', 170, false, 'ggc'),
  ('ch90', '도의회 북부분원', 'E050', 'https://stream02.cdn.gov-ntruss.com/live2/ch90/playlist.m3u8', 180, false, 'ggc'),
  ('chT1', '외부 스트림 테스트', 'TEST1', '', 190, true, 'manual')
ON CONFLICT (id) DO NOTHING;

COMMENT ON TABLE channels IS
  '생중계 채널 — 위원회명·HLS 주소·방송상태 판정 방식. 비면 자막이 시작되지 않는다';
COMMENT ON COLUMN channels.code IS
  '기관 생중계 API 의 채널 코드(경기도의회 adCode). 기관 중립 제공자(probe)에서는 NULL';
COMMENT ON COLUMN channels.committee IS
  'NULL 이면 name 을 위원회명으로 쓴다. 명부 매칭이 이 값에 걸려 있으니 함부로 채우지 말 것';
COMMENT ON COLUMN channels.status_provider IS
  '방송중 판정 방식: ggc(기관 API) | probe(m3u8 직접 탐침) | manual(관리자 토글) | schedule | none';
COMMENT ON COLUMN channels.manual_until IS
  '수동 방송중의 자동 만료 시각. 끄는 것을 잊으면 STT 가 밤새 돌아 비용이 샌다';
COMMENT ON COLUMN channels.is_test IS
  '외부 스트림 시험 채널(chT1). 목록·통계에서 가려도 되는 채널';

-- ── 소유권 이전 — PostgREST 가 ggc_subtitle 로 접속한다 ─────────────────────
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ggc_subtitle') THEN
    EXECUTE 'ALTER TABLE subtitle.channels OWNER TO ggc_subtitle';
  END IF;
END $$;
