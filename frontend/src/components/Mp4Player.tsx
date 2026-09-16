'use client';

import React, { useEffect, useRef, useState } from 'react';

export interface Mp4PlayerProps {
  vodUrl: string;
  videoRef?: React.MutableRefObject<HTMLVideoElement | null>;
  onTimeUpdate?: (currentTime: number) => void;
  onError?: (error: Error) => void;
  onReady?: () => void;
  /**
   * 처음 열 때 시작할 시점(초). 통합검색·AI 답변에서 특정 발언으로 들어올 때 쓴다.
   *
   * ★"재생된 뒤에 시크"가 아니라 **처음부터 그 위치를 연다.** 둘의 차이가 크다 —
   *   KMS 스트림은 조각 하나가 12.5초·약 3.6MB 라, 0초부터 열고 나중에 옮기면
   *   **엉뚱한 조각 하나를 먼저 통째로 받은 뒤** 다시 목표 조각을 받는다. 기다림이
   *   두 번이고 받는 양이 두 배다(2026-08-25 "재생이 너무 느리다" 의 원인).
   *   게다가 그 시크가 조각 경계에서 되돌아가 **시점 이동 자체가 먹지 않았다.**
   */
  startTime?: number;
  /**
   * 컨테이너 비율/높이 클래스 (기본 aspect-video). 클립 워크벤치는 KMS 영상이 4:3 이라
   * 'aspect-[4/3] max-h-[56vh] mx-auto' 로 좌우 검은 띠를 없앤다.
   */
  aspectClassName?: string;
  /**
   * 영상 위에 겹쳐 그릴 요소 (실제 시각 배지 등). 컨테이너가 relative 이므로
   * absolute 로 배치된다. **의원 영상 추출(클립) 화면은 넘기지 않는다** — 추출본은
   * 원본 영상 그대로여야 한다는 담당자 결정(2026-09-16).
   */
  overlay?: React.ReactNode;
}

/**
 * KMS VOD 재생 URL 변환 (2026-07-21 의회 KMS 개편 대응)
 *
 * KMS가 VOD 재생을 mp4 직접 다운로드에서 Wowza HLS 스트리밍으로 전환했고,
 * mp4 직접 요청은 보안장비에서 지연·차단되어 브라우저 재생이 무한 로딩된다.
 * 기존에 등록된 mp4 주소를 KMS 공식 플레이어와 동일한 HLS 주소로 변환한다:
 *   https://kms.ggc.go.kr/mp4/{path}.mp4
 *   → https://kms.ggc.go.kr/vod/_definst_/{path}.mp4/playlist.m3u8
 * (DB의 vod_url은 mp4 원본을 유지 — 백엔드 STT 다운로드 등 서버측은 mp4 사용)
 */
const KMS_MP4_RE = /^https?:\/\/kms\.ggc\.go\.kr\/mp4\/(.+\.mp4)$/i;

export function toPlayableVodUrl(vodUrl: string): string {
  const m = vodUrl.match(KMS_MP4_RE);
  return m ? `https://kms.ggc.go.kr/vod/_definst_/${m[1]}/playlist.m3u8` : vodUrl;
}

export function isHlsUrl(url: string): boolean {
  return /\.m3u8(\?|$)/i.test(url);
}

export default function Mp4Player({
  vodUrl,
  videoRef,
  onTimeUpdate,
  onError,
  onReady,
  startTime,
  aspectClassName = 'aspect-video',
  overlay,
}: Mp4PlayerProps) {
  const internalRef = useRef<HTMLVideoElement>(null);
  const hlsRef = useRef<{ destroy: () => void } | null>(null);
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;
  // 시작 시점은 **플레이어를 만들 때 한 번** 쓴다. 값이 바뀌었다고 영상을 다시
  // 만들면 안 되므로(같은 회의 안에서 다른 발언으로 옮길 때) ref 로 읽는다.
  const startTimeRef = useRef(startTime);
  startTimeRef.current = startTime;
  const [isLoading, setIsLoading] = useState(true);
  const [hasError, setHasError] = useState(false);

  const playUrl = toPlayableVodUrl(vodUrl);
  const useHls = isHlsUrl(playUrl);

  useEffect(() => {
    if (videoRef) {
      videoRef.current = internalRef.current;
    }
  }, [videoRef]);

  useEffect(() => {
    setIsLoading(true);
    setHasError(false);
  }, [vodUrl]);

  // HLS(m3u8) 재생 — hls.js 동적 로드 (HlsPlayer와 달리 라이브 튜닝 없이 VOD 기본 설정).
  // ★hls.js를 우선 사용: Chrome은 canPlayType('…mpegurl')에 'maybe'를 주면서도
  //   실제로는 m3u8 네이티브 재생이 안 된다(실측) — 네이티브 src는 MSE 미지원
  //   브라우저(iOS Safari)용 폴백으로만 쓴다.
  useEffect(() => {
    if (!useHls) return;
    const video = internalRef.current;
    if (!video) return;

    let cancelled = false;
    void (async () => {
      const HlsLib = (await import('hls.js')).default;
      if (cancelled || !internalRef.current) return;
      if (!HlsLib.isSupported()) {
        // MSE 미지원(iOS Safari 등) — 네이티브 HLS 재생 폴백
        if (internalRef.current.canPlayType('application/vnd.apple.mpegurl')) {
          internalRef.current.src = playUrl;
        } else {
          setHasError(true);
          setIsLoading(false);
          onErrorRef.current?.(new Error('HLS unsupported'));
        }
        return;
      }
      const begin = startTimeRef.current;
      const hls = new HlsLib({
        // 목표 시점의 조각부터 받는다 (-1 = 처음부터). 이것이 "시점 이동이 먹지
        // 않는다"와 "재생이 느리다"를 함께 푸는 자리다.
        startPosition: typeof begin === 'number' && begin > 0 ? begin : -1,
        // 미디어가 붙기 전에 첫 조각을 미리 받아 첫 화면까지의 대기를 줄인다
        startFragPrefetch: true,
      });
      hlsRef.current = hls;
      hls.attachMedia(internalRef.current);
      hls.loadSource(playUrl);
      hls.on(HlsLib.Events.ERROR, (_event: unknown, data: { fatal?: boolean; type?: string }) => {
        if (data?.fatal) {
          setHasError(true);
          setIsLoading(false);
          onErrorRef.current?.(new Error(`HLS error: ${data.type ?? 'unknown'}`));
        }
      });
    })();

    return () => {
      cancelled = true;
      hlsRef.current?.destroy();
      hlsRef.current = null;
    };
  }, [playUrl, useHls]);

  const handleLoadedData = () => {
    setIsLoading(false);
    onReady?.();
  };

  // HLS 가 아닌 일반 mp4 는 hls.js 의 startPosition 이 없으므로, 길이를 알게 된
  // 순간(loadedmetadata) 한 번 옮긴다. 브라우저가 그 지점부터 범위 요청을 한다.
  const startAppliedRef = useRef(false);
  const handleLoadedMetadata = () => {
    const begin = startTimeRef.current;
    const video = internalRef.current;
    if (useHls || startAppliedRef.current || !video) return;
    if (typeof begin !== 'number' || begin <= 0) return;
    startAppliedRef.current = true;
    try {
      video.currentTime = begin;
    } catch {
      /* 시크 실패는 치명적이지 않다 */
    }
  };

  const handleError = () => {
    setHasError(true);
    setIsLoading(false);
    onError?.(new Error('Video error'));
  };

  const handleTimeUpdate = () => {
    if (internalRef.current && onTimeUpdate) {
      onTimeUpdate(internalRef.current.currentTime);
    }
  };

  // 영상 화면 클릭 → 재생/일시정지 토글 (유튜브식)
  const togglePlay = () => {
    const v = internalRef.current;
    if (!v) return;
    if (v.paused) {
      v.play().catch(() => {});
    } else {
      v.pause();
    }
  };

  return (
    <div
      data-testid="mp4-player-container"
      className={`relative bg-black rounded-lg overflow-hidden ${aspectClassName}`}
    >
      <video
        ref={internalRef}
        data-testid="mp4-video"
        // HLS는 hls.js가 MSE로 attach하므로 src를 직접 지정하지 않는다
        src={useHls ? undefined : playUrl}
        className="w-full h-full cursor-pointer"
        onClick={togglePlay}
        onLoadedMetadata={handleLoadedMetadata}
        onLoadedData={handleLoadedData}
        onError={handleError}
        onTimeUpdate={handleTimeUpdate}
      />

      {overlay}

      {isLoading && (
        <div
          data-testid="loading-spinner"
          className="absolute inset-0 flex items-center justify-center bg-black/50"
        >
          <div className="w-12 h-12 border-4 border-gray-300 border-t-primary rounded-full animate-spin" />
        </div>
      )}

      {hasError && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/80 text-white">
          <svg
            className="w-12 h-12 text-error mb-4"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          <p className="text-center">영상을 불러올 수 없습니다.</p>
          <p className="text-sm text-gray-400 mt-1">새로고침해주세요.</p>
        </div>
      )}
    </div>
  );
}
