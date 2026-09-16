import { renderHook, act } from '@testing-library/react';

import { useSubtitleSync } from '../useSubtitleSync';

import type { SubtitleType } from '../../types';

// Mock subtitle data - first subtitle starts at 2, not 0, so initial state has no match
const mockSubtitles: SubtitleType[] = [
  {
    id: '1',
    meeting_id: 'meeting-1',
    start_time: 2,
    end_time: 5,
    text: '안녕하세요 여러분',
    speaker: '의장',
    confidence: 0.95,
    created_at: '2024-01-01T00:00:00Z',
  },
  {
    id: '2',
    meeting_id: 'meeting-1',
    start_time: 5,
    end_time: 10,
    text: '오늘 예산안 심의를 시작하겠습니다',
    speaker: '의장',
    confidence: 0.92,
    created_at: '2024-01-01T00:00:05Z',
  },
  {
    id: '3',
    meeting_id: 'meeting-1',
    start_time: 12,
    end_time: 17,
    text: '예산 관련 질의 있으신 분?',
    speaker: '의장',
    confidence: 0.88,
    created_at: '2024-01-01T00:00:12Z',
  },
];

/**
 * Helper to create a mock HTMLVideoElement with event listener support.
 */
function createMockVideoElement(initialTime = 0): HTMLVideoElement {
  const listeners: Record<string, Array<(...args: unknown[]) => void>> = {};

  const video = {
    currentTime: initialTime,
    paused: true,
    addEventListener: jest.fn((event: string, handler: (...args: unknown[]) => void) => {
      if (!listeners[event]) {
        listeners[event] = [];
      }
      listeners[event].push(handler);
    }),
    removeEventListener: jest.fn((event: string, handler: (...args: unknown[]) => void) => {
      if (listeners[event]) {
        listeners[event] = listeners[event].filter((h) => h !== handler);
      }
    }),
    // Helper to fire events in tests
    _fireEvent: (event: string) => {
      if (listeners[event]) {
        listeners[event].forEach((h) => h());
      }
    },
    _getListeners: () => listeners,
  } as unknown as HTMLVideoElement & {
    _fireEvent: (event: string) => void;
    _getListeners: () => Record<string, Array<(...args: unknown[]) => void>>;
  };

  return video;
}

describe('useSubtitleSync', () => {
  describe('initial state', () => {
    it('should return initial state with currentTime=0, currentSubtitle=null, isPlaying=false', () => {
      const videoRef = { current: createMockVideoElement() };

      const { result } = renderHook(() =>
        useSubtitleSync({
          subtitles: mockSubtitles,
          videoRef,
        })
      );

      expect(result.current.currentTime).toBe(0);
      expect(result.current.currentSubtitle).toBeNull();
      expect(result.current.isPlaying).toBe(false);
    });

    it('should return null currentSubtitle when subtitles array is empty', () => {
      const videoRef = { current: createMockVideoElement() };

      const { result } = renderHook(() =>
        useSubtitleSync({
          subtitles: [],
          videoRef,
        })
      );

      expect(result.current.currentSubtitle).toBeNull();
    });

    it('should handle null videoRef gracefully', () => {
      const videoRef = { current: null };

      const { result } = renderHook(() =>
        useSubtitleSync({
          subtitles: mockSubtitles,
          videoRef,
        })
      );

      expect(result.current.currentTime).toBe(0);
      expect(result.current.currentSubtitle).toBeNull();
      expect(result.current.isPlaying).toBe(false);
    });
  });

  describe('timeupdate event', () => {
    it('should update currentTime when timeupdate event fires', () => {
      const video = createMockVideoElement();
      const videoRef = { current: video };

      const { result } = renderHook(() =>
        useSubtitleSync({
          subtitles: mockSubtitles,
          videoRef,
        })
      );

      // Simulate timeupdate
      act(() => {
        (video as unknown as { currentTime: number }).currentTime = 3;
        (video as unknown as { _fireEvent: (e: string) => void })._fireEvent('timeupdate');
      });

      expect(result.current.currentTime).toBe(3);
    });
  });

  describe('current subtitle matching', () => {
    it('should find currentSubtitle when currentTime falls within a subtitle range', () => {
      const video = createMockVideoElement();
      const videoRef = { current: video };

      const { result } = renderHook(() =>
        useSubtitleSync({
          subtitles: mockSubtitles,
          videoRef,
        })
      );

      // Time 3 falls within subtitle 1 (0-5)
      act(() => {
        (video as unknown as { currentTime: number }).currentTime = 3;
        (video as unknown as { _fireEvent: (e: string) => void })._fireEvent('timeupdate');
      });

      expect(result.current.currentSubtitle).toEqual(mockSubtitles[0]);
    });

    it('should update currentSubtitle as time progresses to next subtitle', () => {
      const video = createMockVideoElement();
      const videoRef = { current: video };

      const { result } = renderHook(() =>
        useSubtitleSync({
          subtitles: mockSubtitles,
          videoRef,
        })
      );

      // Time 7 falls within subtitle 2 (5-10)
      act(() => {
        (video as unknown as { currentTime: number }).currentTime = 7;
        (video as unknown as { _fireEvent: (e: string) => void })._fireEvent('timeupdate');
      });

      expect(result.current.currentSubtitle).toEqual(mockSubtitles[1]);
    });

    it('should return null currentSubtitle when currentTime is between subtitles (gap)', () => {
      const video = createMockVideoElement();
      const videoRef = { current: video };

      const { result } = renderHook(() =>
        useSubtitleSync({
          subtitles: mockSubtitles,
          videoRef,
        })
      );

      // Time 11 falls in the gap between subtitle 2 (5-10) and subtitle 3 (12-17)
      act(() => {
        (video as unknown as { currentTime: number }).currentTime = 11;
        (video as unknown as { _fireEvent: (e: string) => void })._fireEvent('timeupdate');
      });

      expect(result.current.currentSubtitle).toBeNull();
    });

    it('should match subtitle at exact start_time (inclusive)', () => {
      const video = createMockVideoElement();
      const videoRef = { current: video };

      const { result } = renderHook(() =>
        useSubtitleSync({
          subtitles: mockSubtitles,
          videoRef,
        })
      );

      // Exactly at start of subtitle 2
      act(() => {
        (video as unknown as { currentTime: number }).currentTime = 5;
        (video as unknown as { _fireEvent: (e: string) => void })._fireEvent('timeupdate');
      });

      expect(result.current.currentSubtitle).toEqual(mockSubtitles[1]);
    });

    it('should not match subtitle at exact end_time (exclusive)', () => {
      const video = createMockVideoElement();
      const videoRef = { current: video };

      const { result } = renderHook(() =>
        useSubtitleSync({
          subtitles: mockSubtitles,
          videoRef,
        })
      );

      // Exactly at end of subtitle 1 (end_time=5), which is start of subtitle 2
      // Since start_time is inclusive and end_time is exclusive, time=5 should match subtitle 2
      act(() => {
        (video as unknown as { currentTime: number }).currentTime = 5;
        (video as unknown as { _fireEvent: (e: string) => void })._fireEvent('timeupdate');
      });

      expect(result.current.currentSubtitle?.id).toBe('2');
    });
  });

  describe('seekTo', () => {
    it('should set video.currentTime when seekTo is called', () => {
      const video = createMockVideoElement();
      const videoRef = { current: video };

      const { result } = renderHook(() =>
        useSubtitleSync({
          subtitles: mockSubtitles,
          videoRef,
        })
      );

      act(() => {
        result.current.seekTo(15);
      });

      expect(video.currentTime).toBe(15);
    });

    it('should not throw when videoRef is null and seekTo is called', () => {
      const videoRef = { current: null };

      const { result } = renderHook(() =>
        useSubtitleSync({
          subtitles: mockSubtitles,
          videoRef,
        })
      );

      expect(() => {
        act(() => {
          result.current.seekTo(10);
        });
      }).not.toThrow();
    });
  });

  describe('play/pause state tracking', () => {
    it('should set isPlaying=true when play event fires', () => {
      const video = createMockVideoElement();
      const videoRef = { current: video };

      const { result } = renderHook(() =>
        useSubtitleSync({
          subtitles: mockSubtitles,
          videoRef,
        })
      );

      expect(result.current.isPlaying).toBe(false);

      act(() => {
        (video as unknown as { paused: boolean }).paused = false;
        (video as unknown as { _fireEvent: (e: string) => void })._fireEvent('play');
      });

      expect(result.current.isPlaying).toBe(true);
    });

    it('should set isPlaying=false when pause event fires', () => {
      const video = createMockVideoElement();
      const videoRef = { current: video };

      const { result } = renderHook(() =>
        useSubtitleSync({
          subtitles: mockSubtitles,
          videoRef,
        })
      );

      // First, set to playing
      act(() => {
        (video as unknown as { paused: boolean }).paused = false;
        (video as unknown as { _fireEvent: (e: string) => void })._fireEvent('play');
      });

      expect(result.current.isPlaying).toBe(true);

      // Then, pause
      act(() => {
        (video as unknown as { paused: boolean }).paused = true;
        (video as unknown as { _fireEvent: (e: string) => void })._fireEvent('pause');
      });

      expect(result.current.isPlaying).toBe(false);
    });
  });

  describe('cleanup', () => {
    it('should remove event listeners on unmount', () => {
      const video = createMockVideoElement();
      const videoRef = { current: video };

      const { unmount } = renderHook(() =>
        useSubtitleSync({
          subtitles: mockSubtitles,
          videoRef,
        })
      );

      // Verify listeners were added
      expect(video.addEventListener).toHaveBeenCalledWith('timeupdate', expect.any(Function));
      expect(video.addEventListener).toHaveBeenCalledWith('play', expect.any(Function));
      expect(video.addEventListener).toHaveBeenCalledWith('pause', expect.any(Function));

      unmount();

      // Verify listeners were removed
      expect(video.removeEventListener).toHaveBeenCalledWith('timeupdate', expect.any(Function));
      expect(video.removeEventListener).toHaveBeenCalledWith('play', expect.any(Function));
      expect(video.removeEventListener).toHaveBeenCalledWith('pause', expect.any(Function));
    });

    it('should not fail on unmount when videoRef is null', () => {
      const videoRef = { current: null };

      const { unmount } = renderHook(() =>
        useSubtitleSync({
          subtitles: mockSubtitles,
          videoRef,
        })
      );

      expect(() => {
        unmount();
      }).not.toThrow();
    });
  });

  describe('videoRef changes', () => {
    it('should re-attach listeners when videoRef changes', () => {
      const video1 = createMockVideoElement();
      const video2 = createMockVideoElement();
      const videoRef = { current: video1 };

      const { rerender } = renderHook(
        ({ vRef }) =>
          useSubtitleSync({
            subtitles: mockSubtitles,
            videoRef: vRef,
          }),
        { initialProps: { vRef: videoRef } }
      );

      expect(video1.addEventListener).toHaveBeenCalledWith('timeupdate', expect.any(Function));

      // Change videoRef
      const newRef = { current: video2 };
      rerender({ vRef: newRef });

      expect(video2.addEventListener).toHaveBeenCalledWith('timeupdate', expect.any(Function));
    });
  });
});
