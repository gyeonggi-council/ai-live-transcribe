-- 038: 의원 얼굴 인식 + 프로필(약력)
--
-- ⚠ 번호 주의 — 이 파일은 **037 로 운영에 먼저 적용됐다**(2026-09-16 14:05경, poc-db ggcpoc.subtitle).
--   같은 날 다른 작업(영상 시각 배지)이 037_meeting_clock_anchors.sql 을 먼저 main 에 올려 번호가 겹쳤고,
--   나중에 합치는 쪽인 이 파일을 038 로 옮겼다. **DB 에는 이미 들어가 있으니 다시 돌리지 않아도 된다**
--   (다시 돌려도 안전하다 — 전부 IF NOT EXISTS / ADD COLUMN IF NOT EXISTS 다). — 영상 위 [의원 찾기] 와 의원 상세 화면이 쓴다.
--
-- ⚠ 배포보다 **먼저** 적용하고 `kubectl -n ggc-poc rollout restart deploy/ggc-live-transcribe-pgrst`.
--   PostgREST 는 스키마 캐시를 기동 시 한 번만 읽어서, 재시작 없이는 새 테이블이 PGRST205 로 안 보인다.
--
-- 임베딩을 vector(pgvector) 가 아니라 JSONB float 배열로 두는 이유:
--   후보가 위원회 한 곳(13~20명)이거나 많아야 현역 166명이라 내적 한 번이 numpy 로 0.1ms 다.
--   ANN 인덱스가 필요 없는 규모인데 vector 타입을 쓰면 PostgREST·supabase-py 왕복마다
--   문자열 파싱이 끼어 오히려 번거롭다(자막 조각 임베딩 036 은 수십만 행이라 vector 가 맞다).

SET search_path = subtitle, public;   -- 앱 테이블은 subtitle 스키마다. 빼면 public 에 엉뚱한 표가 생긴다

-- ── 1. councilors 프로필 확장 ────────────────────────────────────────────────
ALTER TABLE councilors ADD COLUMN IF NOT EXISTS member_no VARCHAR(20);        -- ggc.go.kr 의원홈페이지 번호
ALTER TABLE councilors ADD COLUMN IF NOT EXISTS homepage_url TEXT;            -- /site/lwmkr/blog/{member_no}/12
ALTER TABLE councilors ADD COLUMN IF NOT EXISTS career JSONB;                 -- 약력 ["(現) …", "(前) …"]
ALTER TABLE councilors ADD COLUMN IF NOT EXISTS profile_synced_at TIMESTAMPTZ;

COMMENT ON COLUMN councilors.member_no IS 'ggc.go.kr 의원홈페이지 번호 (약력 출처)';
COMMENT ON COLUMN councilors.career   IS '약력·경력 문자열 배열 (ggc.go.kr 의원홈페이지 스크레이프)';

-- ── 2. 얼굴 임베딩 ───────────────────────────────────────────────────────────
-- slot 0 = 공식 증명사진(portrait). slot 1.. = 영상에서 자동 등록된 현장 템플릿(video).
-- 증명사진 하나만으로 맞추면 조명·각도·안경·나이 차이를 다 떠안는다. 현장 템플릿이 쌓이면
-- 같은 카메라·같은 조명에서 찍힌 기준이 생겨 정확도가 올라간다(다중 템플릿 최대값 매칭).
CREATE TABLE IF NOT EXISTS councilor_faces (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  councilor_id UUID NOT NULL REFERENCES councilors(id) ON DELETE CASCADE,
  councilor_name VARCHAR(100) NOT NULL,
  model VARCHAR(40) NOT NULL,                     -- 임베딩 모델 식별자 (w600k_r50)
  slot SMALLINT NOT NULL DEFAULT 0,               -- 0=증명사진, 1.. = 현장 템플릿
  source VARCHAR(20) NOT NULL DEFAULT 'portrait', -- portrait | video | manual
  embedding JSONB NOT NULL,                       -- 512차원 단위벡터
  det_score REAL,                                 -- 검출 점수
  face_px INT,                                    -- 얼굴 가로 픽셀 (품질 지표)
  match_score REAL,                               -- 자동 등록 당시 매칭 점수
  channel_id VARCHAR(20),
  captured_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (councilor_id, model, slot)
);

CREATE INDEX IF NOT EXISTS idx_councilor_faces_model ON councilor_faces(model);
CREATE INDEX IF NOT EXISTS idx_councilor_faces_name  ON councilor_faces(councilor_name);

COMMENT ON TABLE councilor_faces IS
  '의원 얼굴 임베딩(ArcFace 512차원). slot 0=공식 증명사진, 1.. = 영상 자동 등록 템플릿.';

ALTER TABLE councilor_faces DISABLE ROW LEVEL SECURITY;

-- ── 3. 소유자 ────────────────────────────────────────────────────────────────
-- 이 파일을 `psql -U postgres` 로 돌리면 새 표의 소유자가 postgres 가 되고, 앱 롤
-- ggc_subtitle 은 **permission denied for table (42501)** 로 한 줄도 못 읽는다
-- (2026-09-16 실제 발생 — 배포 뒤 명부가 0명이었다). 기존 앱 표는 전부 ggc_subtitle 소유다.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ggc_subtitle') THEN
    EXECUTE 'ALTER TABLE subtitle.councilor_faces OWNER TO ggc_subtitle';
    EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON subtitle.councilor_faces TO ggc_subtitle';
  END IF;
END $$;
