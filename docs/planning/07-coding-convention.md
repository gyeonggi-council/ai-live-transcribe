# Coding Convention (코딩 컨벤션)

> 경기도의회 실시간 자막 서비스

---

## 1. 프로젝트 구조

### 1.1 전체 구조

```
project-root/
├── frontend/                 # Next.js 프론트엔드
│   ├── src/
│   │   ├── app/              # App Router 페이지
│   │   ├── components/       # React 컴포넌트
│   │   ├── hooks/            # 커스텀 훅 (8개)
│   │   ├── lib/              # API 클라이언트, Supabase
│   │   ├── config/           # 설정 (navigation.ts)
│   │   ├── contexts/         # React Context (SidebarContext, BreadcrumbContext)
│   │   ├── utils/            # 유틸리티 (highlight 등)
│   │   └── types/            # TypeScript 타입
│   ├── public/               # 정적 파일
│   └── package.json
│
├── backend/                  # FastAPI 백엔드
│   ├── app/
│   │   ├── api/              # API 라우터
│   │   ├── core/             # 설정, 보안
│   │   ├── models/           # 모델 (stub)
│   │   ├── schemas/          # Pydantic 스키마
│   │   ├── services/         # 비즈니스 로직
│   │   └── main.py           # 앱 진입점
│   ├── tests/                # 테스트
│   └── requirements.txt
│
├── specs/                    # 도메인/화면 명세
│   ├── domain/
│   └── screens/
│
├── docs/                     # 문서
│   └── planning/
│
└── docker-compose.yml        # 로컬 개발 환경
```

### 1.2 프론트엔드 구조 상세

```
frontend/src/
├── app/                      # App Router
│   ├── layout.tsx            # 루트 레이아웃
│   ├── page.tsx              # 홈 페이지 (/)
│   ├── live/
│   │   └── page.tsx          # 실시간 뷰어 (/live)
│   └── vod/
│       ├── page.tsx          # VOD 목록 (/vod)
│       └── [id]/
│           └── page.tsx      # VOD 뷰어 (/vod/:id)
│
├── components/               # UI 컴포넌트 (38개+)
│   ├── layout/               # 플랫폼 셸 (Phase 9)
│   │   ├── PlatformLayout.tsx
│   │   ├── Sidebar.tsx
│   │   ├── SidebarNavItem.tsx
│   │   ├── TopHeader.tsx
│   │   ├── Breadcrumbs.tsx
│   │   └── MeetingWorkflowNav.tsx
│   ├── Badge.tsx             # 상태 배지
│   ├── Toast.tsx             # 알림 토스트
│   ├── Header.tsx            # 레거시 (PlatformLayout으로 대체)
│   ├── HlsPlayer.tsx         # HLS 스트리밍 재생
│   ├── Mp4Player.tsx         # MP4 재생
│   ├── SubtitlePanel.tsx     # 자막 히스토리 패널
│   ├── SubtitleItem.tsx      # 자막 단일 아이템
│   ├── SubtitleOverlay.tsx   # 영상 위 플로팅 자막
│   ├── SearchInput.tsx       # 키워드 검색
│   ├── Pagination.tsx        # 페이지네이션
│   ├── ChannelSelector.tsx   # 18개 채널 선택
│   ├── VodTable.tsx          # VOD 목록 테이블
│   ├── VodRegisterModal.tsx  # VOD 등록 모달
│   ├── VideoControls.tsx     # 재생/배속 컨트롤
│   ├── ProofreadingToolbar.tsx # 교정 도구
│   ├── MeetingSummaryPanel.tsx # AI 요약 패널
│   └── ...                   # 기타 컴포넌트
│
├── hooks/                    # 커스텀 훅 (8개)
│   ├── useChannels.ts        # 채널 목록 조회 (SWR)
│   ├── useChannelStatus.ts   # 채널 방송 상태 (SSE)
│   ├── useLiveMeeting.ts     # 실시간 회의 (SWR)
│   ├── useRecentVods.ts      # 최근 VOD 목록 (SWR)
│   ├── useSubtitleWebSocket.ts # WebSocket 실시간 자막
│   ├── useSubtitleSearch.ts  # 자막 검색 + 하이라이트
│   ├── useVodList.ts         # VOD 목록 페이지네이션 (SWR)
│   └── useSubtitleSync.ts    # 영상-자막 동기화
│
├── lib/
│   ├── api.ts                # API 클라이언트
│   └── supabase.ts           # Supabase 클라이언트
│
├── config/
│   └── navigation.ts         # 8모듈 메뉴 트리 + 브레드크럼 맵
│
├── contexts/
│   ├── SidebarContext.tsx     # 사이드바 상태 (접기/펼치기)
│   └── BreadcrumbContext.tsx  # 동적 브레드크럼 제목
│
├── utils/
│   └── highlight.ts          # 검색 하이라이트
│
└── types/
    └── index.ts              # 공통 타입
```

### 1.3 백엔드 구조 상세

```
backend/app/
├── api/                      # REST API + WebSocket (19 파일)
│   ├── meetings.py           # 회의 CRUD + KMS URL 자동변환
│   ├── subtitles.py          # 자막 조회/검색/교정/대조
│   ├── channels.py           # 채널 목록/상태/STT 제어
│   ├── bills.py              # 의안 CRUD + 회의 연결
│   ├── search.py             # 통합 자막 검색
│   ├── exports.py            # 회의록 내보내기 (4형식)
│   ├── websocket.py          # 실시간 자막 WS
│   ├── admin.py              # 관리자 API
│   ├── speakers.py           # 화자 관리
│   └── ...                   # 기타 API
│
├── core/
│   ├── config.py             # Settings (Pydantic)
│   ├── database.py           # Supabase REST 클라이언트
│   └── channels.py           # 18개 HLS 채널 정적 설정
│
├── models/                   # 모델 (stub, ORM 미사용)
│
├── schemas/                  # Pydantic 스키마
│
├── services/                 # 비즈니스 로직 (25 파일)
│   ├── deepgram_stt.py       # Deepgram Streaming STT
│   ├── channel_stt.py        # 채널별 STT 관리
│   ├── channel_status.py     # 채널 방송 상태 조회
│   ├── hls_parser.py         # HLS 2단계 파싱
│   ├── kms_vod_resolver.py   # KMS VOD URL → MP4 변환
│   ├── vod_stt_service.py    # VOD STT 파이프라인
│   ├── subtitle_corrector.py # OpenAI 실시간 자막 교정
│   ├── summary_service.py    # AI 회의 요약
│   ├── grammar_checker.py    # AI 문법 검사
│   ├── verification_service.py # 대조관리
│   ├── dictionary.py         # 용어 사전
│   ├── speaker_utils.py      # 화자 식별 유틸리티
│   ├── transcript_export.py  # 회의록 내보내기
│   ├── pii_masking.py        # 개인정보 마스킹
│   ├── history_tracker.py    # 자막 변경 이력
│   └── auto_stt.py           # 방송 채널 자동 STT 시작
│
├── tasks/                    # 백그라운드 태스크
│
└── main.py                   # FastAPI 앱
```

---

## 2. 네이밍 규칙

### 2.1 파일명

| 구분 | 규칙 | 예시 |
|------|------|------|
| React 컴포넌트 | PascalCase | `VideoPlayer.tsx` |
| 훅 | camelCase (use 접두사) | `useWebSocket.ts` |
| 유틸리티 | camelCase | `formatTime.ts` |
| Python 모듈 | snake_case | `stream_processor.py` |
| 테스트 | `*.test.ts`, `test_*.py` | `api.test.ts`, `test_meetings.py` |

### 2.2 변수/함수명

**TypeScript/JavaScript:**
```typescript
// 변수: camelCase
const meetingId = 'xxx';
const isLoading = false;

// 함수: camelCase, 동사로 시작
function fetchMeetings() { ... }
function handleClick() { ... }

// 상수: UPPER_SNAKE_CASE
const MAX_RETRY_COUNT = 3;
const API_BASE_URL = 'https://...';

// 컴포넌트: PascalCase
function VideoPlayer() { ... }

// 타입/인터페이스: PascalCase
interface Meeting { ... }
type SubtitleStatus = 'loading' | 'ready';
```

**Python:**
```python
# 변수: snake_case
meeting_id = 'xxx'
is_processing = False

# 함수: snake_case
def fetch_meetings():
    pass

async def process_stream():
    pass

# 상수: UPPER_SNAKE_CASE
MAX_RETRY_COUNT = 3
DEEPGRAM_MODEL = 'nova-3'

# 클래스: PascalCase
class StreamProcessor:
    pass

# Private: 밑줄 접두사
def _internal_method():
    pass
```

### 2.3 컴포넌트 Props

```typescript
// Props 인터페이스: 컴포넌트명 + Props
interface VideoPlayerProps {
  streamUrl: string;
  onTimeUpdate?: (time: number) => void;
}

function VideoPlayer({ streamUrl, onTimeUpdate }: VideoPlayerProps) {
  // ...
}
```

---

## 3. TypeScript 규칙

### 3.1 타입 정의

```typescript
// 인터페이스 사용 (객체 타입)
interface Meeting {
  id: string;
  title: string;
  meetingDate: string;
  status: MeetingStatus;
}

// 타입 별칭 (유니온, 간단한 타입)
type MeetingStatus = 'scheduled' | 'live' | 'processing' | 'ended';

// 제네릭 사용
interface ApiResponse<T> {
  data: T;
  meta?: {
    total: number;
    page: number;
  };
}

// 타입 가드
function isMeeting(obj: unknown): obj is Meeting {
  return typeof obj === 'object' && obj !== null && 'id' in obj;
}
```

### 3.2 Strict Mode

```json
// tsconfig.json
{
  "compilerOptions": {
    "strict": true,
    "noImplicitAny": true,
    "strictNullChecks": true
  }
}
```

### 3.3 Import 순서

```typescript
// 1. React/Next.js
import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';

// 2. 외부 라이브러리
import useSWR from 'swr';
import clsx from 'clsx';

// 3. 내부 모듈 (절대 경로)
import { api } from '@/lib/api';
import { Meeting } from '@/types';

// 4. 컴포넌트
import { Button } from '@/components/ui/Button';

// 5. 스타일 (있는 경우)
import styles from './styles.module.css';
```

---

## 4. React 규칙

### 4.1 컴포넌트 구조

```typescript
// 컴포넌트 파일 구조
import { useState, useCallback } from 'react';

interface VideoPlayerProps {
  streamUrl: string;
  autoPlay?: boolean;
}

export function VideoPlayer({ streamUrl, autoPlay = false }: VideoPlayerProps) {
  // 1. 훅
  const [isPlaying, setIsPlaying] = useState(false);

  // 2. 핸들러
  const handlePlay = useCallback(() => {
    setIsPlaying(true);
  }, []);

  // 3. 사이드 이펙트
  useEffect(() => {
    // ...
  }, [streamUrl]);

  // 4. 렌더링
  return (
    <div className="video-player">
      {/* ... */}
    </div>
  );
}
```

### 4.2 훅 규칙

```typescript
// 커스텀 훅: use 접두사
function useWebSocket(url: string) {
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    const ws = new WebSocket(url);
    ws.onopen = () => setIsConnected(true);
    ws.onclose = () => setIsConnected(false);

    return () => ws.close();
  }, [url]);

  return { isConnected };
}
```

### 4.3 조건부 렌더링

```typescript
// 삼항 연산자 (간단한 경우)
{isLoading ? <Spinner /> : <Content />}

// && 연산자 (조건부 표시)
{isError && <ErrorMessage />}

// 분기가 복잡한 경우 함수 분리
function renderContent() {
  if (isLoading) return <Spinner />;
  if (isError) return <ErrorMessage />;
  return <Content data={data} />;
}

return <div>{renderContent()}</div>;
```

---

## 5. Python/FastAPI 규칙

### 5.1 API 엔드포인트

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from app.core.database import get_supabase

router = APIRouter(prefix="/api/meetings", tags=["meetings"])

@router.get("/")
async def get_meetings(
    status: Optional[str] = None,
    limit: int = Query(default=20, le=100),
    offset: int = 0,
    supabase=Depends(get_supabase),
):
    """회의 목록 조회 (Supabase REST)"""
    query = supabase.table("meetings").select("*")
    if status:
        query = query.eq("status", status)
    result = query.order("meeting_date", desc=True).range(offset, offset + limit - 1).execute()
    return {"data": result.data, "meta": {"total": len(result.data)}}

@router.get("/{meeting_id}")
async def get_meeting(meeting_id: str, supabase=Depends(get_supabase)):
    """회의 상세 조회"""
    result = supabase.table("meetings").select("*").eq("id", meeting_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return {"data": result.data[0]}
```

### 5.2 Pydantic 스키마

```python
from pydantic import BaseModel, Field
from datetime import date
from typing import Optional

class MeetingBase(BaseModel):
    title: str = Field(..., min_length=2, max_length=255)
    meeting_date: date

class MeetingCreate(MeetingBase):
    vod_url: Optional[str] = None

class MeetingResponse(MeetingBase):
    id: str
    status: str
    duration_seconds: Optional[int] = None

    class Config:
        from_attributes = True
```

### 5.3 인증 미들웨어 패턴 (Phase 11)

```python
from fastapi import Depends, HTTPException, status
from typing import Optional
import jwt
from datetime import datetime, timedelta

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key")
ALGORITHM = "HS256"

async def get_current_user(
    authorization: Optional[str] = Header(None)
) -> dict:
    """JWT 토큰 검증 및 사용자 정보 반환"""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing"
        )

    try:
        token = authorization.split(" ")[1]  # "Bearer {token}"
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except (jwt.InvalidTokenError, IndexError):
        raise HTTPException(status_code=401, detail="Invalid token")

    return {"user_id": user_id, "role": payload.get("role")}

def require_role(*allowed_roles: str):
    """특정 역할만 접근 가능한 엔드포인트 보호"""
    async def role_checker(current_user: dict = Depends(get_current_user)):
        if current_user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required role: {', '.join(allowed_roles)}"
            )
        return current_user
    return role_checker

# 사용 예시
@router.post("/api/meetings")
async def create_meeting(
    meeting: MeetingCreate,
    current_user: dict = Depends(require_role("MeetingManager", "Admin"))
):
    """VOD 등록 (MeetingManager/Admin만 가능)"""
    # 구현...
    pass
```

### 5.4 AI 서비스 패턴 (Phase 11)

```python
from openai import AsyncOpenAI
from typing import Optional

class AIService:
    """OpenAI GPT-5-mini 기반 AI 서비스"""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    async def query_rag(
        self,
        question: str,
        context_docs: list[str],
        model: str = "gpt-5-mini",
        max_tokens: int = 500
    ) -> dict:
        """RAG 기반 Q&A"""
        system_prompt = """당신은 경기도의회 의회 운영을 지원하는 AI 어시스턴트입니다.
        제공된 회의록, 의안, 의원 정보를 바탕으로 정확하고 전문적인 답변을 해주세요."""

        context_text = "\n\n".join(context_docs)
        user_message = f"""컨텍스트:
{context_text}

질문: {question}"""

        response = await self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            max_tokens=max_tokens,
            temperature=0.7
        )

        return {
            "answer": response.choices[0].message.content,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens
            }
        }

    async def summarize_meeting(
        self,
        subtitles: list[dict],
        model: str = "gpt-5-mini"
    ) -> dict:
        """회의 자막 요약"""
        subtitle_text = "\n".join([s["text"] for s in subtitles])

        response = await self.client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "경기도의회 회의 자막을 분석하여 요약해주세요."
                },
                {
                    "role": "user",
                    "content": f"다음 회의 자막을 요약해주세요:\n\n{subtitle_text}"
                }
            ],
            max_tokens=500
        )

        return {
            "summary": response.choices[0].message.content,
            "model": model
        }

# 사용 예시
@router.post("/api/ai/chat")
async def ai_chat(
    request: ChatRequest,
    current_user: Optional[dict] = Depends(get_current_user)
):
    """AI 질문-답변"""
    ai_service = AIService()
    # 1. 벡터 검색으로 관련 문서 검색 (향후)
    # 2. RAG 기반 응답
    response = await ai_service.query_rag(
        question=request.question,
        context_docs=["문서1", "문서2"]
    )
    # 3. DB 저장
    return {"response": response["answer"]}
```

### 5.5 서비스 패턴 (Supabase REST)

```python
from app.core.database import get_supabase

# 서비스 함수 패턴 (Supabase REST API 사용)
async def get_meetings(supabase, status=None, limit=20, offset=0):
    """Supabase REST를 통한 회의 목록 조회"""
    query = supabase.table("meetings").select("*")
    if status:
        query = query.eq("status", status)
    result = query.order("meeting_date", desc=True) \
                  .range(offset, offset + limit - 1) \
                  .execute()
    return result.data

async def create_meeting(supabase, meeting_data: dict):
    """회의 생성"""
    result = supabase.table("meetings").insert(meeting_data).execute()
    return result.data[0] if result.data else None
```

> **참고**: asyncpg/SQLAlchemy 미사용. Supabase REST API를 `get_supabase()` FastAPI 의존성으로 주입.

---

## 6. Git 컨벤션

### 6.1 브랜치 전략

```
main              # 프로덕션 브랜치
├── develop       # 개발 브랜치
│   ├── feature/실시간-자막        # 기능 브랜치
│   ├── feature/키워드-검색
│   └── fix/websocket-연결-오류    # 버그 수정 브랜치
```

### 6.2 커밋 메시지

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Type:**
- `feat`: 새 기능
- `fix`: 버그 수정
- `docs`: 문서 수정
- `style`: 코드 포맷팅
- `refactor`: 리팩토링
- `test`: 테스트 추가
- `chore`: 빌드, 설정 변경

**예시:**
```
feat(subtitle): 실시간 자막 WebSocket 연동

- HLS 스트림에서 Deepgram Streaming STT 연결
- 채널별 STT 관리 (sender/receiver/keepalive)
- WebSocket 브로드캐스트 구현

Closes #12
```

### 6.3 PR 규칙

- 제목: 커밋 메시지와 동일한 형식
- 본문: 변경 사항 요약, 테스트 방법
- 리뷰어: 최소 1명
- 머지 조건: 테스트 통과, 리뷰 승인

---

## 7. 코드 품질

### 7.1 Lint 설정

**ESLint (Frontend):**
```json
{
  "extends": [
    "next/core-web-vitals",
    "plugin:@typescript-eslint/recommended"
  ],
  "rules": {
    "no-unused-vars": "error",
    "@typescript-eslint/no-explicit-any": "error"
  }
}
```

**Ruff (Backend):**
```toml
# pyproject.toml
[tool.ruff]
line-length = 100
select = ["E", "F", "I", "N", "W"]

[tool.ruff.isort]
known-first-party = ["app"]
```

### 7.2 포맷터

- Frontend: Prettier
- Backend: Black + isort

### 7.3 Pre-commit Hook

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: frontend-lint
        name: Frontend Lint
        entry: npm run lint
        language: system
        files: ^frontend/

      - id: backend-lint
        name: Backend Lint
        entry: ruff check
        language: system
        files: ^backend/
```

---

## 8. 주석 규칙

### 8.1 필요한 경우에만 주석

```typescript
// ❌ 불필요한 주석
// 회의 ID
const meetingId = meeting.id;

// ✅ 필요한 주석: 비즈니스 로직 설명
// HLS 세그먼트는 Deepgram Streaming WSS로 실시간 전송됨
const CHUNK_DURATION = 10;
```

### 8.2 TODO/FIXME

```typescript
// TODO: v2에서 화자 분리 기능 추가
// FIXME: WebSocket 재연결 시 자막 중복 발생
```

---

## 9. 테스트 규칙

### 9.1 테스트 파일 위치

```
frontend/
├── src/
│   └── components/
│       └── VideoPlayer.tsx
└── tests/
    └── components/
        └── VideoPlayer.test.tsx

backend/
├── app/
│   └── services/
│       └── deepgram_stt.py
└── tests/
    └── services/
        └── test_deepgram_stt.py
```

### 9.2 테스트 네이밍

```typescript
// TypeScript
describe('VideoPlayer', () => {
  it('should render video element with correct source', () => {});
  it('should call onTimeUpdate when video time changes', () => {});
});
```

```python
# Python
class TestDeepgramStt:
    async def test_transcribe_audio_returns_text(self):
        pass

    async def test_transcribe_with_diarize_returns_speakers(self):
        pass
```

---

## 10. 환경 변수

### 10.1 네이밍

```env
# Frontend (.env.local)
NEXT_PUBLIC_API_URL=https://api.example.com
NEXT_PUBLIC_WS_URL=wss://api.example.com

# Backend (.env)
OPENAI_API_KEY=sk-...
DATABASE_URL=postgresql://...
CORS_ORIGINS=https://example.com
```

### 10.2 접근 방법

```typescript
// Frontend
const apiUrl = process.env.NEXT_PUBLIC_API_URL;
```

```python
# Backend
from app.core.config import settings

api_key = settings.OPENAI_API_KEY
```
