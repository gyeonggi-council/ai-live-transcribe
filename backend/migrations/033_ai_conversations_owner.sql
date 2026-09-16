-- 033: AI 대화 이력의 소유자 키 — "본인 것만 보인다"(2026-09-14 담당자 결정)
--
-- 배경: 지금까지 익명 대화까지 전부 저장하고 GET /api/ai/conversations/shared 가 로그인 없이 최근 60건을 공개했다.
-- 이제 세션은 소유자(로그인 user:<uuid> · PIN 관리자 admin:pin · 비로그인 손님 guest:<X-Guest-Id>) 에 고정되고
-- 남의 세션은 조회·이어쓰기 모두 404 다. 소유자를 알 수 없는 요청(손님 표식 없음)은 저장하지 않는다.
--
-- 백필은 user_id 가 있는 행만 행 단위로 한다. 세션 첫 행의 소유자를 세션 전체에 복사하지 않는다 —
-- 옛 shared 화면이 남의 세션을 이어 쓸 수 있어 한 session_id 에 여러 사람·익명 행이 섞였을 수 있다.
-- 익명 행(user_id NULL)은 보존하되 개인 이력에서 빠진다(복원 근거 없음).
--
-- 적용 순서: ★배포보다 먼저★ 적용하고, 적용 뒤 반드시
--   kubectl -n ggc-poc rollout restart deploy/ggc-live-transcribe-pgrst
-- (PostgREST 스키마 캐시 — 028 교훈. 컬럼 없이 새 코드가 뜨면 AI 대화 저장·이력이 전부 실패한다)
SET search_path = subtitle;

ALTER TABLE ai_conversations ADD COLUMN IF NOT EXISTS owner_key TEXT;

UPDATE ai_conversations
   SET owner_key = 'user:' || user_id::text
 WHERE user_id IS NOT NULL AND owner_key IS NULL;

CREATE INDEX IF NOT EXISTS idx_ai_conv_owner_created ON ai_conversations(owner_key, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_conv_meeting ON ai_conversations(meeting_context_id);

COMMENT ON COLUMN ai_conversations.owner_key IS
  '소유자 키: user:<users.id> | admin:pin | guest:<X-Guest-Id>. NULL 이면 소유자 미상(옛 익명 행) — 개인 이력에서 제외';
