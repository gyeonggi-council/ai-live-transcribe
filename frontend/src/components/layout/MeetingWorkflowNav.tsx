'use client';

import React from 'react';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { extractMeetingIdFromPath } from '@/config/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { useBreadcrumb } from '@/contexts/BreadcrumbContext';

interface MeetingWorkflowNavProps {
  collapsed: boolean;
}

const EDIT_ROLES = ['committee_staff', 'stenographer', 'admin'];

const WORKFLOW_STEPS = [
  { label: '회의 정보', suffix: '', requiresAuth: false },
  // 화자 관리/자막 편집/자막 검증 — 비핵심, 나중에 재활성화
];

export default function MeetingWorkflowNav({ collapsed }: MeetingWorkflowNavProps) {
  const pathname = usePathname();
  const { dynamicTitle } = useBreadcrumb();
  const { user } = useAuth();
  const meetingId = extractMeetingIdFromPath(pathname);

  if (!meetingId || collapsed) return null;

  const canEdit = user && EDIT_ROLES.includes(user.role);

  return (
    <div className="border-t border-border p-3">
      <div className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2 px-1">
        현재 회의
      </div>
      {dynamicTitle && (
        <div className="text-sm font-medium text-text mb-3 px-1 truncate" title={dynamicTitle}>
          {dynamicTitle}
        </div>
      )}
      <div className="space-y-0.5">
        {WORKFLOW_STEPS.map((step, index) => {
          const href = `/vod/${meetingId}${step.suffix}`;
          const isActive = pathname === href;
          const disabled = step.requiresAuth && !canEdit;

          if (disabled) {
            return (
              <div
                key={step.suffix || 'info'}
                className="flex items-center gap-2.5 px-2 py-1.5 rounded-md text-sm text-text-muted cursor-not-allowed"
                title="로그인이 필요합니다"
              >
                <span className="flex items-center justify-center w-5 h-5 rounded-full text-xs font-medium bg-surface-overlay text-text-muted">
                  {index + 1}
                </span>
                <span>{step.label}</span>
              </div>
            );
          }

          return (
            <Link
              key={step.suffix || 'info'}
              href={href}
              className={`flex items-center gap-2.5 px-2 py-1.5 rounded-md text-sm transition-colors ${
                isActive
                  ? 'bg-primary-5 text-primary-dark font-medium shadow-[inset_3px_0_0_0_var(--ggc-primary)]'
                  : 'text-text-secondary hover:bg-gray-50 hover:text-text'
              }`}
              aria-current={isActive ? 'page' : undefined}
            >
              <span className={`flex items-center justify-center w-5 h-5 rounded-full text-xs font-medium ${
                isActive ? 'bg-primary text-white' : 'bg-surface-overlay text-text-secondary'
              }`}>
                {index + 1}
              </span>
              <span>{step.label}</span>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
