'use client';

import React, { useEffect } from 'react';

import Image from 'next/image';
import Link from 'next/link';

import VisitorCounter from '@/components/VisitorCounter';
import {
  HIDDEN_MODULE_IDS,
  NAV_MODULES,
  SIDEBAR_COLLAPSED_WIDTH,
  SIDEBAR_WIDTH,
  TOOL_LINKS,
} from '@/config/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { useSidebar } from '@/contexts/SidebarContext';

import MeetingWorkflowNav from './MeetingWorkflowNav';
import SidebarNavItem from './SidebarNavItem';

const ROLE_LABELS: Record<string, string> = {
  anonymous: '비로그인',
  council_guest: '의회망',
  staff: '직원',
  committee_staff: '위원회 직원',
  meeting_manager: '회의 관리자',
  stenographer: '속기사',
  admin: '관리자',
};

export default function Sidebar() {
  const { collapsed, mobileOpen, toggleCollapsed, setMobileOpen } = useSidebar();
  const { user, logout, councilNetwork } = useAuth();
  // 로그인하지 않은 의회망 방문자는 'council_guest' — 발언영상·AI 그룹이 열린다(2026-09-11 담당자 요청)
  const role = user?.role ?? (councilNetwork ? 'council_guest' : 'anonymous');

  const visibleModules = NAV_MODULES.filter(
    (m) =>
      !HIDDEN_MODULE_IDS.has(m.id) &&
      (!m.roles || m.roles.includes(role)),
  );

  // 모바일 사이드바 열림 상태일 때:
  // 1) ESC 키로 닫기
  // 2) body 스크롤 잠금 (뒷면 스크롤 방지)
  useEffect(() => {
    if (!mobileOpen) return;

    function handleEsc(e: KeyboardEvent) {
      if (e.key === 'Escape') setMobileOpen(false);
    }
    document.addEventListener('keydown', handleEsc);

    // 스크롤 잠금
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', handleEsc);
      document.body.style.overflow = originalOverflow;
    };
  }, [mobileOpen, setMobileOpen]);

  const sidebarContent = (
    <div className="flex flex-col h-full">
      {/* 로고 + 시스템 제목 */}
      <Link
        href="/"
        className={`flex items-center border-b border-border hover:bg-gray-50 transition-colors ${collapsed ? 'justify-center px-2 py-4' : 'px-4 py-4'}`}
      >
        {collapsed ? (
          <Image
            src="https://www.ggc.go.kr/design/theme/asa/images/assembly_mark.png"
            alt="경기도의회"
            width={32}
            height={32}
            className="h-8 w-8 object-contain"
            unoptimized
          />
        ) : (
          <div className="flex items-center gap-2.5">
            <Image
              src="https://www.ggc.go.kr/design/theme/asa/images/assembly_mark.png"
              alt="경기도의회"
              width={36}
              height={36}
              className="h-9 w-9 object-contain flex-shrink-0"
              unoptimized
            />
            <div>
              <div className="text-sm font-semibold text-text leading-tight">경기도의회</div>
              <div className="text-[11px] text-text-muted leading-tight">영상회의록 통합플랫폼</div>
            </div>
          </div>
        )}
      </Link>

      {/* 네비게이션 모듈 + 도구 묶음 */}
      <nav className="flex-1 min-h-0 overflow-y-auto py-2.5 flex flex-col">
        {visibleModules.map((module) => (
          <SidebarNavItem key={module.id} module={module} collapsed={collapsed} />
        ))}

        {/* 업무 메뉴와 도구 사이의 빈 공간 — 도구는 아래에 붙는다 */}
        <div className="flex-1 min-h-[12px]" />

        {/* 도구 — 외부 링크·다운로드·공지. 업무 동선과 섞이지 않게 맨 아래 별도 묶음 */}
        {!collapsed && (
          <div data-testid="sidebar-tools">
            <div className="px-4 pb-1.5">
              <span className="text-[11px] font-bold tracking-[0.08em] text-text-dim">도구</span>
            </div>
            {TOOL_LINKS.map((tool) =>
              tool.external ? (
                <a
                  key={tool.id}
                  href={tool.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1.5 h-8 px-4 text-[13px] text-text-muted hover:bg-gray-50 hover:text-text-secondary transition-colors"
                >
                  {tool.label}
                  <svg className="w-3 h-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                  </svg>
                </a>
              ) : (
                <Link
                  key={tool.id}
                  href={tool.href}
                  className="flex items-center h-8 px-4 text-[13px] text-text-muted hover:bg-gray-50 hover:text-text-secondary transition-colors"
                >
                  {tool.label}
                </Link>
              ),
            )}
          </div>
        )}
      </nav>

      {/* 회의 워크플로우 서브내비 */}
      <MeetingWorkflowNav collapsed={collapsed} />

      {/*
        하단 한 줄 — 접속자 · 계정 · 접기.
        예전에는 접속자 / 계정 / 접기가 각자 구분선을 달고 3층으로 쌓여 있었다
        (로고 아래선까지 세면 4겹). 성격이 다 다른 것도 아니고 전부 "메뉴가 아닌 것"이라
        한 줄에 모으고 구분선을 하나만 남겼다 (2026-08-25 개선안 2c).
      */}
      <div
        className={`flex-shrink-0 border-t border-border ${
          collapsed ? 'flex flex-col items-center gap-1.5 px-2 py-2.5' : 'flex items-center gap-2 px-3 py-2.5'
        }`}
      >
        {!collapsed && <VisitorCounter variant="inline" />}

        {user ? (
          <div className={collapsed ? 'contents' : 'flex flex-shrink-0 items-center gap-2 ml-auto min-w-0'}>
            {!collapsed && (
              <span className="max-w-[84px] truncate text-xs font-semibold text-text" title={`${user.display_name} · ${ROLE_LABELS[user.role] ?? user.role}`}>
                {user.display_name}
              </span>
            )}
            <button
              onClick={logout}
              className="text-xs text-text-muted hover:text-error transition-colors whitespace-nowrap"
              aria-label="로그아웃"
            >
              로그아웃
            </button>
          </div>
        ) : (
          <div className={collapsed ? 'contents' : 'flex flex-shrink-0 items-center gap-2 ml-auto min-w-0'}>
            {councilNetwork && !collapsed && (
              <span
                data-testid="council-guest-badge"
                className="text-xs text-text-muted whitespace-nowrap"
                title="의회 안에서 접속해 로그인 없이 발언영상·AI 어시스턴트를 쓸 수 있습니다"
              >
                의회망
              </span>
            )}
            <Link
              href="/login"
              className="text-xs font-semibold text-primary hover:text-primary-dark transition-colors whitespace-nowrap"
            >
              로그인
            </Link>
          </div>
        )}

        <button
          onClick={toggleCollapsed}
          className="flex-shrink-0 grid h-6 w-6 place-items-center rounded text-text-dim hover:bg-gray-50 hover:text-text-secondary transition-colors"
          aria-label={collapsed ? '사이드바 펼치기' : '사이드바 접기'}
          title={collapsed ? '사이드바 펼치기' : '사이드바 접기'}
        >
          <svg
            className={`w-[15px] h-[15px] transition-transform ${collapsed ? 'rotate-180' : ''}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7" />
          </svg>
        </button>
      </div>
    </div>
  );

  return (
    <>
      {/* 모바일 오버레이 (백드롭) */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 lg:hidden animate-fade-in"
          onClick={() => setMobileOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* 모바일 사이드바 */}
      <aside
        data-testid="sidebar-mobile"
        role="navigation"
        aria-label="주 메뉴"
        aria-hidden={!mobileOpen}
        className={`fixed top-0 left-0 z-50 h-full bg-white border-r border-border transition-transform duration-300 lg:hidden ${
          mobileOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
        style={{ width: SIDEBAR_WIDTH }}
      >
        {sidebarContent}
      </aside>

      {/* 데스크톱 사이드바 */}
      <aside
        data-testid="sidebar-desktop"
        className="hidden lg:flex flex-col bg-white border-r border-border transition-all duration-300 flex-shrink-0"
        style={{ width: collapsed ? SIDEBAR_COLLAPSED_WIDTH : SIDEBAR_WIDTH }}
      >
        {sidebarContent}
      </aside>
    </>
  );
}
