'use client';

import React from 'react';

import Link from 'next/link';

import Button from '@/components/ui/Button';
import type { MeetingType, StatsOverviewType } from '@/types';

export interface DashboardWorkQueueProps {
  processingVods: MeetingType[];
  draftMeetings: MeetingType[];
  statsOverview: StatsOverviewType | null;
  kpiLoading: boolean;
  kpiError: string;
  onRetryKpi: () => void;
}

function formatDuration(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600);
  return `${hours.toLocaleString()}시간`;
}

function formatConfidence(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export default function DashboardWorkQueue({
  processingVods,
  draftMeetings,
  statsOverview,
  kpiLoading,
  kpiError,
  onRetryKpi,
}: DashboardWorkQueueProps) {
  return (
    <aside className="space-y-4" aria-label="작업 현황">
      {/* Processing VODs */}
      <section className="bg-white rounded-lg border border-border p-4">
        <div className="flex items-center gap-2 mb-3">
          <h3 className="text-sm font-semibold text-gray-900">처리 대기 VOD</h3>
          {processingVods.length > 0 && (
            <span className="px-1.5 py-0.5 rounded-full text-xs font-medium bg-warning-bg/20 text-warning">
              {processingVods.length}건
            </span>
          )}
        </div>
        {processingVods.length === 0 ? (
          <p className="text-sm text-gray-400 py-2">대기 중인 VOD가 없습니다</p>
        ) : (
          <ul className="space-y-2">
            {processingVods.map((vod) => (
              <li key={vod.id}>
                <Link
                  href={`/vod/${vod.id}`}
                  className="block px-3 py-2 rounded-md border border-warning-bg/30 bg-warning-bg/10 hover:bg-warning-bg/20 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                >
                  <p className="text-sm font-medium text-gray-800 truncate">{vod.title}</p>
                  <p className="text-xs text-warning mt-0.5">자막 생성중</p>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Draft meetings needing verification */}
      <section className="bg-white rounded-lg border border-border p-4">
        <div className="flex items-center gap-2 mb-3">
          <h3 className="text-sm font-semibold text-gray-900">검증 필요</h3>
          {draftMeetings.length > 0 && (
            <span className="px-1.5 py-0.5 rounded-full text-xs font-medium bg-warning-bg/20 text-warning">
              {draftMeetings.length}건
            </span>
          )}
        </div>
        {draftMeetings.length === 0 ? (
          <p className="text-sm text-gray-400 py-2">검증 대기 건이 없습니다</p>
        ) : (
          <ul className="space-y-2">
            {draftMeetings.map((m) => (
              <li key={m.id}>
                <Link
                  href={`/vod/${m.id}/verify`}
                  className="block px-3 py-2 rounded-md border border-warning-bg/30 bg-warning-bg/10 hover:bg-warning-bg/20 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                >
                  <p className="text-sm font-medium text-gray-800 truncate">{m.title}</p>
                  <p className="text-xs text-warning mt-0.5">검토 대기</p>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* KPI Stats */}
      <section className="bg-white rounded-lg border border-border p-4" aria-label="운영 지표">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-900">운영 지표</h3>
          {kpiError && (
            <Button variant="outline" size="sm" onClick={onRetryKpi} className="h-7 px-2 text-xs">
              다시 시도
            </Button>
          )}
        </div>
        {kpiError ? (
          <p className="text-sm text-error" role="alert">{kpiError}</p>
        ) : (
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-md bg-gray-50 px-3 py-2">
              <p className="text-[10px] text-gray-400 uppercase">회의</p>
              <p className="text-base font-semibold text-gray-900">
                {kpiLoading ? '-' : `${(statsOverview?.total_meetings ?? 0).toLocaleString()}건`}
              </p>
            </div>
            <div className="rounded-md bg-gray-50 px-3 py-2">
              <p className="text-[10px] text-gray-400 uppercase">자막</p>
              <p className="text-base font-semibold text-gray-900">
                {kpiLoading ? '-' : `${(statsOverview?.total_subtitles ?? 0).toLocaleString()}개`}
              </p>
            </div>
            <div className="rounded-md bg-gray-50 px-3 py-2">
              <p className="text-[10px] text-gray-400 uppercase">녹화</p>
              <p className="text-base font-semibold text-gray-900">
                {kpiLoading ? '-' : formatDuration(statsOverview?.total_duration ?? 0)}
              </p>
            </div>
            <div className="rounded-md bg-gray-50 px-3 py-2">
              <p className="text-[10px] text-gray-400 uppercase">인식률</p>
              <p className="text-base font-semibold text-gray-900">
                {kpiLoading ? '-' : formatConfidence(statsOverview?.average_confidence ?? 0)}
              </p>
            </div>
          </div>
        )}
      </section>
    </aside>
  );
}
