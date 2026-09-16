-- 023: subtitles.kind — 자막 종류 (실시간 vs AI 자막 비교 기능)
--
-- 'live' = 실시간 방송 중 생성된 자막 (gpt-4o-transcribe, 정확하지만 화자구분 없음)
-- 'ai'   = VOD AI 자막 생성 (gpt-4o-transcribe-diarize, 화자구분 있음)
-- 두 종류를 함께 보존해 회의록에서 토글 비교할 수 있게 한다.
-- 기존 자막은 'ai'로 간주(하위 호환 — 대부분 AI 재전사된 상태).

ALTER TABLE subtitles ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'ai';

CREATE INDEX IF NOT EXISTS idx_subtitles_meeting_kind
    ON subtitles (meeting_id, kind, start_time);

COMMENT ON COLUMN subtitles.kind IS '자막 종류: live(실시간) / ai(VOD 화자구분 재전사)';
