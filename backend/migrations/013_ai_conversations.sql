-- Phase 11B: AI 어시스턴트 대화 이력 테이블
-- @TASK P11B - AI Assistant conversations

CREATE TABLE IF NOT EXISTS ai_conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL,
  user_id UUID REFERENCES users(id),
  role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
  content TEXT NOT NULL,
  sources JSONB,
  meeting_context_id UUID REFERENCES meetings(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_conv_session ON ai_conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_ai_conv_user ON ai_conversations(user_id);
