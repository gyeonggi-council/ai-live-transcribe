import React from 'react';

import { act, renderHook, waitFor } from '@testing-library/react';
import { SWRConfig } from 'swr';

import { apiClient } from '@/lib/api';
import type { MeetingType } from '@/types';

import { useVodList, type UseVodListOptions } from '../useVodList';

// Mock the api module
jest.mock('@/lib/api', () => ({
  apiClient: jest.fn(),
}));

const mockedApiClient = apiClient as jest.MockedFunction<typeof apiClient>;

describe('useVodList', () => {
  const mockVods: MeetingType[] = [
    {
      id: 'vod-1',
      title: '제122회 본회의',
      meeting_date: '2026-02-04',
      stream_url: null,
      vod_url: 'https://vod.example.com/122',
      status: 'ended',
      duration_seconds: 5400,
      created_at: '2026-02-04T09:00:00Z',
      updated_at: '2026-02-04T11:30:00Z',
    },
    {
      id: 'vod-2',
      title: '제121회 상임위원회',
      meeting_date: '2026-02-03',
      stream_url: null,
      vod_url: 'https://vod.example.com/121',
      status: 'processing',
      duration_seconds: 7200,
      created_at: '2026-02-03T09:00:00Z',
      updated_at: '2026-02-03T11:00:00Z',
    },
  ];

  const createWrapper = () => {
    const TestWrapper = ({ children }: { children: React.ReactNode }) => (
      <SWRConfig value={{ provider: () => new Map() }}>
        {children}
      </SWRConfig>
    );

    return TestWrapper;
  };

  beforeEach(() => {
    jest.clearAllMocks();
    mockedApiClient.mockResolvedValue(mockVods);
  });

  const renderVodHook = async (options?: UseVodListOptions) => {
    const result = renderHook(() => useVodList(options), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await Promise.resolve();
    });

    return result;
  };

  describe('Initial State', () => {
    it('loads data on initial render', async () => {
      const { result } = await renderVodHook();

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(result.current.vods).toEqual(mockVods);
    });
  });

  describe('Data Fetching', () => {
    it('fetches VOD list from API', async () => {
      const { result } = await renderVodHook();

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(mockedApiClient).toHaveBeenCalledWith(
        expect.stringContaining('/api/meetings')
      );
      expect(mockedApiClient).toHaveBeenCalledWith(
        expect.stringContaining('status=processing%2Cended')
      );
    });

    it('returns VOD data after fetch', async () => {
      const { result } = await renderVodHook();

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(result.current.vods).toEqual(mockVods);
    });
  });

  describe('Pagination Support', () => {
    it('sends offset derived from page to API', async () => {
      // page=2 with default perPage=10 → offset = (2-1)*10 = 10
      const { result } = await renderVodHook({ page: 2 });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(mockedApiClient).toHaveBeenCalledWith(
        expect.stringContaining('offset=10')
      );
    });

    it('sends limit derived from perPage to API', async () => {
      const { result } = await renderVodHook({ page: 1, perPage: 20 });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(mockedApiClient).toHaveBeenCalledWith(
        expect.stringContaining('limit=20')
      );
    });

    it('returns pagination info', async () => {
      const { result } = await renderVodHook();

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      // Backend returns plain array; total is array length
      expect(result.current.total).toBe(mockVods.length);
      expect(result.current.page).toBe(1);
      expect(result.current.perPage).toBe(10);
      // 2 items < 10 perPage, so hasNext is false
      expect(result.current.hasNext).toBe(false);
    });

    it('sets hasNext true when returned items fill the page', async () => {
      // Create 10 items to fill a page
      const fullPage = Array.from({ length: 10 }, (_, i) => ({
        ...mockVods[0],
        id: `vod-${i}`,
      }));
      mockedApiClient.mockResolvedValue(fullPage);

      const { result } = await renderVodHook();

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(result.current.hasNext).toBe(true);
    });
  });

  describe('Error Handling', () => {
    it('returns error when API fails', async () => {
      const mockError = new Error('Network error');
      mockedApiClient.mockRejectedValue(mockError);

      const { result } = await renderVodHook();

      await waitFor(() => {
        expect(result.current.error).not.toBeNull();
      });

      expect(result.current.error).toBe(mockError);
      expect(result.current.vods).toEqual([]);
    });
  });

  describe('Mutate Function', () => {
    it('provides mutate function for refetching', async () => {
      const { result } = await renderVodHook();

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(typeof result.current.mutate).toBe('function');
    });
  });

  describe('Default Values', () => {
    it('uses default page=1 (offset=0) when not specified', async () => {
      const { result } = await renderVodHook();

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(mockedApiClient).toHaveBeenCalledWith(
        expect.stringContaining('offset=0')
      );
    });

    it('uses default perPage=10 (limit=10) when not specified', async () => {
      const { result } = await renderVodHook();

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(mockedApiClient).toHaveBeenCalledWith(
        expect.stringContaining('limit=10')
      );
    });
  });
});
