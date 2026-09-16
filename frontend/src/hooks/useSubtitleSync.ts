/**
 * useSubtitleSync 훅
 *
 * VOD 영상과 자막을 동기화하는 훅입니다.
 *
 * 특징:
 * - 영상 시간 → 현재 자막 하이라이트 (timeupdate 이벤트 기반)
 * - 자막 클릭 → 영상 시점 이동 (seekTo)
 * - 재생 상태 추적 (play/pause 이벤트)
 * - autoScroll 옵션 (SubtitlePanel에서 currentTime을 사용)
 */

'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';

import type { SubtitleType } from '@/types';

/**
 * 훅 옵션 인터페이스
 */
export interface UseSubtitleSyncOptions {
  /** 자막 배열 */
  subtitles: SubtitleType[];
  /** 비디오 요소 Ref */
  videoRef: React.MutableRefObject<HTMLVideoElement | null>;
  /** 자동 스크롤 여부 (기본값: true) */
  autoScroll?: boolean;
}

/**
 * 훅 반환 인터페이스
 */
export interface UseSubtitleSyncReturn {
  /** 현재 시간에 해당하는 자막 */
  currentSubtitle: SubtitleType | null;
  /** 현재 영상 시간 */
  currentTime: number;
  /** 특정 시간으로 이동 */
  seekTo: (time: number) => void;
  /** 재생 중인지 */
  isPlaying: boolean;
}

/**
 * 현재 시간에 해당하는 자막 찾기
 *
 * start_time은 inclusive, end_time은 exclusive로 판별합니다.
 */
function findCurrentSubtitle(
  subtitles: SubtitleType[],
  time: number
): SubtitleType | null {
  const found = subtitles.find(
    (s) => time >= s.start_time && time < s.end_time
  );
  return found ?? null;
}

/**
 * VOD 자막 동기화 훅
 *
 * @param options - 훅 옵션
 * @returns 현재 자막, 시간, seekTo 함수, 재생 상태
 *
 * @example
 * ```tsx
 * const videoRef = useRef<HTMLVideoElement>(null);
 * const { currentSubtitle, currentTime, seekTo, isPlaying } = useSubtitleSync({
 *   subtitles,
 *   videoRef,
 *   autoScroll: true,
 * });
 *
 * return (
 *   <>
 *     <video ref={videoRef} src={vodUrl} />
 *     <SubtitlePanel
 *       subtitles={subtitles}
 *       currentTime={currentTime}
 *       onSubtitleClick={seekTo}
 *     />
 *   </>
 * );
 * ```
 */
export function useSubtitleSync(
  options: UseSubtitleSyncOptions
): UseSubtitleSyncReturn {
  const { subtitles, videoRef } = options;

  // State
  const [currentTime, setCurrentTime] = useState<number>(0);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);

  // 현재 시간에 해당하는 자막 계산
  const currentSubtitle = useMemo(
    () => findCurrentSubtitle(subtitles, currentTime),
    [subtitles, currentTime]
  );

  /**
   * 특정 시간으로 이동
   */
  const seekTo = useCallback(
    (time: number) => {
      const video = videoRef.current;
      if (!video) return;
      video.currentTime = time;
    },
    [videoRef]
  );

  // 비디오 이벤트 리스너 등록/해제
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const handleTimeUpdate = () => {
      setCurrentTime(video.currentTime);
    };

    const handlePlay = () => {
      setIsPlaying(true);
    };

    const handlePause = () => {
      setIsPlaying(false);
    };

    video.addEventListener('timeupdate', handleTimeUpdate);
    video.addEventListener('play', handlePlay);
    video.addEventListener('pause', handlePause);

    return () => {
      video.removeEventListener('timeupdate', handleTimeUpdate);
      video.removeEventListener('play', handlePlay);
      video.removeEventListener('pause', handlePause);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoRef]);

  return {
    currentSubtitle,
    currentTime,
    seekTo,
    isPlaying,
  };
}

export default useSubtitleSync;
