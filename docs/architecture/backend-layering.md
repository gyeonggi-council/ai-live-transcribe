# 백엔드 점진 계층화 가이드 (라우터 → 서비스 → 리포지토리)

> 2026-08 클린아키텍처 점진 도입. 파일럿: `minutes.py`(템플릿), `meetings.py`, `subtitles.py`, `notifications.py`.
> 나머지 라우터는 이 문서의 체크리스트대로 커밋 단위로 이관한다.

## 1. 계층 책임

| 계층 | 위치 | 책임 | 금지 |
|------|------|------|------|
| 라우터 | `app/api/` | HTTP 파라미터, 인가(Depends), 상태코드·detail 매핑, 로깅 | `.table()` 직접 호출, 비즈니스 로직 |
| 서비스 | `app/services/` | 비즈니스 로직, 폴백 정책, 오케스트레이션 | HTTPException (예외는 ValueError/LookupError로 raise) |
| 리포지토리 | `app/repositories/` | `.table()` 호출 전담, raw dict 반환 | 예외 처리(전파만), 폴백, 로깅, HTTP |

- 서비스 관례: 함수형은 첫 인자 `supabase: Client` (기존 30여 서비스와 동일), 내부에서 `Repo(supabase)` 생성. 상태 있는 서비스는 생성자 주입 클래스 (`councilor_sync.py` 원형).
- 비즈니스 로직 없는 단순 CRUD는 서비스 생략 — 라우터가 `Depends(get_*_repository)` 직접 위임 (`app/api/deps.py`).
- 오류 매핑 관례: 서비스 `LookupError` → 라우터 404, `ValueError` → 400/422 (detail 문자열은 서비스가 소유).

## 2. 철칙 (동작 동일성)

- **select 컬럼 문자열·체인 순서를 기존 쿼리와 바이트 동일하게 유지**한다. (`tests/conftest.py`의 MockSupabaseQuery 호환 + PostgREST 동작 보존)
- **`.single()`/`.maybe_single()` 도입 금지** — mock 미지원. `.limit(1)` + `data[0] or None` 패턴 유지.
- count는 `select("id", count="exact")` 문자열 그대로.
- 핸들러는 `async def` + 동기 클라이언트 호출 유지 (threadpool 오프로딩 금지 — 동시성 순서가 변함).
- dict 흐름 유지 — response_model/도메인 dataclass 도입은 별도 트랙.
- mock 지원 체인 집합: select/eq/ilike/order/range/limit/update/insert/delete/upsert/neq/lt/in_ — 이 밖의 메서드가 필요하면 conftest 확장을 같은 커밋에 포함.

## 3. 라우터 1개 이관 체크리스트 (커밋 단위)

1. 해당 라우터의 `.table(` 호출 목록화 → 기존 repo 메서드 재사용 또는 추가 (기존 쿼리 미러링).
2. `grep -rn "patch(\"app.api.<라우터>" backend/tests/` → 패치되는 이름이 있으면 **bare-name re-export 유지 + 핸들러도 bare-name 호출** (`meetings.py`의 `# noqa: F401` 블록 참조). 모듈 경로 호출(`service.foo()`)로 바꾸면 테스트 패치가 무력화된다.
3. 조회성 단순 엔드포인트: `Depends(get_*_repository)` 직접 위임.
4. 로직 있는 엔드포인트: 서비스 함수 추출 (Client 첫 인자), HTTP 매핑은 라우터에 남긴다.
5. `pytest` 녹색 + `grep -c "\.table(" app/api/<라우터>.py` == 0 확인.

## 4. 테스트 seam

`app.dependency_overrides[get_supabase]` 하나가 라우터→서비스→리포지토리 전 계층을 관통한다
(리포지토리 provider가 `Depends(get_supabase)` 경유이기 때문). **신규 fixture를 만들지 않는다.**
리포지토리 자체는 `tests/repositories/`에서 MockSupabaseClient 직접 주입으로 계약 테스트.

## 5. 이관 현황

| 라우터 | 상태 |
|--------|------|
| minutes, meetings, subtitles, notifications | ✅ 이관 완료 (`.table()` 0건) |
| bills, search, exports, channels, admin, ai, auth, agenda_files, collaborative, councilors, dictionary, speakers, stats, stenography, websocket | ⏳ 레거시 (후속 PR) |
| `history_tracker`·`verification_service` (사실상 리포지토리 형태 서비스) | ⏳ repositories/로 후속 이관 대상 |
