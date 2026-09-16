'use client';

import React, { useState } from 'react';

import { API_BASE_URL } from '@/lib/api';
import type { MeetingType } from '@/types';

/**
 * 회의 썸네일 — 서버가 ffmpeg 로 뽑아 캐시한 JPEG(`/api/meetings/{id}/thumbnail`, 약 13~18KB).
 * 홈 대시보드(RecentMeetingsPanel)와 회의 목록(MeetingCard)이 같이 쓴다.
 *
 * ★ `<video preload="metadata">` 로 브라우저가 직접 만들게 하지 말 것 — KMS MP4 는
 *   moov 가 파일 끝에 있어(비 fast-start, 1시간짜리 937MB·moov 3MB) 회의 한 건마다
 *   수 MB 를 받는다. 2026-08-22 "모바일이 느리다" 신고의 원인이었다.
 *
 * VOD 가 없거나(생중계·등록 전) 이미지를 못 받으면 `label`(위원회명) 자리표시로 떨어진다.
 */
export default function MeetingThumbnail({
  meeting,
  label,
  className = '',
}: {
  meeting: Pick<MeetingType, 'id' | 'vod_url'>;
  label: string;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);

  return (
    <div
      className={`aspect-video overflow-hidden rounded-md border border-border bg-surface-raised ${className}`}
      aria-hidden="true"
      data-testid="meeting-thumbnail"
    >
      {meeting.vod_url && !failed ? (
        // eslint-disable-next-line @next/next/no-img-element -- 외부 API 가 주는 캐시 JPEG (next/image 최적화 불필요)
        <img
          src={`${API_BASE_URL}/api/meetings/${meeting.id}/thumbnail`}
          alt=""
          loading="lazy"
          decoding="async"
          onError={() => setFailed(true)}
          className="h-full w-full object-cover"
        />
      ) : (
        <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-primary-5 to-surface-raised">
          <span className="line-clamp-2 px-1 text-center text-[9px] font-bold leading-tight text-primary-dark/60 lg:text-[10px]">
            {label}
          </span>
        </div>
      )}
    </div>
  );
}
