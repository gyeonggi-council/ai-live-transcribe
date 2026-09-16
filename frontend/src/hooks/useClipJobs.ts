'use client';

import useSWR from 'swr';

import { listClipJobs } from '@/lib/api';
import type { ClipJobListResponseType, ClipJobType } from '@/types';

export const CLIP_JOB_POLL_MS = 3000;

export function isActiveClipJob(job: ClipJobType): boolean {
  return job.status === 'queued' || job.status === 'running';
}

export interface UseClipJobsOptions {
  scope?: 'mine' | 'all';
  meetingId?: string | null;
  days?: number;
  enabled?: boolean;
}

export interface UseClipJobsResult {
  jobs: ClipJobType[];
  store: ClipJobListResponseType['store'] | null;
  isLoading: boolean;
  error: Error | null;
  refresh: () => void;
}

/**
 * 추출 기록(기본 7일). 진행 중인 잡이 하나라도 있으면 3초마다 다시 읽는다 —
 * 진행률 폴링을 따로 두지 않고 목록 하나로 끝낸다.
 */
export function useClipJobs(o: UseClipJobsOptions = {}): UseClipJobsResult {
  const scope = o.scope ?? 'mine';
  const days = o.days ?? 7;
  const enabled = o.enabled ?? true;
  const key = enabled ? ['clip-jobs', scope, o.meetingId ?? '', days] : null;
  const { data, error, isLoading, mutate } = useSWR<ClipJobListResponseType>(
    key,
    () => listClipJobs({ scope, days, meetingId: o.meetingId ?? null }),
    {
      revalidateOnFocus: true,
      refreshInterval: (latest) =>
        latest?.jobs?.some(isActiveClipJob) ? CLIP_JOB_POLL_MS : 0,
    }
  );
  return {
    jobs: data?.jobs ?? [],
    store: data?.store ?? null,
    isLoading: enabled && isLoading,
    error: (error as Error) ?? null,
    refresh: () => {
      void mutate();
    },
  };
}
