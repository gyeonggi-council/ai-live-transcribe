-- Phase 11A: Users & Authentication
-- @TASK P11A-R1-T1 - 사용자/세션 테이블 생성
-- @SPEC docs/planning/02-trd.md#인증-API

-- users 테이블
CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username VARCHAR(50) UNIQUE NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  display_name VARCHAR(100) NOT NULL,
  role VARCHAR(20) NOT NULL DEFAULT 'staff'
    CHECK (role IN ('anonymous','staff','committee_staff','meeting_manager','stenographer','admin')),
  assigned_committee VARCHAR(100),
  is_active BOOLEAN NOT NULL DEFAULT true,
  last_login_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- user_sessions 테이블
CREATE TABLE IF NOT EXISTS user_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash VARCHAR(255) NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_expires_at ON user_sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

-- 초기 admin 계정은 Python seed 스크립트로 처리
-- (비밀번호 해싱이 필요하므로 SQL에서 직접 삽입하지 않음)
