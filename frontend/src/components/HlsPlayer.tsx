'use client';

import React, { useEffect, useRef, useState } from 'react';

import { clockFromPlayingDate, resolveSyncTargetSec, syncTargetFromSearch } from '@/utils/liveSync';

import type Hls from 'hls.js';

export interface HlsPlayerProps {
  streamUrl: string;
  videoRef?: React.MutableRefObject<HTMLVideoElement | null>;
  onError?: (error: Error) => void;
  onReady?: () => void;
  /**
   * 라이브 엣지로부터의 현재 재생 지연(초)을 1초 주기로 기록하는 ref.
   * 자막 정밀 동기화(영상시계 역산)에 사용. 측정 불가(네이티브 HLS 등)면 null.
   */
  latencyRef?: React.MutableRefObject<number | null>;
  /**
   * 지금 재생 위치의 자막 시계(초)를 읽는 함수를 담는 ref — 서버 보관분 재생목록의 PDT 를 hls.js
   * `playingDate` 로 읽는다. PDT 가 없으면(원본 재생목록 등) 함수가 null 을 돌려준다.
   */
  playingClockRef?: React.MutableRefObject<(() => number | null) | null>;
  /**
   * 영상 지연 목표(초). 부모가 `?sync=N` > 서버값(채널 상태 응답) > 빌드 기본 순으로 고른 값
   * (utils/liveSync.pickSyncTarget). 없으면 이 컴포넌트가 `?sync=N` > 빌드 기본으로 해석한다.
   * ★마운트 시 1회만 읽는다 — hls.js 는 시작 뒤 목표를 낮춰도 스스로 앞으로 못 따라오므로
   *   값이 바뀌어도 플레이어를 다시 만들지 않는다(재생 끊김 방지).
   */
  syncTargetSec?: number;
  /** hls.js 의 유효 목표 지연(targetLatency)을 1초 주기로 기록하는 ref — 스톨 뒤에도 목표가 그대로인지 본다 */
  targetLatencyRef?: React.MutableRefObject<number | null>;
}

const MAX_NETWORK_RETRIES = 3;

/**
 * 라이브 엣지에서 의도적으로 뒤로 잡는 재생 지연(초) — **빌드 기본(폴백)**.
 * 자막이 "영상이 그 발언에 도달하기 전에" 항상 준비되도록 영상을 자막 준비 지연보다
 * 깊게 늦춘다 → 시작시간 게이팅으로 완전 동기화 (VOD처럼). 값의 규칙:
 *   목표 = ceil(sync_need_p99 + 여유 1)   (sync_need = 자막 준비 지연 ready_lag + 수집 지연 edge_lag, 창마다 서버 계측)
 * 2026-09-03 본회의 실측(창 49개): 준비 지연 p50 10.7 · p95 13.8 · 최대 14.0초 → 20.
 * 2026-09-14 부터 **실제 목표는 서버가 준다**(채널 상태 응답 `sync_target_sec` = api env
 * LIVE_SYNC_TARGET_SEC, 재빌드 없이 조정 — 1단계 18). 이 상수는 서버에 못 닿을 때의 폴백이라 20 을 유지한다.
 * 자막은 재생목록 PDT(또는 실측 지연) 기준으로 게이팅되므로 동기화 자체는 항상 유지된다.
 * 서버 재생목록의 TARGETDURATION(10) 이 hls.js 의 바닥이라 10초 아래로는 못 내려간다.
 *
 * 현장 실험: URL 에 `?sync=N` 을 붙이면 그 세션만 N초로 동작한다(전체 새로고침 필요).
 * 줄일 때는 window.__syncDebug.lateCount 가 0 으로 유지되는지 본다.
 */
// 빈 문자열(Dockerfile ARG 미지정)·비정상 값은 기본값으로, 정상 값은 8~60 으로 클램프.
export const LIVE_SYNC_TARGET_SEC = resolveSyncTargetSec(process.env.NEXT_PUBLIC_LIVE_SYNC_SEC, 20);

const HlsPlayer = React.memo(function HlsPlayer({
  streamUrl,
  videoRef,
  onError,
  onReady,
  latencyRef,
  playingClockRef,
  syncTargetSec: syncTargetSecProp,
  targetLatencyRef,
}: HlsPlayerProps) {
  const internalRef = useRef<HTMLVideoElement>(null);
  // 목표는 스트림을 (재)시작할 때만 읽는다 — prop 변경이 hls 재생성으로 이어지지 않게 ref 로 든다
  const syncTargetPropRef = useRef(syncTargetSecProp);
  syncTargetPropRef.current = syncTargetSecProp;
  const hlsRef = useRef<Hls | null>(null);
  const networkRetryCount = useRef(0);
  const [isLoading, setIsLoading] = useState(true);
  const [hasError, setHasError] = useState(false);
  // 동기화 지연 톱업 진행 중 (일시정지로 라이브 지연을 목표치까지 확보)
  const [isSyncBuffering, setIsSyncBuffering] = useState(false);
  // 톱업 정지 남은 초 — 오버레이에 표시해 "왜 멈췄나"를 보이게 한다
  const [syncRemainingSec, setSyncRemainingSec] = useState(0);

  useEffect(() => {
    if (videoRef) {
      videoRef.current = internalRef.current;
    }
  }, [videoRef]);

  useEffect(() => {
    const videoElement = internalRef.current;
    if (!videoElement) return;

    setIsLoading(true);
    setHasError(false);
    setIsSyncBuffering(false);
    networkRetryCount.current = 0;

    // Cleanup previous HLS instance
    if (hlsRef.current) {
      hlsRef.current.destroy();
      hlsRef.current = null;
    }

    let cancelled = false;
    let latencyTimer: ReturnType<typeof setInterval> | null = null;
    let topUpTimer: ReturnType<typeof setInterval> | null = null;
    // 부모가 고른 값(?sync > 서버 > 빌드 기본) 이 있으면 그것, 없으면 세션 한정 `?sync=N` > 빌드 기본
    const syncTargetSec =
      syncTargetPropRef.current ??
      syncTargetFromSearch(typeof window !== 'undefined' ? window.location.search : undefined, LIVE_SYNC_TARGET_SEC);

    // hls.js를 동적 import — 라이브 영상이 실제 마운트될 때만 로드(번들 다이어트, ~150KB 분리)
    void (async () => {
      const HlsLib = (await import('hls.js')).default;
      if (cancelled || !internalRef.current) return;

      if (HlsLib.isSupported()) {
        const hls = new HlsLib({
          // 라이브 스트리밍 버퍼 최적화 — 자막 동기화를 위해 의도적으로 깊은 지연
          // (세그먼트 개수 기반 count 대신 절대 초로 지정)
          liveSyncDuration: syncTargetSec,
          // 목표보다 이만큼 더 밀리면 hls.js 가 따라잡는다. 20→10 (2026-09-03): 스톨 뒤
          // 최악 지연을 목표+10 으로 묶는다. 자막 게이팅은 실측 지연을 쓰므로 정합은 유지된다.
          liveMaxLatencyDuration: syncTargetSec + 10,
          // 스톨마다 목표를 +1초씩(상한 targetduration=10) 올리는 hls.js 기본을 끈다 — 회의 중 스톨 10번이면
          // 목표가 조용히 +10초 밀리고 아래 드리프트 스냅은 그 커진 목표에 착지했다(2026-09-14).
          liveSyncOnStallIncrease: 0,
          liveDurationInfinity: true,
          maxBufferLength: 30,
          maxMaxBufferLength: 120,
          maxBufferSize: 100 * 1000 * 1000,
          maxBufferHole: 0.5,
          highBufferWatchdogPeriod: 2,
          manifestLoadingMaxRetry: 10,
          manifestLoadingRetryDelay: 1000,
          levelLoadingMaxRetry: 10,
          levelLoadingRetryDelay: 1000,
          fragLoadingMaxRetry: 10,
          fragLoadingRetryDelay: 1000,
          lowLatencyMode: false,
          startLevel: -1,
          backBufferLength: 30,
        });
        hlsRef.current = hls;
        if (playingClockRef) {
          playingClockRef.current = () => clockFromPlayingDate(hls.playingDate?.getTime());
        }

        hls.attachMedia(videoElement);
        hls.loadSource(streamUrl);

        hls.on(HlsLib.Events.MANIFEST_PARSED, () => {
          setIsLoading(false);
          // 라이브 스트림 자동 재생
          videoElement.play().catch(() => {
            // autoplay 정책에 의해 차단될 수 있음 — muted로 재시도
            videoElement.muted = true;
            videoElement.play().catch(() => {});
          });
          onReady?.();
        });

        // 라이브 엣지에서 너무 밀리면 자동 복구
        // (liveSyncPosition = 엣지 - 목표 지연. 정지/버퍼링이 쌓여 목표보다 10초 이상
        //  더 밀렸을 때만 목표 지점으로 스냅. 착지 여유 3→1 (2026-09-03) → 0 (2026-09-14, hls.js 자체
        //  앞점프와 같은 지점 — 스냅 뒤 영구 +1초를 없앤다). 예전 "엣지−31초" 가 담당자가 체감한
        //  "홈페이지보다 30초" 였다)
        hls.on(HlsLib.Events.FRAG_BUFFERED, () => {
          if (!videoElement.paused && hls.liveSyncPosition) {
            const drift = hls.liveSyncPosition - videoElement.currentTime;
            if (drift > 10) {
              videoElement.currentTime = hls.liveSyncPosition;
            }
          }
        });

        // 라이브 엣지 대비 실측 재생 지연을 1초 주기로 외부에 노출 — 자막 동기화용.
        // ★hls.latency는 timeupdate에서만 갱신되는 캐시라 일시정지(동기화 톱업)·
        // 리버퍼링 중에 동결된다 — 그동안 실제 지연은 커지는데 작은 옛 값을 쓰면
        // 자막이 영상보다 먼저 나온다. 엣지 추정(estimateLiveEdge = 플레이리스트
        // 엣지 + 경과시간)은 호출 시점마다 전진하므로 이것으로 직접 계산한다.
        if (latencyRef) {
          latencyTimer = setInterval(() => {
            let l: number | null = null;
            try {
              const lc = (hls as unknown as {
                latencyController?: { estimateLiveEdge?: () => number | null };
              }).latencyController;
              const edge = lc?.estimateLiveEdge?.();
              if (edge != null && Number.isFinite(edge)) {
                l = edge - videoElement.currentTime;
              }
            } catch {
              // hls.js 내부 API 변경 시 아래 캐시값 폴백
            }
            if (l == null || !Number.isFinite(l) || l <= 0) {
              const cached = hls.latency;
              l = Number.isFinite(cached) && cached > 0 ? cached : null;
            }
            latencyRef.current = l;
            if (targetLatencyRef) {
              // hls.js 가 지금 쓰는 유효 목표 — liveSyncOnStallIncrease 를 껐으니 스톨 뒤에도 syncTargetSec 이어야 한다
              try {
                const t = hls.targetLatency;
                targetLatencyRef.current = t != null && Number.isFinite(t) ? t : null;
              } catch {
                targetLatencyRef.current = null;
              }
            }
          }, 1000);
        }

        // ── 동기화 지연 톱업 ─────────────────────────────────────────
        // 플레이리스트 윈도우가 얕으면(예: 2초×3개 = 6초) hls.js는 목표
        // 지연(LIVE_SYNC_TARGET_SEC)을 잡을 수 없다 — 가장 오래된 세그먼트가
        // 그게 한계라서. 그 부족분만큼 시작 직후 일시정지로 메꾼다: 멈춰 있는
        // 동안 라이브 엣지는 전진하고 버퍼는 쌓이므로, 재개하면 지연 = 기존 +
        // 정지 시간이 된다. 자막은 그 지연 안에서 항상 영상보다 먼저 도착한다.
        let topUpDone = false;
        hls.on(HlsLib.Events.FRAG_CHANGED, () => {
          if (topUpDone) return;
          topUpDone = true;
          // 재생 시작 후 3초 뒤에 실측 — hls.latency가 안정된 다음 판단
          setTimeout(() => {
            if (cancelled || hlsRef.current !== hls) return;
            const l = hls.latency;
            if (!Number.isFinite(l) || l <= 0) return;
            const gap = syncTargetSec - l;
            if (gap <= 3 || videoElement.paused) return; // 이미 충분/사용자 정지
            const holdSec = Math.min(gap, syncTargetSec);
            setIsSyncBuffering(true);
            setSyncRemainingSec(Math.ceil(holdSec));
            videoElement.pause();
            const resumeAt = Date.now() + holdSec * 1000;
            topUpTimer = setInterval(() => {
              setSyncRemainingSec(Math.max(0, Math.ceil((resumeAt - Date.now()) / 1000)));
            }, 500);
            setTimeout(() => {
              if (topUpTimer) clearInterval(topUpTimer);
              topUpTimer = null;
              if (cancelled || hlsRef.current !== hls) return;
              setIsSyncBuffering(false);
              videoElement.play().catch(() => {});
            }, holdSec * 1000);
          }, 3000);
        });

        hls.on(HlsLib.Events.ERROR, (_event, data) => {
          if (data.fatal) {
            switch (data.type) {
              case HlsLib.ErrorTypes.NETWORK_ERROR:
                networkRetryCount.current += 1;
                if (networkRetryCount.current <= MAX_NETWORK_RETRIES) {
                  console.warn(`HLS network error, recovering... (${networkRetryCount.current}/${MAX_NETWORK_RETRIES})`);
                  hls.startLoad();
                } else {
                  console.error('HLS network error: max retries exceeded');
                  setHasError(true);
                  setIsLoading(false);
                  onError?.(new Error('스트림에 연결할 수 없습니다'));
                }
                break;
              case HlsLib.ErrorTypes.MEDIA_ERROR:
                console.warn('HLS media error, recovering...');
                hls.recoverMediaError();
                break;
              default:
                setHasError(true);
                setIsLoading(false);
                onError?.(new Error(`HLS Error: ${data.type}`));
                break;
            }
          }
        });
      } else if (videoElement.canPlayType('application/vnd.apple.mpegurl')) {
        // Native HLS support (Safari)
        videoElement.src = streamUrl;
      }
    })();

    return () => {
      cancelled = true;
      if (latencyTimer) clearInterval(latencyTimer);
      if (topUpTimer) clearInterval(topUpTimer);
      if (latencyRef) latencyRef.current = null;
      if (targetLatencyRef) targetLatencyRef.current = null;
      if (playingClockRef) playingClockRef.current = null;
      if (hlsRef.current) {
        hlsRef.current.destroy();
        hlsRef.current = null;
      }
    };
  }, [streamUrl, onError, onReady, latencyRef, playingClockRef, targetLatencyRef]);

  const handleLoadedData = () => {
    setIsLoading(false);
  };

  const handleError = () => {
    setHasError(true);
    setIsLoading(false);
    onError?.(new Error('Video error'));
  };

  return (
    <div
      data-testid="hls-player-container"
      className="relative bg-black rounded-lg overflow-hidden aspect-video"
    >
      <video
        ref={internalRef}
        data-testid="hls-video"
        controls
        autoPlay
        playsInline
        className="w-full h-full"
        onLoadedData={handleLoadedData}
        onError={handleError}
      />

      {isLoading && (
        <div
          data-testid="loading-spinner"
          className="absolute inset-0 flex items-center justify-center bg-black/50"
        >
          <div className="w-12 h-12 border-4 border-gray-300 border-t-primary rounded-full animate-spin" />
        </div>
      )}

      {isSyncBuffering && (
        <div
          data-testid="sync-buffering"
          className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/60"
        >
          <div className="w-10 h-10 border-4 border-gray-300 border-t-primary rounded-full animate-spin" />
          <p className="text-white text-sm">
            자막 동기화 준비 중... {syncRemainingSec > 0 ? `${syncRemainingSec}초 후 재생됩니다` : '잠시 후 재생됩니다'}
          </p>
        </div>
      )}

      {hasError && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/80 text-white">
          <svg
            className="w-12 h-12 text-danger mb-4"
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
          <p className="text-center">영상을 불러올 수 없습니다</p>
          <p className="text-sm text-gray-400 mt-1">현재 방송 중이 아니거나 스트림에 문제가 있습니다</p>
        </div>
      )}
    </div>
  );
});

export default HlsPlayer;
