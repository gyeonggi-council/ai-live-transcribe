/**
 * Card — KRDS 표준 카드 컨테이너
 *
 * 흰 배경 + KRDS border(#e6e8ea) + rounded-lg. padding prop으로 내부 여백 제어.
 */

import React from 'react';

export type CardPadding = 'none' | 'sm' | 'md' | 'lg';

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  /** 내부 여백: none | sm(p-3) | md(p-4, 기본) | lg(p-6) */
  padding?: CardPadding;
}

const PADDING_CLASSES: Record<CardPadding, string> = {
  none: '',
  sm: 'p-3',
  md: 'p-4',
  lg: 'p-6',
};

export default function Card({ padding = 'md', className = '', children, ...rest }: CardProps) {
  return (
    <div
      className={`bg-white border border-border rounded-lg ${PADDING_CLASSES[padding]} ${className}`
        .replace(/\s+/g, ' ')
        .trim()}
      {...rest}
    >
      {children}
    </div>
  );
}
