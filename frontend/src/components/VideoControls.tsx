'use client';

import React, { useEffect, useState } from 'react';

export interface VideoControlsProps {
  videoRef: React.MutableRefObject<HTMLVideoElement | null>;
  currentTime: number;
  duration: number;
}

const SPEED_OPTIONS = [0.5, 1, 1.5, 2] as const;

/**
 * Format seconds into mm:ss or h:mm:ss
 */
function formatTime(seconds: number): string {
  const totalSeconds = Math.floor(seconds);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const secs = totalSeconds % 60;

  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  }
  return `${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

export default function VideoControls({
  videoRef,
  currentTime,
  duration,
}: VideoControlsProps) {
  const [playbackRate, setPlaybackRate] = useState(1);
  const [isPaused, setIsPaused] = useState(true);
  const video = videoRef.current;

  // 영상의 play/pause 이벤트를 구독해 버튼 아이콘을 항상 실제 상태와 동기화.
  // (하단 버튼뿐 아니라 영상 클릭으로 토글해도 아이콘이 정확히 반영됨)
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const sync = () => setIsPaused(v.paused);
    sync();
    v.addEventListener('play', sync);
    v.addEventListener('pause', sync);
    return () => {
      v.removeEventListener('play', sync);
      v.removeEventListener('pause', sync);
    };
  }, [videoRef]);

  const handlePlayPause = () => {
    if (!video) return;
    if (video.paused) {
      video.play();
    } else {
      video.pause();
    }
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!video) return;
    const newTime = Number(e.target.value);
    video.currentTime = newTime;
  };

  const handleSpeedChange = (speed: number) => {
    if (video) {
      video.playbackRate = speed;
    }
    setPlaybackRate(speed);
  };

  // 전체화면 — 자막 오버레이까지 함께 확대되도록 video가 아니라 컨테이너를 넘긴다.
  // (iOS Safari는 컨테이너 전체화면을 지원하지 않아 video 전용 API로 폴백)
  const handleFullscreen = () => {
    const v = videoRef.current;
    if (!v) return;
    if (document.fullscreenElement) {
      document.exitFullscreen?.();
      return;
    }
    const container = (v.parentElement ?? v) as HTMLElement & {
      webkitRequestFullscreen?: () => void;
    };
    const iosVideo = v as HTMLVideoElement & { webkitEnterFullscreen?: () => void };
    if (typeof container.requestFullscreen === 'function') {
      container.requestFullscreen();
    } else if (typeof container.webkitRequestFullscreen === 'function') {
      container.webkitRequestFullscreen();
    } else if (typeof iosVideo.webkitEnterFullscreen === 'function') {
      iosVideo.webkitEnterFullscreen();
    }
  };

  // 한 줄 배치 — 세로로 쌓으면 모바일에서 자막 영역을 그만큼 잡아먹는다.
  // 배속은 버튼 4개 대신 셀렉트 하나로 접어 폭도 함께 줄였다.
  return (
    <div
      data-testid="video-controls"
      className="flex items-center gap-2 px-3 py-2 bg-white border border-gray-200 rounded-b-lg sm:gap-3 sm:px-4"
    >
      <button
        data-testid="play-pause-button"
        onClick={handlePlayPause}
        aria-label={isPaused ? '재생' : '일시정지'}
        className="shrink-0 p-1.5 rounded-full hover:bg-gray-100 transition-colors"
      >
        {isPaused ? (
          <svg className="w-5 h-5 text-gray-700" fill="currentColor" viewBox="0 0 24 24">
            <path d="M8 5v14l11-7z" />
          </svg>
        ) : (
          <svg className="w-5 h-5 text-gray-700" fill="currentColor" viewBox="0 0 24 24">
            <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" />
          </svg>
        )}
      </button>

      <span
        data-testid="time-display"
        className="shrink-0 whitespace-nowrap text-xs text-gray-600 font-mono tabular-nums sm:text-sm"
      >
        {formatTime(currentTime)} / {formatTime(duration)}
      </span>

      {/* Timeline seekbar */}
      <input
        data-testid="timeline-seekbar"
        type="range"
        min="0"
        max={String(duration)}
        value={String(currentTime)}
        aria-label="재생 위치"
        onChange={handleSeek}
        className="h-1.5 min-w-0 flex-1 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-primary"
      />

      {/* Playback speed */}
      <select
        data-testid="speed-selector"
        aria-label="재생 속도"
        value={String(playbackRate)}
        onChange={(e) => handleSpeedChange(Number(e.target.value))}
        className="shrink-0 rounded border border-gray-200 bg-gray-50 py-1 pl-1.5 pr-5 text-xs font-medium text-gray-700 hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
      >
        {SPEED_OPTIONS.map((speed) => (
          <option key={speed} value={String(speed)}>
            {speed}x
          </option>
        ))}
      </select>

      <button
        data-testid="fullscreen-button"
        onClick={handleFullscreen}
        aria-label="전체화면"
        title="전체화면"
        className="shrink-0 p-1.5 rounded-full text-gray-600 hover:bg-gray-100 transition-colors"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M4 8V4m0 0h4M4 4l5 5m11-5v4m0-4h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5v-4m0 4h-4m4 0l-5-5" />
        </svg>
      </button>
    </div>
  );
}
