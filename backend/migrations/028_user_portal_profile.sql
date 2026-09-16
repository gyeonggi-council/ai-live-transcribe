-- 028: users 에 경기도의정포털 프로필 보관 (QR 자동 등록 대응)
--
-- QR 로그인 시 상류가 주는 프로필을 저장한다. 필드 정본은
-- https://ggc-mobile-login-git.vercel.app/openapi.json 의
-- GET /api/v1/auth/qr/{sessionId} authenticated 응답이다.
--
-- ★저장하지 않는 것 (2026-08-22 사용자 결정):
--     wallet_id · holder_did · wallet_created_at — DID/전자지갑 식별자.
--       자막 서비스는 DID 로 할 일이 없고(인증은 상류가 끝낸다),
--       가지고 있지 않으면 유출될 일도 없다.
--     access_token · refresh_token — QR 계약 불변식 5. 받는 즉시 폐기한다.
--   컬럼을 만들지 않는 것이 그 규칙의 집행 장치다. 추가하지 말 것.

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS portal_role           VARCHAR(50),
  ADD COLUMN IF NOT EXISTS dept_name             VARCHAR(100),
  ADD COLUMN IF NOT EXISTS group_name            VARCHAR(100),
  ADD COLUMN IF NOT EXISTS job_position          VARCHAR(50),
  ADD COLUMN IF NOT EXISTS portal_last_login     DATE,
  ADD COLUMN IF NOT EXISTS portal_app_last_login DATE,
  ADD COLUMN IF NOT EXISTS profile_synced_at     TIMESTAMPTZ;

-- QR 로 자동 생성되는 계정은 비밀번호가 없다.
ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;

COMMENT ON COLUMN users.portal_role IS
  '의정포털 권한 원문 (예: ROLE_COUNCILOR). users.role(이 서비스 권한)과 다른 값이다';
COMMENT ON COLUMN users.dept_name IS '의정포털 deptnm — 부서명';
COMMENT ON COLUMN users.group_name IS '의정포털 group_name — 부서 그룹';
COMMENT ON COLUMN users.job_position IS '의정포털 jobpositionname — 직급';
COMMENT ON COLUMN users.portal_last_login IS
  '의정포털 웹 마지막 로그인. users.last_login_at(이 서비스 로그인)과 다른 값이다';
COMMENT ON COLUMN users.portal_app_last_login IS '의정포털 앱 마지막 로그인';
COMMENT ON COLUMN users.profile_synced_at IS 'QR 로그인으로 프로필을 마지막에 갱신한 시각';
