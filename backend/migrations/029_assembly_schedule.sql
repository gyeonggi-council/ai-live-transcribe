-- 029: 의사일정 자동 연동 (경기도의회 의정캘린더 수집)
--
-- 배경: 라이브 회의가 "본회의 생중계" 라는 제목으로만 생겨 어느 회기에도 속하지 못했고
--       (회의 목록은 제목의 '제N회'로 회기를 묶는다), 앞으로 열릴 회의를 미리 알 방법이
--       없었다. 의회 홈페이지 의정캘린더를 주기적으로 수집해 두 문제를 함께 없앤다.
--
-- 출처: https://www.ggc.go.kr/site/main/schedule/list/{YYYY-MM-DD}/ALL
--       표의 <tr class="A011 table_tr"> 에서 class 첫 토큰이 곧 위원회 코드이며
--       app/core/channels.py 의 CHANNELS[].code 와 그대로 맞는다(이름 매칭 불필요).

-- ★이 두 줄이 없으면 조용히 틀린다 (ggc-services/CLAUDE.md 규약):
--   ① provision 은 postgres(superuser)로 도는데 `ALTER ROLE ... SET search_path` 는 그 롤로
--      접속할 때만 걸린다 → search_path 를 여기서 직접 잡지 않으면 표가 public 에 생긴다.
--   ② superuser 가 만든 표는 소유자가 postgres 라 앱 롤(ggc_subtitle)이 접근하지 못한다
--      → 파일 끝에서 소유권을 넘긴다. 기존 표(meetings·subtitles·users)는 전부 ggc_subtitle 소유다(실측).
SET search_path = subtitle;

-- ── 1) 같은 날 같은 채널의 1차/2차를 구분하기 위한 차수 ──────────────────────
--   지금까지 라이브 회의 재사용 키가 (channel_id, meeting_date) 뿐이라, 1차가 끝나고
--   2차가 열리면 2차 자막이 1차 회의에 합쳐졌다. 차수를 저장해 키에 포함한다.
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS session_order INT;

COMMENT ON COLUMN meetings.session_order IS
  '차수 (제N차) — 생중계 일정 API 의 adCha. 같은 날 같은 채널의 회의를 가르는 키의 일부';

-- ── 2) 수집한 의사일정 ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS assembly_schedule (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  schedule_date  DATE NOT NULL,
  committee_code TEXT NOT NULL,        -- A011(본회의) / C105(기획재정위) … = CHANNELS[].code
  committee_name TEXT NOT NULL,        -- 표의 '구분' 칸 그대로
  start_time     TEXT,                 -- '11:00' (표기가 흔들려 텍스트로 둔다)
  session_no     INT,                  -- 제393회 — 안건 문구 또는 생중계 API(adTh)
  session_order  INT,                  -- 제1차 — 생중계 API(adCha)
  session_kind   TEXT,                 -- 임시회 / 정례회
  agenda_items   JSONB NOT NULL DEFAULT '[]'::jsonb,  -- ["제393회 임시회 회기 결정", …]
  agenda_hash    TEXT NOT NULL DEFAULT '',            -- 안건 변경 감지용 (내용 해시)
  is_cancelled   BOOLEAN NOT NULL DEFAULT false,      -- 달력에서 사라짐 (행은 지우지 않는다)
  first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  changed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 내용이 '실제로 바뀐' 시각
  synced_at      TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 마지막으로 '확인한' 시각
  CONSTRAINT uq_assembly_schedule_date_code UNIQUE (schedule_date, committee_code)
);

CREATE INDEX IF NOT EXISTS idx_assembly_schedule_date
  ON assembly_schedule(schedule_date);

COMMENT ON TABLE assembly_schedule IS
  '경기도의회 의정캘린더에서 수집한 의사일정 — 라이브 회의 제목·회기 부여와 예정 일정 표시의 근거';
COMMENT ON COLUMN assembly_schedule.agenda_hash IS
  '안건 변경 감지용 해시. 같으면 synced_at 만 갱신하고 changed_at 은 두어, "언제 확인했나"와 "언제 바뀌었나"를 가른다';
COMMENT ON COLUMN assembly_schedule.is_cancelled IS
  '달력에서 사라진 일정. 삭제하지 않는 이유 — 사라졌다는 사실 자체가 정보다(회의 취소)';

-- ── 3) 소유권 이전 — PostgREST 가 ggc_subtitle 로 접속한다 ──────────────────
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ggc_subtitle') THEN
    EXECUTE 'ALTER TABLE subtitle.assembly_schedule OWNER TO ggc_subtitle';
  END IF;
END $$;
