-- 018: councilor_voiceprints — 의원 목소리 샘플 (실명 화자 식별용)
--
-- gpt-4o-transcribe-diarize의 known_speaker_references에 넘길 2~10초 음성 샘플을 저장한다.
-- Railway 파일시스템은 휘발성이므로 작은 샘플(8초 16kHz wav ≈ 250KB)을 DB에 base64로 보관한다.
-- 회의 위원회별로 ≤4명을 선택해 diarize에 전달 → segments[].speaker가 "A/B" 대신 실제 의원명이 됨.

CREATE TABLE IF NOT EXISTS councilor_voiceprints (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  councilor_id UUID NOT NULL REFERENCES councilors(id) ON DELETE CASCADE,
  councilor_name VARCHAR(100) NOT NULL,         -- diarize known_speaker_names로 사용할 표기 이름
  committee VARCHAR(200),                        -- 회의별 후보 선택용 (의원의 첫 위원회)
  sample_format VARCHAR(40) NOT NULL DEFAULT 'audio/wav',
  sample_b64 TEXT NOT NULL,                       -- 16kHz mono wav의 base64 (data: 프리픽스 없음)
  duration_ms INT,                                -- 샘플 길이 (2000~10000 권장)
  source VARCHAR(20) DEFAULT 'upload',            -- upload | meeting_clip
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(councilor_id)                            -- 의원당 1개 (재등록 시 upsert)
);

CREATE INDEX IF NOT EXISTS idx_voiceprints_committee
  ON councilor_voiceprints(committee);

COMMENT ON TABLE councilor_voiceprints IS
  '의원 목소리 샘플(base64 wav). diarize known_speaker_references로 실명 화자 식별. 의원당 1개.';
