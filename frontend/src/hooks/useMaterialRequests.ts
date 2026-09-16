/**
 * useMaterialRequests 훅
 *
 * 회의의 요구자료(의원 자료 제출 요구) 감지 목록을 관리합니다.
 * - REST로 초기 목록 로드 (SWR)
 * - 라이브: WS material_request_detected 이벤트를 appendRequest로 증분 반영
 * - 상태 변경(확인/무시/등록됨)·수동 추가 낙관적 반영
 */

'use client';

import { useCallback } from 'react';

import useSWR from 'swr';

import {
  createMaterialRequest,
  getMaterialRequests,
  scanMaterialRequests,
  updateMaterialRequest,
} from '@/lib/api';
import type { MaterialRequestType } from '@/types';

export interface UseMaterialRequestsResult {
  requests: MaterialRequestType[];
  isLoading: boolean;
  error: Error | null;
  /** WS 감지 이벤트 증분 반영 (중복 id 무시) */
  appendRequest: (request: MaterialRequestType) => void;
  /** 상태/내용 수정 (낙관적 갱신) */
  update: (
    requestId: string,
    updates: Partial<
      Pick<MaterialRequestType, 'status' | 'summary' | 'councilor_name' | 'department'>
    >
  ) => Promise<void>;
  /** 수동 추가 */
  addManual: (body: {
    summary: string;
    councilor_name?: string;
    start_time?: number;
  }) => Promise<void>;
  /** VOD/사후 전체 자막 AI 스캔 */
  scan: () => Promise<number>;
  isScanning: boolean;
  refresh: () => void;
}

export function useMaterialRequests(
  meetingId: string | null | undefined
): UseMaterialRequestsResult {
  const key = meetingId ? `/api/meetings/${meetingId}/material-requests` : null;
  const { data, error, isLoading, mutate, isValidating } = useSWR<MaterialRequestType[]>(
    key,
    () => getMaterialRequests(meetingId as string),
    { revalidateOnFocus: false }
  );

  // 방어: API 오류 응답이 배열이 아닌 형태로 와도 UI가 죽지 않게
  const requests = Array.isArray(data) ? data : [];

  const appendRequest = useCallback(
    (request: MaterialRequestType) => {
      mutate(
        (prev) => {
          const list = prev ?? [];
          if (list.some((r) => r.id === request.id)) return list;
          return [...list, request].sort(
            (a, b) => (a.start_time ?? 0) - (b.start_time ?? 0)
          );
        },
        { revalidate: false }
      );
    },
    [mutate]
  );

  const update = useCallback(
    async (
      requestId: string,
      updates: Partial<
        Pick<MaterialRequestType, 'status' | 'summary' | 'councilor_name' | 'department'>
      >
    ) => {
      // 낙관적 갱신 → 실패 시 재검증으로 롤백
      mutate(
        (prev) => (prev ?? []).map((r) => (r.id === requestId ? { ...r, ...updates } : r)),
        { revalidate: false }
      );
      try {
        await updateMaterialRequest(meetingId as string, requestId, updates);
      } catch (e) {
        await mutate();
        throw e;
      }
    },
    [meetingId, mutate]
  );

  const addManual = useCallback(
    async (body: { summary: string; councilor_name?: string; start_time?: number }) => {
      const created = await createMaterialRequest(meetingId as string, body);
      appendRequest(created);
    },
    [meetingId, appendRequest]
  );

  const scan = useCallback(async () => {
    const result = await scanMaterialRequests(meetingId as string);
    await mutate(result.items, { revalidate: false });
    return result.count;
  }, [meetingId, mutate]);

  return {
    requests,
    isLoading,
    error: error ?? null,
    appendRequest,
    update,
    addManual,
    scan,
    isScanning: isValidating,
    refresh: () => void mutate(),
  };
}
