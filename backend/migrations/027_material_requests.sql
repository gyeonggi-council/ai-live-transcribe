-- 027: 요구자료(의원 자료 제출 요구) 감지 목록
-- 배경: 실시간 자막 모니터링 직원과 의회사무처가 회의 중 의원의 자료 제출 요구를
--       놓치지 않고 목록화할 수 있도록, 자막에서 자동 감지된 요구자료를 저장한다.
--       사무처는 이 목록을 참고해 별도 시스템(KMS)에 공식 등록한다.
CREATE TABLE IF NOT EXISTS material_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  meeting_id UUID NOT NULL,
  subtitle_id UUID,                          -- 근거 자막 (있으면)
  start_time DOUBLE PRECISION,               -- 발언 시각(초) — 영상 점프용
  speaker TEXT,                              -- 자막 화자 라벨 (화자 N / 실명)
  councilor_name TEXT,                       -- 요구 의원 실명 (추정 — 직원이 수정 가능)
  summary TEXT NOT NULL,                     -- 요청 자료 제목 (예: '지방채 발행 검토 자료')
  request_text TEXT,                         -- 핵심 요구 발언 원문 발췌
  department TEXT,                           -- 요구 대상 부서/기관 (언급 시)
  confidence TEXT NOT NULL DEFAULT 'medium', -- high | medium | low
  status TEXT NOT NULL DEFAULT 'detected',   -- detected | confirmed | dismissed | registered
  source TEXT NOT NULL DEFAULT 'live',       -- live | vod_scan | manual
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_material_requests_meeting
  ON material_requests(meeting_id, start_time);

COMMENT ON TABLE material_requests IS
  '자막에서 감지된 의원 요구자료 — 사무처 KMS 공식 등록의 보조 목록 (라이브 자동감지 + VOD 스캔 + 수동)';
