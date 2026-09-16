/**
 * 회의 시각 기준점 — 자막 시계(초) ↔ 실제 시각(벽시계). 순수 함수 (테스트 가능).
 *
 * **왜 단순 덧셈이 안 되는가.** 자막 `start_time` 은 회의 시작으로부터의 경과가 아니라
 * **수신된 오디오 초**다. 정회로 방송이 끊기면 자막 시계는 멈추지만 실제 시각은 흐른다.
 * "회의 시작 시각 + start_time" 으로 계산하면 정회 한 번에 그 길이만큼 통째로 틀어진다.
 *
 * 그래서 서버가 (자막 시계, 그때의 실제 시각) 쌍을 구간마다 준다
 * (`GET /api/meetings/{id}/clock-anchors` · backend services/meeting_clock.py).
 * 여기서는 그 쌍들로 **구간별 선형 매핑**만 한다:
 *
 *     실제시각 = 기준점.wall + (자막시계 − 기준점.clock)      (기준점 = clock ≤ 자막시계 중 마지막)
 */

export interface ClockAnchor {
  /** 자막 start_time 과 같은 시계(초) */
  clock: number;
  /** 그 시계 지점의 실제 시각 (epoch ms) */
  wallMs: number;
}

/** 기준점의 출처 — 화면이 "정확/근사/표시 안 함"을 가르는 값 */
export type ClockAnchorSource = 'recorded' | 'estimated' | 'none';

export interface ClockAnchorsResponse {
  source: ClockAnchorSource;
  anchors: ClockAnchor[];
}

/** API 응답(JSON)을 기준점 배열로. 깨진 항목은 버리고, 시계 오름차순으로 정렬한다. */
export function parseClockAnchors(raw: unknown): ClockAnchor[] {
  if (!Array.isArray(raw)) return [];
  const out: ClockAnchor[] = [];
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue;
    const clock = Number((item as { clock?: unknown }).clock);
    const wallMs = Date.parse(String((item as { wall?: unknown }).wall ?? ''));
    if (!Number.isFinite(clock) || !Number.isFinite(wallMs)) continue;
    out.push({ clock, wallMs });
  }
  return out.sort((a, b) => a.clock - b.clock);
}

/**
 * 자막 시계 → 실제 시각(epoch ms). 기준점이 없으면 null.
 * 첫 기준점보다 앞선 지점은 그 기준점에서 거꾸로 늘려 답한다(녹음 시작 직전의 몇 초).
 */
export function wallMsFromClock(anchors: ClockAnchor[], clock: number | null | undefined): number | null {
  if (!anchors.length || clock == null || !Number.isFinite(clock)) return null;
  let chosen = anchors[0]!;
  for (const a of anchors) {
    if (a.clock <= clock) chosen = a;
    else break;
  }
  return chosen.wallMs + (clock - chosen.clock) * 1000;
}

/**
 * 라이브 전용 기준점 — 서버 상태 방송(stt_status)으로 즉석에서 만든다.
 *
 * `audioClock` 은 서버가 **그 메시지를 보낸 순간까지 디코딩한** 오디오 초이고, 그 소리는
 * 재생목록 엣지보다 `edgeLagSec` 만큼 앞서 방송된 것이다(backend _edge_lag_now 와 같은 정의).
 * 따라서 자막 시계 0 의 실제 시각 = 메시지 수신 시각 − (audioClock + edgeLag).
 */
export function liveClockAnchor(o: {
  audioClock: number | null | undefined;
  receivedAt: number;
  edgeLagSec: number;
}): ClockAnchor | null {
  const { audioClock, receivedAt, edgeLagSec } = o;
  if (audioClock == null || !Number.isFinite(audioClock)) return null;
  const lag = Number.isFinite(edgeLagSec) ? edgeLagSec : 0;
  return { clock: 0, wallMs: receivedAt - (audioClock + lag) * 1000 };
}

/**
 * 기준점의 흔들림 억제 — 매 상태 방송마다 ±1초씩 출렁이면 화면의 초가 앞뒤로 튄다.
 * 새 값이 이전과 `toleranceMs` 안이면 이전 값을 그대로 쓴다(시계가 뒤로 가지 않게).
 */
export function stabilizeAnchor(
  prev: ClockAnchor | null,
  next: ClockAnchor | null,
  toleranceMs = 3000,
): ClockAnchor | null {
  if (!next) return prev;
  if (!prev) return next;
  const prevWallAtNextClock = prev.wallMs + (next.clock - prev.clock) * 1000;
  return Math.abs(prevWallAtNextClock - next.wallMs) <= toleranceMs ? prev : next;
}

function pad2(n: number): string {
  return n.toString().padStart(2, '0');
}

/**
 * 실제 시각 표기. 라이브는 `12:07:23`, VOD 는 날짜까지 `2026-09-16 12:07:23`.
 * (자막 목록의 시각 표기와 같은 형식 — 두 곳이 어긋나 보이지 않게 한다)
 */
export function formatWallClock(
  ms: number | null | undefined,
  opts: { withDate?: boolean } = {},
): string | null {
  if (ms == null || !Number.isFinite(ms)) return null;
  const d = new Date(ms);
  const time = `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
  if (!opts.withDate) return time;
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${time}`;
}
