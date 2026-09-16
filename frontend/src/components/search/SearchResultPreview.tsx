'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';

import Mp4Player from '@/components/Mp4Player';
import VideoControls from '@/components/VideoControls';
import { apiClient } from '@/lib/api';
import type { MeetingType } from '@/types';

/**
 * 통합검색 결과 미리보기 (2026-08-25)
 *
 * 검색 결과 줄을 누르면 **페이지를 떠나지 않고 그 자리에서** 해당 발언 시점부터
 * 영상을 본다. 회의 상세로 가는 것은 [이 회의로 이동] 버튼을 눌렀을 때뿐이다.
 *
 * ★ 페이지에 `<video>` 는 항상 한 개만 있어야 한다.
 *   KMS MP4 는 fast-start 가 아니라 moov 가 파일 끝에 있고 1시간짜리가 937MB 다
 *   (2026-08-22 실측). 목록에 미리 깔면 회의 수만큼 그걸 받는다 — 실제로 그렇게
 *   만들었다가 "느리다" 신고를 받았다. 그래서 이 컴포넌트는 **누른 뒤에만** 붙고,
 *   회의 메타도 누른 회의만 조회한다.
 *
 * 재생 로직은 새로 만들지 않는다 — `Mp4Player`(KMS mp4→HLS 변환·hls.js)와
 * `VideoControls`(재생·시크·배속)를 회의 상세와 같은 것으로 쓴다.
 */

/** 회의 메타 캐시 — 같은 회의를 다시 열 때 재조회하지 않는다 */
const meetingCache = new Map<string, MeetingType>();

/** 테스트에서 캐시를 비우기 위한 것 (프로덕션 경로에서 부르지 않는다) */
export function clearPreviewMeetingCache(): void {
  meetingCache.clear();
}

export interface SearchResultPreviewProps {
  meetingId: string;
  /** 이동할 시점(초) — 누른 자막의 start_time */
  startTime: number;
  /** 같은 자막을 다시 눌러도 재시크되도록 하는 증가값 */
  seekNonce: number;
  /** 누른 발언 — 영상 아래 한 줄로 무엇을 보고 있는지 남긴다 */
  hit: { text: string; speaker: string | null };
  /** "00:12:41" 같은 표기 — 검색 페이지의 formatAt 을 그대로 넘겨받는다 */
  timeLabel: string;
  onOpenMeeting: () => void;
  onClose: () => void;
}

export default function SearchResultPreview({
  meetingId,
  startTime,
  seekNonce,
  hit,
  timeLabel,
  onOpenMeeting,
  onClose,
}: SearchResultPreviewProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  /** 아직 영상이 준비되지 않았을 때의 시크 요청을 담아 둔다 */
  const pendingSeekRef = useRef<number | null>(startTime);
  const [meeting, setMeeting] = useState<MeetingType | null>(
    () => meetingCache.get(meetingId) ?? null,
  );
  const [loadError, setLoadError] = useState<string | null>(null);
  const [currentTime, setCurrentTime] = useState(startTime);
  const [duration, setDuration] = useState(0);

  // 회의 메타(vod_url) 조회 — 회의 상세가 쓰는 그 경로다
  useEffect(() => {
    const cached = meetingCache.get(meetingId);
    if (cached) {
      setMeeting(cached);
      setLoadError(null);
      return;
    }
    let cancelled = false;
    setMeeting(null);
    setLoadError(null);
    void (async () => {
      try {
        const data = await apiClient<MeetingType>(`/api/meetings/${meetingId}`);
        if (cancelled) return;
        meetingCache.set(meetingId, data);
        setMeeting(data);
      } catch (err) {
        if (cancelled) return;
        setLoadError(err instanceof Error ? err.message : '회의 정보를 불러오지 못했습니다');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [meetingId]);

  /**
   * 이미 열려 있는 영상을 **다른 발언으로 옮길 때만** 쓰는 시크.
   * 처음 열 때의 위치는 `Mp4Player startTime` 이 잡는다 — 0초부터 열고 나중에
   * 옮기면 엉뚱한 조각을 먼저 통째로 받아 느리고, 조각 경계에서 되돌아가기까지 한다.
   * 재생은 실패해도 조용히 넘어간다 — 시점만 맞으면 목적은 달성된다.
   */
  const seekTo = useCallback((seconds: number) => {
    const video = videoRef.current;
    if (!video || video.readyState < 1) {
      pendingSeekRef.current = seconds;
      return;
    }
    pendingSeekRef.current = null;
    try {
      video.currentTime = seconds;
    } catch {
      /* 시크 실패는 치명적이지 않다 */
    }
    setCurrentTime(seconds);
    const played = video.play?.();
    if (played && typeof played.catch === 'function') played.catch(() => {});
  }, []);

  // 같은 회의 안에서 다른 줄을 눌렀거나, 같은 줄을 다시 눌렀을 때.
  // 처음 여는 순간에는 영상이 아직 없으므로 pendingSeek 에만 담기고,
  // Mp4Player 가 이미 그 위치에서 열었으므로 실제로는 다시 옮길 일이 없다.
  useEffect(() => {
    seekTo(startTime);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startTime, seekNonce]);

  const handleReady = () => {
    const video = videoRef.current;
    if (!video) return;
    setDuration(video.duration || 0);
    // 이미 목표 위치에서 열렸으면(첫 열기) 그대로 두고 재생만 시도한다
    const pending = pendingSeekRef.current;
    if (pending !== null && Math.abs(video.currentTime - pending) > 1.5) {
      seekTo(pending);
      return;
    }
    pendingSeekRef.current = null;
    setCurrentTime(video.currentTime);
    const played = video.play?.();
    if (played && typeof played.catch === 'function') played.catch(() => {});
  };

  const handleTimeUpdate = (time: number) => {
    setCurrentTime(time);
    const video = videoRef.current;
    if (video && video.duration && video.duration !== duration) setDuration(video.duration);
  };

  return (
    <div
      data-testid="search-preview"
      role="region"
      aria-label="검색 결과 영상 미리보기"
      className="border-b border-border-subtle bg-gray-50 px-4 py-3.5 last:border-b-0"
    >
      {meeting?.vod_url ? (
        <>
          <Mp4Player
            vodUrl={meeting.vod_url}
            videoRef={videoRef}
            startTime={startTime}
            onReady={handleReady}
            onTimeUpdate={handleTimeUpdate}
          />
          <VideoControls videoRef={videoRef} currentTime={currentTime} duration={duration} />
        </>
      ) : meeting ? (
        // 생중계는 있었지만 관리자가 아직 VOD 주소를 등록하지 않은 회의 —
        // 회의 상세의 vod-pending 블록과 같은 어휘를 쓴다
        <div
          data-testid="search-preview-pending"
          className="flex aspect-video flex-col items-center justify-center gap-2 rounded-lg bg-gray-900 p-6 text-center"
        >
          <svg className="h-12 w-12 text-gray-400" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 10.5l4.72-4.72a.75.75 0 011.28.53v11.38a.75.75 0 01-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 002.25-2.25v-9a2.25 2.25 0 00-2.25-2.25h-9A2.25 2.25 0 002.25 7.5v9a2.25 2.25 0 002.25 2.25z" />
          </svg>
          <p className="text-[15px] font-semibold text-white">영상이 아직 등록되지 않았습니다</p>
          <p className="max-w-sm text-[13px] leading-relaxed text-white/60">
            자막은 저장되어 있습니다. 회의로 이동하면 자막 전문을 볼 수 있습니다.
          </p>
        </div>
      ) : loadError ? (
        <div
          data-testid="search-preview-error"
          className="flex aspect-video items-center justify-center rounded-lg border border-border bg-surface px-6 text-center text-[13.5px] text-danger"
        >
          영상을 불러오지 못했습니다 — {loadError}
        </div>
      ) : (
        <div
          data-testid="search-preview-loading"
          className="flex aspect-video items-center justify-center rounded-lg bg-gray-900"
        >
          <div className="h-9 w-9 animate-spin rounded-full border-2 border-white/25 border-t-white/80" />
        </div>
      )}

      {/* 지금 보고 있는 발언 한 줄 — 영상만 뜨면 무엇을 찾다 왔는지 잊는다 */}
      <div className="mt-2.5 flex flex-wrap items-start gap-2">
        <span className="mt-0.5 inline-flex shrink-0 items-center gap-1 rounded bg-primary/10 px-1.5 py-0.5 font-mono text-[11.5px] text-primary">
          <span className="text-[9px] leading-none" aria-hidden="true">
            ▶
          </span>
          {timeLabel}
        </span>
        {hit.speaker && (
          <span className="mt-px shrink-0 rounded-full bg-blue-50 px-2 py-0.5 text-xs font-semibold text-blue-700">
            {hit.speaker}
          </span>
        )}
        <span className="min-w-0 flex-1 text-[13.5px] leading-relaxed text-text-secondary">
          {hit.text}
        </span>
      </div>

      <div className="mt-2.5 flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          data-testid="search-preview-close"
          className="inline-flex h-8 items-center rounded-md border border-border-strong bg-surface px-3 text-[13px] font-medium text-text-secondary transition-colors hover:bg-surface-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          닫기
        </button>
        <button
          type="button"
          onClick={onOpenMeeting}
          data-testid="search-preview-open"
          className="inline-flex h-8 items-center gap-1 rounded-md bg-primary px-3 text-[13px] font-semibold text-white transition-colors hover:bg-primary-dark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-1"
        >
          이 회의로 이동
          <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={2.25} viewBox="0 0 24 24" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </button>
      </div>
    </div>
  );
}
