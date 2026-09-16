'use client';

import useSWR from 'swr';

import { isActiveClipJob } from '@/hooks/useClipJobs';
import { listMeetingAutoClips, listRecentAutoClips } from '@/lib/api';
import type { AutoClipListResponseType, ClipJobType } from '@/types';

/** 자르는 중인 자동 클립이 있으면 이 간격으로 다시 읽는다 — 한 의원이 몇 분씩 걸려 3초 폴링은 과하다 */
export const AUTO_CLIP_POLL_MS = 10000;

export interface UseAutoClipsOptions {
  /** 있으면 그 회의 것만, 없으면 최근 days 일 전체 */
  meetingId?: string | null;
  days?: number;
  enabled?: boolean;
}

export interface UseAutoClipsResult {
  jobs: ClipJobType[];
  notice: string | null;
  ttlDays: number | null;
  isLoading: boolean;
  error: Error | null;
  refresh: () => void;
}

/** 서버가 미리 잘라 둔 의원 영상(자동 클립). 워크벤치의 의원 카드·편집기·추출 기록이 같은 키를 공유한다. */
export function useAutoClips(o: UseAutoClipsOptions = {}): UseAutoClipsResult {
  const enabled = o.enabled ?? true;
  const days = o.days ?? 3;
  const key = enabled ? ['auto-clips', o.meetingId ?? 'recent', days] : null;
  const { data, error, isLoading, mutate } = useSWR<AutoClipListResponseType>(
    key,
    () => (o.meetingId ? listMeetingAutoClips(o.meetingId) : listRecentAutoClips(days)),
    {
      revalidateOnFocus: true,
      refreshInterval: (latest) => (latest?.jobs?.some(isActiveClipJob) ? AUTO_CLIP_POLL_MS : 0),
    }
  );
  return {
    jobs: data?.jobs ?? [],
    notice: data?.notice ?? null,
    ttlDays: data?.ttl_days ?? null,
    isLoading: enabled && isLoading,
    error: (error as Error) ?? null,
    refresh: () => {
      void mutate();
    },
  };
}
