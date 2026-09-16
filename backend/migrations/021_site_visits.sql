-- 021_site_visits.sql
-- 접속자 수 집계 (오늘 / 누적)
--
-- 방문 1건당 1행(insert-only). 프론트엔드가 localStorage로 브라우저당 하루 1회만
-- 기록하므로 1행 = 방문자 1명. 개인정보(IP 등)는 저장하지 않는다.
--   오늘 접속자 = visited_on 이 오늘인 행 수
--   누적 접속자 = 전체 행 수
--
-- ★Supabase 수동 적용 필요.

CREATE TABLE IF NOT EXISTS site_visits (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    visited_on  DATE NOT NULL DEFAULT CURRENT_DATE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 오늘 집계(visited_on = today) 가속용 인덱스
CREATE INDEX IF NOT EXISTS idx_site_visits_visited_on ON site_visits (visited_on);
