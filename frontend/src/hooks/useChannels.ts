'use client';

import useSWR from 'swr';

import { apiClient } from '@/lib/api';
import type { ChannelType } from '@/types';

async function fetcher(endpoint: string): Promise<ChannelType[]> {
  return apiClient<ChannelType[]>(endpoint);
}

export interface UseChannelsResult {
  channels: ChannelType[];
  isLoading: boolean;
  error: Error | null;
}

export function useChannels(): UseChannelsResult {
  const { data, error, isLoading } = useSWR<ChannelType[]>(
    '/api/channels',
    fetcher,
  );

  return {
    channels: data ?? [],
    isLoading,
    error: error ?? null,
  };
}

export default useChannels;
