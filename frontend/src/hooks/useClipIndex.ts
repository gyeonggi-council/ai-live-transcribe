'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import useSWR from 'swr';

import { getClipIndex, updateClipOffset } from '@/lib/api';
import type { ClipIndexType } from '@/types';

const OFFSET_SAVE_DEBOUNCE_MS = 600;

export interface UseClipIndexResult {
  index: ClipIndexType | null;
  isLoading: boolean;
  error: Error | null;
  /** 초안(실시간 자막) 인덱스의 시간축 보정값(초). 서버에 debounce 저장된다 */
  offset: number;
  setOffset: (v: number) => void;
  /** 표시할 때 세그먼트에 더할 값 — source=live 일 때만 offset, 아니면 0 */
  shift: number;
  refresh: () => void;
}

/**
 * 의원별 발언 구간 인덱스 + 초안 오프셋.
 *
 * 서버가 주는 live 세그먼트는 STT 시계(미보정)라 화면에서는 `start + shift` 로 그린다.
 * 오프셋은 회의당 하나이며 바꾸면 600ms 뒤 PUT 으로 저장한다(실패해도 화면은 유지).
 */
export function useClipIndex(meetingId: string | null): UseClipIndexResult {
  const { data, error, isLoading, mutate } = useSWR<ClipIndexType>(
    meetingId ? `clip-index:${meetingId}` : null,
    () => getClipIndex(meetingId as string),
    { revalidateOnFocus: false }
  );
  const [offset, setOffsetState] = useState(0);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (data) setOffsetState(Number(data.time_offset) || 0);
  }, [data]);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const setOffset = useCallback(
    (v: number) => {
      const val = Number.isFinite(v) ? Math.round(v * 10) / 10 : 0;
      setOffsetState(val);
      if (!meetingId) return;
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => {
        updateClipOffset(meetingId, val).catch(() => {
          /* 저장 실패는 다음 변경 때 다시 시도된다 */
        });
      }, OFFSET_SAVE_DEBOUNCE_MS);
    },
    [meetingId]
  );

  return {
    index: data ?? null,
    isLoading: Boolean(meetingId) && isLoading,
    error: (error as Error) ?? null,
    offset,
    setOffset,
    shift: data?.source === 'live' ? offset : 0,
    refresh: () => {
      void mutate();
    },
  };
}
