import {
  HLS_CLOCK_EPOCH_MS,
  LateArrivalTracker,
  clockFromPlayingDate,
  pickSyncTarget,
  resolveSyncTargetSec,
  resolveVideoClock,
  syncTargetFromSearch,
} from '../liveSync';

describe('clockFromPlayingDate', () => {
  it('PDT 기준일(2000-01-01)로부터의 초가 자막 시계', () => {
    // 서버 hls_parser: 자막 시계 12.5초 → 2000-01-01T00:00:12.500Z
    expect(clockFromPlayingDate(Date.parse('2000-01-01T00:00:12.500Z'))).toBe(12.5);
    expect(clockFromPlayingDate(HLS_CLOCK_EPOCH_MS + 21348_700)).toBeCloseTo(21348.7);
  });

  it('PDT 가 없으면 null', () => {
    expect(clockFromPlayingDate(null)).toBeNull();
    expect(clockFromPlayingDate(undefined)).toBeNull();
    expect(clockFromPlayingDate(NaN)).toBeNull();
  });
});

describe('resolveVideoClock', () => {
  const base = { serverClockNow: 1000, edgeLagSec: 3, maxLagSec: 45 };

  it('PDT 시계가 있으면 추정 없이 그대로 쓴다', () => {
    expect(resolveVideoClock({ ...base, pdtClock: 979.4, hlsLatency: 20 })).toEqual({
      clock: 979.4,
      source: 'pdt',
    });
  });

  it('서버 시계와 동떨어진 PDT(원본 재생목록의 실제 날짜 등)는 버리고 지연 추정', () => {
    const realDatePdt = (Date.parse('2026-09-11T08:00:00Z') - HLS_CLOCK_EPOCH_MS) / 1000;
    expect(resolveVideoClock({ ...base, pdtClock: realDatePdt, hlsLatency: 20 })).toEqual({
      clock: 983,
      source: 'latency',
    });
    expect(resolveVideoClock({ ...base, pdtClock: 700, hlsLatency: 20 }).source).toBe('latency');
  });

  it('PDT 도 지연 측정도 없으면 동기화 불가', () => {
    expect(resolveVideoClock({ ...base, pdtClock: null, hlsLatency: null })).toEqual({
      clock: null,
      source: null,
    });
  });

  it('지연 추정은 서버 시계 − maxLag 아래로 내려가지 않는다', () => {
    expect(resolveVideoClock({ ...base, pdtClock: null, hlsLatency: 200 }).clock).toBe(955);
  });
});

describe('resolveSyncTargetSec', () => {
  it('없거나 비정상이면 fallback', () => {
    expect(resolveSyncTargetSec(null, 28)).toBe(28);
    expect(resolveSyncTargetSec('', 28)).toBe(28);
    expect(resolveSyncTargetSec('abc', 28)).toBe(28);
  });

  it('정상 값은 반올림해 그대로', () => {
    expect(resolveSyncTargetSec('20', 28)).toBe(20);
    expect(resolveSyncTargetSec('19.6', 28)).toBe(20);
  });

  it('8~60초로 클램프', () => {
    expect(resolveSyncTargetSec('3', 28)).toBe(8);
    expect(resolveSyncTargetSec('999', 28)).toBe(60);
  });

  it('search 문자열에서 읽는다', () => {
    expect(syncTargetFromSearch('?channel=ch14&sync=20', 28)).toBe(20);
    expect(syncTargetFromSearch('?channel=ch14', 28)).toBe(28);
    expect(syncTargetFromSearch(undefined, 28)).toBe(28);
  });
});

describe('LateArrivalTracker', () => {
  const sub = (id: string, start: number) => ({ id, start_time: start });

  it('동기화 성립 시점의 백로그는 판정하지 않는다', () => {
    const t = new LateArrivalTracker();
    t.observe([sub('a', 10), sub('b', 20)], 100);
    expect(t.lateCount).toBe(0);
  });

  it('성립 뒤 도착한 자막이 영상 시계보다 앞선 시작이면 늦은 도착', () => {
    const t = new LateArrivalTracker();
    t.observe([sub('a', 10)], 100);
    t.observe([sub('a', 10), sub('b', 97.5)], 100); // 영상은 이미 100 — 2.5초 늦음
    expect(t.lateCount).toBe(1);
    expect(t.maxLateSec).toBe(2.5);
  });

  it('영상 시계보다 뒤에 시작하는 자막은 정상(게이팅 대기)', () => {
    const t = new LateArrivalTracker();
    t.observe([], 100);
    t.observe([sub('c', 105)], 100);
    expect(t.lateCount).toBe(0);
  });

  it('같은 자막은 한 번만 판정한다', () => {
    const t = new LateArrivalTracker();
    t.observe([], 100);
    t.observe([sub('b', 90)], 100);
    t.observe([sub('b', 90)], 110);
    expect(t.lateCount).toBe(1);
  });

  it('동기화가 끊기면 다음 성립 때 백로그를 다시 거른다', () => {
    const t = new LateArrivalTracker();
    t.observe([], 100);
    t.observe([sub('b', 90)], null);
    t.observe([sub('b', 90), sub('c', 95)], 120);
    expect(t.lateCount).toBe(0);
  });
});

describe('pickSyncTarget', () => {
  it('?sync 가 있으면 서버값보다 이긴다 (8~60 클램프)', () => {
    expect(pickSyncTarget({ search: '14', server: 18, fallback: 20 })).toEqual({ value: 14, source: 'query' });
    expect(pickSyncTarget({ search: '3', server: 18, fallback: 20 })).toEqual({ value: 8, source: 'query' });
  });

  it('서버값(채널 상태 응답 sync_target_sec)이 있으면 그것 — 반올림·클램프', () => {
    expect(pickSyncTarget({ search: null, server: 18, fallback: 20 })).toEqual({ value: 18, source: 'server' });
    expect(pickSyncTarget({ search: '', server: 17.4, fallback: 20 })).toEqual({ value: 17, source: 'server' });
    expect(pickSyncTarget({ search: null, server: 99, fallback: 20 })).toEqual({ value: 60, source: 'server' });
  });

  it('둘 다 없거나 비정상이면 빌드 기본(서버에 못 닿을 때의 폴백)', () => {
    expect(pickSyncTarget({ search: null, server: undefined, fallback: 20 })).toEqual({ value: 20, source: 'default' });
    expect(pickSyncTarget({ search: 'abc', server: null, fallback: 20 })).toEqual({ value: 20, source: 'default' });
    expect(pickSyncTarget({ search: null, server: NaN, fallback: 20 })).toEqual({ value: 20, source: 'default' });
  });
});
