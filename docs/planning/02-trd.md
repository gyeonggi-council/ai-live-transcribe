# TRD (기술 요구사항 정의서)

> 경기도의회 실시간 자막 서비스
> 최종 갱신: 2026-03-18 (Phase 9 완료 반영)

---

## MVP 캡슐

| # | 항목 | 내용 |
|---|------|------|
| 1 | 목표 | 경기도의회 회의 영상에 실시간/VOD 자막을 제공 |
| 2 | 페르소나 | 경기도의회 직원 |
| 3 | 핵심 기능 | 실시간 자막, 키워드 검색, VOD 자막, 채널 시스템, 자막 교정, 의안 관리, 대조 관리, AI 요약, 플랫폼 셸 UI |
| 4 | 성공 지표 | 자막 지연 < 5초, 정확도 > 90% |
| 5 | 입력 지표 | 일일 사용 시간, 검색 빈도 |
| 6 | 비기능 요구 | 5명 동시 접속, 응답 < 2초 |
| 7 | 현재 상태 | Phase 0~9 완료 |

---

## 1. 시스템 아키텍처

### 1.1 고수준 아키텍처

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         System Architecture                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  [경기도의회 HLS 스트림 (18채널)]                                       │
│       │                                                                 │
│       │ HLS (m3u8) - 마스터→미디어→TS 세그먼트 (2단계 파싱)            │
│       ▼                                                                 │
│  ┌──────────────────────────────────────────────────────┐               │
│  │  Railway Server (FastAPI)                            │               │
│  │                                                      │               │
│  │  ┌──────────────┐  ┌──────────────┐                  │               │
│  │  │ HLS Parser   │  │ Channel STT  │ (채널별 관리)    │               │
│  │  │ (2단계 파싱) │→│ Manager      │                  │               │
│  │  └──────────────┘  └──────┬───────┘                  │               │
│  │                           │                          │               │
│  │                    ┌──────▼───────┐                   │               │
│  │                    │ Deepgram     │ (Streaming WSS)   │               │
│  │                    │ Nova-3 STT  │                   │               │
│  │                    └──────┬───────┘                   │               │
│  │                           │                          │               │
│  │  ┌──────────────┐  ┌─────▼────────┐                  │               │
│  │  │ Dictionary   │→│ 용어 교정    │                  │               │
│  │  │ Service      │  └──────┬───────┘                  │               │
│  │  └──────────────┘         │                          │               │
│  │                    ┌──────▼───────┐                   │               │
│  │                    │ OpenAI       │ (GPT-5-mini)     │               │
│  │                    │ Corrector    │ (배치 큐 교정)   │               │
│  │                    └──────┬───────┘                   │               │
│  │                           │                          │               │
│  │  ┌──────────────┐  ┌─────▼────────┐                  │               │
│  │  │ WebSocket    │←─│ 자막 텍스트  │                  │               │
│  │  │ Server       │  └──────────────┘                  │               │
│  │  └──────┬───────┘                                    │               │
│  │         │         ┌──────────────┐                   │               │
│  │         │         │ Self-Ping    │ (Railway 슬립 방지)│              │
│  │         │         │ Health Check │                   │               │
│  │         │         └──────────────┘                   │               │
│  └─────────┼────────────────────────────────────────────┘               │
│            │                                                            │
│            │ WebSocket (subtitle_created/interim/corrected)             │
│            ▼                                                            │
│  ┌─────────────────┐     ┌──────────────┐                               │
│  │  Vercel (Next)  │────▶│  Supabase    │                               │
│  │  Frontend       │     │  (PostgreSQL)│                               │
│  │  + Platform     │     │  REST API    │                               │
│  │    Shell UI     │     └──────────────┘                               │
│  └─────────────────┘                                                    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2 데이터 흐름

```
1. 실시간 자막 흐름:
   HLS Master Playlist → Media Playlist → TS 세그먼트 (2단계 파싱)
   → Deepgram Streaming WSS → 자막 텍스트
   → 용어 사전 교정 → DB 저장 + WebSocket 브로드캐스트 (subtitle_created)
   → OpenAI 배치 큐 교정 → WebSocket 브로드캐스트 (subtitle_corrected)

2. VOD 자막 흐름:
   KMS VOD URL → MP4 직접 변환 (ffmpeg 미사용)
   → Deepgram REST API (diarize=true)
   → 화자 그룹핑 → 용어 사전 교정 → DB 배치 저장

3. 채널 상태 흐름:
   경기도의회 API → 18채널 방송 상태 조회 → SSE 스트림
   → 방송 시작 감지 → 자동 STT 시작

4. 검색 흐름:
   검색어 입력 → Supabase ILIKE 검색 → 결과 하이라이트

5. AI 요약 흐름:
   자막 데이터 → OpenAI GPT-5-mini → 요약/안건/핵심결정/후속조치
```

### 1.3 컴포넌트 설명

| 컴포넌트 | 역할 | 왜 이 선택? |
|----------|------|-------------|
| Railway (FastAPI) | 백엔드 서버, 스트림 처리, WebSocket | Long-running process 지원, 비동기 |
| Vercel (Next.js 14) | 프론트엔드 호스팅 | App Router, SSR, 무료 티어 |
| Supabase | DB (REST API 사용) | Full-Text Search 내장, 무료 티어 |
| Deepgram Nova-3 | 실시간 STT (Streaming WebSocket) | 한국어 정확도, 실시간 스트리밍 지원 |
| OpenAI GPT-5-mini | 자막 교정, 문법 검사, AI 요약 | 비용 효율, 한국어 지원 |

---

## 2. 권장 기술 스택

### 2.1 프론트엔드

| 항목 | 선택 | 이유 | 벤더 락인 리스크 |
|------|------|------|-----------------|
| 프레임워크 | Next.js 14 (App Router) | SSR, 최신 App Router | 중간 |
| 언어 | TypeScript (strict mode) | 타입 안전성 | 낮음 |
| 스타일링 | TailwindCSS | 빠른 개발, 유틸리티 기반 | 낮음 |
| 데이터 페칭 | SWR | 경량, 캐싱, 재검증 | 낮음 |
| 영상 플레이어 | HLS.js (실시간) + HTML5 Video (VOD) | HLS 스트림 지원, 경량 | 낮음 |
| 실시간 통신 | 네이티브 WebSocket | 표준 API, 추가 의존성 불필요 | 없음 |
| 테스트 | Jest + React Testing Library | 표준 테스트 도구 | 낮음 |
| E2E 테스트 | Playwright | 크로스 브라우저 지원 | 낮음 |

### 2.2 백엔드

| 항목 | 선택 | 이유 | 벤더 락인 리스크 |
|------|------|------|-----------------|
| 프레임워크 | FastAPI | 비동기 지원, WebSocket, 자동 문서화 | 낮음 |
| 언어 | Python 3.11+ | Deepgram SDK 호환 | 낮음 |
| DB 클라이언트 | Supabase REST API (httpx) | asyncpg 한글 사용자명 이슈 회피 | 낮음 |
| 검증 | Pydantic v2 | FastAPI 통합, 타입 안전 | 낮음 |
| WebSocket | FastAPI 네이티브 WebSocket | 양방향 실시간 통신 | 낮음 |
| HTTP 클라이언트 | httpx | 비동기 HTTP, KMS VOD 변환 | 낮음 |
| 테스트 | pytest | 표준 Python 테스트 | 낮음 |

### 2.3 데이터베이스

| 항목 | 선택 | 이유 |
|------|------|------|
| 메인 DB | Supabase (PostgreSQL) | Full-Text Search, REST API |
| 검색 | ILIKE + pg_trgm | 한국어 부분 문자열 검색 |
| 접근 방식 | REST API (asyncpg 미사용) | Windows 한글 사용자명 SSL 문제 회피 |

### 2.4 외부 서비스

| 항목 | 선택 | 이유 |
|------|------|------|
| 실시간 STT | Deepgram Nova-3 (Streaming WebSocket) | 한국어 정확도, 실시간 스트리밍 지원 |
| VOD STT | Deepgram Nova-3 (REST API, diarize=true) | 화자 분리 지원 |
| 텍스트 교정 | OpenAI GPT-5-mini | 의회 용어/의원명 교정, 비용 효율 |
| 문법 검사 | OpenAI GPT-5-mini | 한국어 맞춤법, 띄어쓰기 |
| 회의 요약 | OpenAI GPT-5-mini | 안건별 요약, 핵심 결정 추출 |
| 실시간 교정 | OpenAI GPT-5-mini (배치 큐) | 3개씩 10초 간격 배치 처리 |

### 2.5 인프라

| 항목 | 선택 | 이유 | 비용 예상 |
|------|------|------|----------|
| 백엔드 호스팅 | Railway | Long-running + Self-ping 슬립 방지 | $10-20/월 |
| 프론트 호스팅 | Vercel | 무료 티어 충분 | $0 |
| DB | Supabase | 무료 티어 충분 | $0 |
| STT | Deepgram API | 사용량 기반 | $10-30/월 |
| AI | OpenAI API | 교정 + 요약 + 문법검사 | $5-15/월 |

---

## 3. 비기능 요구사항

### 3.1 성능

| 항목 | 요구사항 | 측정 방법 |
|------|----------|----------|
| 자막 지연 | < 5초 (음성→표시) | 타임스탬프 비교 |
| API 응답 | < 2초 (P95) | API 모니터링 |
| 초기 로딩 | < 3초 (FCP) | Lighthouse |
| WebSocket 연결 | < 1초 | 연결 시간 측정 |
| 배치 교정 | 3개/10초 주기 | 큐 모니터링 |

### 3.2 보안

| 항목 | 요구사항 |
|------|----------|
| 인증 | MVP: 없음 (내부 사용) |
| API 키 | 환경 변수 (.env, .env.local) |
| HTTPS | Railway/Vercel 기본 제공 |
| CORS | 특정 도메인만 허용 |
| PII | 개인정보 마스킹 기능 (Phase 6B) |

### 3.3 확장성

| 항목 | 현재 | 목표 |
|------|------|------|
| 동시 사용자 | 5명 | 50명 |
| 동시 채널 STT | 18개 (전체) | 18개 |
| 저장 자막 | 100시간 | 1000시간 |

### 3.4 안정성 (Railway)

| 항목 | 대응 방안 |
|------|----------|
| App Sleeping | Self-ping 헬스체크 (5분 간격) |
| STT 정리 | AutoSttManager.stop_all() 일괄 중지 |
| SubtitleCorrector | lifespan에서 start/stop 관리 |

---

## 4. 외부 API 연동

### 4.1 Deepgram Nova-3 (실시간 STT)

| 항목 | 내용 |
|------|------|
| 용도 | 음성→텍스트 변환 (실시간 Streaming STT) |
| 엔드포인트 | `wss://api.deepgram.com/v1/listen` |
| 모델 | `nova-3` |
| 파라미터 | `language: "ko"`, `model: "nova-3"`, `smart_format: true`, `diarize: true` |
| 처리 방식 | 3개 동시 태스크: sender(세그먼트 전송), receiver(결과 수신), keepalive |

### 4.2 Deepgram Nova-3 (VOD STT)

| 항목 | 내용 |
|------|------|
| 용도 | VOD 영상 → 자막 생성 (화자 분리 포함) |
| 방식 | MP4 직접 Deepgram에 스트리밍 (ffmpeg 미사용) |
| 파라미터 | `diarize: true`, `language: "ko"` |
| 화자 라벨 | 자동 ("화자 1", "화자 2", ...) |

### 4.3 OpenAI GPT-5-mini

| 항목 | 내용 |
|------|------|
| 용도 | 의회용어/의원이름 교정, 문법 검사, 회의 요약, 실시간 자막 교정 |
| 모델 | `gpt-5-mini` (비용 효율) |
| 실시간 교정 | 3개 자막씩 10초 간격 배치 큐 처리 |
| 회의 요약 | summary_text, agenda_summaries, key_decisions, action_items |

### 4.4 경기도의회 스트림

| 항목 | 내용 |
|------|------|
| 실시간 | `https://stream01.cdn.gov-ntruss.com/live/{ch}/playlist.m3u8` (18채널) |
| VOD | `https://kms.ggc.go.kr/mp4/{mp4src}` |
| 채널 상태 API | `/getOnairListTodayData.do`, `/getQuickVodList.do` |
| KMS VOD 변환 | `var mp4file="..."` 정규식 추출 → MP4 URL 생성 |

---

## 5. 접근제어·권한 모델

### 5.1 역할 정의 (Phase 11)

| 역할 | 신원 | 인증 | 설명 | 권한 |
|------|------|------|------|------|
| **Anonymous** | 비로그인 | 불필요 | 일반 시민/직원 | 생중계 자막, 회의록, AI Q&A 조회 (쓰기 불가) |
| **Staff** | 로그인 (일반직원) | 필수 | 경기도의회 직원 (기본) | Anonymous + 통합검색 + VOD 조회 |
| **CommitteeStaff** | 로그인 (전문위원실) | 필수 | 소관 상임위 담당자 | Staff + 소관위 회의 관리 + 의안 연계 + 자막 편집 |
| **MeetingManager** | 로그인 (회의담당) | 필수 | 회의록 관리 담당자 | CommitteeStaff + VOD 등록 + 자막 교정 + 검증 + 회의록 발행 |
| **Stenographer** | 로그인 (속기사) | 필수 | 속기록 작성/편집 | MeetingManager + 속기사 대시보드 + 속기 편집 전문 |
| **Admin** | 로그인 (관리자) | 필수 | 시스템 관리자 | 모든 권한 + 사용자 관리 + 시스템 설정 + API 상태 |

### 5.2 권한 매트릭스

| 기능 | Anonymous | Staff | CommitteeStaff | MeetingManager | Stenographer | Admin |
|-----|-----------|-------|-----------------|----------------|--------------|-------|
| 생중계 자막 조회 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 회의록 조회 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| AI Q&A | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 통합검색 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| VOD 조회 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| VOD 등록 | ❌ | ❌ | ❌ | ✅ | ❌ | ✅ |
| 자막 편집 | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| 자막 검증 | ❌ | ❌ | ❌ | ✅ | ❌ | ✅ |
| 회의록 발행 | ❌ | ❌ | ❌ | ✅ | ❌ | ✅ |
| 의안 관리 | ❌ | ❌ | ✅ | ✅ | ❌ | ✅ |
| 속기 편집 | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| 사용자 관리 | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| 시스템 설정 | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

### 5.3 인증 방식 (Phase 11)

| 항목 | 내용 |
|------|------|
| 인증 타입 | JWT 기반 (Bearer Token) |
| 로그인 화면 | `/login` (신규 S-15) |
| 토큰 저장 | HttpOnly Cookie (보안) |
| 토큰 만료 | 24시간 (configurable) |
| 새로고침 | Refresh Token 지원 (v2) |
| 비로그인 접근 | `/` (홈), `/live` (실시간), `/ai` (AI), `/search` (통합검색 읽기전용) 가능 |

### 5.4 위원회 필터 기본값

**전문위원실 직원 (CommitteeStaff)만 해당:**
- 소관 위원회 자동 필터 적용
- 의안 목록, VOD 목록에서 기본값으로 표시
- 사용자 프로필에서 `assigned_committee` 저장
- UI에서 필터 변경 가능 (기본값은 수정 불가)

---

## 6. 데이터 모델

### 6.1 주요 테이블 (9개 상세 + 6개 추가)

```sql
-- 회의 (Meeting)
CREATE TABLE meetings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title VARCHAR(255) NOT NULL,
  meeting_date DATE NOT NULL,
  stream_url TEXT,
  vod_url TEXT,
  status VARCHAR(20) DEFAULT 'scheduled',
  duration_seconds INT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 자막 (Subtitle) - verification_status 포함
CREATE TABLE subtitles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  meeting_id UUID REFERENCES meetings(id) ON DELETE CASCADE,
  start_time FLOAT NOT NULL,
  end_time FLOAT NOT NULL,
  text TEXT NOT NULL,
  speaker VARCHAR(100),
  confidence FLOAT,
  verification_status VARCHAR(20) DEFAULT 'unverified',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 채널 (Channel)
CREATE TABLE channels (
  id VARCHAR(10) PRIMARY KEY,
  name VARCHAR(200) NOT NULL,
  code VARCHAR(50),
  stream_url TEXT
);

-- 용어 사전 (Dictionary)
CREATE TABLE dictionary (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  wrong_text VARCHAR(200) NOT NULL,
  correct_text VARCHAR(200) NOT NULL,
  category VARCHAR(50),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 의안 (Bill) - Phase 5
CREATE TABLE bills (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  bill_number VARCHAR(50) NOT NULL,
  title VARCHAR(500) NOT NULL,
  proposer VARCHAR(200),
  committee VARCHAR(200),
  status VARCHAR(50) DEFAULT 'received',
  proposed_date DATE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 의안-회의 연결 (BillMention) - Phase 5
CREATE TABLE bill_mentions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  bill_id UUID REFERENCES bills(id),
  meeting_id UUID REFERENCES meetings(id),
  subtitle_id UUID REFERENCES subtitles(id),
  start_time FLOAT,
  end_time FLOAT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 회의 안건 (MeetingAgenda) - Phase 6A
CREATE TABLE meeting_agendas (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  meeting_id UUID REFERENCES meetings(id),
  title VARCHAR(500) NOT NULL,
  order_num INT,
  start_time FLOAT,
  end_time FLOAT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 자막 변경 이력 (SubtitleHistory) - Phase 6A
CREATE TABLE subtitle_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subtitle_id UUID REFERENCES subtitles(id),
  old_text TEXT,
  new_text TEXT,
  changed_by VARCHAR(100),
  changed_at TIMESTAMPTZ DEFAULT NOW()
);

-- AI 회의 요약 (MeetingSummary) - Phase 7
CREATE TABLE meeting_summaries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  meeting_id UUID REFERENCES meetings(id),
  summary_text TEXT,
  agenda_summaries JSONB,
  key_decisions JSONB,
  action_items JSONB,
  model_used VARCHAR(50),
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 6.2 데이터 흐름

```
Meeting 생성 → 채널 STT 시작 → Subtitle 실시간 저장
                            → WebSocket 브로드캐스트 (subtitle_created)
                            → Dictionary 기반 교정
                            → SubtitleCorrector 배치 교정 (subtitle_corrected)
                            → Verification QA 대조 관리

VOD 등록 → KMS URL 변환 → Deepgram STT → 화자 그룹핑
        → DB 저장 → 교정도구(용어점검/AI문법검사)
        → 대조관리 → AI 요약 → 회의록 내보내기
```

---

## 6. AI 아키텍처 (Phase 11)

### 6.1 RAG 기반 Q&A 파이프라인

```
사용자 질문
    │
    ▼
┌─────────────────────────────────┐
│ 벡터 검색 (Supabase + pgvector) │  ← 회의록/의안/의원 데이터 임베딩
│ (관련 문서 상위 5개 검색)         │
└────────┬────────────────────────┘
         │
         ▼
┌────────────────────────────────────────┐
│ 프롬프트 구성                           │
│ - 시스템 메시지 (의회 전문가 역할)      │
│ - 검색된 문서 (컨텍스트)               │
│ - 사용자 질문                           │
└────────┬───────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────┐
│ OpenAI GPT-5-mini 호출                │
│ (토큰 최적화: max_tokens=500)          │
└────────┬───────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────┐
│ 응답 반환 + 저장                        │
│ - ai_conversations 테이블에 저장        │
│ - 사용자에게 스트리밍 응답              │
└────────────────────────────────────────┘
```

### 6.2 실시간 AI 요약 (생중계)

| 항목 | 내용 |
|------|------|
| 트리거 | 방송 시작 후 1분 경과 |
| 주기 | 매 5분마다 자동 생성 |
| 입력 | 최신 5분 자막 (약 50~100개 자막) |
| 모델 | GPT-5-mini |
| 출력 | 핵심 내용 3~5줄 요약 |
| UI | S-01 메인화면 + S-02 생중계 패널 |

### 6.3 VOD AI 요약 (기존, Phase 7)

| 항목 | 내용 |
|------|------|
| 트리거 | 사용자 수동 요청 또는 자막 완성 자동 |
| 입력 | 전체 회의 자막 |
| 모델 | GPT-5-mini |
| 출력 | summary_text, agenda_summaries, key_decisions, action_items |
| UI | S-10 회의록 작성 + S-04 VOD 뷰어 (S-14에서 통합) |

### 6.4 AI 대화 모델 (신규, Phase 11)

```typescript
// ai_conversations 테이블
{
  id: UUID,
  user_id: UUID,          // 로그인 사용자
  session_id: UUID,       // 대화 세션 (같은 주제끼리 그룹)
  user_question: TEXT,
  ai_response: TEXT,
  source_documents: JSONB,  // 검색된 문서 메타 (회의ID, 의안ID 등)
  model_used: VARCHAR,
  input_tokens: INT,
  output_tokens: INT,
  created_at: TIMESTAMPTZ
}
```

### 6.5 벡터 저장소 (v2)

현재: 메모리 기반 검색 (Supabase ILIKE)
- 비용 절감, 즉시 구현 가능
- 정확도: 부분 일치, 한국어 형태소 분석 부족

향후: pgvector 지원 (OpenAI Embeddings)
```sql
-- Migration: add pgvector support
CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE meetings ADD COLUMN embedding vector(1536);
ALTER TABLE meeting_summaries ADD COLUMN embedding vector(1536);
CREATE INDEX ON meetings USING ivfflat (embedding vector_cosine_ops);
```

---

## 7. API 설계

### 7.1 RESTful 엔드포인트

#### Meetings

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | /api/meetings | 회의 목록 (status, limit, offset) |
| GET | /api/meetings/live | 실시간 회의 (channel 파라미터) |
| GET | /api/meetings/{id} | 회의 상세 (채널 ID도 지원) |
| POST | /api/meetings | VOD 등록 (KMS URL 자동 변환) |
| POST | /api/meetings/from-url | URL만으로 VOD 등록 (메타데이터 자동 추출) |
| POST | /api/meetings/{id}/stt | VOD STT 처리 시작 (백그라운드) |

#### Subtitles

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | /api/meetings/{id}/subtitles | 자막 목록 |
| GET | /api/meetings/{id}/subtitles/search | 자막 검색 |
| PATCH | /api/meetings/{id}/subtitles/{sid} | 자막 개별 수정 |
| PATCH | /api/meetings/{id}/subtitles | 자막 배치 수정 |

#### 교정 도구 (Phase 6B)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | /api/meetings/{id}/subtitles/check-terminology | 용어 점검 |
| POST | /api/meetings/{id}/subtitles/apply-terminology | 용어 일괄 교정 |
| POST | /api/meetings/{id}/subtitles/check-grammar | AI 문법 검사 |
| POST | /api/meetings/{id}/subtitles/apply-grammar | AI 문법 교정 적용 |

#### 대조 관리 (Phase 7)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | /api/meetings/{id}/subtitles/verification-stats | 대조 진행률 |
| GET | /api/meetings/{id}/subtitles/review-queue | 검토 대기열 (신뢰도순) |
| PATCH | /api/meetings/{id}/subtitles/{sid}/verify | 개별 대조 상태 변경 |
| POST | /api/meetings/{id}/subtitles/batch-verify | 일괄 대조 처리 |

#### Channels

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | /api/channels | 전체 채널 목록 (18개) |
| GET | /api/channels/status | 채널 + 실시간 방송 상태 |
| GET | /api/channels/status/stream | SSE 실시간 상태 스트림 |
| GET | /api/channels/{id} | 채널 상세 |
| POST | /api/channels/{id}/stt/start | STT 시작 |
| POST | /api/channels/{id}/stt/stop | STT 중지 |
| GET | /api/channels/{id}/stt/status | STT 상태 확인 |

#### Bills (Phase 5)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | /api/bills | 의안 목록 (committee, status, q 필터) |
| GET | /api/bills/{bill_id} | 의안 상세 (연결된 회의 포함) |
| POST | /api/bills | 의안 등록 |
| POST | /api/bills/{bill_id}/mentions | 의안-회의 연결 |
| GET | /api/bills/{bill_id}/mentions | 의안-회의 연결 목록 |

#### Search (Phase 5)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | /api/search | 통합 자막 검색 (q, date_from, date_to, speaker, limit, offset) |

#### Exports (Phase 5)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | /api/meetings/{id}/export | 회의록 내보내기 (format=markdown\|srt\|json\|official) |

#### Summaries (Phase 7)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | /api/meetings/{id}/summary | AI 요약 생성 |
| GET | /api/meetings/{id}/summary | 요약 조회 |
| DELETE | /api/meetings/{id}/summary | 요약 삭제 |

#### Dictionary (용어사전)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | /api/dictionary | 사전 목록 (category, limit, offset) |
| POST | /api/dictionary | 사전 항목 추가/수정 (upsert) |
| DELETE | /api/dictionary/{id} | 사전 항목 삭제 |

#### Councilors (의원정보)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | /api/councilors | 의원 목록 (committee, q 필터) |
| GET | /api/councilors/sync-status | 동기화 상태 |
| GET | /api/councilors/{id} | 의원 상세 |
| POST | /api/councilors/sync | 외부 API 동기화 |

#### Speakers (화자)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | /api/meetings/{id}/speakers | 화자별 발언 타임라인 |
| POST | /api/meetings/{id}/speakers/suggest | AI 화자 이름 제안 |
| POST | /api/meetings/{id}/speakers/merge | 화자 병합 |
| GET | /api/meetings/{id}/speakers/clip | 발언 영상 클립 추출 |

#### Minutes (회의록)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | /api/meetings/{id}/minutes/by-agenda | 안건별 자막 분류 |

#### Collaborative (공동편집)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | /api/meetings/{id}/edit-sessions | 편집 세션 목록 |
| POST | /api/meetings/{id}/edit-sessions | 편집 세션 시작 |
| PATCH | /api/meetings/{id}/edit-sessions/{sid} | 세션 업데이트 |
| DELETE | /api/meetings/{id}/edit-sessions/{sid} | 세션 종료 |
| GET | /api/meetings/{id}/comments | 코멘트 목록 |
| POST | /api/meetings/{id}/subtitles/{sid}/comments | 코멘트 추가 |
| PATCH | /api/meetings/{id}/comments/{cid} | 코멘트 수정 |
| DELETE | /api/meetings/{id}/comments/{cid} | 코멘트 삭제 |

#### Notifications (알림)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | /api/notifications | 알림 목록 (limit, is_read) |
| POST | /api/notifications | 알림 생성 |
| PATCH | /api/notifications/{id}/read | 읽음 처리 |

#### Agenda Files (부록파일)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | /api/meetings/{id}/agendas/{aid}/files | 파일 업로드 |
| GET | /api/meetings/{id}/agendas/{aid}/files | 파일 목록 |
| GET | /api/meetings/{id}/agendas/{aid}/files/{fid}/download | 파일 다운로드 |
| DELETE | /api/meetings/{id}/agendas/{aid}/files/{fid} | 파일 삭제 |

#### Stenography (속기록)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | /api/meetings/{id}/stenography | 속기록 목록 |
| POST | /api/meetings/{id}/stenography | 속기록 등록 |
| PATCH | /api/meetings/{id}/stenography/{rid} | 속기록 수정 |
| DELETE | /api/meetings/{id}/stenography/{rid} | 속기록 삭제 |
| GET | /api/meetings/{id}/stenography/{rid}/compare | STT 대조 |

#### Stats (통계)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | /api/stats/overview | 전체 현황 통계 |
| GET | /api/stats/speakers | 화자별 통계 |
| GET | /api/stats/meetings | 월별 회의 통계 |
| GET | /api/stats/report | 기간 리포트 (markdown/json) |

#### Admin (관리자)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | /api/admin/api-status | 외부 API 상태 (OpenAI, Deepgram, Supabase, KMS 등) |

#### Auth (Phase 11)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | /api/auth/login | 로그인 (username, password) |
| POST | /api/auth/logout | 로그아웃 |
| POST | /api/auth/refresh | 토큰 갱신 |
| GET | /api/auth/me | 현재 사용자 정보 + 권한 |

#### AI Chat (Phase 11)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | /api/ai/chat | 질문 제출 (RAG 기반 Q&A) |
| GET | /api/ai/conversations | 대화 이력 조회 |
| GET | /api/ai/conversations/{id} | 특정 대화 상세 |
| DELETE | /api/ai/conversations/{id} | 대화 삭제 |

#### Utility

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | / | 서비스 상태 |
| GET | /health | 헬스체크 |

### 7.2 WebSocket 이벤트

| 이벤트 | 방향 | 페이로드 | 설명 |
|--------|------|----------|------|
| `subtitle_created` | S→C | `{ id, start_time, end_time, text, speaker, confidence }` | 최종 확정 자막 |
| `subtitle_interim` | S→C | `{ text, is_final: false }` | 중간(partial) 자막 |
| `subtitle_corrected` | S→C | `{ id, original_text, corrected_text }` | AI 교정 결과 |

**WebSocket 경로**: `/ws/meetings/{meeting_id}/subtitles` (str 타입, UUID/채널ID 모두 지원)

### 7.3 응답 형식

**성공:**
```json
{
  "data": { ... },
  "meta": { "total": 100, "page": 1 }
}
```

**에러:**
```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "회의를 찾을 수 없습니다."
  }
}
```

---

## 8. 실시간 처리 파이프라인

### 8.1 HLS → Deepgram Streaming 파이프라인

```python
# 의사 코드 - channel_stt.py
async def start_stt(channel_id: str):
    stream_url = get_channel_stream_url(channel_id)

    # 1. HLS 마스터 플레이리스트 파싱
    media_url = parse_master_playlist(stream_url)

    # 2. Deepgram Streaming WebSocket 연결
    dg_ws = await connect_deepgram(
        model="nova-3",
        language="ko",
        smart_format=True,
        diarize=True
    )

    # 3. 3개 동시 태스크 실행
    await asyncio.gather(
        sender_task(media_url, dg_ws),     # TS 세그먼트 → Deepgram
        receiver_task(dg_ws, meeting_id),  # Deepgram → 자막 저장/브로드캐스트
        keepalive_task(dg_ws)              # 연결 유지
    )
```

### 8.2 VOD STT 파이프라인 (ffmpeg 미사용)

```python
# 의사 코드 - vod_stt_service.py
async def process_vod(meeting_id: str, vod_url: str):
    # 1. MP4 다운로드 (진행률 6-18%)
    audio_data = await download_mp4(vod_url)

    # 2. Deepgram REST API 호출 (진행률 20-92%)
    result = await stt_service.transcribe(
        audio_data, diarize=True
    )

    # 3. 화자 그룹핑
    subtitles = group_words_by_speaker(result.words)

    # 4. 용어 사전 교정 + DB 저장 (진행률 100%)
    corrected = apply_dictionary(subtitles)
    await save_subtitles(meeting_id, corrected)
```

### 8.3 실시간 자막 교정 파이프라인 (Phase 8)

```python
# 의사 코드 - subtitle_corrector.py
class SubtitleCorrectorService:
    # 3개 자막씩 10초 간격 배치 처리
    async def correction_loop():
        while running:
            batch = collect_queue(max_size=3)
            if batch:
                corrected = await openai_correct(batch)
                for item in corrected:
                    await broadcast("subtitle_corrected", item)
            await asyncio.sleep(10)
```

### 8.4 지연 시간 분석

| 단계 | 예상 시간 | 최적화 방안 |
|------|----------|------------|
| HLS 세그먼트 다운로드 | 1초 | 2단계 파싱 최적화 |
| Deepgram Streaming | 1-2초 | 실시간 스트리밍 |
| 용어 교정 | 0.1초 | 인메모리 사전 |
| 저장/브로드캐스트 | 0.2초 | 비동기 |
| **총합** | **~3초** | 목표 5초 이내 달성 |
| AI 교정 (비동기) | 10초 주기 | 배치 큐, UX 영향 없음 |

---

## 9. 테스트 전략

### 9.1 테스트 피라미드

| 레벨 | 도구 | 현황 |
|------|------|------|
| Unit | pytest (BE) / Jest (FE) | BE 309개, FE 415개 통과 |
| Integration | pytest + httpx | Critical paths 커버 |
| E2E | Playwright | 주요 사용자 흐름 |

### 9.2 테스트 시나리오

**핵심 시나리오:**
1. 채널 선택 → STT 시작 → 실시간 자막 수신
2. VOD URL 등록 → KMS 변환 → 자막 생성 → 재생
3. 키워드 검색 → 하이라이트 → 시점 이동
4. 자막 편집 → 저장 → 이력 추적
5. 대조 관리 → 검토 대기열 → 승인/플래그
6. AI 요약 생성 → 요약 조회
7. 플랫폼 셸 네비게이션 → 사이드바/브레드크럼 동작

### 9.3 품질 게이트

- [x] 단위 테스트 통과 (Frontend 415/415, Backend 309/309)
- [x] 자막 지연 < 5초
- [x] 린트 통과 (ruff / ESLint)
- [x] 타입 체크 통과
- [x] 빌드 성공

---

## 10. 배포 전략

### 10.1 환경

| 환경 | 용도 | URL |
|------|------|-----|
| Development | 로컬 개발 | localhost:3000, localhost:8000 |
| Preview | PR 미리보기 | Vercel Preview |
| Production | 실서비스 | Vercel (FE) + Railway (BE) |

### 10.2 CI/CD

```yaml
# GitHub Actions 의사 코드
on: push
jobs:
  test:
    - lint (ruff, ESLint)
    - type-check
    - unit-tests (pytest, jest)
  deploy:
    needs: test
    - railway deploy (backend)
    - vercel deploy (frontend)
```

### 10.3 환경 변수

```env
# Backend (.env)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-service-role-key
OPENAI_API_KEY=sk-...
DEEPGRAM_API_KEY=...
DATABASE_URL=postgresql://...

# Frontend (.env.local)
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
```

---

## Decision Log

| ID | 결정 | 선택 | 대안 | 이유 |
|----|------|------|------|------|
| D1 | STT 방식 | Deepgram Nova-3 Streaming | OpenAI Whisper API | 실시간 스트리밍 지원, 더 낮은 지연 |
| D2 | 프론트엔드 | Next.js 14 (App Router) | React+Vite | SSR, 사용자 선택 |
| D3 | 실시간 통신 | 네이티브 WebSocket | Socket.io | 추가 의존성 불필요 |
| D4 | 호스팅 | Railway | Cloud Run | 간편한 설정, Self-ping 지원 |
| D5 | DB | Supabase (REST API) | asyncpg 직접 연결 | Windows 한글 사용자명 SSL 이슈 |
| D6 | 상태관리 | SWR | Zustand | 서버 상태 중심, 경량 |
| D7 | VOD 처리 | MP4 직접 스트리밍 | ffmpeg 오디오 추출 | 의존성 제거, 단순화 |
| D8 | AI 교정 | GPT-5-mini 배치 큐 | 실시간 동기 처리 | 비용 효율, UX 영향 최소 |
| D9 | 레이아웃 | PlatformLayout (사이드바 기반) | 단순 Header 기반 | 8모듈 네비게이션, 확장성 |
