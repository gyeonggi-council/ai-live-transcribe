'use client';

import React from 'react';

import { usePathname } from 'next/navigation';

import AppLoginRequired from '@/components/AppLoginRequired';
import { useAuth } from '@/contexts/AuthContext';

import Breadcrumbs from './Breadcrumbs';
import GlobalNavControls from './GlobalNavControls';
import MobileBrandBar from './MobileBrandBar';
import Sidebar from './Sidebar';

/**
 * 플랫폼 셸 우회가 필요한 경로 — 해당 화면은 자체 헤더/내비를 가짐
 *
 * - /operator: 사무처 운영자 콘솔 (운영자 모드 뱃지 + 긴급 제어 전용 헤더)
 */
const FULLSCREEN_ROUTES = ['/operator'];

/**
 * 셸을 통째로 걷어내는 경로 — **아직 로그인하지 않은 사람이 보는 화면**이다.
 *
 * 2026-08-28 까지 /login 은 이 셸 **안에서** 그려졌다. 그래서 로그인 화면 옆에
 * 사이드바(회의·의안·속기 메뉴)와 브레드크럼, 우측 상단 전역 컨트롤이 같이 떴다 —
 * 아직 들어오지도 않은 사람에게 내부 메뉴를 펼쳐 보인 셈이고, 화면은 "로그인하는 곳"
 * 처럼 보이지 않았다. 게다가 셸이 `h-screen overflow-hidden` + 안쪽 `overflow-y-auto`
 * 라서 로그인 카드가 **뷰포트가 아니라 남은 칸**을 기준으로 눕는 바람에 세로 스크롤이 생겼다.
 *
 * FULLSCREEN_ROUTES 와 나누는 이유는 넘침 처리다 — 운영자 콘솔은 스스로 높이를 맞추므로
 * `overflow-hidden` 이 맞지만, 로그인 카드는 작은 화면에서 넘칠 수 있어 스크롤을 남겨야 한다.
 */
const BARE_ROUTES = ['/login'];

export default function PlatformLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, loading, loginRequired } = useAuth();
  const matches = (routes: string[]) =>
    routes.some((route) => pathname === route || pathname?.startsWith(`${route}/`));

  if (matches(BARE_ROUTES)) {
    return <div className="min-h-screen overflow-y-auto">{children}</div>;
  }

  // 의회사무처 직원 PC 대역은 로그인해야 본다 — 막는 대신 앱 로그인 안내를 띄운다(2026-09-16 담당자 결정).
  // 판정은 서버(/api/auth/network)가 하고, 로그인하면 이 화면은 사라진다.
  if (!loading && loginRequired && !user) {
    return <AppLoginRequired />;
  }

  if (matches(FULLSCREEN_ROUTES)) {
    return <div className="h-screen overflow-hidden">{children}</div>;
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-surface">
      {/* 플랫폼 공통 상단바(UtilityBar)는 이 서비스에서 띄우지 않는다 (2026-08-25 사용자 요청).
          휴대폰 폭에서 10개 링크가 5줄로 접혀 화면 위쪽 1/4을 먹었고, 회의를 보러 온
          사람에게는 매번 지나쳐야 하는 띠가 됐다. 컴포넌트(`./UtilityBar`)와 정본
          토큰(`.ggc-utility-bar`)은 다른 서비스가 쓰므로 지우지 않고 두었다 —
          되살릴 때는 이 자리에 <UtilityBar /> 한 줄만 되돌리면 된다. */}
      <div className="relative flex flex-1 min-h-0">
      {/* 스킵 링크: 키보드 사용자가 반복 내비게이션을 건너뛰고 본문으로 이동 */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-[60] focus:rounded-md focus:bg-primary focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-white"
      >
        본문 바로가기
      </a>
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0 relative">
        {/* 휴대폰에서만 보이는 의회 마크 — 사이드바가 서랍으로 숨어 소속이 사라진 자리.
            보일지 말지는 컴포넌트가 스스로 정한다(경로 + 채널 선택 여부). 그래서
            `useSearchParams` 를 쓰며, Next 14 규칙상 Suspense 안이어야 한다 —
            여기만 감싸므로 나머지 페이지의 정적 렌더는 그대로다. */}
        <React.Suspense fallback={null}>
          <MobileBrandBar />
        </React.Suspense>
        {/* 전역 컨트롤: 헤더 바 제거 → 페이지 제목 줄과 같은 높이로 우측 상단에 표시.
            모바일에서 마크 줄(48px)이 생기면 그 줄 안쪽 오른편에 자연히 들어앉는다. */}
        <div className="absolute top-5 right-4 sm:top-6 sm:right-6 z-30">
          <GlobalNavControls />
        </div>
        <main
          id="main-content"
          tabIndex={-1}
          className="flex-1 flex flex-col overflow-y-auto bg-surface focus:outline-none"
        >
          {/* 브레드크럼: 홈(/)에서는 Breadcrumbs 자체가 숨음 */}
          <div className="shrink-0">
            <Breadcrumbs />
          </div>
          {/* h-full 루트 페이지(/live, /vod/[id]/* 등)가 브레드크럼을 제외한 잔여 높이를 기준으로 잡도록 */}
          <div className="flex-1 min-h-0">{children}</div>
        </main>
      </div>
      </div>
    </div>
  );
}
