/**
 * 회의 시각 기준점 — 자막 시계 ↔ 실제 시각.
 *
 * 여기서 지키려는 것은 하나다: **정회를 건너뛴 시계로 실제 시각을 만들지 않는다.**
 * 자막 시계는 수신된 오디오만 세므로, 정회 1시간은 시계에 없지만 시계(벽시계)로는 흘렀다.
 */

import {
  formatWallClock,
  liveClockAnchor,
  parseClockAnchors,
  stabilizeAnchor,
  wallMsFromClock,
} from '../meetingClock';

const at = (h: number, m: number, s = 0) => new Date(2026, 8, 16, h, m, s).getTime(); // 2026-09-16 로컬

describe('parseClockAnchors', () => {
  it('ISO 시각을 epoch ms 로 바꾸고 시계순으로 정렬한다', () => {
    const anchors = parseClockAnchors([
      { clock: 1800, wall: new Date(at(11, 30)).toISOString() },
      { clock: 0, wall: new Date(at(10, 0)).toISOString() },
    ]);
    expect(anchors.map((a) => a.clock)).toEqual([0, 1800]);
    expect(anchors[0]!.wallMs).toBe(at(10, 0));
  });

  it('깨진 항목은 버린다 (배열이 아니면 빈 배열)', () => {
    expect(parseClockAnchors(null)).toEqual([]);
    expect(parseClockAnchors([{ clock: 'x', wall: 'y' }, { clock: 1 }])).toEqual([]);
  });
});

describe('wallMsFromClock', () => {
  const anchors = [
    { clock: 0, wallMs: at(10, 0) },
    { clock: 1800, wallMs: at(11, 30) }, // 30분 방송 뒤 1시간 정회, 11:30 재개
  ];

  it('한 구간 안에서는 흐른 만큼 더한다', () => {
    expect(wallMsFromClock(anchors, 600)).toBe(at(10, 10));
  });

  it('정회 뒤 장면은 재개 기준점을 쓴다 (기준점이 없으면 1시간 틀릴 지점)', () => {
    expect(wallMsFromClock(anchors, 2400)).toBe(at(11, 40));
  });

  it('첫 기준점보다 앞선 지점은 거꾸로 늘린다', () => {
    expect(wallMsFromClock([{ clock: 100, wallMs: at(10, 1, 40) }], 40)).toBe(at(10, 0, 40));
  });

  it('기준점이나 시계가 없으면 답하지 않는다 — 틀린 시각보다 없는 편이 낫다', () => {
    expect(wallMsFromClock([], 10)).toBeNull();
    expect(wallMsFromClock(anchors, null)).toBeNull();
  });
});

describe('liveClockAnchor', () => {
  it('서버 상태 방송으로 자막 시계 0 의 실제 시각을 잡는다', () => {
    // 10:30:00 에 받은 상태에서 audio_clock=1800(=30분), 수집 지연 3초
    // → 시계 0 은 10:30:00 − 1803초 = 09:59:57
    const anchor = liveClockAnchor({
      audioClock: 1800,
      receivedAt: at(10, 30),
      edgeLagSec: 3,
    });
    expect(anchor).not.toBeNull();
    expect(anchor!.clock).toBe(0);
    expect(anchor!.wallMs).toBe(at(9, 59, 57));
  });

  it('영상 시계를 얹으면 화면 속 장면의 시각이 된다 (엣지보다 20초 뒤 재생)', () => {
    const anchor = liveClockAnchor({ audioClock: 1800, receivedAt: at(10, 30), edgeLagSec: 3 })!;
    // 영상이 보여주는 지점의 자막 시계가 1780초라면 그 장면은 10:29:40 에 방송된 것
    expect(wallMsFromClock([anchor], 1780)).toBe(at(10, 29, 37));
  });

  it('audio_clock 이 없으면 만들지 않는다', () => {
    expect(liveClockAnchor({ audioClock: null, receivedAt: at(10, 0), edgeLagSec: 3 })).toBeNull();
  });
});

describe('stabilizeAnchor', () => {
  it('오차 범위 안의 흔들림은 무시한다 — 화면의 초가 앞뒤로 튀지 않게', () => {
    const prev = { clock: 0, wallMs: at(10, 0) };
    const jitter = { clock: 0, wallMs: at(10, 0) + 1200 };
    expect(stabilizeAnchor(prev, jitter)).toBe(prev);
  });

  it('허용치를 넘는 보정은 받아들인다 (스톨·재시작 뒤 진짜 교정)', () => {
    const prev = { clock: 0, wallMs: at(10, 0) };
    const corrected = { clock: 0, wallMs: at(10, 0) + 30000 };
    expect(stabilizeAnchor(prev, corrected)).toBe(corrected);
  });

  it('새 값이 없으면 이전 값을 유지한다 (상태 방송이 잠시 끊겨도 시계는 흐른다)', () => {
    const prev = { clock: 0, wallMs: at(10, 0) };
    expect(stabilizeAnchor(prev, null)).toBe(prev);
  });
});

describe('formatWallClock', () => {
  it('라이브는 시:분:초, VOD 는 날짜까지', () => {
    expect(formatWallClock(at(12, 7, 23))).toBe('12:07:23');
    expect(formatWallClock(at(12, 7, 23), { withDate: true })).toBe('2026-09-16 12:07:23');
  });

  it('값이 없으면 null (배지가 사라진다)', () => {
    expect(formatWallClock(null)).toBeNull();
    expect(formatWallClock(Number.NaN)).toBeNull();
  });
});
