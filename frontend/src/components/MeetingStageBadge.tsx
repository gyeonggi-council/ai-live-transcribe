'use client';

import React from 'react';

import type { MeetingType } from '@/types';
import { STAGE_TONE_CLASS, getMeetingStage } from '@/utils/meetingStage';

export interface MeetingStageBadgeProps {
  meeting: Pick<MeetingType, 'status'> &
    Partial<Pick<MeetingType, 'subtitle_stage' | 'vod_url'>>;
  size?: 'sm' | 'md';
  className?: string;
}

/**
 * 회의의 현재 자막 단계 배지 — 라벨·색은 getMeetingStage 한 곳에서만 나온다.
 * 생중계 중이면 점멸 점을 붙여 "지금 벌어지는 일"임을 표시한다.
 */
export default function MeetingStageBadge({
  meeting,
  size = 'sm',
  className = '',
}: MeetingStageBadgeProps) {
  const info = getMeetingStage(meeting);
  const pad = size === 'md' ? 'px-3 py-1 text-sm' : 'px-2.5 py-0.5 text-xs';

  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full font-medium ${pad} ${STAGE_TONE_CLASS[info.tone]} ${className}`.trim()}
      data-testid="meeting-stage-badge"
      data-stage={info.filterKey}
    >
      {info.isLive && (
        <span
          className="h-1.5 w-1.5 shrink-0 rounded-full bg-live animate-live-pulse"
          aria-hidden="true"
        />
      )}
      {info.statusLabel}
    </span>
  );
}
