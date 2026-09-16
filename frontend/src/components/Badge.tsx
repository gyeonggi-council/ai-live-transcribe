import React from 'react';

export type BadgeVariant = 'live' | 'success' | 'warning' | 'secondary';

export interface BadgeProps {
  variant: BadgeVariant;
  children: React.ReactNode;
  className?: string;
}

// KRDS 시맨틱 연한 톤 (live=danger 계열)
const variantStyles: Record<BadgeVariant, string> = {
  live: 'bg-danger/10 text-danger',
  success: 'bg-success/10 text-success',
  warning: 'bg-warning-bg/20 text-warning-dark',
  secondary: 'bg-surface-raised text-text-secondary',
};

export default function Badge({ variant, children, className = '' }: BadgeProps) {
  const baseStyles = 'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium';
  const variantStyle = variantStyles[variant];

  return (
    <span className={`${baseStyles} ${variantStyle} ${className}`.trim()}>
      {variant === 'live' && (
        <span className="w-2 h-2 bg-danger rounded-full mr-1.5 animate-live-pulse" />
      )}
      {children}
    </span>
  );
}
