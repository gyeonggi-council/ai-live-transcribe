'use client';

import { useEffect, useState } from 'react';

import { apiClient } from '@/lib/api';
import type { SubtitleType } from '@/types';

const PAGE_SIZE = 1000; // 백엔드 limit 상한
const MAX_PAGES = 20; // 안전 상한 (20,000건) — 장시간 본회의 최대 1617건 관찰

/**
 * 회의 자막 전체를 페이지 순회로 받는다 — 발언영상 워크벤치의 자막 패널용(2026-09-11 담당자 요청).
 * 종류는 서버 기본값(AI 자막이 있으면 AI — VOD 시간축과 같다)을 따른다.
 * 한 페이지가 올 때마다 화면에 붙인다(vod/[id] 화면의 loadSubtitles 와 같은 규칙).
 * 자막 조회는 공개 API 라 로그인·의회망 손님 모두 된다. 실패해도 자르기는 되므로 조용히 빈 목록.
 */
export function useMeetingSubtitles(meetingId: string | null): { subtitles: SubtitleType[]; isLoading: boolean } {
  const [subtitles, setSubtitles] = useState<SubtitleType[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    setSubtitles([]);
    if (!meetingId) {
      setIsLoading(false);
      return undefined;
    }
    const state = { cancelled: false };
    (async () => {
      setIsLoading(true);
      const all: SubtitleType[] = [];
      try {
        for (let page = 0; page < MAX_PAGES; page++) {
          const resp = await apiClient<{ items: SubtitleType[]; total: number }>(
            `/api/meetings/${meetingId}/subtitles?limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`
          );
          if (state.cancelled) return;
          const items = resp.items ?? [];
          all.push(...items);
          setSubtitles([...all]);
          if (items.length < PAGE_SIZE) break;
          if (resp.total && all.length >= resp.total) break;
        }
      } catch {
        // 자막이 없어도 영상 자르기는 된다 — 패널이 "자막 없음" 을 보여 준다
      } finally {
        if (!state.cancelled) setIsLoading(false);
      }
    })();
    return () => {
      state.cancelled = true;
    };
  }, [meetingId]);

  return { subtitles, isLoading };
}
