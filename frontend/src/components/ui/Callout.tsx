/**
 * Callout — KRDS 표준 안내 박스
 *
 * variant: info | warning | success | danger
 * 좌측 아이콘 + 연한 시맨틱 배경 + 테두리. danger는 role="alert".
 */

import React from 'react';

export type CalloutVariant = 'info' | 'warning' | 'success' | 'danger';

export interface CalloutProps {
  variant?: CalloutVariant;
  /** 굵은 제목 (선택) */
  title?: string;
  children: React.ReactNode;
  className?: string;
}

interface VariantStyle {
  container: string;
  icon: string;
  iconPath: string;
}

const VARIANT_STYLES: Record<CalloutVariant, VariantStyle> = {
  info: {
    container: 'bg-info/5 border-info/30',
    icon: 'text-info',
    iconPath: 'M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
  },
  warning: {
    container: 'bg-warning-bg/10 border-warning-bg/40',
    icon: 'text-warning-bg',
    iconPath:
      'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z',
  },
  success: {
    container: 'bg-success/5 border-success/30',
    icon: 'text-success',
    iconPath: 'M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
  },
  danger: {
    container: 'bg-danger/5 border-danger/30',
    icon: 'text-danger',
    iconPath:
      'M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z',
  },
};

export default function Callout({
  variant = 'info',
  title,
  children,
  className = '',
}: CalloutProps) {
  const style = VARIANT_STYLES[variant];

  return (
    <div
      role={variant === 'danger' ? 'alert' : 'note'}
      className={`flex gap-3 rounded-md border p-4 text-sm text-gray-800 ${style.container} ${className}`
        .replace(/\s+/g, ' ')
        .trim()}
    >
      <svg
        className={`mt-0.5 h-5 w-5 flex-shrink-0 ${style.icon}`}
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
        strokeWidth={2}
        aria-hidden="true"
      >
        <path strokeLinecap="round" strokeLinejoin="round" d={style.iconPath} />
      </svg>
      <div className="min-w-0 flex-1">
        {title && <p className="mb-1 font-semibold text-gray-900">{title}</p>}
        {children}
      </div>
    </div>
  );
}
