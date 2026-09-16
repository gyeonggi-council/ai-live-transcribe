/**
 * useRecentVods 훅 테스트
 *
 * 테스트 케이스:
 * 1. 최근 VOD 목록 가져오기
 * 2. 빈 목록 처리
 * 3. 로딩 상태 처리
 * 4. 에러 상태 처리
 * 5. limit 옵션 적용
 * 6. 캐싱 동작 확인
 */

import type { ReactNode } from 'react';

import { renderHook, waitFor, act } from '@testing-library/react';
import { SWRConfig } from 'swr';

import { apiClient } from '@/lib/api';
import type { MeetingType } from '@/types';

import { useRecentVods } from '../useRecentVods';

// Mock the API client
jest.mock('@/lib/api', () => ({
  apiClient: jest.fn(),
  API_BASE_URL: 'http://localhost:8000',
}));

const mockApiClient = apiClient as jest.MockedFunction<typeof apiClient>;

// Mock VOD data
const mockVods: MeetingType[] = [
  {
    id: 'vod-1',
    title: '제122회 본회의',
    meeting_date: '2026-02-04',
    stream_url: null,
    vod_url: 'https://vod.example.com/meeting122.mp4',
    status: 'ended',
    duration_seconds: 7200,
    created_at: '2026-02-04T09:00:00Z',
    updated_at: '2026-02-04T15:00:00Z',
  },
  {
    id: 'vod-2',
    title: '제121회 상임위원회',
    meeting_date: '2026-02-03',
    stream_url: null,
    vod_url: 'https://vod.example.com/meeting121.mp4',
    status: 'ended',
    duration_seconds: 5400,
    created_at: '2026-02-03T09:00:00Z',
    updated_at: '2026-02-03T14:00:00Z',
  },
  {
    id: 'vod-3',
    title: '제120회 본회의',
    meeting_date: '2026-02-02',
    stream_url: null,
    vod_url: null,
    status: 'processing',
    duration_seconds: 3600,
    created_at: '2026-02-02T09:00:00Z',
    updated_at: '2026-02-02T12:00:00Z',
  },
];

// SWR test wrapper to disable cache between tests
function TestWrapper({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      {children}
    </SWRConfig>
  );
}

function SharedCacheWrapper({ children }: { children: ReactNode }) {
  return <SWRConfig value={{ dedupingInterval: 2000 }}>{children}</SWRConfig>;
}

const createWrapper = () => TestWrapper;

describe('useRecentVods', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Data fetching', () => {
    it('should fetch recent VOD list successfully', async () => {
      mockApiClient.mockResolvedValueOnce(mockVods);

      const { result } = renderHook(() => useRecentVods(), {
        wrapper: createWrapper(),
      });

      // 초기 로딩 상태
      expect(result.current.isLoading).toBe(true);

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(result.current.vods).toEqual(mockVods);
      expect(result.current.error).toBeNull();
      expect(mockApiClient).toHaveBeenCalledWith(
        '/api/meetings?status=processing%2Cended&limit=5'
      );
    });

    it('should apply custom limit option', async () => {
      mockApiClient.mockResolvedValueOnce(mockVods.slice(0, 3));

      const { result } = renderHook(() => useRecentVods({ limit: 3 }), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(mockApiClient).toHaveBeenCalledWith(
        '/api/meetings?status=processing%2Cended&limit=3'
      );
    });
  });

  describe('Empty list handling', () => {
    it('should handle empty VOD list', async () => {
      mockApiClient.mockResolvedValueOnce([]);

      const { result } = renderHook(() => useRecentVods(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(result.current.vods).toEqual([]);
      expect(result.current.error).toBeNull();
    });

    it('should return empty array as default', async () => {
      mockApiClient.mockResolvedValueOnce(null);

      const { result } = renderHook(() => useRecentVods(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(result.current.vods).toEqual([]);
    });
  });

  describe('Loading state', () => {
    it('should show loading state while fetching', async () => {
      mockApiClient.mockImplementation(
        () =>
          new Promise((resolve) => {
            setTimeout(() => resolve(mockVods), 100);
          })
      );

      const { result } = renderHook(() => useRecentVods(), {
        wrapper: createWrapper(),
      });

      expect(result.current.isLoading).toBe(true);
      expect(result.current.vods).toEqual([]);

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(result.current.vods).toEqual(mockVods);
    });
  });

  describe('Error handling', () => {
    it('should handle API error gracefully', async () => {
      const error = new Error('API Error');
      mockApiClient.mockRejectedValueOnce(error);

      const { result } = renderHook(() => useRecentVods(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(result.current.error).toBeTruthy();
      expect(result.current.vods).toEqual([]);
    });

    it('should handle network error', async () => {
      mockApiClient.mockRejectedValueOnce(new Error('Network error'));

      const { result } = renderHook(() => useRecentVods(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.error).not.toBeNull();
      });

      expect(result.current.vods).toEqual([]);
    });
  });

  describe('Caching', () => {
    it('should cache data and not refetch on re-render', async () => {
      mockApiClient.mockResolvedValue(mockVods);

      const { result, rerender } = renderHook(() => useRecentVods(), {
        wrapper: SharedCacheWrapper,
      });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(mockApiClient).toHaveBeenCalledTimes(1);

      // 리렌더
      rerender();

      // 캐시된 데이터 사용으로 API 재호출 없음
      expect(mockApiClient).toHaveBeenCalledTimes(1);
      expect(result.current.vods).toEqual(mockVods);
    });
  });

  describe('Mutate', () => {
    it('should provide mutate function to manually refresh', async () => {
      mockApiClient.mockResolvedValue(mockVods);

      const { result } = renderHook(() => useRecentVods(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(typeof result.current.mutate).toBe('function');

      // mutate 호출
      await act(async () => {
        result.current.mutate();
      });

      // mutate 후 API 재호출 확인
      await waitFor(() => {
        expect(mockApiClient).toHaveBeenCalledTimes(2);
      });
    });
  });

  describe('Status filtering', () => {
    it('should only fetch meetings with processing or ended status', async () => {
      mockApiClient.mockResolvedValueOnce(mockVods);

      renderHook(() => useRecentVods(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(mockApiClient).toHaveBeenCalled();
      });

      const calledUrl = mockApiClient.mock.calls[0]?.[0];
      expect(calledUrl).toContain('status=processing%2Cended');
    });
  });
});
