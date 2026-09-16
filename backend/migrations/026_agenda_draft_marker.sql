-- 026: 안건 초안 생성 1회 마커
-- 배경: 안건 초안 생성(POST /agenda-draft)의 1회 가드가 "meeting_agendas 존재 여부"만 봤는데,
--       추출 결과가 0개인 시도는 흔적이 없어 새로고침 시 버튼이 재활성화되고 서버 409도 뚫렸다.
--       결과(안건 행)와 무관하게 "시도 발생" 자체를 meetings에 기록한다.
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS agenda_draft_at TIMESTAMPTZ;

COMMENT ON COLUMN meetings.agenda_draft_at IS
  '안건 초안 생성(agenda-draft) 최초 실행 시각 — 회의당 1회 정책 마커 (0개 추출이어도 기록)';
