# AI 실시간 자막 서비스 (경기도의회)

의회 회의 생중계와 VOD 에 **AI 음성인식 자막**을 붙이는 웹 서비스입니다.
경기도의회가 실제 운영 중인 소스를 다른 지방의회가 참고·도입할 수 있도록 공개합니다.

생중계 채널의 HLS 스트림을 서버가 받아 음성을 글로 옮기고, 화자를 나누고, 의회 용어로 교정해
브라우저에 실시간으로 내보냅니다. 회의가 끝나면 같은 자막이 VOD·검색·회의록·발언 영상 클립으로 이어집니다.

> ⚠ **그대로 가져다 배포할 수는 없습니다.** 경기도의회의 영상 시스템·인증·브랜딩이 코드에 붙어 있습니다.
> 무엇을 바꿔야 하는지는 아래 [다른 의회가 도입하려면](#다른-의회가-도입하려면) 을 보세요.

---

## 무엇을 하는가

| | 기능 |
|---|---|
| **실시간 자막** | 18개 채널 HLS 스트리밍 + WebSocket 자막 스트림. 영상과 자막을 초 단위로 맞춘다 |
| **STT 파이프라인** | HLS TS 세그먼트를 짧은 창으로 잘라 OpenAI 전사 → 화자 분리 → 의회 용어 교정 |
| **VOD 자막** | MP4 에 자막 동기화, 배속 재생, 자막 클릭으로 시점 이동 |
| **자막 검색** | 전체 회의 자막 통합 검색 + 날짜·화자 필터, 뜻으로 찾기(임베딩) |
| **화자 관리** | 화자별 타임라인, AI 이름 제안, 병합, 발언 영상 클립 추출 |
| **회의록** | 안건별 자막 분류 + AI 요약 + 부록 파일 + 발간. 마크다운·SRT·JSON·HWPX 내보내기 |
| **속기 대조** | 속기록 등록 후 STT 결과와 대조, 검토 대기열, 신뢰도 기반 QA |
| **AI 도우미** | 회의 내용 질의응답, 안건별 요약, 핵심 결정·후속 조치 정리 |
| **의안 관리** | 의안 CRUD + 회의-의안 연결 + 상태 추적 |
| **접속 통계** | 접속처·시간대·회의별 이용 현황. **IP 를 저장하지 않고** 접속처 이름만 남긴다 |

주요 화면: `/live` 실시간 · `/vod` VOD 목록 · `/vod/[id]` 뷰어 · `/search` 검색 · `/ai` AI 도우미 ·
`/clips` 클립 워크벤치 · `/stenography` 속기 · `/bills` 의안 · `/visits` 접속 통계 · `/admin` 관리자

---

## 아키텍처

```
브라우저 ──HTTPS/WSS──> Traefik(Ingress)
                          ├─> web   : Next.js 14 (App Router, SSR + API 프록시)
                          └─> api   : FastAPI (REST + WebSocket + SSE)
                                        ├─> OpenAI API        (전사·교정·요약·임베딩)
                                        ├─> HLS 스트림 서버    (생중계 수집)
                                        ├─> 영상관리시스템(KMS) (VOD·속기록)
                                        └─> PostgREST ──> PostgreSQL 16 + pgvector
              clipper : 발언 영상 클립 추출 작업자 (api 와 같은 이미지)
```

| 분류 | 기술 |
|---|---|
| Frontend | Next.js 14 · TypeScript · TailwindCSS · SWR · HLS.js |
| Backend | FastAPI · Python 3.11+ · WebSocket · httpx · ffmpeg |
| Database | PostgreSQL 16 + pgvector, **PostgREST** 를 통해 접근 |
| STT / AI | OpenAI (전사·화자분리·교정·요약·임베딩) |
| 배포 | k3s 단일 노드 + Traefik (컨테이너 3종: web · api · clipper) |

**DB 접근 방식에 주의.** 백엔드는 `supabase-py` 클라이언트를 쓰지만 실제 접속 대상은
**클러스터 안의 PostgREST** 입니다(`SUPABASE_URL` 이 PostgREST 주소를 가리킴). 라이브러리 이름 때문에
Supabase 호스팅이 필요하다고 오해하기 쉬운데, **자체 PostgreSQL + PostgREST 로 완결됩니다.**
PostgREST 는 `GROUP BY` 를 못 하므로 집계는 전부 SQL 뷰로 만들어 둡니다.

---

## 시작하기

### 사전 요구사항

- Node.js 18+ · Python 3.11+ · ffmpeg
- PostgreSQL 16 (+ pgvector 확장) · PostgREST
- OpenAI API 키

### 1. 데이터베이스

`backend/migrations/` 의 SQL 을 **번호 순서대로** 적용합니다(36개. 번호는 여러 갈래에서 붙어 일부가 겹치거나 비어 있습니다).
전용 스키마(`subtitle`)와 전용 롤로 격리하는 것을 전제로 합니다 — 각 파일 앞머리의 `SET search_path` 를 참고하세요.

```bash
for f in backend/migrations/*.sql; do psql "$DATABASE_URL" -f "$f"; done
```

> 표·뷰를 추가한 뒤에는 **PostgREST 를 재시작**해야 스키마 캐시에 반영됩니다.
> 하지 않으면 새 표에 대한 요청이 조용히 404 로 떨어집니다.

### 2. 백엔드

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env      # 값을 채운다 (아래 설정 표 참조)
uvicorn app.main:app --reload --port 8000
```

`JWT_SECRET_KEY` 가 비어 있으면 **서버가 기동하지 않습니다**(토큰 위조 방지).
`openssl rand -hex 32` 로 만들어 넣으세요.

### 3. 프런트엔드

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev                # http://localhost:3000
```

### 4. 테스트

```bash
cd backend  && python -m pytest -v
cd frontend && npx jest
```

---

## 설정

값은 **환경변수로만** 줍니다. 소스나 컨테이너 이미지에 비밀을 넣지 마세요.
전체 항목은 `backend/app/core/config.py`(Pydantic Settings, 110여 개)에 있고, 자주 쓰는 것은 아래와 같습니다.

| 환경변수 | 설명 |
|---|---|
| `SUPABASE_URL` / `SUPABASE_KEY` | PostgREST 주소와 키 |
| `SUPABASE_SCHEMA` | 사용할 스키마(운영은 `subtitle`) |
| `OPENAI_API_KEY` | 전사·교정·요약·임베딩에 쓰인다 |
| `JWT_SECRET_KEY` | **필수.** 비면 기동 실패 |
| `ADMIN_QUICK_PIN` | 관리 기능 앞 PIN. 비우면 PIN 로그인이 꺼진다 |
| `CORS_ORIGINS` | 허용 출처 JSON 배열 |
| `STT_AUTO_START` | 방송 중 채널을 감지하면 자동으로 전사를 시작할지 |
| `LIVE_SYNC_TARGET_SEC` | 영상을 라이브 엣지에서 일부러 늦추는 초(자막 준비 지연을 흡수) |
| `VOD_AUTO_STT_*` | VOD 자동 자막 생성 시각·일일 상한 |
| `COUNCIL_NETWORK_RANGES` | 로그인 없이 열어 줄 내부망 IP 대역. **소스에 두지 말고 ConfigMap 으로** |
| `COUNCIL_SITE_LABELS` | 접속 통계의 접속처 이름표. 같은 원칙으로 소스 밖에 둔다 |
| `GGC_LOGIN_BASE_URL` | QR 로그인 상류. 비우면 QR 로그인이 꺼진다 |

**비용 주의** — 전사·요약이 전부 OpenAI 유료 API 입니다. 회의 한 건의 VOD 자막 생성에
수백 원~수천 원이 듭니다. 도입 전에 **월 사용 한도를 반드시 설정**하세요.

---

## 배포

`deploy/ncp/` 에 k3s 배포 스크립트가 번호 순으로 있습니다
(`10` 소스 동기화 → `20` 이미지 빌드 → `35` 배포 → `40` 검증, 되돌리기는 `90`).
**서버 주소·SSH 키 같은 배포 대상 좌표는 저장소에 두지 않습니다** — `deploy/ncp/env.sh.example`
을 복사해 `env.sh` 를 만들어 채우고, 그 파일은 `.gitignore` 로 제외됩니다.

k8s 매니페스트는 `k8s/` 에 있습니다(web·api·clipper Deployment + PostgREST + Ingress).
이미지 태그에 `latest` 를 쓰지 않고 `<YYYYMMDD>-<HHMM>-<소스해시8>` 를 씁니다 —
배포됐다는 증거를 "이미지 태그가 실제로 바뀌었는가"로 확인하기 위해서입니다.

---

## 다른 의회가 도입하려면

코어(전사 파이프라인·화자 융합·클립 추출·이름 교정·자막 동기화)는 기관 중립적입니다.
반면 **아래 네 곳은 경기도의회에 맞춰 코드에 박혀 있어 반드시 고쳐야 합니다.**

| 무엇 | 어디 | 해야 할 일 |
|---|---|---|
| **채널 정의** | `backend/app/core/channels.py` | 18개 채널(위원회명·채널 ID·HLS 스트림 주소·영상관리시스템 코드)이 정적 리스트다. 기관 채널로 교체 |
| **영상관리시스템(KMS) 연동** | `backend/app/services/kms_*.py` 등 | VOD 주소 해석·속기록·안건·일정을 경기도의회 KMS 규격으로 읽는다. 기관 시스템에 맞는 어댑터 필요 |
| **인증** | `backend/app/api/auth.py`, `frontend/src/app/login` | QR 로그인이 경기도 의정포털 앱 전용 계약이고 SSO 는 내부 서비스에 의존한다. 기관 인증으로 교체 |
| **브랜딩·데이터** | `frontend/src/app/ggc-tokens.css`, `frontend/public/ci/`, `backend/data/*.json` | 색·CI·의원 명부를 교체(경기도의회 CI 는 상표라 사용 불가 — `NOTICE` 참조) |

그 밖에 `경기도의회`·`ggc` 문자열이 화면 문구와 주석에 널리 쓰입니다.
소스에 남아 있는 **의원 성명과 발언 예시는 공개된 회의록에서 온 것**이며, 도입 시 해당 기관 데이터로 바꾸면 됩니다.

---

## 문서

| 문서 | 내용 |
|---|---|
| [서비스 명세](docs/service-spec.md) | 서비스 개요와 범위 |
| [백엔드 계층 구조](docs/architecture/backend-layering.md) | api / service / repository 역할 분리 |
| [PRD](docs/planning/01-prd.md) · [TRD](docs/planning/02-trd.md) | 제품·기술 요구사항 |
| [DB 설계](docs/planning/04-database-design.md) | 스키마 설계 |
| [디자인 시스템](docs/planning/05-design-system.md) · [화면 명세](docs/planning/06-screens.md) | UI 규약 |
| [코딩 컨벤션](docs/planning/07-coding-convention.md) | 코드 스타일 |
| `specs/` | 도메인·화면 명세(YAML) |

---

## 라이선스

[Apache License 2.0](LICENSE). 함께 배포되는 글꼴·상표·데이터에 대한 고지는 [NOTICE](NOTICE) 를 보세요.

**경기도의회 CI 와 명칭은 상표이며 이 라이선스의 대상이 아닙니다.** 도입 기관의 것으로 바꿔 주세요.
