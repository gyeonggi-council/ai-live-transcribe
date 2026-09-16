import { clampTime, formatBytes, formatHMS, formatLen, parseHMS, withEnd, withStart } from '../clipTime';

describe('clipTime', () => {
  it('formatHMS 는 항상 HH:MM:SS', () => {
    expect(formatHMS(0)).toBe('00:00:00');
    expect(formatHMS(3723.9)).toBe('01:02:03');
    expect(formatHMS(-5)).toBe('00:00:00');
    expect(formatHMS(NaN)).toBe('00:00:00');
  });

  it('parseHMS 는 HH:MM:SS·MM:SS·SS·한국어 길이를 받는다', () => {
    expect(parseHMS('01:02:03')).toBe(3723);
    expect(parseHMS('12:30')).toBe(750);
    expect(parseHMS('90')).toBe(90);
    expect(parseHMS('1시간 2분 3초')).toBe(3723);
    expect(parseHMS('25분')).toBe(1500);
    expect(parseHMS('')).toBeNull();
    expect(parseHMS('abc')).toBeNull();
    expect(parseHMS('1:2:3:4')).toBeNull();
  });

  it('formatLen 은 사람이 읽는 길이', () => {
    expect(formatLen(45)).toBe('45초');
    expect(formatLen(156)).toBe('2분 36초');
    expect(formatLen(3725)).toBe('1시간 02분');
  });

  it('formatBytes', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(15 * 1024 * 1024)).toBe('15.0 MB');
    expect(formatBytes(3 * 1024 ** 3)).toBe('3.00 GB');
  });

  it('withStart / withEnd 는 뒤집힌 구간을 바로잡는다 (app.html markStart/markEnd)', () => {
    expect(withStart({ start: 0, end: 50 }, 100, 1000)).toEqual({ start: 100, end: 1000 });
    expect(withStart({ start: 0, end: 500 }, 100, 1000)).toEqual({ start: 100, end: 500 });
    expect(withEnd({ start: 300, end: 500 }, 100, 1000)).toEqual({ start: 0, end: 100 });
    expect(withEnd({ start: 50, end: 500 }, 2000, 1000)).toEqual({ start: 50, end: 1000 });
    expect(clampTime(-3, 10)).toBe(0);
  });
});
