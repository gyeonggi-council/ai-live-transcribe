import { renderHook, act } from '@testing-library/react';

import { useSubtitleSearch } from '../useSubtitleSearch';

import type { SubtitleType } from '../../types';

// Mock subtitle data
const mockSubtitles: SubtitleType[] = [
  {
    id: '1',
    meeting_id: 'meeting-1',
    start_time: 0,
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
    start_time: 10,
    end_time: 15,
    text: '예산 관련 질의 있으신 분?',
    speaker: '의장',
    confidence: 0.88,
    created_at: '2024-01-01T00:00:10Z',
  },
  {
    id: '4',
    meeting_id: 'meeting-1',
    start_time: 15,
    end_time: 20,
    text: '네, 질의 드리겠습니다',
    speaker: '김의원',
    confidence: 0.91,
    created_at: '2024-01-01T00:00:15Z',
  },
  {
    id: '5',
    meeting_id: 'meeting-1',
    start_time: 20,
    end_time: 25,
    text: '예산안에 대해 문의드립니다',
    speaker: '김의원',
    confidence: 0.93,
    created_at: '2024-01-01T00:00:20Z',
  },
];

describe('useSubtitleSearch', () => {
  describe('filtering subtitles by search query', () => {
    it('should return all subtitles when query is empty', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({ subtitles: mockSubtitles, query: '' })
      );

      expect(result.current.filteredSubtitles).toHaveLength(5);
      expect(result.current.filteredSubtitles).toEqual(mockSubtitles);
    });

    it('should return all subtitles when query is whitespace only', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({ subtitles: mockSubtitles, query: '   ' })
      );

      expect(result.current.filteredSubtitles).toHaveLength(5);
    });

    it('should filter subtitles matching the query', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({ subtitles: mockSubtitles, query: '예산' })
      );

      expect(result.current.filteredSubtitles).toHaveLength(3);
      expect(result.current.filteredSubtitles.map((s) => s.id)).toEqual(['2', '3', '5']);
    });

    it('should return empty array when no match found', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({ subtitles: mockSubtitles, query: '없는단어' })
      );

      expect(result.current.filteredSubtitles).toHaveLength(0);
    });

    it('should be case insensitive', () => {
      const subtitlesWithEnglish: SubtitleType[] = [
        {
          id: '1',
          meeting_id: 'meeting-1',
          start_time: 0,
          end_time: 5,
          text: 'Hello World',
          speaker: null,
          confidence: 0.95,
          created_at: '2024-01-01T00:00:00Z',
        },
        {
          id: '2',
          meeting_id: 'meeting-1',
          start_time: 5,
          end_time: 10,
          text: 'hello everyone',
          speaker: null,
          confidence: 0.92,
          created_at: '2024-01-01T00:00:05Z',
        },
      ];

      const { result } = renderHook(() =>
        useSubtitleSearch({ subtitles: subtitlesWithEnglish, query: 'HELLO' })
      );

      expect(result.current.filteredSubtitles).toHaveLength(2);
    });
  });

  describe('match indices', () => {
    it('should return indices of matching subtitles', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({ subtitles: mockSubtitles, query: '예산' })
      );

      // Original indices: 1, 2, 4 (0-indexed)
      expect(result.current.matchIndices).toEqual([1, 2, 4]);
    });

    it('should return empty indices when no match', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({ subtitles: mockSubtitles, query: '없는단어' })
      );

      expect(result.current.matchIndices).toEqual([]);
    });

    it('should return empty indices when query is empty', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({ subtitles: mockSubtitles, query: '' })
      );

      expect(result.current.matchIndices).toEqual([]);
    });
  });

  describe('first match', () => {
    it('should return first matching subtitle', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({ subtitles: mockSubtitles, query: '예산' })
      );

      expect(result.current.firstMatch).toEqual(mockSubtitles[1]);
    });

    it('should return null when no match', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({ subtitles: mockSubtitles, query: '없는단어' })
      );

      expect(result.current.firstMatch).toBeNull();
    });

    it('should return null when query is empty', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({ subtitles: mockSubtitles, query: '' })
      );

      expect(result.current.firstMatch).toBeNull();
    });
  });

  describe('match count', () => {
    it('should return total match count', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({ subtitles: mockSubtitles, query: '예산' })
      );

      expect(result.current.matchCount).toBe(3);
    });

    it('should return 0 when no match', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({ subtitles: mockSubtitles, query: '없는단어' })
      );

      expect(result.current.matchCount).toBe(0);
    });
  });

  describe('current match index navigation', () => {
    it('should start with currentMatchIndex at 0 when there are matches', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({ subtitles: mockSubtitles, query: '예산' })
      );

      expect(result.current.currentMatchIndex).toBe(0);
    });

    it('should return -1 when no matches', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({ subtitles: mockSubtitles, query: '없는단어' })
      );

      expect(result.current.currentMatchIndex).toBe(-1);
    });

    it('should navigate to next match', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({ subtitles: mockSubtitles, query: '예산' })
      );

      expect(result.current.currentMatchIndex).toBe(0);

      act(() => {
        result.current.goToNextMatch();
      });

      expect(result.current.currentMatchIndex).toBe(1);

      act(() => {
        result.current.goToNextMatch();
      });

      expect(result.current.currentMatchIndex).toBe(2);
    });

    it('should wrap around to first match after last', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({ subtitles: mockSubtitles, query: '예산' })
      );

      // Go to last match
      act(() => {
        result.current.goToNextMatch();
        result.current.goToNextMatch();
      });

      expect(result.current.currentMatchIndex).toBe(2);

      // Should wrap to 0
      act(() => {
        result.current.goToNextMatch();
      });

      expect(result.current.currentMatchIndex).toBe(0);
    });

    it('should navigate to previous match', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({ subtitles: mockSubtitles, query: '예산' })
      );

      // Go to second match first
      act(() => {
        result.current.goToNextMatch();
      });

      expect(result.current.currentMatchIndex).toBe(1);

      act(() => {
        result.current.goToPrevMatch();
      });

      expect(result.current.currentMatchIndex).toBe(0);
    });

    it('should wrap around to last match when going previous from first', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({ subtitles: mockSubtitles, query: '예산' })
      );

      expect(result.current.currentMatchIndex).toBe(0);

      act(() => {
        result.current.goToPrevMatch();
      });

      expect(result.current.currentMatchIndex).toBe(2); // Last match
    });

    it('should do nothing when navigating with no matches', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({ subtitles: mockSubtitles, query: '없는단어' })
      );

      expect(result.current.currentMatchIndex).toBe(-1);

      act(() => {
        result.current.goToNextMatch();
      });

      expect(result.current.currentMatchIndex).toBe(-1);

      act(() => {
        result.current.goToPrevMatch();
      });

      expect(result.current.currentMatchIndex).toBe(-1);
    });
  });

  describe('current match subtitle', () => {
    it('should return current match subtitle', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({ subtitles: mockSubtitles, query: '예산' })
      );

      expect(result.current.currentMatch).toEqual(mockSubtitles[1]);

      act(() => {
        result.current.goToNextMatch();
      });

      expect(result.current.currentMatch).toEqual(mockSubtitles[2]);
    });

    it('should return null when no matches', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({ subtitles: mockSubtitles, query: '없는단어' })
      );

      expect(result.current.currentMatch).toBeNull();
    });
  });

  describe('reset on query change', () => {
    it('should reset currentMatchIndex when query changes', () => {
      const { result, rerender } = renderHook(
        ({ query }) => useSubtitleSearch({ subtitles: mockSubtitles, query }),
        { initialProps: { query: '예산' } }
      );

      // Navigate to second match
      act(() => {
        result.current.goToNextMatch();
      });

      expect(result.current.currentMatchIndex).toBe(1);

      // Change query
      rerender({ query: '질의' });

      // Should reset to 0
      expect(result.current.currentMatchIndex).toBe(0);
    });
  });

  describe('empty subtitles', () => {
    it('should handle empty subtitles array', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({ subtitles: [], query: '예산' })
      );

      expect(result.current.filteredSubtitles).toHaveLength(0);
      expect(result.current.matchCount).toBe(0);
      expect(result.current.firstMatch).toBeNull();
      expect(result.current.currentMatch).toBeNull();
    });
  });

  describe('filterMode option', () => {
    it('should return only matching subtitles when filterMode is "match"', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({
          subtitles: mockSubtitles,
          query: '예산',
          filterMode: 'match',
        })
      );

      expect(result.current.filteredSubtitles).toHaveLength(3);
    });

    it('should return all subtitles when filterMode is "all"', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({
          subtitles: mockSubtitles,
          query: '예산',
          filterMode: 'all',
        })
      );

      expect(result.current.filteredSubtitles).toHaveLength(5);
      expect(result.current.matchCount).toBe(3);
    });

    it('should default to "match" filterMode', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({ subtitles: mockSubtitles, query: '예산' })
      );

      expect(result.current.filteredSubtitles).toHaveLength(3);
    });
  });

  describe('isMatch helper', () => {
    it('should correctly identify matching subtitles', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({
          subtitles: mockSubtitles,
          query: '예산',
          filterMode: 'all',
        })
      );

      expect(result.current.isMatch('1')).toBe(false);
      expect(result.current.isMatch('2')).toBe(true);
      expect(result.current.isMatch('3')).toBe(true);
      expect(result.current.isMatch('4')).toBe(false);
      expect(result.current.isMatch('5')).toBe(true);
    });

    it('should return false for unknown id', () => {
      const { result } = renderHook(() =>
        useSubtitleSearch({ subtitles: mockSubtitles, query: '예산' })
      );

      expect(result.current.isMatch('unknown')).toBe(false);
    });
  });
});
