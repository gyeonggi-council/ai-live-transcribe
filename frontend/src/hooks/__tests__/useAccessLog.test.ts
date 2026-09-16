import { act, renderHook } from '@testing-library/react';

import { recordAccess } from '@/lib/api';

import { logAccess, usePageAccessLog, useWatchAccessLog, visitorKey, WATCH_PING_MS } from '../useAccessLog';

jest.mock('@/lib/api', () => ({
  __esModule: true,
  recordAccess: jest.fn().mockResolvedValue(undefined),
}));

const mockRecord = recordAccess as jest.Mock;

describe('접속 기록 보내기 (2026-09-16)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.localStorage.clear();
  });

  it('브라우저 표식은 그날 하루만 쓴다 — 날짜가 붙은 키 하나만 남는다', () => {
    const key = visitorKey();
    expect(key).toBeTruthy();
    expect(visitorKey()).toBe(key); // 같은 날은 같은 값

    const saved = Object.keys(window.localStorage).filter((k) => k.startsWith('ggc_visit_key_'));
    expect(saved).toHaveLength(1);
    expect(saved[0]).toMatch(/^ggc_visit_key_\d{4}-\d{2}-\d{2}$/);
    // 어제 것은 치운다
    window.localStorage.setItem('ggc_visit_key_2000-01-01', 'old');
    visitorKey();
    expect(window.localStorage.getItem('ggc_visit_key_2000-01-01')).toBeNull();
  });

  it('화면 열람은 한 번만 보낸다', () => {
    const { rerender } = renderHook(() => usePageAccessLog('/live'));
    rerender();
    rerender();

    expect(mockRecord).toHaveBeenCalledTimes(1);
    expect(mockRecord).toHaveBeenCalledWith(expect.objectContaining({ kind: 'page', path: '/live' }));
  });

  it('IP·계정은 보내지 않는다', () => {
    logAccess('search', { meetingId: 'm-1' });

    const sent = mockRecord.mock.calls[0][0];
    expect(Object.keys(sent).sort()).toEqual(['kind', 'meetingId', 'path', 'visitorKey']);
  });

  describe('시청 신호', () => {
    beforeEach(() => jest.useFakeTimers());
    afterEach(() => jest.useRealTimers());

    it('재생 중이면 5분마다 보낸다', () => {
      renderHook(() => useWatchAccessLog({ kind: 'watch_live', meetingId: 'ch60', active: true }));

      expect(mockRecord).toHaveBeenCalledTimes(1); // 시작하자마자 1회
      act(() => {
        jest.advanceTimersByTime(WATCH_PING_MS * 2);
      });
      expect(mockRecord).toHaveBeenCalledTimes(3);
      expect(mockRecord).toHaveBeenLastCalledWith(expect.objectContaining({ kind: 'watch_live', meetingId: 'ch60' }));
    });

    it('재생 중이 아니면 보내지 않는다', () => {
      renderHook(() => useWatchAccessLog({ kind: 'watch_vod', meetingId: 'm-1', active: false }));

      act(() => {
        jest.advanceTimersByTime(WATCH_PING_MS * 3);
      });
      expect(mockRecord).not.toHaveBeenCalled();
    });

    it('탭이 숨겨져 있으면 보내지 않는다 — 틀어 놓고 잊은 창을 세지 않는다', () => {
      const spy = jest.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
      renderHook(() => useWatchAccessLog({ kind: 'watch_live', meetingId: 'ch60', active: true }));

      act(() => {
        jest.advanceTimersByTime(WATCH_PING_MS * 2);
      });
      expect(mockRecord).not.toHaveBeenCalled();
      spy.mockRestore();
    });

    it('화면을 떠나면 더 보내지 않는다', () => {
      const { unmount } = renderHook(() =>
        useWatchAccessLog({ kind: 'watch_live', meetingId: 'ch60', active: true })
      );
      unmount();

      act(() => {
        jest.advanceTimersByTime(WATCH_PING_MS * 3);
      });
      expect(mockRecord).toHaveBeenCalledTimes(1);
    });
  });
});
