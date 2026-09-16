# GGC Subtitle Frontend

## 실행

```bash
npm install
cp .env.local.example .env.local
npm run dev
```

- 기본 접속: `http://localhost:3000/live`
- 백엔드 WS/API는 `.env.local`의 `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL` 기준

## 저지연(목표 체감 500ms) 스트리밍 자막 파이프라인

이번 변경으로 다음을 적용함:

- STT 결과를 `partial(미확정)` / `final(확정)` 분리 처리
- partial은 즉시 렌더링 (`subtitle_interim`, `stt_partial`)
- final은 확정 자막 리스트에 반영 (`subtitle_created`, `stt_final`)
- 깜빡임 최소화: partial은 별도 라인에 유지, final 도착 시만 교체
- 지연 로깅 추가
  - `server_received_at` (오디오 수신 시각)
  - partial/final 도착 시각
  - e2e ms 계산 로그 (`[Latency] partial/final`)
- 브라우저 마이크 → WebSocket 업링크 훅 추가 (`useMicSttStream`)

## 마이크 스트리밍 사용

`/live` 상단의 **마이크 스트림 시작** 버튼으로 브라우저 마이크 오디오를 서버 WebSocket으로 전송.

- 업링크 엔드포인트: `NEXT_PUBLIC_STT_STREAM_WS_URL + /ws/stt/stream?meeting_id=...`
- 오디오 전송 포맷: `audio/webm;codecs=opus`, 250ms chunk
- 메타 전송: `audio_meta(seq, sent_at, size)` + binary audio chunk

## Fallback Mock 모드

서버 STT 키/연결이 없는 개발 환경에서는:

```env
NEXT_PUBLIC_STT_MOCK_MODE=true
```

- 실제 WS 대신 가짜 partial/final 스트림 생성
- UI/검색/오버레이 동작 검증 가능

## 테스트

```bash
npm run type-check
npm test -- useSubtitleWebSocket
npm run build
```

## 라이브 영상-자막 동기화 (2026-09-03 정정)

옛 "지연 최적화 체크리스트"(표시 지연 200~400ms, `stt_partial` 주기 등)는 Deepgram 스트리밍
시절 것이라 지웠다. 지금 라이브는 **12초 창 배치 전사**라 partial 이벤트가 없고, 영상을
라이브 엣지에서 일부러 N초 늦춰 자막이 항상 먼저 준비되게 한 뒤 `videoClock` 게이팅으로 맞춘다.

- 영상 지연 목표: **서버가 준다**(api 파드 env `LIVE_SYNC_TARGET_SEC` → 채널 상태 응답 `sync_target_sec`, 2026-09-14) —
  `src/utils/liveSync.ts` `pickSyncTarget` 이 `?sync=N` > 서버 > 빌드 기본(`HlsPlayer.tsx` `LIVE_SYNC_TARGET_SEC` 20, 폴백) 순으로 고른다.
  재빌드 없이 env 로 조정하고, 값의 근거는 `ceil(sync_need_p99 + 1)`(정본 `docs/live-sync-eval-2026-09.md`)
- 현장 실험: `/live?channel=ch14&sync=20` — 그 세션만 20초로(전체 새로고침 필요)
- 진단: 브라우저 콘솔 `window.__syncDebug` → `syncTarget`·`syncTargetSource`(query/server/default) · `hlsTargetLatency`(스톨 뒤에도 목표와 같아야) ·
  `readyLagP95`·`edgeLagP95`·`syncNeedP95`(서버 실측) · `decodeMarginSec`·`edgeLagObserved`(브라우저 역산, 서버 edge_lag 와 ±1초) ·
  `hlsLatency` · `hlsWindowSec`(원본 재생목록 깊이) · `lateCount`(영상보다 늦게 온 자막 수, 0 유지가 목표)
- `NEXT_PUBLIC_SUBTITLE_DISPLAY_DELAY_MS`(기본 5000) 는 동기화 실패 시 폴백일 뿐이다
- 설계 설명은 저장소 루트 `CLAUDE.md` "라이브 영상-자막 동기화" 절
