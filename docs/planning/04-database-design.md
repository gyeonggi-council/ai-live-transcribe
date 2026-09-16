# Database Design (데이터베이스 설계)

> 경기도의회 실시간 자막 서비스
> 최종 갱신: 2026-03-18 (Phase 9 완료 반영)

---

## 1. 개요

| 항목 | 내용 |
|------|------|
| DBMS | PostgreSQL (Supabase) |
| 접근 방식 | Supabase REST API (asyncpg 미사용) |
| 주요 기능 | Full-Text Search, Realtime, JWT Auth (Phase 11) |
| 테이블 수 | 19개 (기존 15개 + 신규 4개: users, user_sessions, ai_conversations, stenography_edit_history) |
| 마이그레이션 | 12개 (001~011) |

---

## 2. ERD (Entity-Relationship Diagram)

```
┌─────────────────┐       ┌─────────────────────┐
│    meetings     │       │      subtitles       │
├─────────────────┤       ├─────────────────────┤
│ id (PK)         │───┐   │ id (PK)             │
│ title           │   │   │ meeting_id (FK)     │──┐
│ meeting_date    │   └──▶│ start_time          │  │
│ stream_url      │       │ end_time            │  │
│ vod_url         │       │ text                │  │
│ status          │       │ speaker             │  │
│ duration_seconds│       │ confidence          │  │
│ created_at      │       │ verification_status │  │
│ updated_at      │       │ created_at          │  │
└────────┬────────┘       └──────────┬──────────┘  │
         │                           │              │
         │ 1:N                       │ 1:N          │
         │                           ▼              │
         │                ┌─────────────────────┐   │
         │                │  subtitle_history   │   │
         │                ├─────────────────────┤   │
         │                │ id (PK)             │   │
         │                │ subtitle_id (FK)    │───┘
         │                │ old_text            │
         │                │ new_text            │
         │                │ changed_by          │
         │                │ changed_at          │
         │                └─────────────────────┘
         │
         │ 1:N
         ▼
┌─────────────────┐       ┌─────────────────────┐
│ meeting_agendas │       │ meeting_summaries   │
├─────────────────┤       ├─────────────────────┤
│ id (PK)         │       │ id (PK)             │
│ meeting_id (FK) │       │ meeting_id (FK)     │
│ title           │       │ summary_text        │
│ order_num       │       │ agenda_summaries    │
│ start_time      │       │ key_decisions       │
│ end_time        │       │ action_items        │
│ created_at      │       │ model_used          │
└─────────────────┘       │ created_at          │
                          └─────────────────────┘

┌─────────────────┐       ┌─────────────────────┐
│     bills       │       │   bill_mentions     │
├─────────────────┤       ├─────────────────────┤
│ id (PK)         │───┐   │ id (PK)             │
│ bill_number     │   └──▶│ bill_id (FK)        │
│ title           │       │ meeting_id (FK)     │◀── meetings
│ proposer        │       │ subtitle_id (FK)    │◀── subtitles
│ committee       │       │ start_time          │
│ status          │       │ end_time            │
│ proposed_date   │       │ created_at          │
│ created_at      │       └─────────────────────┘
│ updated_at      │
└─────────────────┘

┌─────────────────┐       ┌─────────────────────┐
│    channels     │       │    dictionary       │
├─────────────────┤       ├─────────────────────┤
│ id (PK) ch1~90 │       │ id (PK)             │
│ name            │       │ wrong_text          │
│ code            │       │ correct_text        │
│ stream_url      │       │ category            │
└─────────────────┘       │ created_at          │
                          └─────────────────────┘
```

**관계 요약:**
- meetings 1:N subtitles (회의별 자막)
- meetings 1:N meeting_agendas (회의별 안건)
- meetings 1:1 meeting_summaries (회의별 AI 요약)
- subtitles 1:N subtitle_history (자막별 변경 이력)
- bills 1:N bill_mentions (의안별 회의 연결)
- bill_mentions N:1 meetings, subtitles (다대일)

---

## 3. 테이블 상세

### 3.1 meetings (회의)

| 컬럼명 | 타입 | 제약조건 | 설명 |
|--------|------|----------|------|
| id | UUID | PK, DEFAULT gen_random_uuid() | 고유 식별자 |
| title | VARCHAR(255) | NOT NULL | 회의 제목 |
| meeting_date | DATE | NOT NULL | 회의 날짜 |
| stream_url | TEXT | NULL | 실시간 스트림 URL |
| vod_url | TEXT | NULL | VOD URL |
| status | VARCHAR(20) | DEFAULT 'scheduled' | 상태 |
| duration_seconds | INT | NULL | 총 재생 시간 (초) |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | 생성 시각 |
| updated_at | TIMESTAMPTZ | DEFAULT NOW() | 수정 시각 |

**status 값**: `scheduled` | `live` | `processing` | `ended`

**인덱스:**
- `idx_meetings_status` ON (status)
- `idx_meetings_date` ON (meeting_date DESC)

```sql
CREATE TABLE meetings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title VARCHAR(255) NOT NULL,
  meeting_date DATE NOT NULL,
  stream_url TEXT,
  vod_url TEXT,
  status VARCHAR(20) DEFAULT 'scheduled'
    CHECK (status IN ('scheduled', 'live', 'processing', 'ended')),
  duration_seconds INT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_meetings_status ON meetings(status);
CREATE INDEX idx_meetings_date ON meetings(meeting_date DESC);

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER meetings_updated_at
  BEFORE UPDATE ON meetings
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();
```

---

### 3.2 subtitles (자막)

| 컬럼명 | 타입 | 제약조건 | 설명 |
|--------|------|----------|------|
| id | UUID | PK, DEFAULT gen_random_uuid() | 고유 식별자 |
| meeting_id | UUID | FK → meetings(id), ON DELETE CASCADE | 회의 FK |
| start_time | FLOAT | NOT NULL | 시작 시간 (초) |
| end_time | FLOAT | NOT NULL | 종료 시간 (초) |
| text | TEXT | NOT NULL | 자막 텍스트 |
| speaker | VARCHAR(100) | NULL | 화자 (화자 1, 화자 2, ...) |
| confidence | FLOAT | NULL | 인식 신뢰도 (0~1) |
| verification_status | VARCHAR(20) | DEFAULT 'unverified' | 대조 상태 |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | 생성 시각 |

**verification_status 값**: `unverified` | `verified` | `flagged`

**인덱스:**
- `idx_subtitles_meeting_time` ON (meeting_id, start_time)
- `idx_subtitles_text_search` USING GIN (to_tsvector('simple', text))
- `idx_subtitles_text_trgm` USING GIN (text gin_trgm_ops)
- `idx_subtitles_verification` ON (meeting_id, verification_status)

```sql
CREATE TABLE subtitles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  start_time FLOAT NOT NULL,
  end_time FLOAT NOT NULL,
  text TEXT NOT NULL,
  speaker VARCHAR(100),
  confidence FLOAT CHECK (confidence >= 0 AND confidence <= 1),
  verification_status VARCHAR(20) DEFAULT 'unverified'
    CHECK (verification_status IN ('unverified', 'verified', 'flagged')),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_subtitles_meeting_time ON subtitles(meeting_id, start_time);
CREATE INDEX idx_subtitles_text_search ON subtitles USING GIN (to_tsvector('simple', text));
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX idx_subtitles_text_trgm ON subtitles USING GIN (text gin_trgm_ops);
CREATE INDEX idx_subtitles_verification ON subtitles(meeting_id, verification_status);
```

---

### 3.3 channels (채널)

| 컬럼명 | 타입 | 제약조건 | 설명 |
|--------|------|----------|------|
| id | VARCHAR(10) | PK | 채널 ID (ch1~ch90) |
| name | VARCHAR(200) | NOT NULL | 위원회명 |
| code | VARCHAR(50) | NULL | 채널 코드 |
| stream_url | TEXT | NULL | HLS 스트림 URL |

> 참고: 채널 데이터는 `backend/app/core/channels.py`에서 정적으로 정의 (18개 채널)

```sql
CREATE TABLE channels (
  id VARCHAR(10) PRIMARY KEY,
  name VARCHAR(200) NOT NULL,
  code VARCHAR(50),
  stream_url TEXT
);
```

---

### 3.4 dictionary (용어 사전)

| 컬럼명 | 타입 | 제약조건 | 설명 |
|--------|------|----------|------|
| id | UUID | PK, DEFAULT gen_random_uuid() | 고유 식별자 |
| wrong_text | VARCHAR(200) | NOT NULL, UNIQUE | 잘못 인식되는 텍스트 |
| correct_text | VARCHAR(200) | NOT NULL | 올바른 텍스트 |
| category | VARCHAR(50) | NULL | 분류 (councilor, term, etc.) |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | 생성 시각 |

```sql
CREATE TABLE dictionary (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  wrong_text VARCHAR(200) NOT NULL,
  correct_text VARCHAR(200) NOT NULL,
  category VARCHAR(50),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(wrong_text)
);

CREATE INDEX idx_dictionary_wrong ON dictionary(wrong_text);
CREATE INDEX idx_dictionary_category ON dictionary(category);
```

---

### 3.5 bills (의안) — Phase 5

| 컬럼명 | 타입 | 제약조건 | 설명 |
|--------|------|----------|------|
| id | UUID | PK, DEFAULT gen_random_uuid() | 고유 식별자 |
| bill_number | VARCHAR(50) | NOT NULL | 의안번호 |
| title | VARCHAR(500) | NOT NULL | 의안명 |
| proposer | VARCHAR(200) | NULL | 제안자 |
| committee | VARCHAR(200) | NULL | 소관 위원회 |
| status | VARCHAR(50) | DEFAULT 'received' | 상태 |
| proposed_date | DATE | NULL | 제안일 |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | 생성 시각 |
| updated_at | TIMESTAMPTZ | DEFAULT NOW() | 수정 시각 |

**status 값**: `received` | `reviewing` | `decided` | `promulgated`

```sql
CREATE TABLE bills (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  bill_number VARCHAR(50) NOT NULL,
  title VARCHAR(500) NOT NULL,
  proposer VARCHAR(200),
  committee VARCHAR(200),
  status VARCHAR(50) DEFAULT 'received'
    CHECK (status IN ('received', 'reviewing', 'decided', 'promulgated')),
  proposed_date DATE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_bills_committee ON bills(committee);
CREATE INDEX idx_bills_status ON bills(status);
```

---

### 3.6 bill_mentions (의안-회의 연결) — Phase 5

| 컬럼명 | 타입 | 제약조건 | 설명 |
|--------|------|----------|------|
| id | UUID | PK, DEFAULT gen_random_uuid() | 고유 식별자 |
| bill_id | UUID | FK → bills(id) | 의안 FK |
| meeting_id | UUID | FK → meetings(id) | 회의 FK |
| subtitle_id | UUID | FK → subtitles(id) | 자막 FK (선택) |
| start_time | FLOAT | NULL | 발언 시작 시간 |
| end_time | FLOAT | NULL | 발언 종료 시간 |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | 생성 시각 |

```sql
CREATE TABLE bill_mentions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  bill_id UUID REFERENCES bills(id),
  meeting_id UUID REFERENCES meetings(id),
  subtitle_id UUID REFERENCES subtitles(id),
  start_time FLOAT,
  end_time FLOAT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_bill_mentions_bill ON bill_mentions(bill_id);
CREATE INDEX idx_bill_mentions_meeting ON bill_mentions(meeting_id);
```

---

### 3.7 meeting_agendas (회의 안건) — Phase 6A

| 컬럼명 | 타입 | 제약조건 | 설명 |
|--------|------|----------|------|
| id | UUID | PK, DEFAULT gen_random_uuid() | 고유 식별자 |
| meeting_id | UUID | FK → meetings(id) | 회의 FK |
| title | VARCHAR(500) | NOT NULL | 안건 제목 |
| order_num | INT | NULL | 순번 |
| start_time | FLOAT | NULL | 시작 시간 |
| end_time | FLOAT | NULL | 종료 시간 |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | 생성 시각 |

```sql
CREATE TABLE meeting_agendas (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  meeting_id UUID REFERENCES meetings(id) ON DELETE CASCADE,
  title VARCHAR(500) NOT NULL,
  order_num INT,
  start_time FLOAT,
  end_time FLOAT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_meeting_agendas_meeting ON meeting_agendas(meeting_id);
```

---

### 3.8 subtitle_history (자막 변경 이력) — Phase 6A

| 컬럼명 | 타입 | 제약조건 | 설명 |
|--------|------|----------|------|
| id | UUID | PK, DEFAULT gen_random_uuid() | 고유 식별자 |
| subtitle_id | UUID | FK → subtitles(id) | 자막 FK |
| old_text | TEXT | NULL | 변경 전 텍스트 |
| new_text | TEXT | NULL | 변경 후 텍스트 |
| changed_by | VARCHAR(100) | NULL | 변경자 |
| changed_at | TIMESTAMPTZ | DEFAULT NOW() | 변경 시각 |

```sql
CREATE TABLE subtitle_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subtitle_id UUID REFERENCES subtitles(id) ON DELETE CASCADE,
  old_text TEXT,
  new_text TEXT,
  changed_by VARCHAR(100),
  changed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_subtitle_history_subtitle ON subtitle_history(subtitle_id);
CREATE INDEX idx_subtitle_history_time ON subtitle_history(changed_at DESC);
```

---

### 3.9 meeting_summaries (AI 회의 요약) — Phase 7

| 컬럼명 | 타입 | 제약조건 | 설명 |
|--------|------|----------|------|
| id | UUID | PK, DEFAULT gen_random_uuid() | 고유 식별자 |
| meeting_id | UUID | FK → meetings(id), UNIQUE | 회의 FK (1:1) |
| summary_text | TEXT | NULL | 전체 요약문 |
| agenda_summaries | JSONB | NULL | 안건별 요약 |
| key_decisions | JSONB | NULL | 핵심 결정 사항 |
| action_items | JSONB | NULL | 후속 조치 사항 |
| model_used | VARCHAR(50) | NULL | 사용 AI 모델명 |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | 생성 시각 |

```sql
CREATE TABLE meeting_summaries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  meeting_id UUID REFERENCES meetings(id) ON DELETE CASCADE UNIQUE,
  summary_text TEXT,
  agenda_summaries JSONB,
  key_decisions JSONB,
  action_items JSONB,
  model_used VARCHAR(50),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_meeting_summaries_meeting ON meeting_summaries(meeting_id);
```

---

### 3.10 users (사용자) — Phase 11

| 컬럼명 | 타입 | 제약조건 | 설명 |
|--------|------|----------|------|
| id | UUID | PK, DEFAULT gen_random_uuid() | 고유 식별자 |
| username | VARCHAR(100) | NOT NULL, UNIQUE | 로그인 username |
| password_hash | VARCHAR(255) | NOT NULL | 해시된 비밀번호 (bcrypt) |
| name | VARCHAR(200) | NOT NULL | 사용자 실명 |
| email | VARCHAR(200) | NULL | 이메일 |
| role | VARCHAR(50) | DEFAULT 'Staff' | 역할 (Anonymous/Staff/CommitteeStaff/MeetingManager/Stenographer/Admin) |
| assigned_committee | VARCHAR(200) | NULL | 소관 위원회 (CommitteeStaff만) |
| is_active | BOOLEAN | DEFAULT true | 활성화 여부 |
| last_login_at | TIMESTAMPTZ | NULL | 마지막 로그인 시각 |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | 생성 시각 |
| updated_at | TIMESTAMPTZ | DEFAULT NOW() | 수정 시각 |

```sql
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username VARCHAR(100) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  name VARCHAR(200) NOT NULL,
  email VARCHAR(200),
  role VARCHAR(50) DEFAULT 'Staff'
    CHECK (role IN ('Staff', 'CommitteeStaff', 'MeetingManager', 'Stenographer', 'Admin')),
  assigned_committee VARCHAR(200),
  is_active BOOLEAN DEFAULT true,
  last_login_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_role ON users(role);
```

---

### 3.11 user_sessions (사용자 세션) — Phase 11

| 컬럼명 | 타입 | 제약조건 | 설명 |
|--------|------|----------|------|
| id | UUID | PK, DEFAULT gen_random_uuid() | 고유 식별자 |
| user_id | UUID | FK → users(id) | 사용자 FK |
| token | TEXT | NOT NULL | JWT 토큰 |
| refresh_token | TEXT | NULL | 갱신 토큰 (v2) |
| ip_address | VARCHAR(50) | NULL | 접속 IP |
| user_agent | TEXT | NULL | User-Agent |
| expires_at | TIMESTAMPTZ | NOT NULL | 토큰 만료 시각 |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | 생성 시각 |

```sql
CREATE TABLE user_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token TEXT NOT NULL,
  refresh_token TEXT,
  ip_address VARCHAR(50),
  user_agent TEXT,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_user_sessions_user ON user_sessions(user_id);
CREATE INDEX idx_user_sessions_token ON user_sessions(token);
```

---

### 3.12 ai_conversations (AI 대화) — Phase 11

| 컬럼명 | 타입 | 제약조건 | 설명 |
|--------|------|----------|------|
| id | UUID | PK, DEFAULT gen_random_uuid() | 고유 식별자 |
| user_id | UUID | FK → users(id), nullable | 사용자 FK (비로그인 시 NULL) |
| session_id | UUID | NULL | 세션 ID (대화 그룹) |
| user_question | TEXT | NOT NULL | 사용자 질문 |
| ai_response | TEXT | NOT NULL | AI 응답 |
| source_documents | JSONB | NULL | 검색된 문서 메타 (회의ID, 의안ID) |
| model_used | VARCHAR(50) | DEFAULT 'gpt-5-mini' | 사용 AI 모델 |
| input_tokens | INT | NULL | 입력 토큰 수 |
| output_tokens | INT | NULL | 출력 토큰 수 |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | 생성 시각 |

```sql
CREATE TABLE ai_conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  session_id UUID,
  user_question TEXT NOT NULL,
  ai_response TEXT NOT NULL,
  source_documents JSONB,
  model_used VARCHAR(50) DEFAULT 'gpt-5-mini',
  input_tokens INT,
  output_tokens INT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_ai_conversations_user ON ai_conversations(user_id);
CREATE INDEX idx_ai_conversations_session ON ai_conversations(session_id);
CREATE INDEX idx_ai_conversations_created ON ai_conversations(created_at DESC);
```

---

### 3.13 stenography_edit_history (속기록 수정 이력) — Phase 11

| 컬럼명 | 타입 | 제약조건 | 설명 |
|--------|------|----------|------|
| id | UUID | PK, DEFAULT gen_random_uuid() | 고유 식별자 |
| line_id | UUID | FK → stenography_lines(id) | 속기록 라인 FK |
| old_text | TEXT | NULL | 변경 전 텍스트 |
| new_text | TEXT | NULL | 변경 후 텍스트 |
| changed_field | VARCHAR(50) | NULL | 변경 필드 (text/speaker/start_ms/end_ms) |
| changed_by | VARCHAR(100) | NULL | 변경자 (속기사명) |
| changed_at | TIMESTAMPTZ | DEFAULT NOW() | 변경 시각 |

```sql
CREATE TABLE stenography_edit_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  line_id UUID REFERENCES stenography_lines(id) ON DELETE CASCADE,
  old_text TEXT,
  new_text TEXT,
  changed_field VARCHAR(50),
  changed_by VARCHAR(100),
  changed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_stenography_edit_history_line ON stenography_edit_history(line_id);
CREATE INDEX idx_stenography_edit_history_time ON stenography_edit_history(changed_at DESC);
```

---

### 3.14 meeting_summaries (AI 회의 요약) — Phase 7

| 컬럼명 | 타입 | 제약조건 | 설명 |
|--------|------|----------|------|
| id | UUID | PK, DEFAULT gen_random_uuid() | 고유 식별자 |
| meeting_id | UUID | FK → meetings(id), UNIQUE | 회의 FK (1:1) |
| summary_text | TEXT | NULL | 전체 요약문 |
| agenda_summaries | JSONB | NULL | 안건별 요약 |
| key_decisions | JSONB | NULL | 핵심 결정 사항 |
| action_items | JSONB | NULL | 후속 조치 사항 |
| model_used | VARCHAR(50) | NULL | 사용 AI 모델명 |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | 생성 시각 |

```sql
CREATE TABLE meeting_summaries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  meeting_id UUID REFERENCES meetings(id) ON DELETE CASCADE UNIQUE,
  summary_text TEXT,
  agenda_summaries JSONB,
  key_decisions JSONB,
  action_items JSONB,
  model_used VARCHAR(50),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_meeting_summaries_meeting ON meeting_summaries(meeting_id);
```

---

## 4. 주요 쿼리

### 4.1 실시간 회의 조회

```sql
SELECT * FROM meetings
WHERE status = 'live'
ORDER BY meeting_date DESC LIMIT 1;
```

### 4.2 자막 검색 (통합)

```sql
-- 전체 회의 통합 검색
SELECT s.*, m.title as meeting_title, m.meeting_date
FROM subtitles s
JOIN meetings m ON s.meeting_id = m.id
WHERE s.text ILIKE '%예산%'
ORDER BY m.meeting_date DESC, s.start_time;
```

### 4.3 회의별 자막 조회

```sql
SELECT * FROM subtitles
WHERE meeting_id = $1
ORDER BY start_time;
```

### 4.4 대조 대기열 (신뢰도 낮은 순)

```sql
SELECT * FROM subtitles
WHERE meeting_id = $1
  AND verification_status = 'unverified'
ORDER BY confidence ASC NULLS FIRST
LIMIT 50;
```

### 4.5 대조 진행률

```sql
SELECT
  COUNT(*) FILTER (WHERE verification_status = 'verified') as verified,
  COUNT(*) FILTER (WHERE verification_status = 'flagged') as flagged,
  COUNT(*) FILTER (WHERE verification_status = 'unverified') as unverified,
  COUNT(*) as total
FROM subtitles
WHERE meeting_id = $1;
```

### 4.6 의안 관련 회의 조회

```sql
SELECT b.*, bm.meeting_id, m.title as meeting_title,
       bm.start_time, bm.end_time
FROM bills b
LEFT JOIN bill_mentions bm ON b.id = bm.bill_id
LEFT JOIN meetings m ON bm.meeting_id = m.id
WHERE b.id = $1;
```

### 4.7 AI 요약 조회

```sql
SELECT * FROM meeting_summaries
WHERE meeting_id = $1;
```

---

## 5. 데이터 흐름

### 5.1 실시간 자막 저장

```
1. 채널 STT 시작 → HLS 세그먼트 다운로드
2. Deepgram Streaming WSS로 오디오 전송
3. Dictionary 기반 용어 교정
4. subtitles 테이블에 INSERT
5. WebSocket으로 클라이언트에 브로드캐스트 (subtitle_created)
6. SubtitleCorrector 배치 큐에 추가
7. 3개 모이면 OpenAI GPT-5-mini 교정
8. 교정 결과 DB UPDATE + WebSocket (subtitle_corrected)
```

### 5.2 VOD 자막 생성

```
1. KMS VOD URL → MP4 직접 변환 (ffmpeg 미사용)
2. MP4 → Deepgram REST API (diarize=true)
3. 화자 그룹핑 (speaker_utils.py)
4. Dictionary 기반 용어 교정
5. subtitles 테이블에 배치 INSERT
6. meetings 상태 업데이트 (status: 'ended')
```

### 5.3 자막 편집 워크플로우

```
1. 사용자가 자막 텍스트 수정
2. subtitle_history에 변경 이력 저장 (old_text, new_text)
3. subtitles 테이블 UPDATE
```

### 5.4 대조 관리 워크플로우

```
1. 검토 대기열 조회 (신뢰도 낮은 순)
2. 사용자가 개별/일괄 대조 처리
3. verification_status 변경 (unverified → verified/flagged)
4. 진행률 통계 갱신
```

---

## 6. Supabase 설정

### 6.1 Row Level Security (RLS)

현재 인증 없이 사용하므로 RLS 비활성화:

```sql
ALTER TABLE meetings DISABLE ROW LEVEL SECURITY;
ALTER TABLE subtitles DISABLE ROW LEVEL SECURITY;
ALTER TABLE channels DISABLE ROW LEVEL SECURITY;
ALTER TABLE dictionary DISABLE ROW LEVEL SECURITY;
ALTER TABLE bills DISABLE ROW LEVEL SECURITY;
ALTER TABLE bill_mentions DISABLE ROW LEVEL SECURITY;
ALTER TABLE meeting_agendas DISABLE ROW LEVEL SECURITY;
ALTER TABLE subtitle_history DISABLE ROW LEVEL SECURITY;
ALTER TABLE meeting_summaries DISABLE ROW LEVEL SECURITY;
```

### 6.2 Realtime 설정

```sql
ALTER PUBLICATION supabase_realtime ADD TABLE subtitles;
```

---

## 7. 마이그레이션 이력

| 파일 | 내용 | Phase |
|------|------|-------|
| 001_initial.sql | meetings, subtitles, dictionary, channels 테이블 | 0 |
| 002_adapt_existing_schema.sql | 기존 테이블 적응 | 0 |
| 002_seed_data.sql | 초기 데이터 | 0 |
| 003_bills.sql | bills, bill_mentions 테이블 | 5 |
| 004_phase6a.sql | meeting_agendas, subtitle_history 테이블 | 6A |
| 005_phase7.sql | meeting_summaries, verification_status 컬럼 | 7 |
| 006_missing_tables.sql | 누락 테이블 보완 | - |
| 007_dictionary_created_by.sql | dictionary created_by 컬럼 | - |
| 008_collaborative_tables.sql | 협업 관련 테이블 (edit_sessions, subtitle_comments) | - |
| 009_councilors_expansion.sql | 의원 데이터 확장 | - |
| 010_councilors_enrichment.sql | 의원 데이터 보강 | - |
| 011_stenography_lines.sql | stenography_lines 테이블 (Phase 10) | 10 |
| 012_phase11_auth.sql | users, user_sessions, ai_conversations, stenography_edit_history 테이블 (Phase 11) | 11 |

---

## 8. 백업 및 복구

### 8.1 Supabase 자동 백업

- Supabase Pro 플랜: 일일 자동 백업
- Free 플랜: 수동 백업 필요

### 8.2 수동 백업

```bash
pg_dump -h db.xxx.supabase.co -U postgres -d postgres > backup.sql
```

---

## 9. 성능 고려사항

### 9.1 인덱스 전략

| 쿼리 패턴 | 인덱스 |
|----------|--------|
| 회의 상태 조회 | idx_meetings_status |
| 회의 날짜순 정렬 | idx_meetings_date |
| 회의별 자막 시간순 | idx_subtitles_meeting_time |
| 자막 전문 검색 | idx_subtitles_text_search |
| 자막 부분 검색 | idx_subtitles_text_trgm |
| 대조 상태별 조회 | idx_subtitles_verification |
| 의안 위원회별 조회 | idx_bills_committee |
| 자막 변경 이력 조회 | idx_subtitle_history_subtitle |

### 9.2 파티셔닝 (v2)

자막 데이터가 많아지면 월별 파티셔닝 고려:

```sql
CREATE TABLE subtitles (
  ...
) PARTITION BY RANGE (created_at);

CREATE TABLE subtitles_2026_01 PARTITION OF subtitles
  FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
```
