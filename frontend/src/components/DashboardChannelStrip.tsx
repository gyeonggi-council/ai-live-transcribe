'use client';

import React, { useMemo } from 'react';

import Link from 'next/link';

import type { ChannelType } from '@/types';

export interface DashboardChannelStripProps {
  channels: ChannelType[];
  isLoading: boolean;
}

const STATUS_PRIORITY: Record<number, number> = {
  1: 0, // 방송중
  2: 1, // 정회중
  0: 2, // 방송전
  3: 3, // 종료
  4: 4, // 생중계없음
};

function ChannelCard({ channel }: { channel: ChannelType }) {
  const status = channel.livestatus ?? 0;
  const isLive = status === 1;
  const isRecess = status === 2;

  return (
    <Link
      href={`/live?channel=${channel.id}`}
      className={`flex flex-col items-center p-3 rounded-lg border transition-all hover:shadow-md ${
        isLive
          ? 'border-danger/30 bg-danger/5 hover:border-danger/50'
          : isRecess
            ? 'border-warning-bg/40 bg-warning-bg/10 hover:border-warning-bg/60'
            : 'border-gray-200 bg-white hover:border-gray-300'
      }`}
    >
      <span className="text-sm font-medium text-gray-800 text-center truncate w-full">
        {channel.name}
      </span>
      {channel.has_schedule && channel.session_no && (
        <span className="text-[10px] text-gray-400 mt-0.5">
          제{channel.session_no}회 제{channel.session_order}차
        </span>
      )}
      <div className="mt-1.5">
        {isLive ? (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-danger/10 text-danger">
            <span className="relative flex h-1.5 w-1.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-danger/70 opacity-75" />
              <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-danger" />
            </span>
            ON AIR
          </span>
        ) : isRecess ? (
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-warning-bg/20 text-warning">
            정회중
          </span>
        ) : null}
      </div>
    </Link>
  );
}

export default function DashboardChannelStrip({ channels, isLoading }: DashboardChannelStripProps) {
  const { activeChannels, restSummary } = useMemo(() => {
    const sorted = [...channels].sort((a, b) => {
      const pa = STATUS_PRIORITY[a.livestatus ?? 0] ?? 9;
      const pb = STATUS_PRIORITY[b.livestatus ?? 0] ?? 9;
      if (pa !== pb) return pa - pb;
      if (a.has_schedule !== b.has_schedule) return a.has_schedule ? -1 : 1;
      return 0;
    });

    const active = sorted.filter(
      (ch) => ch.livestatus === 1 || ch.livestatus === 2
    );
    const beforeCount = sorted.filter((ch) => (ch.livestatus ?? 0) === 0).length;
    const endedCount = sorted.filter(
      (ch) => ch.livestatus === 3 || ch.livestatus === 4
    ).length;

    return {
      activeChannels: active,
      restSummary: { beforeCount, endedCount },
    };
  }, [channels]);

  const liveCount = channels.filter((ch) => ch.livestatus === 1).length;

  if (isLoading) {
    return (
      <section className="bg-white rounded-lg border border-gray-200 p-4" aria-label="채널 현황">
        <h2 className="text-base font-semibold text-gray-900 mb-3">채널 현황</h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-20 rounded-lg bg-gray-100 animate-pulse" />
          ))}
        </div>
      </section>
    );
  }

  return (
    <section className="bg-white rounded-lg border border-gray-200 p-4" aria-label="채널 현황">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-base font-semibold text-gray-900">채널 현황</h2>
        <Link href="/live" className="text-sm text-primary hover:underline">
          전체 채널 보기
        </Link>
      </div>

      {activeChannels.length > 0 ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
          {activeChannels.map((ch) => (
            <ChannelCard key={ch.id} channel={ch} />
          ))}
        </div>
      ) : (
        <p className="text-sm text-gray-500 py-4 text-center">
          현재 방송 중인 채널이 없습니다
        </p>
      )}

      <div className="mt-3 flex items-center gap-2 text-xs text-gray-400">
        {liveCount > 0 && (
          <span className="px-2 py-0.5 rounded-full bg-danger/10 text-danger font-medium">
            {liveCount}개 방송중
          </span>
        )}
        <span>방송전 {restSummary.beforeCount}개</span>
        <span className="text-gray-300">|</span>
        <span>종료 {restSummary.endedCount}개</span>
      </div>
    </section>
  );
}
