'use client';

import React from 'react';

import { usePathname } from 'next/navigation';

import { BREADCRUMB_MAP } from '@/config/navigation';
import { useBreadcrumb } from '@/contexts/BreadcrumbContext';

export default function Breadcrumbs() {
  const pathname = usePathname();
  const { dynamicTitle } = useBreadcrumb();

  // 정적 매핑에서 브레드크럼 가져오기
  let crumbs = BREADCRUMB_MAP[pathname];

  // 동적 경로 처리: /vod/[id], /vod/[id]/edit, /vod/[id]/verify
  if (!crumbs && pathname.startsWith('/vod/')) {
    const segments = pathname.split('/').filter(Boolean);
    // /vod/[id]
    if (segments.length === 2) {
      crumbs = ['회의관리', dynamicTitle || 'VOD 상세'];
    }
    // /vod/[id]/speaker
    else if (segments.length === 3 && segments[2] === 'speaker') {
      crumbs = ['화자관리', dynamicTitle || 'VOD 상세', '화자 식별'];
    }
    // /vod/[id]/edit
    else if (segments.length === 3 && segments[2] === 'edit') {
      crumbs = ['교정/편집관리', dynamicTitle || 'VOD 상세', '자막 편집'];
    }
    // /vod/[id]/verify
    else if (segments.length === 3 && segments[2] === 'verify') {
      crumbs = ['대조관리', dynamicTitle || 'VOD 상세', '자막 검증'];
    }
    // /vod/[id]/clips
    else if (segments.length === 3 && segments[2] === 'clips') {
      crumbs = ['발언영상', dynamicTitle || 'VOD 상세', '발언영상 추출'];
    }
    // /vod/[id]/materials (요구자료 전체 화면)
    else if (segments.length === 3 && segments[2] === 'materials') {
      crumbs = ['회의관리', dynamicTitle || 'VOD 상세', '요구자료'];
    }
  }

  // 홈(/) 에서는 브레드크럼 숨김 — 사이드바에서 현재 위치가 명확함
  if (!crumbs || crumbs.length === 0 || pathname === '/') {
    return null;
  }

  return (
    <nav
      aria-label="브레드크럼"
      className="flex items-center text-sm text-gray-500 min-w-0 px-4 sm:px-6 py-2 pr-20"
    >
      {crumbs.map((crumb, index) => (
        <React.Fragment key={index}>
          {index > 0 && (
            <span className="mx-1.5 text-text-muted" aria-hidden="true">/</span>
          )}
          {index === crumbs!.length - 1 ? (
            <span className="text-text font-medium truncate" aria-current="page">{crumb}</span>
          ) : (
            <span className="text-text-muted truncate">{crumb}</span>
          )}
        </React.Fragment>
      ))}
    </nav>
  );
}
