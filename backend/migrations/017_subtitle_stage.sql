-- 017: meetings.subtitle_stage 컬럼 추가
-- 자막 워크플로우 5단계:
--   none      — 자막 없음
--   draft     — 라이브 STT 초안
--   ai        — MP3 업로드 + Deepgram AI 재생성 (정확한 초벌)
--   reviewing — 속기사 교정 진행 중
--   final     — 속기사 교정 완료
--
-- 자막 개수로 파생 불가 (reviewing/final은 속기사 의도 반영)

ALTER TABLE meetings
  ADD COLUMN IF NOT EXISTS subtitle_stage VARCHAR(16) NOT NULL DEFAULT 'none'
  CHECK (subtitle_stage IN ('none','draft','ai','reviewing','final'));

-- 백필: 자막이 1건이라도 있는 기존 회의는 draft로 간주
UPDATE meetings m
SET subtitle_stage = 'draft'
FROM (
  SELECT meeting_id, COUNT(*) AS c
  FROM subtitles
  GROUP BY meeting_id
) s
WHERE m.id = s.meeting_id
  AND s.c > 0
  AND m.subtitle_stage = 'none';

CREATE INDEX IF NOT EXISTS idx_meetings_subtitle_stage
  ON meetings(subtitle_stage);

COMMENT ON COLUMN meetings.subtitle_stage IS
  '자막 워크플로우 단계: none → draft(라이브) → ai(Deepgram) → reviewing(속기사) → final';
