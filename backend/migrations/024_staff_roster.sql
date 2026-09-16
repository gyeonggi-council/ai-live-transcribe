-- 024: staff_roster — 집행부 공무원/전문위원 명부
--
-- 속기록(KMS 임시회의록)의 출석 명단 섹션(출석공무원/출석전문위원)을 파싱해
-- 위원회별 실명 명부를 축적한다. 이름 교정·글로서리 바이어스·화자 귀속의 공통 원천.
--   name/title:  실명과 직책 원문 (예: 배성호 / 국장)
--   department:  부서 (예: 건설국, 전문위원은 NULL)
--   full_title:  결합 직함 (예: 건설국장 — 부서+직책, 직책에 부서가 담기면 그대로)
--   같은 사람이 여러 속기록에 재등장하면 UNIQUE 충돌 → last_seen_date 갱신(upsert).
--
-- ★Supabase 수동 적용 필요.

CREATE TABLE IF NOT EXISTS staff_roster (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    committee      TEXT NOT NULL,
    name           TEXT NOT NULL,
    title          TEXT NOT NULL,
    department     TEXT,
    full_title     TEXT NOT NULL,
    source_mntsid  TEXT,
    last_seen_date DATE,
    created_at     TIMESTAMPTZ DEFAULT now(),
    UNIQUE (committee, name, full_title)
);

-- 위원회별 명부 조회 가속용 인덱스
CREATE INDEX IF NOT EXISTS idx_staff_roster_committee ON staff_roster (committee);
