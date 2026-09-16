/**
 * useLiveMeeting 훅 테스트
 */

import type { ReactNode } from 'react';

import { act, renderHook, waitFor } from '@testing-library/react';
import { SWRConfig } from 'swr';

import { apiClient } from '@/lib/api';
import type { MeetingType } from '@/types';

import { useLiveMeeting } from '../useLiveMeeting';

// Mock the API client
jest.mock('@/lib/api', () => ({
  apiClient: jest.fn(),
  API_BASE_URL: 'http://localhost:8000',
}));

const mockApiClient = apiClient as jest.MockedFunction<typeof apiClient>;

// Mock meeting data
const mockLiveMeeting: MeetingType = {
  id: 'meeting-1',
  title: '제123회 본회의',
  meeting_date: '2026-02-05',
  stream_url: 'https://stream.example.com/live/playlist.m3u8',
  vod_url: null,
  status: 'live',
  duration_seconds: null,
  created_at: '2026-02-05T09:00:00Z',
  updated_at: '2026-02-05T09:00:00Z',
};

// SWR test wrapper to isolate cache between tests
function createWrapper() {
  const TestWrapper = ({ children }: { children: ReactNode }) => {
    return (
      <SWRConfig value={{ provider: () => new Map() }}>
        {children}
      </SWRConfig>
    );
  };

  return TestWrapper;
}

describe('useLiveMeeting', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  const renderLiveHook = async () => {
    const result = renderHook(() => useLiveMeeting(), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await Promise.resolve();
    });

    return result;
  };

  describe('Data fetching', () => {
    it('should fetch live meeting data successfully', async () => {
      mockApiClient.mockResolvedValueOnce(mockLiveMeeting);

      const { result } = await renderLiveHook();

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(result.current.meeting).toEqual(mockLiveMeeting);
      expect(result.current.error).toBeNull();
      expect(mockApiClient).toHaveBeenCalledWith('/api/meetings/live');
    });

    it('should return null when no live meeting exists', async () => {
      mockApiClient.mockResolvedValueOnce(null);

      const { result } = await renderLiveHook();

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(result.current.meeting).toBeNull();
      expect(result.current.error).toBeNull();
    });
  });

  describe('Loading state', () => {
    it('should show loading state while fetching', async () => {
      jest.useFakeTimers();

      mockApiClient.mockImplementation(
        () =>
          new Promise((resolve) => {
            setTimeout(() => resolve(mockLiveMeeting), 100);
          })
      );

      const { result } = await renderLiveHook();

      expect(result.current.isLoading).toBe(true);
      expect(result.current.meeting).toBeNull();

      await act(async () => {
        jest.advanceTimersByTime(100);
      });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(result.current.meeting).toEqual(mockLiveMeeting);
    });
  });

  describe('Error handling', () => {
    it('should handle API error gracefully', async () => {
      mockApiClient.mockRejectedValueOnce(new Error('API Error'));

      const { result } = await renderLiveHook();

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(result.current.error).toBeTruthy();
      expect(result.current.meeting).toBeNull();
    });

    it('should handle network error', async () => {
      mockApiClient.mockRejectedValueOnce(new Error('Network error'));

      const { result } = await renderLiveHook();

      await waitFor(() => {
        expect(result.current.error).not.toBeNull();
      });

      expect(result.current.meeting).toBeNull();
    });
  });

  describe('Polling', () => {
    it('should poll every 5 seconds', async () => {
      mockApiClient.mockResolvedValue(mockLiveMeeting);
      jest.useFakeTimers();

      await renderLiveHook();

      await waitFor(() => {
        expect(mockApiClient).toHaveBeenCalledTimes(1);
      });

      await act(async () => {
        jest.advanceTimersByTime(5000);
      });

      await waitFor(() => {
        expect(mockApiClient).toHaveBeenCalledTimes(2);
      });

      await act(async () => {
        jest.advanceTimersByTime(5000);
      });

      await waitFor(() => {
        expect(mockApiClient).toHaveBeenCalledTimes(3);
      });
    });

    it('should update data when meeting status changes', async () => {
      const updatedMeeting = { ...mockLiveMeeting, status: 'ended' as const };
      jest.useFakeTimers();

      mockApiClient
        .mockResolvedValueOnce(mockLiveMeeting)
        .mockResolvedValueOnce(updatedMeeting);

      const { result } = await renderLiveHook();

      await waitFor(() => {
        expect(result.current.meeting?.status).toBe('live');
      });

      await act(async () => {
        jest.advanceTimersByTime(5000);
      });

      await waitFor(() => {
        expect(result.current.meeting?.status).toBe('ended');
      });
    });
  });

  describe('Mutate', () => {
    it('should provide mutate function to manually refresh', async () => {
      mockApiClient.mockResolvedValue(mockLiveMeeting);

      const { result } = await renderLiveHook();

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(typeof result.current.mutate).toBe('function');

      await act(async () => {
        result.current.mutate();
      });

      await waitFor(() => {
        expect(mockApiClient).toHaveBeenCalledTimes(2);
      });
    });
  });
});
