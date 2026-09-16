'use client';

import React from 'react';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { extractMeetingIdFromPath } from '@/config/navigation';
import type { NavModule } from '@/config/navigation';

/** Heroicons outline SVG paths */
const ICON_PATHS: Record<string, string> = {
  'calendar': 'M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5',
  'document-text': 'M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z',
  'user-group': 'M18 18.72a9.094 9.094 0 003.741-.479 3 3 0 00-4.682-2.72m.94 3.198l.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0112 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 016 18.719m12 0a5.971 5.971 0 00-.941-3.197m0 0A5.995 5.995 0 0012 12.75a5.995 5.995 0 00-5.058 2.772m0 0a3 3 0 00-4.681 2.72 8.986 8.986 0 003.74.477m.94-3.197a5.971 5.971 0 00-.94 3.197M15 6.75a3 3 0 11-6 0 3 3 0 016 0zm6 3a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0zm-13.5 0a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0z',
  'check-badge': 'M9 12.75L11.25 15 15 9.75M21 12c0 1.268-.63 2.39-1.593 3.068a3.745 3.745 0 01-1.043 3.296 3.745 3.745 0 01-3.296 1.043A3.745 3.745 0 0112 21c-1.268 0-2.39-.63-3.068-1.593a3.746 3.746 0 01-3.296-1.043 3.745 3.745 0 01-1.043-3.296A3.745 3.745 0 013 12c0-1.268.63-2.39 1.593-3.068a3.745 3.745 0 011.043-3.296 3.746 3.746 0 013.296-1.043A3.746 3.746 0 0112 3c1.268 0 2.39.63 3.068 1.593a3.746 3.746 0 013.296 1.043 3.746 3.746 0 011.043 3.296A3.745 3.745 0 0121 12z',
  'pencil-square': 'M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10',
  'clipboard-document-list': 'M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25z',
  'magnifying-glass': 'M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z',
  'film': 'M4.5 4.5h15A1.5 1.5 0 0121 6v12a1.5 1.5 0 01-1.5 1.5h-15A1.5 1.5 0 013 18V6a1.5 1.5 0 011.5-1.5zM7.5 4.5v15m9-15v15M3 9h4.5M3 15h4.5M16.5 9H21M16.5 15H21',
  'document-duplicate': 'M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 01-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 011.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 00-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 01-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 00-3.375-3.375h-1.5a1.125 1.125 0 01-1.125-1.125v-1.5a3.375 3.375 0 00-3.375-3.375H9.75',
  'sparkles': 'M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z',
  'cog-6-tooth': 'M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z M15 12a3 3 0 11-6 0 3 3 0 016 0z',
};

function NavIcon({ name, className }: { name: string; className?: string }) {
  const path = ICON_PATHS[name];
  if (!path) return null;
  return (
    <svg className={className || 'w-5 h-5'} fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d={path} />
    </svg>
  );
}

interface SidebarNavItemProps {
  module: NavModule;
  collapsed: boolean;
}

/** 활성 항목 공통 표식 — 왼쪽 3px 레일 + 연한 브랜드 배경 */
const ACTIVE_ROW = 'bg-primary-5 text-primary-dark font-semibold shadow-[inset_3px_0_0_0_var(--ggc-primary)]';
const IDLE_ROW = 'text-text-secondary font-medium hover:bg-gray-50 hover:text-text';

/**
 * SidebarNavItem — 사이드바 한 모듈.
 *
 * **아코디언이 없다**(2026-08-25 개선안 2c). 예전에는 모든 모듈이 접혔다 펴지는
 * 버튼이었는데, 자식이 하나뿐인 모듈(AI 어시스턴트·통합검색 등)까지 한 번 눌러야
 * 목적지가 나와서 클릭 한 번이 순수한 낭비였다. 이제 두 모양뿐이다.
 *
 * - 자식 1개  → **직행 링크** (아이콘 + 이름이 곧 그 자식의 href)
 * - 자식 2개+ → **정적 묶음** (이름은 누를 수 없는 머리글, 자식은 항상 보인다)
 *
 * 회의 컨텍스트가 필요한 모듈(`requiresMeeting`)은 /vod/[id] 밖에서 비활성이며,
 * 그때는 눌리지 않는 흐린 줄로 남긴다 — 사라지면 메뉴가 회의마다 달라 보인다.
 */
export default function SidebarNavItem({ module, collapsed }: SidebarNavItemProps) {
  const pathname = usePathname();
  const meetingId = extractMeetingIdFromPath(pathname);

  const isDisabled = Boolean(module.requiresMeeting && !meetingId);

  const hrefOf = (item: NavModule['items'][number]) =>
    item.href || (item.getHref && meetingId ? item.getHref(meetingId) : null);

  // 현재 경로가 이 모듈의 하위 항목 중 하나인지 확인
  const isActive = module.items.some((item) => hrefOf(item) === pathname);

  const single = module.items.length === 1 ? module.items[0] : null;
  const singleHref = single ? hrefOf(single) : null;

  if (collapsed) {
    // 접힌 사이드바 — 아이콘만. 자식 1개면 그 자식으로, 여럿이면 첫 자식으로 간다.
    const target = singleHref ?? (module.items.length > 0 ? hrefOf(module.items[0]!) : null);
    const iconRow = `w-full flex items-center justify-center py-3 transition-colors ${
      isActive
        ? 'text-primary-dark bg-primary-5 shadow-[inset_3px_0_0_0_var(--ggc-primary)]'
        : 'text-text-muted hover:bg-gray-50 hover:text-text-secondary'
    }`;

    return (
      <div className="relative group">
        {target && !isDisabled ? (
          <Link href={target} className={iconRow} aria-label={module.label}>
            <NavIcon name={module.icon} />
          </Link>
        ) : (
          <div className={`${iconRow} text-text-muted`} aria-label={module.label} aria-disabled="true">
            <NavIcon name={module.icon} />
          </div>
        )}
        {/* 호버 툴팁 */}
        <div className="absolute left-full top-0 ml-2 hidden group-hover:block z-50">
          <div className="bg-surface-overlay text-text text-xs rounded px-2 py-1 whitespace-nowrap border border-border">
            {module.label}
          </div>
        </div>
      </div>
    );
  }

  // ── 자식이 하나 → 직행 링크 ─────────────────────────────────────────────
  if (single && singleHref) {
    if (isDisabled) {
      return (
        <div
          className="flex items-center gap-3 px-4 h-[38px] text-sm text-text-muted cursor-not-allowed"
          aria-disabled="true"
          title="회의를 먼저 선택하세요"
        >
          <NavIcon name={module.icon} className="w-[19px] h-[19px] flex-shrink-0 text-text-dim" />
          <span className="flex-1 text-left">{module.label}</span>
        </div>
      );
    }

    return (
      <Link
        href={singleHref}
        className={`flex items-center gap-3 px-4 h-[38px] text-sm transition-colors ${isActive ? ACTIVE_ROW : IDLE_ROW}`}
        aria-current={isActive ? 'page' : undefined}
      >
        <NavIcon
          name={module.icon}
          className={`w-[19px] h-[19px] flex-shrink-0 ${isActive ? 'text-primary' : 'text-text-dim'}`}
        />
        <span className="flex-1 text-left">{module.label}</span>
      </Link>
    );
  }

  // ── 자식이 여럿 → 정적 묶음 ─────────────────────────────────────────────
  return (
    <div>
      {module.dividerBefore && <div className="border-t border-border my-2 h-px" />}

      {/* 머리글 — 누를 수 없다. 목적지가 아니라 이름표다. */}
      <div className="flex items-center gap-2.5 px-4 pt-1.5 pb-1.5">
        <NavIcon name={module.icon} className="w-4 h-4 flex-shrink-0 text-text-dim" />
        <span className="text-[11px] font-bold tracking-[0.08em] text-text-dim">{module.label}</span>
      </div>

      {module.items.map((item) => {
        const href = hrefOf(item);
        if (!href) return null;
        const itemActive = pathname === href;

        // 외부 링크(http...)는 새 탭으로
        if (/^https?:\/\//.test(href)) {
          return (
            <a
              key={item.id}
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 h-9 pl-[42px] pr-4 text-sm text-text-secondary hover:bg-gray-50 hover:text-text transition-colors"
            >
              {item.label}
              <svg className="w-3 h-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
            </a>
          );
        }

        if (isDisabled) {
          return (
            <div
              key={item.id}
              className="flex items-center h-9 pl-[42px] pr-4 text-sm text-text-muted cursor-not-allowed"
              aria-disabled="true"
            >
              {item.label}
            </div>
          );
        }

        return (
          <Link
            key={item.id}
            href={href}
            className={`flex items-center h-9 pl-[42px] pr-4 text-sm transition-colors ${itemActive ? ACTIVE_ROW : IDLE_ROW}`}
            aria-current={itemActive ? 'page' : undefined}
          >
            {item.label}
          </Link>
        );
      })}
    </div>
  );
}
