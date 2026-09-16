# 이관 사양 — 실시간 자막 서비스 → 업무플랫폼 검증환경(NCP PoC)

> ggc-deploy 스킬 Phase 1 산출물. 신규 서비스 기획이 아니라 **가동 중 서비스의 이관**이므로
> 기능 사양은 기존 `docs/planning/` 정본을 따르고, 여기에는 이관 요구사항만 둔다.
> 결정 근거: 2026-08-17 사용자 확정 (플랜 승인).

## 무엇을 해결하나

Vercel(프론트)·Railway(백엔드)·Supabase(DB) 외부 SaaS 의존을 전부 제거하고
자체 서버(poc-app k3s + poc-db PostgreSQL 16)에서 운영한다.

## 요구사항

| ID | 요구사항 | 검증(게이트) |
|---|---|---|
| REQ-01 | 프론트(Next.js standalone)·백엔드(FastAPI) 컨테이너가 k3s `ggc-poc` 네임스페이스에서 가동 | 40-verify [2][3] G-ROLLOUT |
| REQ-02 | `https://<poc-app 공인 IP>/transcribe` 경로 기반 노출, 문서 허브(`/`)와 공존 | 40-verify [8][12] G-EXTERNAL·G-HUB-ALIVE |
| REQ-03 | 실시간 자막 WS(`/transcribe/ws/...`)가 Traefik 경유로 동작 | 40-verify [8] WS 101 |
| REQ-04 | STT 파이프라인 전제(ffmpeg 9.0 정적 바이너리) 충족 | 40-verify [5] |
| REQ-05 | DB_BACKEND 스위치: Phase A = supabase, Phase B = postgres(poc-db `ggcpoc.subtitle`) | 40-verify [11] |
| REQ-06 | Supabase 스키마+데이터 전량 이관, 테이블별 행수 100% 대사 | 31-import 대사 리포트 |
| REQ-07 | STT 동시 처리 1~2채널, 수동 시작 운영 (`STT_AUTO_START=false` 고정) | 40-verify [11] + E2E |
| REQ-08 | 실채널 E2E: 방송 채널 1개 5~10분 STT → 자막 표시 + `subtitle.subtitles` 적재 | P5 게이트 (수동) |
| REQ-09 | 접속은 내부(의회망) + 담당자 PC 만 — ACG 443 허용 출발지 한정 | H1·H2 + G-EXTERNAL |
| REQ-10 | 비밀값(Supabase·DB·JWT·PIN·OpenAI)은 Secret/TTY 로만 취급, Git·이미지·로그 불기록 | G-NOSECRET |

## 자동 결정 사항 (스킬 표준)

- 네임스페이스 `ggc-poc` · 경로 `/transcribe` (금지 경로 `/`·`/api`·`/login`·`/docs` 회피 확인)
- 이미지 태그 `YYYYMMDD-HHMM-<소스해시8>` · latest 금지 · HSTS 금지 · 2단계 노출
- DB 는 기존 `ggcpoc` 안 `subtitle` 스키마 격리, 전용 롤 `ggc_subtitle`
- OpenAI 는 기존 공유 Secret `openai-api` 참조 (복제 금지) — 과금 상한은 담당자의
  OpenAI 월 하드리밋(H4)이 최종 방어선

## 사용자·공개 범위

- 사용자: 의회 내부(속기·의정 담당 직원, 필요 시 의원실). 외부 공개 안 함.
- 상시 가동 전환(월 ~30만 원)은 2026-08-17 사용자 승인.

## 트랙 분업 (충돌 방지)

- **코드 트랙**(별도 세션): `backend/app/**`, `frontend/src/**` — DB_BACKEND DI 전환, strict TDD
- **인프라 트랙**(이 작업): `backend/Dockerfile`, `frontend/Dockerfile`, `k8s/**`, `deploy/ncp/**`, `docs/handoffs/**`
- 코드 트랙에 요청한 계약: 마이그레이션 SQL 스키마 비한정(search_path), 라이브 스키마 베이스라인 인식,
  `DATABASE_URL` 드라이버 표기 확인(psycopg3), `stt_max_channels`(기본 2) 설정 추가
