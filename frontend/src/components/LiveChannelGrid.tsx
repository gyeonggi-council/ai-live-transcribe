'use client';

import React, { useMemo } from 'react';

import Link from 'next/link';

import type { ChannelType } from '@/types';

import LiveChannelCard from './LiveChannelCard';

export interface LiveChannelGridProps {
  channels: ChannelType[];
  isLoading: boolean;
}

/** 방송 중인 채널 최대 표시 수 */
const MAX_LIVE_DISPLAY = 4;

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center rounded-[10px] border border-border bg-white py-12">
      {/* 아이콘을 원형 바탕 위에 올려 '비어 있음'이 오류가 아니라 상태로 읽히게 한다 */}
      <div className="mb-4 grid h-20 w-20 place-items-center rounded-full bg-surface-raised">
        <svg
          className="h-9 w-9 text-text-muted"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.5}
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="m15.75 10.5 4.72-4.72a.75.75 0 0 1 1.28.53v11.38a.75.75 0 0 1-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 0 0 2.25-2.25v-9a2.25 2.25 0 0 0-2.25-2.25h-9A2.25 2.25 0 0 0 2.25 7.5v9a2.25 2.25 0 0 0 2.25 2.25Z"
          />
        </svg>
      </div>
      <p className="mb-1 text-base font-bold text-gray-900">현재 진행 중인 방송이 없습니다</p>
      <p className="text-sm text-text-muted">방송이 시작되면 여기에 표시됩니다.</p>
    </div>
  );
}

/**
 * 대시보드 '지금 방송 중' 구역.
 *
 * 2026-08-25 개선안 2d 로 **바깥 카드를 벗겼다**. 예전에는 `Card > 카드격자` 라
 * 테두리가 두 겹이었고, 그 두 겹이 화면의 다른 구역들과 붙어 어디가 한 덩어리인지
 * 흐려졌다. 제목 + 내용이면 충분하다.
 */
export default function LiveChannelGrid({ channels, isLoading }: LiveChannelGridProps) {
  const liveChannels = useMemo(
    () => channels.filter((ch) => ch.livestatus === 1).slice(0, MAX_LIVE_DISPLAY),
    [channels],
  );

  if (isLoading) {
    return (
      <section aria-label="실시간 방송 현황" className="flex flex-col gap-3">
        <div className="h-5 w-32 animate-pulse rounded bg-surface-raised" />
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {Array.from({ length: 2 }).map((_, i) => (
            <div
              key={i}
              className="h-[122px] animate-pulse rounded-[10px] border border-border bg-surface-raised"
            />
          ))}
        </div>
      </section>
    );
  }

  return (
    <section aria-label="실시간 방송 현황" className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between gap-4">
        <h2 className="flex items-center gap-2 text-[15px] font-bold tracking-heading text-text">
          {liveChannels.length > 0 && (
            <span
              className="h-2 w-2 shrink-0 animate-live-pulse rounded-full bg-live"
              aria-hidden="true"
            />
          )}
          지금 방송 중
          {liveChannels.length > 0 && (
            <span className="text-[13px] font-medium text-text-muted">{liveChannels.length}</span>
          )}
        </h2>
        <Link href="/live" className="shrink-0 text-[13px] font-semibold text-primary hover:underline">
          전체 채널 {channels.length > 0 ? `${channels.length}개 ` : ''}보기 &rarr;
        </Link>
      </div>

      {liveChannels.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {liveChannels.map((ch) => (
            <LiveChannelCard key={ch.id} channel={ch} />
          ))}
        </div>
      ) : (
        <EmptyState />
      )}
    </section>
  );
}
