'use client';

import React, { useState } from 'react';

import Link from 'next/link';

import AutoClipsPanel from '@/components/clips/AutoClipsPanel';
import ClipJobsPanel from '@/components/clips/ClipJobsPanel';
import { CLIP_ROLES } from '@/components/clips/ClipWorkbench';
import PageHeader from '@/components/PageHeader';
import RoleGuard from '@/components/RoleGuard';
import { useAuth } from '@/contexts/AuthContext';

type View = 'mine' | 'auto' | 'all';

/**
 * /clips/jobs — 추출 기록 (7일 보관 · 재다운로드). 관리자는 전체 기록도 본다.
 * 「자동 클립」 탭(2026-09-10)은 모두가 본다 — AI 자막이 끝난 회의의 의원 전원 영상을 서버가 미리 잘라 둔 것.
 */
function JobsContent() {
  const { user } = useAuth();
  const [view, setView] = useState<View>('mine');
  const isAdmin = user?.role === 'admin';
  // 로그인하지 않은 의회망 방문자는 브라우저별로 기록이 갈린다(X-Guest-Id) — 다른 PC·다른 브라우저에서는 안 보인다
  const isGuest = !user;
  const tabs: { key: View; label: string; testId: string }[] = [
    { key: 'mine', label: isGuest ? '이 브라우저의 기록' : '내 기록', testId: 'scope-mine' },
    { key: 'auto', label: '자동 클립', testId: 'scope-auto' },
    ...(isAdmin ? [{ key: 'all' as View, label: '전체', testId: 'scope-all' }] : []),
  ];

  return (
    <div className="p-6 max-w-6xl mx-auto w-full">
      <PageHeader
        title="추출 기록"
        description={
          view === 'auto'
            ? 'AI 자막이 끝난 회의의 의원 발언 영상을 서버가 자동으로 잘라 둡니다(720p). 3일 동안 내려받을 수 있습니다.'
            : isGuest
              ? '로그인 없이 추출한 기록은 이 브라우저에서만 보입니다. 완료된 클립은 7일 동안 다시 내려받을 수 있습니다.'
              : '완료된 클립은 7일 동안 다시 내려받을 수 있습니다. 저장 공간이 차면 오래된 것부터 지워집니다.'
        }
        actions={
          <div className="flex items-center gap-2">
            <div className="inline-flex rounded-md overflow-hidden border border-border text-[13px]">
              {tabs.map((t, i) => (
                <button
                  key={t.key}
                  type="button"
                  data-testid={t.testId}
                  className={`px-3 py-1.5 ${i ? 'border-l border-border' : ''} ${
                    view === t.key ? 'bg-primary text-white' : 'bg-white text-text-muted'
                  }`}
                  onClick={() => setView(t.key)}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <Link href="/clips" className="text-sm text-primary underline">
              워크벤치로
            </Link>
          </div>
        }
      />
      {view === 'auto' ? <AutoClipsPanel days={3} /> : <ClipJobsPanel scope={view} />}
    </div>
  );
}

export default function ClipJobsPage() {
  return (
    <RoleGuard
      roles={CLIP_ROLES}
      fallback={
        <div className="p-8 text-center text-gray-500">
          <p className="mb-3">추출 기록은 로그인이 필요합니다.</p>
          <Link href="/login" className="text-primary underline">
            로그인 하러 가기
          </Link>
        </div>
      }
    >
      <JobsContent />
    </RoleGuard>
  );
}
