-- 015: 생중계 회의 자동 생성을 위한 channel_id 컬럼 추가
-- 방송 시작 시 자동으로 회의 레코드를 생성하고 채널과 연결합니다.

ALTER TABLE meetings ADD COLUMN IF NOT EXISTS channel_id VARCHAR(20);

-- 채널별 live 회의를 빠르게 조회하기 위한 인덱스
CREATE INDEX IF NOT EXISTS idx_meetings_channel_status ON meetings(channel_id, status);
