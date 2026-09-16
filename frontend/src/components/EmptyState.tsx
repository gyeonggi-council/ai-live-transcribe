/**
 * EmptyState — 데이터 없음/에러 상태 공용 컴포넌트
 *
 * 단순 "데이터가 없습니다" 텍스트의 문제:
 * - 사용자가 "무엇을 해야 할지" 모름
 * - 정말 없는 건지 로딩 실패인지 불분명
 * - 공공기관 톤과 맞지 않음
 *
 * 이 컴포넌트는:
 * - 아이콘(또는 커스텀 노드)으로 상태 시각화
 * - 명확한 제목 + 보조 설명
 * - 선택적 주요 액션(CTA)
 * - variant로 일반 빈 상태 vs 에러 구분
 */

import React from 'react';

import { Button } from './ui';

type Variant = 'default' | 'error' | 'search';

export interface EmptyStateProps {
  variant?: Variant;
  title: string;
  description?: string;
  action?: {
    label: string;
    onClick: () => void;
  };
  secondaryAction?: {
    label: string;
    onClick: () => void;
  };
  /** 커스텀 아이콘 슬롯 (미지정 시 variant 기본 아이콘) */
  icon?: React.ReactNode;
  className?: string;
}

const DEFAULT_ICONS: Record<Variant, React.ReactNode> = {
  default: (
    <svg className="w-14 h-14" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z" />
    </svg>
  ),
  error: (
    <svg className="w-14 h-14" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
    </svg>
  ),
  search: (
    <svg className="w-14 h-14" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
    </svg>
  ),
};

export default function EmptyState({
  variant = 'default',
  title,
  description,
  action,
  secondaryAction,
  icon,
  className = '',
}: EmptyStateProps) {
  const iconColor = variant === 'error' ? 'text-danger/60' : 'text-gray-300';

  return (
    <div
      role={variant === 'error' ? 'alert' : 'status'}
      className={`flex flex-col items-center justify-center text-center py-12 px-6 ${className}`}
    >
      <div className={`mb-4 ${iconColor}`}>{icon ?? DEFAULT_ICONS[variant]}</div>
      <h3
        className={`text-base font-semibold mb-1 ${
          variant === 'error' ? 'text-danger' : 'text-gray-800'
        }`}
      >
        {title}
      </h3>
      {description && (
        <p className="text-sm text-gray-500 max-w-md mb-4 leading-relaxed">{description}</p>
      )}
      {(action || secondaryAction) && (
        <div className="flex items-center gap-2 mt-2">
          {action && (
            <Button variant="primary" size="md" onClick={action.onClick}>
              {action.label}
            </Button>
          )}
          {secondaryAction && (
            <Button variant="outline" size="md" onClick={secondaryAction.onClick}>
              {secondaryAction.label}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
