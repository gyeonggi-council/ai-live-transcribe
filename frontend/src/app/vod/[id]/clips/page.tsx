'use client';

import React, { useEffect } from 'react';

import Link from 'next/link';

import ClipWorkbench, { CLIP_ROLES } from '@/components/clips/ClipWorkbench';
import RoleGuard from '@/components/RoleGuard';
import { useBreadcrumb } from '@/contexts/BreadcrumbContext';
import { apiClient } from '@/lib/api';
import type { MeetingType } from '@/types';

interface ClipsPageProps {
  params: { id: string };
}

/**
 * /vod/[id]/clips — 이 회의의 발언영상 추출 (웹 워크벤치, 2026-09)
 *
 * 예전엔 `ggcextractor://open?midx=` 로 데스크톱 추출기를 띄우던 핸드오프 페이지였다.
 * 이제 브라우저에서 바로 자른다 — 회의가 정해져 있으니 회의 목록은 접고 시작한다.
 */
function ClipsPageContent({ meetingId }: { meetingId: string }) {
  const { setTitle } = useBreadcrumb();

  useEffect(() => {
    let cancelled = false;
    apiClient<MeetingType>(`/api/meetings/${meetingId}`)
      .then((m) => {
        if (!cancelled && m?.title) setTitle(m.title);
      })
      .catch(() => {
        /* 브레드크럼 제목은 부가 정보 */
      });
    return () => {
      cancelled = true;
    };
  }, [meetingId, setTitle]);

  return (
    <div data-testid="clips-page" className="h-full min-h-0">
      <ClipWorkbench meetingId={meetingId} listCollapsed />
    </div>
  );
}

export default function ClipsPage({ params }: ClipsPageProps) {
  return (
    <RoleGuard
      roles={CLIP_ROLES}
      fallback={
        <div className="p-8 text-center text-gray-500">
          <p className="mb-3">발언영상 추출은 로그인이 필요합니다.</p>
          <Link href="/login" className="text-primary underline">
            로그인 하러 가기
          </Link>
        </div>
      }
    >
      <ClipsPageContent meetingId={params.id} />
    </RoleGuard>
  );
}
