-- 034: 긴 회의 요약(맵리듀스)과 요약 신뢰도 표시 (2026-09-14)
--
-- 배경: 요약은 자막 앞 12,000자(≈초반 20~30분)만 보고 만들어졌고 그 사실이 어디에도 남지 않았다.
-- 이제 긴 회의는 안건 구간·화자 경계로 청크를 나눠 청크 요약 → 병합 요약을 만들고,
--   segments      청크별 중간 결과(구간 시각·요약·결정·조치·수치·발언자) — AI 대화의 컨텍스트가 재사용한다
--   speakers      발언자별 요지(청크 결과 병합)
--   source_chars  요약에 실제로 들어간 자막 글자 수
--   complete      true = 전 구간을 본 요약 · false = 앞부분만 본 옛 요약(화면에 "부분 요약" 배지, 다시 만들 수 있다)
--   generated_from ai | live | unknown — live 자막으로 만든 요약은 AI 자막이 완성되면 다시 만들 수 있다
-- 캐시는 그대로 회의당 1행(UNIQUE meeting_id). 생성 도중 일부 청크가 실패하면 저장하지 않는다.
--
-- 적용 순서: ★배포보다 먼저★ 적용하고, 적용 뒤 반드시
--   kubectl -n ggc-poc rollout restart deploy/ggc-live-transcribe-pgrst
-- (PostgREST 스키마 캐시 — 028 교훈. 컬럼 없이 새 코드가 뜨면 upsert 가 PGRST204 로 실패해 요약 저장이 막힌다)
SET search_path = subtitle;

ALTER TABLE meeting_summaries ADD COLUMN IF NOT EXISTS segments JSONB;
ALTER TABLE meeting_summaries ADD COLUMN IF NOT EXISTS speakers JSONB;
ALTER TABLE meeting_summaries ADD COLUMN IF NOT EXISTS source_chars INTEGER;
ALTER TABLE meeting_summaries ADD COLUMN IF NOT EXISTS complete BOOLEAN;
ALTER TABLE meeting_summaries ADD COLUMN IF NOT EXISTS generated_from TEXT;

-- 기존 행 = 앞 12,000자 기준(부분 요약). 원천 자막 종류는 알 수 없다.
UPDATE meeting_summaries
   SET complete = false, generated_from = COALESCE(generated_from, 'unknown')
 WHERE complete IS NULL;

COMMENT ON COLUMN meeting_summaries.complete IS 'true = 자막 전 구간을 본 요약. false = 앞부분만 본 옛 요약(다시 만들 수 있다)';
COMMENT ON COLUMN meeting_summaries.segments IS '청크별 중간 요약 [{idx, order_num, title, start_time, end_time, summary, decisions, action_items, numbers, speakers}]';
