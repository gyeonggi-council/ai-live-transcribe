# ggc subcrip 점검/개선 리포트 (2026-02-20)

## 1) Socratic 점검 절차 (요약)
아래 질문 기반으로 현재 기능을 점검했습니다.

1. 사용자가 메인에서 가장 먼저 해야 할 행동이 명확한가?
2. 로딩/오류/빈 상태에서 다음 행동(Recovery CTA)이 제공되는가?
3. 상태 텍스트가 도메인 언어(한국어)로 일관되게 제공되는가?
4. 키보드/스크린리더 관점에서 모달 사용성이 충분한가?
5. 반응형에서 주요 CTA가 우선순위대로 노출되는가?

## 2) 점검 결과와 미구현/미흡 항목
### A. 메인 화면
- [미흡] 정보 위계가 약해 첫 행동(실시간 보기 vs VOD 관리) 판단이 어려움
- [미흡] 오류 상태에서 재시도 버튼 부재
- [미흡] CTA가 고정 3열이라 작은 화면에서 밀도 높음

### B. 상태 표기
- [미흡] Recent VOD 상태가 일부 raw status 문자열(live/scheduled)로 노출될 수 있음

### C. VOD 등록 모달 접근성
- [미흡] Escape 닫기 미지원
- [미흡] 초기 포커스 미설정
- [미흡] aria-describedby / 에러 필드 연결 약함
- [미흡] 모달 오픈 중 body scroll lock 없음

## 3) 우선순위 및 구현
### P1 (즉시 적용)
1. 메인 화면 UX 개선 (정보 위계 + CTA + 반응형)
2. 오류 복구 CTA(다시 시도) 추가
3. 모달 접근성 보강(Escape/포커스/aria)
4. VOD 상태 라벨 현지화 보강

### P2 (후속)
1. 메인 KPI/운영 통계 카드 실데이터 연동
2. 모달 focus trap 완전 구현
3. E2E 회귀 자동화 확장

## 4) 실제 변경 사항
### 코드 변경
- `src/app/page.tsx`
  - 히어로 섹션 + 핵심 안내 카드 추가
  - CTA 영역 반응형 개선(1열/2열/3열)
  - 실시간/최근회의 오류 상태에 `다시 시도` 버튼 추가
  - 접근성 보강(`aria-live`, `role="alert"`, button type 명시)
- `src/components/RecentVodList.tsx`
  - 상태 뱃지 매핑 확장:
    - live → `진행 중`
    - scheduled → `예정`
    - unknown fallback → `상태 확인 필요`
- `src/components/VodRegisterModal.tsx`
  - Escape 키 닫기 추가
  - 오픈 시 URL 입력창 autofocus
  - `aria-describedby`, `aria-invalid`, `aria-describedby(error)` 연결
  - 모달 오픈 시 body scroll lock 적용

### 테스트 변경
- `src/components/__tests__/VodRegisterModal.test.tsx`
  - `aria-describedby` 연결 테스트 추가
  - Escape 키 닫기 테스트 추가
- `src/components/__tests__/RecentVodList.test.tsx`
  - scheduled/live 상태 라벨 현지화 테스트 추가

## 5) 버그 재현/원인/수정/회귀
### Bug-01: 상태 라벨 원문 노출
- 재현: Recent VOD 데이터에 `scheduled` 또는 `live` 포함 시 영어 raw 문자열 노출
- 원인: `getStatusBadge()` default에서 원문 status 반환
- 수정: 상태별 한글 라벨 매핑 추가
- 회귀 확인: 단위 테스트에 scheduled/live 케이스 추가

### Bug-02: 모달 키보드 접근성 부족
- 재현: 모달 열고 ESC 입력 시 닫히지 않음
- 원인: keydown 핸들러 미구현
- 수정: ESC 핸들러 등록 및 로딩 중 보호 조건 적용
- 회귀 확인: ESC 테스트 추가

## 6) 남은 TODO
1. 모달 focus trap(탭 순환) 완전 지원
2. 메인 대시보드 실데이터 지표(오늘 회의 수, 처리 대기 수 등) API 연동
3. 홈 페이지 통합 테스트(app 라우팅/오류 상태 상호작용) 추가
4. 접근성 자동 점검(jest-axe) 도입

## 7) 실행/테스트 방법
```bash
# 의존성 설치
npm install

# 개발 서버
npm run dev

# 린트
npm run lint

# 테스트
npm test

# 특정 컴포넌트 테스트(선택)
npm test -- VodRegisterModal
npm test -- RecentVodList
```
