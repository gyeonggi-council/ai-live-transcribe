# 통합 편입 설계서 — 실시간 자막·전자회의록(ggc-subtitle)

> **P2-④ 설계 정본 · 2026-07-16 작성.** 경기도의회 AI 의정플랫폼 통합구축 실행계획(`ggc_ai_platform/docs/10-통합구축-실행계획.md`) P2-④ 산출물.
> 이 시스템의 1차 목표는 **재구축이 아니라 통합 규약 편입**이다 — Phase 0~12로 완성된 기능 자산(실시간/VOD STT·속기 편집기·대조관리·AI 요약·RAG)을 보존하면서, 통합성 게이트 6축 중 편입 가능한 축부터 순차 통과시킨다.
> 관련 정본: 게이트 정의 `docs/10` §1 · SSO 계약 `docs/11` · 의원 연동 계약 `docs/04` · 디자인 `docs/03`+`docs/08` · 데이터 표준 `docs/06` · 스택 표준 `docs/09`. 레지스트리 등록: `db/core/V6__register_subtitle.sql`(SUBTITLE, integrated=FALSE).
> **이 문서는 설계서다 — 코드 변경 없음.** 각 절의 이행 절차는 후속 작업 태스크의 근거가 된다.

---

## 0. 현행 요약 (통합 관점 인벤토리)

| 축 | 현행 | 통합 관점 진단 |
|---|---|---|
| 스택 | Next.js 14(App Router, Tailwind v3) + FastAPI(Python 3.11) | 표준(eGovFrame Boot 5 + React 19/Vite)과 불일치 — §5 특례 검토 대상 |
| DB | **별도 Supabase 프로젝트**(통합 허브 `flepxywvrcqpkmycefmw` 아님), 테이블 21종, 마이그레이션 `backend/migrations/001~019`(수기 SQL, 대시보드 적용) | 통합 허브·온프레미스 `ggc_council` 어느 쪽에도 미편입, DDL이 루트 `db/`에 미등재 — §4 |
| 인증 | 자체 JWT(users/user_sessions, bcrypt + HS256 24h), 역할 6종 | core.principals 미연결 — §2 |
| 디자인 | 자체 GAC 팔레트(`gac-dark-blue #3C5D89` 등, tailwind.config), PlatformLayout 셸(사이드바 8모듈 + TopHeader 48px) | ggc-tokens v1.1 미적용, `.ggc-utility-bar` 없음 — §3 |
| 의원 데이터 | 자체 `councilors` 테이블 — 경기도의회 공개 API(`ggcmemrecinfoview`, mi_code 키)에서 `POST /api/councilors/sync`로 동기화. `councilor_voiceprints`(음성 샘플, 의원당 1개)가 FK 참조 | **의원 정본 중복(G5 위반)** — 정본은 hr → `core.v_members` — §1 |
| 의안 데이터 | 자체 `bills`(자유 등록) + `bill_mentions`(의안-회의-자막 연결) | 의안 정본은 BIMS(G5) — bills는 로컬 재구축에 해당 — §6 |
| 위원회 표기 | councilors.committees(JSONB 자유 텍스트), bills.committee(VARCHAR 자유 텍스트), users.assigned_committee(VARCHAR) | `core.committees`(16개) 미참조 — G5 위반 부속 항목 |
| 배포 | Vercel(FE) + Railway(BE) + Supabase | 외부 클라우드 3원 구성 — 온프레미스 편입 시 네트워크 제약 — §4 |
| 레지스트리 | `core.systems` SUBTITLE 등록 완료(2026-07-16, integrated=FALSE) | G6 부분 통과 — 포털 노출·스위처 등재 잔여 |

---

## 1. G5 — 의원 정본 전환: 자체 councilors → core.v_members 참조

### 1.1 현행 구조와 문제

- `councilors`(마이그레이션 002·009·010): id(UUID), name, party, district, committee, committees(JSONB), role, mi_code(경기도의회 공개 API 동기화 키), profile_image_url, active, synced_at.
- 동기화: `councilor_sync.py`가 경기도의회 공개 API를 호출해 mi_code 기준 upsert, 응답에 없는 의원은 `active=false` 비활성화(삭제 아님).
- 소비처: 화자 식별(diarize known_speakers·speaker_cue_tracker 위원회 명부), 속기 AI 화자 매칭, CouncilorPicker UI, RAG 컨텍스트.
- `councilor_voiceprints`(018·019): councilor_id FK(**ON DELETE CASCADE**), councilor_name, committee, sample_b64(16kHz wav base64 ≈250KB), is_chair. **UNIQUE(councilor_id)** — 의원당 1개.
- 문제: 의원 인사 정보의 정본은 hr → `core.member_details`/`v_members`(제12대 167명, 정당·선거구 100%)인데, 이 시스템은 별도 공개 API를 정본처럼 사용 — 동일 인물이 두 체계에서 다른 식별자(mi_code vs principal_id)를 가지며, 인사관리에서 확정한 위원회 배정·임기 변경이 반영되지 않는다.

### 1.2 참조 방법 후보 비교 (별도 Supabase 프로젝트 → 뷰 직접 조회 불가)

| 후보 | 방식 | 장점 | 단점 | 판정 |
|---|---|---|---|---|
| **A. 허브 공개 API** | hr(또는 포털)이 의원 조회 공개 API를 신설하고 subtitle이 호출 | 실시간성, DB 결합 없음 | **해당 API가 아직 없다**(docs/04 §2 "구축 시" 전제). hr 측 신규 개발 필요 — subtitle 편입이 타 시스템 개발에 종속. 인증·키 관리 추가 | 보류(API 생기면 B의 소스 교체만으로 전환 가능) |
| **B. 읽기전용 배치 동기화** ★권고 | FastAPI 백엔드가 허브 Postgres에 **읽기전용 계정**으로 접속해 `core.v_members`를 주기(예: 1일 1회 + 수동 트리거) SELECT → 로컬 councilors를 캐시로 갱신. ggc-platform의 SYNC_CORE_MASTER, BIMS 검증 배치와 동일 패턴(docs/04 §2) | **기존 sync 구조를 소스만 교체**(GGC 공개 API → core.v_members)해 재사용 — 코드 변경 최소. 화자 식별 등 소비처는 무변경. 허브 장애 시에도 캐시로 서비스 지속(STT 실시간성에 유리) | 최대 1주기 지연(의원 데이터 변경 빈도상 허용), 허브 접속 자격증명 관리(Railway env) | **단기 채택** |
| **C. DB 편입 후 뷰 직결** | §4의 통합 DB 편입(subtitle 스키마) 완료 후 `core.v_members` 직접 조인 | 지연 0, 캐시 테이블 소멸 가능 | G2 편입이 선행조건(온프레미스 컷오버와 연동 — §4에서 단계적 접근 권고) | **장기 목표**(B는 C로 가는 무손실 경유지) |

**권고: B(즉시) → C(G2 편입 시).** B의 핵심 설계 — councilors를 "정본"에서 **"core.v_members의 로컬 읽기 캐시"로 강등**하고, 이를 테이블 COMMENT와 코드 주석에 명시한다. 캐시 강등 이후 councilors에 대한 로컬 편집 API(POST/PATCH)는 차단(동기화가 유일한 쓰기 경로).

### 1.3 재키잉(re-keying) 설계

- councilors에 `principal_id UUID` 컬럼 추가(UNIQUE, NULL 허용 — 과도기). 동기화 시 `core.v_members.principal_id`를 저장하고, **upsert 키를 mi_code → principal_id로 교체**한다.
- 최초 전환 시 기존 행 매핑: 이름+선거구로 `core.v_members`와 대사(167명 전수) → 매칭 실패분은 수동 확인 목록 출력(동명이인 주의 — docs/11 §5.3과 동일 원칙). mi_code는 과도기 참조용으로 보존 후 C 단계에서 폐기.
- 컬럼 매핑: name/party/district ← v_members 동일 필드, committee/committees ← 위원회 조인 결과(**자유 텍스트 금지 — core.committees 명칭·id 사용**, docs/04 §3-3), role ← is_chair(위원장 여부), profile_image_url ← photo_url. 공개 API에만 있는 필드(office_number 등)는 v_members 부재 시 보존 유지.

### 1.4 councilor_voiceprints FK 재설계

음성 샘플은 **이 시스템이 정본인 고유 데이터**다(hr에 없음). 캐시로 강등된 councilors에 CASCADE로 매달아 두면 캐시 재구축·행 삭제 시 실측 등록한 voiceprint가 소실된다.

1. `councilor_voiceprints`에 `principal_id UUID NOT NULL` 컬럼 추가(백필: councilors.principal_id 경유). **UNIQUE(councilor_id) → UNIQUE(principal_id)로 교체** — 의원당 1개 규약을 정본 식별자 기준으로.
2. `councilor_id` FK는 `ON DELETE CASCADE → ON DELETE SET NULL`(또는 FK 제거)로 완화 — 캐시 조작이 voiceprint를 지우지 못하게.
3. 서비스 계층(`voiceprint_service.py`·diarize `_get_known_speakers`)의 조회 키를 principal_id로 교체. councilor_name(diarize known_speaker_names 표기)·committee(후보 선택)·is_chair(위원장 지정)는 동기화 시 v_members 값으로 자동 갱신하는 반정규화 컬럼으로 유지.
4. C 단계(DB 편입) 도달 시: councilor_voiceprints.principal_id에 `core.principals(id)` 실 FK 부여, councilors 캐시 테이블 폐기 검토.

### 1.5 이행 절차·회귀 체크리스트

1. 마이그레이션(스키마 SQL은 §4.4에 따라 루트 `db/subtitle/`에 작성): principal_id 컬럼 2개 + UNIQUE 교체 + FK 완화.
2. 허브에 읽기전용 계정 발급(portal의 Hikari read-only 패턴 준용 — `default_transaction_read_only=on`), Railway env `HUB_DB_URL` 추가.
3. `councilor_sync.py` 소스 교체 + 최초 전수 대사 스크립트(매칭 리포트 출력).
4. 회귀 체크: ① 의원 수 167 일치 ② voiceprint 전 건 principal_id 백필·유실 0 ③ diarize known_speaker 실측(`verify_openai_stt.py --known-speaker`) ④ speaker_cue_tracker 위원회 명부 해석 ⑤ CouncilorPicker·/admin/voiceprints UI ⑥ 위원장(is_chair) 표시.

---

## 2. G3 — 인증 전환: 자체 JWT → SSO (docs/11 계약)

### 2.1 현행과 목표

- 현행: `users`/`user_sessions`(012), bcrypt + python-jose HS256 **24시간** 토큰, localStorage 저장. 역할 6종, `require_role`/`optional_auth` 미들웨어, 조회 API는 비로그인 허용.
- 목표: 포털=OIDC IdP(Authorization Code + PKCE), `sub`=core.principals.id, 역할은 `roles` 클레임의 SUBTITLE 코드만 신뢰(docs/11 §2·§3). 자체 회원 테이블 신설 금지 원칙 대비, 이 시스템의 users는 **기존 자산**이므로 과도기 병존 후 principal_accounts로 흡수한다.

### 2.2 역할 매핑 (users.role → principal_accounts.local_role)

| 현행 역할 | local_role(SUBTITLE) | principal_type | 비고 |
|---|---|---|---|
| anonymous | (매핑 없음) | — | 비로그인 조회 — SSO 후에도 조회 API는 무인증 유지(`optional_auth` 존치) |
| staff | `staff` | staff | 일반직원 |
| committee_staff | `committee_staff` | staff | **committee_id 클레임 필수** — 현행 users.assigned_committee(자유 텍스트)를 core.committees.id로 정규화해 매핑 |
| meeting_manager | `meeting_manager` | staff | 회의담당 |
| stenographer | `stenographer` | staff | 속기사 |
| admin | `admin` | admin | 시스템 관리자 |

규칙(docs/11 §3): 메뉴·행위 세부 인가는 클레임에 넣지 않는다 — `require_role` 미들웨어와 `navigation.ts` roles 필터는 로컬 역할 기준으로 존치하고, 역할의 **출처만** JWT 자체 발급 → ID 토큰 roles 클레임으로 바꾼다.

### 2.3 RP 아키텍처 (FastAPI 특수성)

표준 이행 경로(docs/11 §6)는 Spring Security `oauth2Login`을 전제하나 이 시스템은 Python이다. 권고 구성:

- **Next.js 프론트가 OIDC RP**: Authorization Code + PKCE로 포털 IdP 로그인 → 토큰 수신. AuthContext/useAuth 구조 유지(토큰 소스만 교체). 토큰 보관은 localStorage → **httpOnly 쿠키(Route Handler 경유)로 상향** 권고(현행 localStorage는 XSS 노출면).
- **FastAPI는 리소스 서버**: IdP JWKS(RS256) 공개키로 액세스 토큰 서명 검증 + `roles["SUBTITLE"]` 추출. `auth_middleware.py`의 검증 함수만 교체하면 `require_role`/`optional_auth` 서명은 그대로 — 라우터 17개 무변경.
- 세션·수명은 docs/11 §4 준수: 액세스/ID 30분(현행 24h에서 단축), 리프레시 8h 회전식, IdP 로그아웃 전파(RP-Initiated Logout).

### 2.4 과도기 규칙 (docs/11 §7 적용)

1. **지금(포털 IdP 완성 전)**: 자체 JWT 유지 + **principal 매핑만 준비** — users 전 계정을 `core.principals`(staff/admin) + `core.principal_accounts(system_code='SUBTITLE', local_id=users.id::text, local_role=users.role)`로 등록(허브 적용, integration V2 자동 매핑 패턴·이메일 기준 대사). Supabase Auth 신설 금지 조항은 자체 JWT라 해당 없음 — 단 **users에 신규 기능 의존을 늘리지 않는다**.
2. **전환 판정 조건**: SSO 완성 판정(파일럿 + 포털 IdP + 최소 2개 시스템 RP) 후 P2-④ 후속으로 RP 전환. 그 전까지 UI에 "통합 로그인" 문구 금지.
3. **전환 후**: users.password_hash 폐기(로그인 경로 제거), users는 로컬 프로필(표시명·환경설정)로 축소 또는 폐기. user_sessions 폐기. 감사 로그(성공·실패·잠금)는 IdP 이벤트로 이관.
4. 계정 병합: 동일 인물이 타 시스템 계정을 이미 가진 경우 `db/README.md` 규칙 3 절차로 단일 principal에 재연결.

---

## 3. G4 — 디자인 편입: ggc-tokens v1.1 + 유틸리티 바

### 3.1 원칙

기존 **사이드바 8모듈 + TopHeader 48px 셸(PlatformLayout) 구조는 유지**한다 — docs/08의 GNB 64px/LNB 256px 업무 셸로의 개편은 이번 범위가 아니다(재구축 아님 원칙). 편입 대상은 ① 색·폰트 토큰 정렬 ② 유틸리티 바 ③ 상태 배지 3가지다.

### 3.2 적용 방안 (Next.js 14 + Tailwind v3)

1. **토큰 로드**: `design/ggc-tokens.css` v1.1 + `design/ggc-components.css`를 저장소에 복사(타 앱과 동일하게 사본 이식) → `globals.css` 최상단에서 이 순서로 import.
2. **Tailwind 브리지**: `tailwind.config.js`의 GAC 팔레트를 `--ggc-*` 변수 참조로 교체 —
   `gac-dark-blue #3C5D89` → `var(--ggc-primary)`(#3C5D93 — BIMS 본문 CI 예외는 BIMS 한정이므로 이 시스템은 공통 토큰으로 정규화), `navy-*` 계열 → primary-dark/deep/light, `blue-50` 선택 배경 → `--ggc-primary-light`. 폰트는 Pretendard GOV(`--ggc-font`)로 통일.
3. **유틸리티 바**: PlatformLayout 최상단(TopHeader 위)에 `.ggc-utility-bar` 삽입 — 좌측 기관명, 우측 통합서비스 스위처. 이 앱은 외부 배포(Vercel)이므로 내부망 시스템(입법역량지원 :8080, BIMS :9090)은 `span.disabled` + "(내부망)" 표기(docs/03 §2.1 내부망 규칙). 스위처에 자기 항목 "실시간 자막"을 active로. **역방향 등재**: 의사일정·하이패스·인사관리·현안분석·포털 스위처에 `https://ggcsubai.vercel.app` 추가(각 저장소 작업 — 조정자에 요청).
4. **배지 통일**: Badge 컴포넌트(Live/VOD/verification_status/속기 status)를 `.ggc-badge` 알약 패턴으로 — live=`--info`, verified/approved=`--approved`, flagged/rejected=`--rejected`, draft/unverified=`--pending` 계열 매핑.
5. **레이아웃 인접 정렬(선택)**: 사이드바 active `bg-blue-50 text-primary` → `--ggc-primary-light`+`--ggc-primary`, 카드 그림자 → 1px 보더(docs/08 §1.4) — 셸 구조 변경 없이 스타일 값만.
6. 회귀: Jest 스냅샷·레이아웃 테스트(SidebarContext 등 모킹 규약 유지), Playwright E2E 스모크.

---

## 4. G2 — DB 통합 편입: 별도 Supabase → 통합 DB subtitle 스키마

### 4.1 데이터 특성 분석

| 항목 | 실측/추정 | 편입 영향 |
|---|---|---|
| subtitles 쓰기 부하 | 라이브 자막 1건/3~5초/채널 + interim 브로드캐스트, 회의당 2,000~5,000행. 상임위 다채널 동시(최대 18채널) 시 초당 수 건 insert + WS 팬아웃 | 통합 허브(의사일정·하이패스·hr·issue 공유)에 **상시 실시간 쓰기 부하를 추가**하는 유일한 시스템이 됨 — 격리 근거 |
| 저장 볼륨 | subtitles·stenography_lines 누적형(회의록 영구 보존), councilor_voiceprints base64 ≈250KB×167명 ≈ 42MB | 스토리지 자체는 크지 않음 — 쓰기 패턴이 쟁점 |
| 접근 방식 | 백엔드가 Supabase **REST(PostgREST)** 사용(asyncpg 미사용 — Windows 한글 사용자명 SSL 이슈) | 허브 편입 시 허브 PostgREST에 subtitle 스키마 노출 필요. 온프레미스 편입 시 PostgREST 부재 → 드라이버 교체(httpx→psycopg) 작업 발생 |
| 네트워크 | 백엔드가 Railway(외부 클라우드) | **온프레미스 `ggc_council`에 Railway에서 접속 불가**(인바운드 차단 전제) — DB 편입은 STT 워커의 온프레미스 재배치와 동시에만 성립 |

### 4.2 판단: 단계적 편입 (즉시 이관 비권고)

**1단계(현행 유지 + 정본화·연합)**: 별도 Supabase 유지(core.systems integrated=FALSE 상태 지속). 대신 ① 스키마 DDL을 루트 `db/subtitle/V1__subtitle_baseline.sql`(001~019 통합본)로 **버전관리 편입**(G2의 "모든 DDL이 db/에 존재" 요건 선행 충족 — docs/06 표준: 주제영역 매핑·COMMENT 정비 포함) ② §1의 배치 동기화·§2의 principal 매핑으로 데이터 연합.

**2단계(본편입)**: P4 인프라(HCI·3망) 확보 및 온프레미스 컷오버 시점에 `ggc_council.subtitle` 스키마로 이관 — STT 워커(§5)의 온프레미스 이전과 한 패키지로. 이관 절차는 `db/README.md` 5) `pg_dump --schema` 패턴. 이때 DB 접근 계층을 PostgREST REST → 직결(psycopg)로 교체하고, §1은 C 단계(뷰 직결)로 승격.

**중간 허브 이관(별도 Supabase → 통합 허브 Supabase)은 비권고**: 실시간 쓰기 부하를 공유 허브에 올리는 리스크 대비, 어차피 온프레미스 최종 이행이 예정돼 있어 이중 이관 비용만 발생한다. 예외 — 온프레미스 일정이 장기 지연되고 §1-C(뷰 직결)의 실익이 커지면 재검토.

### 4.3 편입 시 스키마 설계 원칙

- 스키마명 `subtitle`, 전 테이블 이관(21종). `users`/`user_sessions`는 §2 전환 완료 시 제외(또는 로컬 프로필만).
- `councilors` 캐시는 C 단계에서 폐기 검토, `councilor_voiceprints.principal_id` → `core.principals` 실 FK.
- `bills`는 §6 결과에 따라 BIMS 참조 캐시로 축소.
- 자유 텍스트 위원회 컬럼 전부 `core.committees` 참조로 정규화.

---

## 5. 스택 특례 권고안 (G1 — docs/09 개정 판단 자료, 결론 미결)

### 5.1 쟁점 분리: STT 파이프라인 ≠ 웹/API 계층

이 시스템의 G1 판단은 두 층을 분리해야 성립한다.

**① STT 파이프라인(실시간 미디어 워커) — FastAPI/Python 전용 워커 존치가 합리적이라고 판단(권고).**

| 관점 | 근거 |
|---|---|
| 기술 특성 | persistent ffmpeg 서브프로세스(HLS TS→PCM16 디코딩), OpenAI Realtime **WebSocket 상시 연결**, 롤링 PCM 버퍼(~12초), 채널별 상태머신(speaker_cue_tracker) — 장기 실행 stateful 워커로, 요청-응답 웹앱(eGovFrame/Servlet) 모델과 근본적으로 다름 |
| 생태계 | OpenAI SDK·오디오 처리·difflib 퍼지 매칭 등 Python 자연 자산. JVM 재작성 시 등가 라이브러리 검증 비용 + 실측 튜닝(Phase 12에서 실제 국회 영상으로 검증한 파이프라인) 전면 재현 필요 |
| 재작성 비용 대비 편익 | services 25종 + 검증 스크립트, 표준화 편익은 "언어 통일" 외 없음 — STT 워커는 사용자 UI·업무 트랜잭션이 없어 표준화의 원 목적(운영·유지보수 단일화, 디자인·인증 통일)과 접점이 작음 |
| 선례 정합 | docs/09 표준 자체가 LLM 방향에서 "사전학습+RAG, Claude 헤드리스 오케스트레이션(Python 아닌 CLI지만 외부 프로세스)"을 인정 — 특수 워커의 프로세스 분리는 기존 설계 문법과 정합 |

특례 성립 조건(제안): 워커는 **API 표면을 최소화**(STT 시작/중지/상태 + 자막 WS)하고, 자막 데이터는 통합 DB(2단계 이후 subtitle 스키마)에 기록하며, 인증은 §2 계약을 따른다. 즉 "특례는 프로세스·언어에 한정, 데이터·인증·디자인 규약은 예외 없음".

**② 웹/API 계층(Next.js 14 프론트 + FastAPI REST 19라우터) — 별도 트랙으로 분리, 이번 편입 범위에서 제외(권고).**

| 선택지 | 비용 | 편익 |
|---|---|---|
| (a) 존치(특례 확대) | 0. 단 플랫폼 내 Next.js 계열이 subtitle만 잔존하게 될 때 운영 이원화 지속 | 기능 자산(컴포넌트 45+·테스트 578+309) 무손실 |
| (b) 표준 전환(eGovFrame+React 19) | 라우터 19종·화면 16종·컴포넌트 45종 재작성 — P2 확산군(hr·schedule·hipass) 1개 시스템 이상의 물량. 속기 편집기(가상 스크롤·단축키)·실시간 WS 뷰어 등 고상호작용 UI의 회귀 위험 | G1 완전 통과, 운영 스택 단일화 |
| (c) 절충: 프론트만 React 19/Vite 전환 + FastAPI를 REST 계약(`/api/v1`, 1-base 페이징)만 표준 정렬 | 중간 | 부분 통과 — 언어 이원(Python) 잔존 |

**권고**: 이번 P2-④는 G2~G6 편입에 집중하고, 웹/API 계층의 (a)/(b)/(c) 선택은 **P3(BIMS JSP→React) 완료 후 재평가** — 그 시점에 조직의 React 전환 역량·템플릿 성숙도가 검증돼 있어 (b)/(c)의 실측 견적이 가능하다. STT 워커 특례(①)는 그와 독립적으로 docs/09 §5 미결 항목에 "확정" 반영을 제안한다. **최종 결정은 조정자(docs/09 개정) 몫으로 미결로 남긴다.**

---

## 6. BIMS 연계 — 자체 bills와 의안 정본의 관계 정리

### 6.1 현행과 문제

- `bills`(003): bill_number(자유 텍스트, 예 "제2026-123호"), title, proposer, committee(자유 텍스트), status 4종(received/reviewing/decided/promulgated — BIMS 생애주기와 별개 축약본). 수기 등록(POST /api/bills).
- `bill_mentions`: 의안↔회의↔자막 구간 연결 — **이 시스템 고유의 가치 데이터**(어느 회의 몇 분 몇 초에 논의됐는지).
- 문제: 의안 생애주기의 정본은 BIMS(G5 검증표), 소비는 읽기전용 API(`X-API-KEY`)다. 현행 bills는 정본의 로컬 재구축이며 의안번호·상태가 BIMS와 대사되지 않는다.

### 6.2 전환 설계: bills = BIMS 참조 캐시, bill_mentions = 이 시스템 정본

1. `bills`에 `bims_bill_id`(BIMS 측 의안 PK) 컬럼 추가. **신규 의안 등록 UI를 "수기 입력" → "BIMS 검색-연결"로 교체**: 속기·회의 담당자가 BIMS 읽기전용 API로 의안 검색 → 선택 시 로컬 bills에 메타데이터 캐시 upsert(bims_bill_id 키) + bill_mentions 연결. 수기 등록은 BIMS 미등재 안건(보고·청원 등) 한정 폴백으로 존치(`bims_bill_id IS NULL`로 구분).
2. **대사 배치**: 주기적으로 bims_bill_id 보유 건의 title·proposer·committee·상태를 BIMS API로 재조회해 캐시 갱신 — status는 BIMS 생애주기를 로컬 4종으로 축약 매핑(매핑표는 구현 시 BIMS 상태전이 정의 기준으로 확정). 기존 수기 등록분은 의안번호·제목 유사 매칭으로 1회 백필(매칭 리포트 출력, 미매칭은 수동).
3. proposer는 §1 전환 후 `core.v_members` 표기와 정합 검증(BIMS 목표모델 검증과 동일 원칙 — docs/04 §2), committee는 core.committees 명칭으로 정규화.
4. 네트워크 참고: BIMS는 내부망(:9090)이므로 Railway 백엔드에서 직접 호출 불가할 수 있음 — 과도기에는 대사 배치를 내부에서 실행(수동/조정자 PC)하거나 포털 경유 프록시 검토, 본편입(§4 2단계, 온프레미스 재배치) 후 자연 해소.

---

## 7. 게이트 자체 평가 + 편입 작업 순서

### 7.1 G1~G6 현황 자체 평가 (2026-07-16)

| 게이트 | 상태 | 근거 | 통과 경로 |
|---|---|---|---|
| G1 단일 스택 | ✗ 미통과 | Next.js 14 + FastAPI | STT 워커 특례 확정(§5-①) + 웹/API 계층 P3 후 재평가(§5-②) — docs/09 개정 대기 |
| G2 단일 DB | ✗ 미통과 | 별도 Supabase, DDL 루트 db/ 미등재 | 1단계: db/subtitle/V1 베이스라인 정본화 → 2단계: 온프레미스 컷오버 시 본편입(§4) |
| G3 단일 인증 | ✗ 미통과 | 자체 JWT(users) | principal 매핑 선행 → SSO 완성 판정 후 OIDC RP 전환(§2) |
| G4 단일 디자인 | ✗ 미통과(셸 구조는 보유) | 자체 GAC 팔레트, 유틸바 없음. PlatformLayout 셸·역할별 메뉴는 이미 구조적으로 정합 | 토큰 브리지 + 유틸바 + 배지(§3) — 즉시 가능 |
| G5 정본 데이터 계약 | ✗ 미통과 | councilors 자체 정본화, bills 자유 등록, 위원회 자유 텍스트 | 의원: 배치 동기화 B안(§1), 의안: BIMS 참조 캐시(§6), 위원회: core.committees 정규화 |
| G6 포털 허브 연동 | △ 부분 통과 | core.systems SUBTITLE 등록 완료(V6, 온프레미스 적용·허브 대기) | 허브에 V6 적용 + 포털 대시보드 상태 노출 + 전 시스템 스위처 등재(§3-3) |

### 7.2 편입 작업 순서 (위험 낮은 것부터)

| 순서 | 작업 | 게이트 | 위험 | 비고 |
|---|---|---|---|---|
| 1 | 디자인 편입: 토큰·유틸바·배지 | G4 | 낮음(UI 한정, 테스트 자산 풍부) | 코드 변경 첫 착수 대상 |
| 2 | G6 마무리: 허브 V6 적용·스위처 상호 등재·포털 노출 | G6 | 낮음(등록·설정성) | 타 저장소 스위처 등재는 조정자 배분 |
| 3 | 스키마 정본화: `db/subtitle/V1__subtitle_baseline.sql`(001~019 통합 + COMMENT·주제영역 정비) | G2(1단계) | 낮음(문서화 성격, 런타임 무영향) | 루트 db/에만 추가 — 분업 원칙 |
| 4 | 의원 정본 전환: principal_id 재키잉 + voiceprint FK 완화 + 동기화 소스 교체 | G5 | 중간(화자 식별 회귀 — §1.5 체크리스트) | 허브 읽기전용 계정 발급 필요 |
| 5 | principal 매핑 준비: users → principal_accounts(SUBTITLE) 등록 | G3(과도기) | 낮음(허브 등록만, 앱 무변경) | 4와 병행 가능 |
| 6 | BIMS 연계: bims_bill_id + 검색-연결 UI + 대사 배치 | G5 | 중간(BIMS API 접근 경로 — §6.4) | 내부망 제약 확인 선행 |
| 7 | SSO RP 전환 | G3 | 중상(인증 전면 교체) | **선행조건**: SSO 완성 판정(파일럿+포털 IdP+2개 RP) |
| 8 | DB 본편입 + STT 워커 온프레미스 재배치 + REST→직결 교체 | G2(2단계)·G5(C) | 높음(인프라 종속) | **선행조건**: P4 인프라. 컷오버 계획 별도 수립 |
| 9 | 웹/API 계층 표준 전환 여부 확정 | G1 | — | P3 완료 후 재평가, docs/09 개정으로 확정(§5) |

### 7.3 조정자 확인 요청 사항

1. STT 워커 특례(§5-①)의 docs/09 §5 반영 여부 — 본 문서를 판단 자료로 제출.
2. 허브 읽기전용 계정 발급 정책(§1.5-2)과 users→principal 매핑 SQL의 db/ 등재 위치(core vs integration).
3. BIMS API의 외부(Railway) 접근 가능 여부(§6.4) — 불가 시 대사 배치 실행 위치 결정.
