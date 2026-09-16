# Feature Tasks (기능별 세부 태스크)

> Phase 0~10 완료, Phase 11 개선 진행중

---

## Phase 11: AI 어시스턴트 + 권한 체계 + 속기 UX 개선

상태: **계획 수립** (2026-03-19)

### Phase 11 Feature Map

| 영역 | 기능 | 중요도 | 난이도 | 의존성 |
|------|------|--------|--------|--------|
| **메인화면** | 생중계 현황 대시보드 (F1) | 높음 | 중 | 없음 |
| **메인화면** | AI 실시간 요약 카드 (F2) | 높음 | 중 | 백엔드 AI 요약 |
| **AI** | AI 대화형 Q&A 패널 (F3) | 높음 | 중 | DB (ai_conversations) |
| **AI** | 회의록 AI 요약 조회 (F4) | 중 | 낮음 | 기존 기능 활용 |
| **속기** | 텍스트 중심 편집기 (F5) | 높음 | 중 | 속기 라인 편집 API |
| **속기** | 음성-텍스트 통합 편집 (F6) | 높음 | 중 | 음성 플레이어 + STT 참고 |
| **속기** | AI 자동 교정 (F7) | 중 | 중 | GPT-5-mini |
| **속기** | 수정 이력 추적 (F8) | 중 | 낮음 | stenography_edit_history |
| **속기** | 수정 UI 편의성 (F9) | 중 | 낮음 | 인라인 편집 |
| **권한** | 비로그인 공개 조회 (F10) | 높음 | 중 | 로그인 시스템 |
| **권한** | 역할 기반 메뉴 제어 (F11) | 높음 | 낮음 | users, user_sessions |
| **권한** | 위원회 필터 기본값 (F12) | 중 | 낮음 | users.assigned_committee |

---

## Phase 5: 고도화 기능 태스크

> /socrates 결과 기반 - 회의록시스템 PPT 분석 → 5개 기능 도출
> 상태: **전체 완료** (2026-02-12)

---

## 우선순위

| 순위 | 기능 | 난이도 | 의존성 |
|------|------|--------|--------|
| 1 | 화자 식별 (Speaker Diarization) | 중 | 없음 (Deepgram diarize 이미 존재) |
| 2 | 자막 수동 교정 (Subtitle Editor) | 중 | 없음 |
| 3 | 통합검색 강화 (Global Search) | 중 | 없음 |
| 4 | 의안-회의록 연결 (Bill Linking) | 상 | DB 스키마 추가 |
| 5 | 공식 회의록 형식 (Official Export) | 중 | 기능 1 (화자 식별) |

---

## Feature 1: 화자 식별 (Speaker Diarization)

### 배경
- `channel_stt.py:347`에 이미 `diarize=true` WebSocket 파라미터 사용 중
- `channel_stt.py:150` `_group_words_by_speaker()` 로직 구현 완료
- `subtitles` 테이블에 `speaker VARCHAR(100)` 컬럼 이미 존재
- **문제**: `vod_stt_service.py:162`에서 `speaker: None` 하드코딩

### [x] Task 1-1: VOD STT에 diarization 활성화
**파일**: `backend/app/services/deepgram_stt.py`
- `transcribe()` 메서드에 `diarize: bool = False` 파라미터 추가
- Deepgram REST API 호출 시 `diarize=true` 쿼리 파라미터 추가
- 응답 JSON에서 `words[].speaker` 필드 파싱
- `TranscriptionResult`에 `words: list[dict]` 필드 추가 (speaker 정보 포함)

### [x] Task 1-2: 화자 그룹핑 유틸리티 추출
**파일**: `backend/app/services/speaker_utils.py` (신규)
- `channel_stt.py:150`의 `_group_words_by_speaker()` 로직을 공통 유틸로 추출
- `channel_stt.py`와 `vod_stt_service.py` 모두에서 사용

### [x] Task 1-3: VodSttService에서 화자 정보 저장
**파일**: `backend/app/services/vod_stt_service.py`
- `stt_service.transcribe(diarize=True)` 호출
- 결과에서 speaker별 그룹핑 → `"화자 1"`, `"화자 2"` 형태로 저장
- `all_subtitles` 리스트에 `speaker` 필드 반영

### [x] Task 1-4: 프론트엔드 화자 표시 개선
**파일**: `frontend/src/components/SubtitleItem.tsx`, `SubtitlePanel.tsx`
- 화자별 색상 구분 (화자 1 = 파랑, 화자 2 = 초록, ...)
- 화자 라벨 스타일링 (뱃지 형태)
- 같은 화자 연속 발언 시 라벨 생략 옵션

---

## Feature 2: 자막 수동 교정 (Subtitle Editor)

### 배경
- 사용자 선택: **별도 편집 페이지** (`/vod/{id}/edit`)
- AI STT 결과의 오인식 수동 교정 필요
- 교정 이력 추적 선택적

### [x] Task 2-1: 자막 수정 API
**파일**: `backend/app/api/subtitles.py`
- `PATCH /api/meetings/{meeting_id}/subtitles/{subtitle_id}` 추가
  - body: `{ text?: string, speaker?: string }`
  - 변경된 필드만 업데이트
  - `updated_at` 자동 갱신

### [x] Task 2-2: 자막 배치 수정 API
**파일**: `backend/app/api/subtitles.py`
- `PATCH /api/meetings/{meeting_id}/subtitles` (배치)
  - body: `{ items: [{ id, text?, speaker? }] }`
  - 여러 자막을 한 번에 수정 (저장 버튼 1회 클릭)

### [x] Task 2-3: 자막 편집 페이지 (프론트엔드)
**파일**: `frontend/src/app/vod/[id]/edit/page.tsx` (신규)
- 좌: 비디오 플레이어 (Mp4Player 재사용)
- 우: 편집 가능한 자막 목록
  - 각 자막 행: 시간 | 화자(드롭다운) | 텍스트(textarea)
  - 현재 재생 위치 → 해당 자막 하이라이트
  - 자막 클릭 → 해당 시점으로 이동
- 상단: "저장" 버튼 (변경된 항목만 PATCH)
- 변경 감지: 저장 전 이탈 시 경고

### [x] Task 2-4: VOD 뷰어에서 편집 페이지 링크
**파일**: `frontend/src/app/vod/[id]/page.tsx`
- 자막이 있을 때 "자막 편집" 버튼 추가
- 클릭 → `/vod/{id}/edit`로 이동

### [x] Task 2-5: API 클라이언트 함수 추가
**파일**: `frontend/src/lib/api.ts`
- `updateSubtitle(meetingId, subtitleId, data)` 추가
- `updateSubtitlesBatch(meetingId, items)` 추가

---

## Feature 3: 통합검색 강화 (Global Search)

### 배경
- 현재: 회의 내 자막 검색만 가능 (`/api/meetings/{id}/subtitles/search`)
- 필요: 전체 회의 통합 검색 + 날짜/화자/주제 필터

### [x] Task 3-1: 통합 검색 API
**파일**: `backend/app/api/search.py` (신규)
- `GET /api/search` 엔드포인트
  - 쿼리: `q` (검색어), `date_from`, `date_to`, `speaker`, `limit`, `offset`
  - subtitles + meetings 조인 검색
  - 결과: `{ items: [{ subtitle, meeting_title, meeting_date }], total }`
- Supabase REST로 구현 (ILIKE + JOIN)

### [x] Task 3-2: 검색 라우터 등록
**파일**: `backend/app/main.py`
- `search_router` import 및 `app.include_router()` 추가

### [x] Task 3-3: 통합 검색 페이지 (프론트엔드)
**파일**: `frontend/src/app/search/page.tsx` (신규)
- 검색 입력 + 필터 (날짜 범위, 화자)
- 검색 결과 목록: 회의명 + 자막 텍스트(하이라이트) + 시간
- 결과 클릭 → `/vod/{id}?t={start_time}`으로 이동
- 페이지네이션

### [x] Task 3-4: Header에 통합 검색 추가
**파일**: `frontend/src/components/Header.tsx`
- 검색 아이콘/버튼 추가
- 클릭 → `/search`로 이동

### [x] Task 3-5: API 클라이언트 함수
**파일**: `frontend/src/lib/api.ts`
- `globalSearch(params)` 함수 추가

---

## Feature 4: 의안-회의록 연결 (Bill Linking)

### 배경
- 회의록시스템 PPT의 핵심: 의안별 심사 이력 추적
- 의안 → 어느 회의에서 논의 → 해당 자막 구간 연결

### [x] Task 4-1: DB 스키마 - bills 테이블
**파일**: `backend/migrations/003_bills.sql` (신규)
```sql
CREATE TABLE bills (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  bill_number VARCHAR(50) NOT NULL,     -- 의안번호
  title VARCHAR(500) NOT NULL,           -- 의안명
  proposer VARCHAR(200),                 -- 제안자
  committee VARCHAR(200),                -- 소관 위원회
  status VARCHAR(50),                    -- 상태 (접수/심사/의결/공포)
  proposed_date DATE,                    -- 제안일
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE bill_mentions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  bill_id UUID REFERENCES bills(id),
  meeting_id UUID REFERENCES meetings(id),
  subtitle_id UUID REFERENCES subtitles(id),
  start_time FLOAT,
  end_time FLOAT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### [x] Task 4-2: 의안 CRUD API
**파일**: `backend/app/api/bills.py` (신규)
- `GET /api/bills` - 의안 목록 (필터: committee, status)
- `GET /api/bills/{id}` - 의안 상세 + 관련 회의록 구간
- `POST /api/bills` - 의안 등록
- `POST /api/bills/{id}/mentions` - 의안-자막 구간 연결

### [x] Task 4-3: 의안 관리 페이지 (프론트엔드)
**파일**: `frontend/src/app/bills/page.tsx` (신규)
- 의안 목록 + 검색/필터
- 의안 클릭 → 관련 회의록 구간 목록
- 회의록 구간 클릭 → VOD 뷰어 해당 시점 이동

---

## Feature 5: 공식 회의록 형식 (Official Export)

### 배경
- 현재 `transcript_export.py`에 마크다운/텍스트/JSON 내보내기 존재
- 필요: 경기도의회 공식 회의록 형식 (화자 구분 + 시간 + 포맷)
- Feature 1 (화자 식별) 완료 후 구현 권장

### [x] Task 5-1: 공식 회의록 포맷 생성
**파일**: `backend/app/services/transcript_export.py`
- `export_official_format()` 함수 추가
- 형식:
  ```
  제XXX회 경기도의회 제X차 [위원회명]
  일시: 2026-02-11

  ○ 위원장 [이름]
    안건 심사를 시작하겠습니다.

  ○ [이름] 위원
    본 의안에 대해 질의하겠습니다...
  ```
- PDF 출력 옵션 (reportlab 또는 weasyprint)

### [x] Task 5-2: 내보내기 API 확장
**파일**: `backend/app/api/exports.py`
- `GET /api/meetings/{id}/export?format=official` 추가
- Content-Type: `text/plain` 또는 `application/pdf`

### [x] Task 5-3: 프론트엔드 내보내기 버튼 확장
**파일**: `frontend/src/components/TranscriptExportButton.tsx`
- "공식 회의록 형식" 옵션 추가

---

## 구현 순서 권장

```
Phase 5-A (화자 식별 + 자막 교정)
  ├── Feature 1: Task 1-1 → 1-2 → 1-3 → 1-4
  └── Feature 2: Task 2-1 → 2-2 → 2-3 → 2-4 → 2-5
      (Feature 1과 병렬 가능)

Phase 5-B (검색 + 내보내기)
  ├── Feature 3: Task 3-1 → 3-2 → 3-3 → 3-4 → 3-5
  └── Feature 5: Task 5-1 → 5-2 → 5-3
      (Feature 1 완료 후)

Phase 5-C (의안 연결)
  └── Feature 4: Task 4-1 → 4-2 → 4-3
      (Feature 3 완료 후가 이상적)
```

---

## 수정 파일 요약

| 구분 | 파일 | 신규/수정 |
|------|------|-----------|
| F1 | `backend/app/services/deepgram_stt.py` | 수정 |
| F1 | `backend/app/services/speaker_utils.py` | 신규 |
| F1 | `backend/app/services/vod_stt_service.py` | 수정 |
| F1 | `backend/app/services/channel_stt.py` | 수정 (공통 유틸 사용) |
| F1 | `frontend/src/components/SubtitleItem.tsx` | 수정 |
| F2 | `backend/app/api/subtitles.py` | 수정 |
| F2 | `frontend/src/app/vod/[id]/edit/page.tsx` | 신규 |
| F2 | `frontend/src/app/vod/[id]/page.tsx` | 수정 |
| F2 | `frontend/src/lib/api.ts` | 수정 |
| F3 | `backend/app/api/search.py` | 신규 |
| F3 | `backend/app/main.py` | 수정 |
| F3 | `frontend/src/app/search/page.tsx` | 신규 |
| F3 | `frontend/src/components/Header.tsx` | 수정 |
| F4 | `backend/migrations/003_bills.sql` | 신규 |
| F4 | `backend/app/api/bills.py` | 신규 |
| F4 | `frontend/src/app/bills/page.tsx` | 신규 |
| F5 | `backend/app/services/transcript_export.py` | 수정 |
| F5 | `backend/app/api/exports.py` | 수정 |
| F5 | `frontend/src/components/TranscriptExportButton.tsx` | 수정 |
