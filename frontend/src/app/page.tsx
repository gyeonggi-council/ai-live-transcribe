'use client';

import React, { useMemo } from 'react';

import {
  LiveChannelGrid,
} from '@/components';
import NotificationOptInBanner from '@/components/NotificationOptInBanner';
import PageHeader from '@/components/PageHeader';
import RecentMeetingsPanel from '@/components/RecentMeetingsPanel';
// import StageWorkQueue from '@/components/StageWorkQueue'; // 비핵심(속기/교정 워크큐) — 나중에 재활성화
import { useChannelStatus, useRecentVods } from '@/hooks';

export default function Home() {
  const { channels, isLoading: channelsLoading } = useChannelStatus();
  const {
    vods: recentVods,
    isLoading: isVodsLoading,
    error: vodsError,
  } = useRecentVods({ limit: 30, statuses: 'live,processing,ended' });

  // 생중계 중인 회의는 위 '실시간 방송 현황' 카드가 이미 보여준다 —
  // 아래 목록은 '지난 회의 영상'이므로 중복을 뺀다.
  // ※ 예전에는 회차 상수(CURRENT_SESSION_NUMBER)로 걸렀는데, 회기가 넘어가면
  //   손으로 고쳐야 해서 실제로 방치됐고(389 로 남은 채 데이터는 392) 목록이
  //   통째로 비어 있었다. 최신순 상위 N 건이면 손댈 일이 없다.
  const pastMeetings = useMemo(
    () => recentVods.filter((v) => v.status !== 'live'),
    [recentVods],
  );

  const today = new Date();
  const dateStr = `${today.getFullYear()}년 ${today.getMonth() + 1}월 ${today.getDate()}일`;
  const dayNames = ['일', '월', '화', '수', '목', '금', '토'];
  const dayStr = dayNames[today.getDay()];

  return (
    <div className="min-h-screen">
      <div className="mx-auto flex max-w-[1360px] flex-col gap-7 px-4 py-6 sm:px-6">
        <PageHeader
          title="대시보드"
          meta={`${dateStr} (${dayStr})`}
          description="실시간 방송 현황과 최근 회의 영상을 한눈에 확인합니다."
          className="mb-0"
        />

        {/* 1) 지금 열리고 있는 회의 */}
        <LiveChannelGrid channels={channels} isLoading={channelsLoading} />

        {/* 2) 지난 회의 영상 — 썸네일 목록, 기본 3건 */}
        <RecentMeetingsPanel
          meetings={pastMeetings}
          isLoading={isVodsLoading}
          hasError={!!vodsError}
        />

        {/* 자막 워크플로우 단계별 진행(속기/교정 워크큐) — 비핵심, 나중에 재활성화
        {!isVodsLoading && !vodsError && recentVods.length > 0 && (
          <StageWorkQueue vods={recentVods} />
        )} */}

        {/* 3) 알림 권한 안내 한 줄
            ※ 바로가기 3칸(채널 목록·회의록·자막 검색)은 2026-08-25 개선안 2d 로 없앴다.
              셋 다 사이드바에 이미 있고, 카드로 한 번 더 깔면 메뉴가 하나 더 생긴다. */}
        <NotificationOptInBanner />
      </div>
    </div>
  );
}
