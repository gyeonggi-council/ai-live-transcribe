-- 010: 의원 테이블 추가 필드
-- 영문명, 한자명, 상세 선거구, 이메일, 팩스 등 보강

ALTER TABLE councilors ADD COLUMN IF NOT EXISTS name_english TEXT;
ALTER TABLE councilors ADD COLUMN IF NOT EXISTS name_chinese TEXT;
ALTER TABLE councilors ADD COLUMN IF NOT EXISTS district_detail TEXT;
ALTER TABLE councilors ADD COLUMN IF NOT EXISTS email TEXT;
ALTER TABLE councilors ADD COLUMN IF NOT EXISTS fax TEXT;
