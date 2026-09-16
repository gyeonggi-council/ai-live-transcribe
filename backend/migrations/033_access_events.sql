-- 033: 접속 통계 — 접속처(이름)·화면·시청 시간 기록
--
-- 배경(2026-09-16 담당자 요청): 사이드바의 「오늘 N · 누적 N」을 눌러 접속 통계를 보게 한다.
-- 기존 site_visits(021)는 날짜 한 칸뿐이라 "누가·언제·무엇을" 을 답할 수 없었다. site_visits 는 그대로 두고
-- (누적 이력 보존·사이드바 숫자) 상세는 이 표에 새로 쌓는다.
--
-- ★개인정보 — 담당자 결정: IP 주소를 저장하지 않는다.★
--   서버가 요청을 받는 순간 core/council_network.site_label() 로 접속처 **이름**(무선인터넷·의회사무처(직원)…·외부)
--   으로 바꾸고 이름만 넣는다. User-Agent 원문·사용자 ID·이름도 넣지 않는다(기기 구분과 역할만).
--   visitor_key 는 브라우저 localStorage 에 **그날 하루만** 사는 난수라 날짜를 넘겨 사람을 따라가지 못한다.
--
-- 032 는 미머지 브랜치(feat/monitor-desk)가 선점했으므로 033 이다.
--
-- 적용 순서: ★배포보다 먼저★ 적용하고, 적용 뒤 반드시
--   kubectl -n ggc-poc rollout restart deploy/ggc-live-transcribe-pgrst
-- (PostgREST 가 스키마를 캐시한다 — 028 교훈. 표·뷰 없이 새 코드가 뜨면 통계만 비고 본 기능은 산다)

SET search_path = subtitle;

CREATE TABLE IF NOT EXISTS access_events (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    occurred_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    visit_date   DATE        NOT NULL,                  -- KST 기준 날짜(앱이 넣는다)
    hour_kst     SMALLINT    NOT NULL DEFAULT 0,        -- 0~23, 시간대 집계용
    weekday_kst  SMALLINT    NOT NULL DEFAULT 0,        -- 0=월 … 6=일, 요일 집계용
    site_label   TEXT        NOT NULL DEFAULT '외부',    -- 접속처 이름(IP 아님)
    kind         TEXT        NOT NULL,                  -- page|watch_live|watch_vod|search|ai|download|record|login_prompt
    meeting_id   UUID,
    device       TEXT,                                  -- pc|mobile|tablet
    role         TEXT,                                  -- anonymous|staff|…|admin (개인 식별자 아님)
    seconds      INTEGER     NOT NULL DEFAULT 0,        -- watch 1건 = 5분(300)
    visitor_key  TEXT,                                  -- 그날만 유효한 난수(중복 제거·방문자 수 세기)
    detail       JSONB
);

CREATE INDEX IF NOT EXISTS idx_access_events_date ON access_events (visit_date);
CREATE INDEX IF NOT EXISTS idx_access_events_date_site ON access_events (visit_date, site_label);
CREATE INDEX IF NOT EXISTS idx_access_events_occurred ON access_events (occurred_at);

COMMENT ON TABLE access_events IS
  '접속 통계 원본(2026-09-16). IP·User-Agent 원문·사용자 식별자를 저장하지 않는다 — 접속처는 이름으로만.';
COMMENT ON COLUMN access_events.site_label IS
  'IP 를 ConfigMap COUNCIL_SITE_LABELS 로 바꾼 접속처 이름. 못 맞추면 외부. 앱 로그인 안내를 본 것은 kind=login_prompt';
COMMENT ON COLUMN access_events.visitor_key IS
  '브라우저 localStorage 의 하루짜리 난수. 날짜를 넘겨 개인을 추적하지 못한다';

-- 집계 뷰 — PostgREST 는 GROUP BY 를 못 하므로 여기서 묶는다(앱은 select+filter 만 한다)
CREATE OR REPLACE VIEW v_access_daily AS
SELECT visit_date,
       site_label,
       COUNT(DISTINCT visitor_key)                      AS visitors,
       COUNT(*) FILTER (WHERE kind = 'page')            AS page_views,
       COUNT(*) FILTER (WHERE kind = 'login_prompt')    AS login_prompts,
       COALESCE(SUM(seconds), 0)                        AS watch_seconds
FROM access_events
GROUP BY visit_date, site_label;

CREATE OR REPLACE VIEW v_access_hourly AS
SELECT visit_date,
       weekday_kst,
       hour_kst,
       COUNT(DISTINCT visitor_key)                      AS visitors,
       COALESCE(SUM(seconds), 0)                        AS watch_seconds
FROM access_events
WHERE kind <> 'login_prompt'
GROUP BY visit_date, weekday_kst, hour_kst;

CREATE OR REPLACE VIEW v_access_meeting AS
SELECT visit_date,
       meeting_id,
       site_label,
       COUNT(DISTINCT visitor_key)                      AS viewers,
       COALESCE(SUM(seconds), 0)                        AS watch_seconds
FROM access_events
WHERE meeting_id IS NOT NULL
GROUP BY visit_date, meeting_id, site_label;

CREATE OR REPLACE VIEW v_access_feature AS
SELECT visit_date,
       site_label,
       kind,
       device,
       COUNT(*)                                         AS events,
       COUNT(DISTINCT visitor_key)                      AS visitors
FROM access_events
GROUP BY visit_date, site_label, kind, device;

ALTER TABLE access_events OWNER TO ggc_subtitle;
ALTER VIEW v_access_daily   OWNER TO ggc_subtitle;
ALTER VIEW v_access_hourly  OWNER TO ggc_subtitle;
ALTER VIEW v_access_meeting OWNER TO ggc_subtitle;
ALTER VIEW v_access_feature OWNER TO ggc_subtitle;
