/**
 * useLiveMeeting 훅
 *
 * 실시간 회의 정보를 가져오고 5초마다 폴링합니다.
 * channelId를 전달하면 해당 채널의 실시간 회의만 조회합니다.
 */

'use client';

import useSWR from 'swr';

import { apiClient } from '@/lib/api';
import type { MeetingType } from '@/types';

const POLLING_INTERVAL = 5000; // 5초

export interface UseLiveMeetingResult {
  meeting: MeetingType | null;
  isLoading: boolean;
  error: Error | null;
  mutate: () => void;
}

async function fetcher(endpoint: string): Promise<MeetingType | null> {
  return apiClient<MeetingType | null>(endpoint);
}

/**
 * 실시간 회의 정보를 가져오는 훅
 *
 * @param channelId - 채널 ID (예: 'ch14'). 없으면 전체 조회.
 */
export function useLiveMeeting(channelId?: string): UseLiveMeetingResult {
  const endpoint = channelId
    ? `/api/meetings/live?channel=${channelId}`
    : '/api/meetings/live';

  const { data, error, isLoading, mutate } = useSWR<MeetingType | null>(
    endpoint,
    fetcher,
    {
      refreshInterval: POLLING_INTERVAL,
      revalidateOnFocus: true,
      revalidateOnReconnect: true,
      errorRetryCount: 3,
      errorRetryInterval: 1000,
    }
  );

  return {
    meeting: data ?? null,
    isLoading,
    error: error ?? null,
    mutate: () => {
      mutate();
    },
  };
}

export default useLiveMeeting;
