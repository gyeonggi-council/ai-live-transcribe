/**
 * 라이브 영상-자막 동기화 보조 (순수 함수 — 테스트 가능).
 *
 * 영상은 라이브 엣지에서 일부러 N초 뒤로 재생한다(HlsPlayer의 liveSyncDuration).
 * 그 N은 자막이 항상 영상보다 먼저 준비되도록 "자막 준비 지연 + 여유"로 정한다.
 * 현장에서 값을 바꿔 가며 체험할 수 있도록 URL 쿼리 `?sync=N` 으로 세션 한정
 * 덮어쓰기를 허용한다(재빌드 불필요). 8~60초로 클램프.
 */

export const SYNC_TARGET_MIN_SEC = 8;
export const SYNC_TARGET_MAX_SEC = 60;

/** `?sync=N` 문자열을 목표 지연(초)으로 해석한다. 비정상이면 fallback. */
export function resolveSyncTargetSec(param: string | null | undefined, fallback: number): number {
  if (param == null || param === '') return fallback;
  const n = Number(param);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(SYNC_TARGET_MAX_SEC, Math.max(SYNC_TARGET_MIN_SEC, Math.round(n)));
}

/** URL search 문자열(`?a=1&sync=20`)에서 목표 지연을 읽는다. */
export function syncTargetFromSearch(search: string | undefined, fallback: number): number {
  if (!search) return fallback;
  try {
    return resolveSyncTargetSec(new URLSearchParams(search).get('sync'), fallback);
  } catch {
    return fallback;
  }
}

/** 영상 지연 목표의 출처 — 진단(window.__syncDebug.syncTargetSource)용 */
export type SyncTargetSource = 'query' | 'server' | 'default';

/**
 * 영상 지연 목표를 고른다 (2026-09-14):
 *   `?sync=N`(현장 실험) > 서버값(채널 상태 응답 `sync_target_sec` = api 파드 env LIVE_SYNC_TARGET_SEC,
 *   재빌드 없이 조정) > 빌드 기본(서버에 못 닿을 때의 안전 폴백). 서버값도 8~60 으로 클램프.
 */
export function pickSyncTarget(o: {
  search: string | null | undefined;
  server: number | null | undefined;
  fallback: number;
}): { value: number; source: SyncTargetSource } {
  const { search, server, fallback } = o;
  if (search != null && search !== '' && Number.isFinite(Number(search))) {
    return { value: resolveSyncTargetSec(search, fallback), source: 'query' };
  }
  if (typeof server === 'number' && Number.isFinite(server)) {
    const v = Math.min(SYNC_TARGET_MAX_SEC, Math.max(SYNC_TARGET_MIN_SEC, Math.round(server)));
    return { value: v, source: 'server' };
  }
  return { value: fallback, source: 'default' };
}

/**
 * 재생목록 PDT 의 기준일. 서버(backend hls_parser.HLS_CLOCK_EPOCH)가 보관분 재생목록의 세그먼트마다
 * PDT = 이 날짜 + 그 세그먼트 첫 음성의 자막 시계(초) 를 싣는다 — 두 값은 같아야 한다.
 */
export const HLS_CLOCK_EPOCH_MS = Date.UTC(2000, 0, 1);

/** hls.js `playingDate`(ms) → 자막 시계(초). */
export function clockFromPlayingDate(ms: number | null | undefined): number | null {
  return ms == null || !Number.isFinite(ms) ? null : (ms - HLS_CLOCK_EPOCH_MS) / 1000;
}

/** PDT 시계를 믿는 범위 — 서버 시계보다 이만큼 이상 뒤처진 값(긴 스톨 너머)은 버린다 */
const PDT_MAX_BEHIND_SEC = 120;

/**
 * 영상이 지금 보여주는 지점의 자막 시계(초).
 *
 * 1순위 `pdtClock` — 재생 중인 세그먼트의 PDT + 세그먼트 안 재생 위치. 추정이 없다(2026-09-11).
 *   서버 시계보다 앞서거나(아직 디코딩 안 한 소리일 수 없다) 너무 뒤처지면 — 원본 재생목록의 실제 날짜
 *   PDT, 서버 재시작 직후의 옛 세그먼트 등 — 버리고 2순위로 간다.
 * 2순위 지연 추정 — 서버시계 − (영상 라이브 지연 − 백엔드 엣지 지연). 보관분 재생목록에서는 엣지 지연
 *   가정(3초)이 맞지 않아 자막이 말보다 평균 2.3초 먼저 떴다(ch60 실측). PDT 가 없을 때만 쓴다.
 */
export function resolveVideoClock(o: {
  serverClockNow: number;
  pdtClock: number | null;
  hlsLatency: number | null;
  edgeLagSec: number;
  maxLagSec: number;
}): { clock: number | null; source: 'pdt' | 'latency' | null } {
  const { serverClockNow, pdtClock, hlsLatency, edgeLagSec, maxLagSec } = o;
  if (
    pdtClock != null &&
    pdtClock <= serverClockNow + 5 &&
    pdtClock >= serverClockNow - PDT_MAX_BEHIND_SEC
  ) {
    return { clock: pdtClock, source: 'pdt' };
  }
  if (hlsLatency == null) return { clock: null, source: null };
  // 지연 측정 이상으로 자막이 무한정 묶이지 않도록 하한 클램프
  const raw = serverClockNow - hlsLatency + edgeLagSec;
  return { clock: Math.max(raw, serverClockNow - maxLagSec), source: 'latency' };
}

/**
 * "영상보다 늦게 도착한 자막" 카운터.
 *
 * 동기화가 성립한 뒤 새로 도착한 자막이 도착 순간 이미 `start_time <= videoClock`
 * 이면, 영상이 그 발언 지점을 지난 뒤에야 자막이 온 것 — 영상 지연이 자막 준비
 * 지연보다 짧다는 증거다. 이 값이 0으로 유지되는 것이 "자막이 영상보다 늦지 않다"의
 * 증거이며, 영상 지연을 줄일 때의 안전 게이지다.
 *
 * 동기화 성립 시점에 이미 있던 자막(접속 백로그)은 판정하지 않는다.
 */
export class LateArrivalTracker {
  private seen = new Set<string>();
  private primed = false;
  lateCount = 0;
  /** 늦게 온 자막의 (videoClock − start_time) 최댓값 — 얼마나 늦었나 */
  maxLateSec = 0;

  observe(subtitles: ReadonlyArray<{ id: string; start_time: number }>, videoClock: number | null): void {
    if (videoClock == null) {
      // 동기화가 끊기면 다음 성립 때 백로그를 다시 걸러야 한다
      this.primed = false;
      return;
    }
    if (!this.primed) {
      this.primed = true;
      this.seen = new Set(subtitles.map((s) => s.id));
      return;
    }
    for (const s of subtitles) {
      if (this.seen.has(s.id)) continue;
      this.seen.add(s.id);
      const late = videoClock - s.start_time;
      if (late > 0) {
        this.lateCount += 1;
        if (late > this.maxLateSec) this.maxLateSec = Math.round(late * 10) / 10;
      }
    }
  }

  reset(): void {
    this.seen = new Set();
    this.primed = false;
    this.lateCount = 0;
    this.maxLateSec = 0;
  }
}
