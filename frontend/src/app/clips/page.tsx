'use client';

import React, { Suspense, useEffect, useState } from 'react';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';

import ClipWorkbench, { CLIP_ROLES } from '@/components/clips/ClipWorkbench';
import RoleGuard from '@/components/RoleGuard';
import { resolveMeetingByMidx } from '@/lib/api';

/**
 * /clips — 발언영상 추출 워크벤치 (데스크톱 영상추출기 대체, 2026-09)
 *
 * ?meeting=<id>  바로 그 회의로
 * ?midx=<n>      옛 추출기 링크(영상 번호) → 회의 ID 로 바꿔 열어 준다
 */
function ClipsPageContent() {
  const router = useRouter();
  const params = useSearchParams();
  const meetingParam = params.get('meeting');
  const midxParam = params.get('midx');
  const [resolveError, setResolveError] = useState<string | null>(null);

  useEffect(() => {
    if (meetingParam || !midxParam || !/^\d+$/.test(midxParam)) return;
    let cancelled = false;
    resolveMeetingByMidx(midxParam)
      .then((r) => {
        if (!cancelled) router.replace(`/clips?meeting=${encodeURIComponent(r.meeting_id)}`);
      })
      .catch((e: unknown) => {
        if (!cancelled) setResolveError(e instanceof Error ? e.message : '회의를 찾지 못했습니다.');
      });
    return () => {
      cancelled = true;
    };
  }, [meetingParam, midxParam, router]);

  return (
    <div className="flex flex-col h-full min-h-0">
      {resolveError && (
        <div data-testid="resolve-error" className="mx-3 mt-3 rounded-md bg-amber-50 px-3 py-2 text-[13px] text-amber-900">
          영상 번호 {midxParam} — {resolveError} 왼쪽 목록에서 회의를 골라 주세요.
        </div>
      )}
      <div className="flex-1 min-h-0">
        <ClipWorkbench
          meetingId={meetingParam}
          onSelectMeeting={(id) => router.replace(`/clips?meeting=${encodeURIComponent(id)}`)}
        />
      </div>
    </div>
  );
}

export default function ClipsPage() {
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
      <Suspense fallback={<div className="p-6 text-sm text-text-muted">불러오는 중…</div>}>
        <ClipsPageContent />
      </Suspense>
    </RoleGuard>
  );
}
