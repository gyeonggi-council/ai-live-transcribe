'use client';

import useSWR from 'swr';

import { apiClient } from '@/lib/api';
import type { UpcomingScheduleType } from '@/types';

async function fetcher(endpoint: string): Promise<UpcomingScheduleType> {
  return apiClient<UpcomingScheduleType>(endpoint);
}

export interface UseUpcomingScheduleResult {
  schedule: UpcomingScheduleType | null;
  isLoading: boolean;
  error: Error | null;
}

/**
 * 다가오는 의사일정 — 의회 홈페이지 의정캘린더 수집분.
 *
 * 서버가 30분마다 다시 맞추므로 화면도 그 정도면 충분하다. 안건은 수시로 바뀌지만
 * 초 단위로 볼 필요는 없고, 회의 중 종일 열어 두는 화면이라 잦은 폴링이 더 해롭다.
 * `includeToday=false` 가 기본인 이유 — 오늘 것은 '오늘 예정' 섹션이 이미 담당한다.
 */
export function useUpcomingSchedule(
  days = 7,
  includeToday = false,
): UseUpcomingScheduleResult {
  const { data, error, isLoading } = useSWR<UpcomingScheduleType>(
    `/api/schedule/upcoming?days=${days}&include_today=${includeToday}`,
    fetcher,
    { refreshInterval: 10 * 60 * 1000, revalidateOnFocus: true },
  );

  return {
    schedule: data ?? null,
    isLoading,
    error: error ?? null,
  };
}
