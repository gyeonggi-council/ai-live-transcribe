'use client';

import React, { useEffect, useRef, useState } from 'react';

import { fetchClipThumb } from '@/lib/api';

/**
 * 클립 썸네일 — 서버가 ffmpeg 로 한 장 뽑아 잡 디렉터리에 캐시한 JPEG(약 20KB).
 *
 * ★ `<img src="…/thumbnail">` 로 직접 걸 수 없다 — JWT 가 localStorage 라 인증이
 *   헤더로만 붙고(의회망 손님도 `X-Guest-Id` 헤더다), `<img>` 는 커스텀 헤더를 못 싣는다.
 *   그래서 fetch + objectURL 이다. 다운로드(`fetchClipJobFile`)와 같은 인증 경로를 쓴다.
 *
 * ★ 화면에 들어올 때만 받는다 — 한 회의에 클립이 100장까지 깔리므로, 다 받으면
 *   화면을 여는 것만으로 서버가 ffmpeg 를 100번 돌린다(`loading="lazy"` 의 대체).
 *
 * 20KB 짜리라 모듈 수준 캐시에 그대로 둔다. 탭을 오가도 다시 받지 않는다.
 */

const _cache = new Map<string, string>();

function keyOf(jobId: string, fileName: string): string {
  return `${jobId}/${fileName}`;
}

export interface ClipThumbProps {
  meetingId: string;
  jobId: string;
  fileName: string;
  /** 우하단 길이 배지 (예: '8분 14초') */
  durationLabel?: string;
  className?: string;
}

export default function ClipThumb({
  meetingId,
  jobId,
  fileName,
  durationLabel,
  className = '',
}: ClipThumbProps) {
  const key = keyOf(jobId, fileName);
  const [url, setUrl] = useState<string | null>(() => _cache.get(key) ?? null);
  const [failed, setFailed] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (_cache.has(key)) {
      setUrl(_cache.get(key) ?? null);
      return;
    }
    setUrl(null);
    setFailed(false);

    const box = boxRef.current;
    if (!box) return;
    const controller = new AbortController();
    let cancelled = false;

    const load = async () => {
      try {
        const blob = await fetchClipThumb(meetingId, jobId, fileName, controller.signal);
        if (cancelled) return;
        if (!blob || blob.size === 0) {
          setFailed(true);
          return;
        }
        const objectUrl = URL.createObjectURL(blob);
        _cache.set(key, objectUrl);
        setUrl(objectUrl);
      } catch {
        if (!cancelled) setFailed(true);
      }
    };

    // IntersectionObserver 가 없는 환경(jsdom·구형)에서는 그냥 바로 받는다
    if (typeof IntersectionObserver === 'undefined') {
      void load();
      return () => {
        cancelled = true;
        controller.abort();
      };
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          observer.disconnect();
          void load();
        }
      },
      { rootMargin: '200px' }
    );
    observer.observe(box);
    return () => {
      cancelled = true;
      observer.disconnect();
      controller.abort();
    };
  }, [key, meetingId, jobId, fileName]);

  return (
    <div
      ref={boxRef}
      data-testid="clip-thumb"
      // KMS 영상이 4:3 이라 16:9 로 담으면 좌우가 잘리거나 검은 띠가 생긴다
      className={`relative aspect-[4/3] overflow-hidden rounded-md border border-border bg-surface-raised ${className}`}
    >
      {url && !failed ? (
        // eslint-disable-next-line @next/next/no-img-element -- 인증 fetch 로 받은 objectURL (next/image 불가)
        <img src={url} alt="" decoding="async" className="h-full w-full object-cover" />
      ) : (
        <div
          data-testid="clip-thumb-placeholder"
          className="flex h-full w-full items-center justify-center bg-gradient-to-br from-primary-5 to-surface-raised"
        >
          {/* 번호는 카드 본문에 이미 있다 — 여기 또 적으면 같은 값이 두 번 보인다 */}
          <span className="text-[16px] text-primary-dark/40" aria-hidden="true">
            {failed ? '🎬' : ''}
          </span>
        </div>
      )}
      {durationLabel && (
        <span className="absolute bottom-1 right-1 rounded bg-black/70 px-1 py-0.5 text-[10px] font-semibold text-white tabular-nums">
          {durationLabel}
        </span>
      )}
    </div>
  );
}
