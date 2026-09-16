'use client';

import useSWR from 'swr';

import { apiClient } from '@/lib/api';
import type { MeetingType } from '@/types';

const DEFAULT_PAGE = 1;
const DEFAULT_PER_PAGE = 10;

export interface UseVodListOptions {
  page?: number;
  perPage?: number;
  /** false 지정 시 API 호출 자체를 건너뜀 (UI 숨김 모드에서 백엔드 부하 절감) */
  enabled?: boolean;
  /**
   * API status 쿼리 파라미터. 기본값 'processing,ended'.
   * '/vod' 페이지에서 진행 중(live) 회의도 포함하려면 'live,processing,ended' 지정.
   */
  statuses?: string;
}

export interface UseVodListResult {
  vods: MeetingType[];
  isLoading: boolean;
  error: Error | null;
  total: number;
  page: number;
  perPage: number;
  hasNext: boolean;
  totalPages: number;
  mutate: () => void;
}

/**
 * SWR fetcher for VOD list
 */
async function fetcher(endpoint: string): Promise<MeetingType[]> {
  return apiClient<MeetingType[]>(endpoint);
}

/**
 * VOD 목록을 가져오는 훅
 *
 * processing 및 ended 상태의 회의 목록을 페이지네이션과 함께 제공합니다.
 *
 * @param options - 옵션 (page, perPage)
 * @returns VOD 목록, 로딩 상태, 에러, 페이지네이션 정보
 */
export function useVodList(options?: UseVodListOptions): UseVodListResult {
  const page = options?.page ?? DEFAULT_PAGE;
  const perPage = options?.perPage ?? DEFAULT_PER_PAGE;
  const enabled = options?.enabled ?? true;
  const statuses = options?.statuses ?? 'processing,ended';

  // 백엔드는 limit(<=100) + offset 기반 — per_page/page를 인식하지 않으므로
  // 여기서 limit/offset으로 변환. 100을 넘는 값은 clamp.
  const effectiveLimit = Math.min(perPage, 100);
  const offset = (page - 1) * effectiveLimit;
  const endpoint = `/api/meetings?status=${encodeURIComponent(statuses)}&limit=${effectiveLimit}&offset=${offset}`;

  const { data, error, isLoading, mutate } = useSWR<MeetingType[]>(
    enabled ? endpoint : null,
    fetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 30000,
      errorRetryCount: 3,
      errorRetryInterval: 1000,
    }
  );

  return {
    vods: data ?? [],
    isLoading,
    error: error ?? null,
    total: data?.length ?? 0,
    page,
    perPage,
    hasNext: (data?.length ?? 0) >= perPage,
    totalPages: 0,
    mutate: () => {
      mutate();
    },
  };
}

export default useVodList;
