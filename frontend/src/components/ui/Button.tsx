'use client';

/**
 * Button — KRDS 표준 버튼 프리미티브
 *
 * variant:
 * - primary: 정부 블루 채움 (기본 액션)
 * - secondary: 연한 primary-5 배경 (보조 액션)
 * - outline: 회색 테두리 흰 배경
 * - danger: 위험/삭제 액션
 * - text: 배경 없는 텍스트 버튼
 *
 * size: sm(32px) | md(40px) | lg(48px)
 * loading: 스피너 표시 + aria-busy + 클릭 차단
 */

import React, { forwardRef } from 'react';

export type ButtonVariant = 'primary' | 'secondary' | 'outline' | 'danger' | 'text';
export type ButtonSize = 'sm' | 'md' | 'lg';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** 로딩 중: 스피너 표시 + 비활성화 + aria-busy */
  loading?: boolean;
}

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: 'bg-primary text-white hover:bg-primary-dark',
  secondary: 'bg-primary-5 text-primary-dark hover:bg-primary-10',
  outline: 'border border-gray-300 bg-white text-gray-900 hover:bg-gray-50',
  danger: 'bg-danger text-white hover:bg-danger/90',
  text: 'text-gray-700 hover:bg-gray-50',
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-sm',
  md: 'h-10 px-4 text-sm',
  lg: 'h-12 px-5 text-base',
};

const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'primary',
    size = 'md',
    loading = false,
    disabled,
    className = '',
    children,
    type = 'button',
    ...rest
  },
  ref
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={[
        'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md font-medium transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-1',
        'disabled:opacity-50 disabled:cursor-not-allowed',
        VARIANT_CLASSES[variant],
        SIZE_CLASSES[size],
        className,
      ]
        .join(' ')
        .trim()}
      {...rest}
    >
      {loading && (
        <span
          className="inline-block h-4 w-4 flex-shrink-0 animate-spin rounded-full border-2 border-current border-t-transparent"
          aria-hidden="true"
        />
      )}
      {children}
    </button>
  );
});

export default Button;
