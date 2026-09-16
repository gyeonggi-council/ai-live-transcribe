/**
 * Skeleton — 로딩 상태를 위한 골격 로더
 *
 * 단순 텍스트 "로딩 중..." 대비 장점:
 * - 실제 콘텐츠 레이아웃 윤곽을 보여줘 이동감(layout shift) 체감 감소
 * - 사용자가 "곧 무엇이 나올지" 예상 가능 → 대기 인내심 증가
 * - animate-pulse로 활성성 시각화
 *
 * 변형(variant):
 * - box: 기본 블록 (커스텀 width/height)
 * - text: 텍스트 한 줄
 * - heading: 제목 크기 (text + 두꺼움)
 * - row: 리스트/테이블 행 (flex gap)
 * - card: 카드 (padding + box shape)
 */

import React from 'react';

type Variant = 'box' | 'text' | 'heading' | 'row' | 'card';

interface SkeletonProps {
  variant?: Variant;
  className?: string;
  count?: number;
  /** 역할 라벨 (스크린리더 안내) */
  label?: string;
}

export default function Skeleton({
  variant = 'box',
  className = '',
  count = 1,
  label = '로딩 중',
}: SkeletonProps) {
  const base = 'animate-pulse bg-gray-100 rounded';

  const variantClass: Record<Variant, string> = {
    box: 'h-4 w-full',
    text: 'h-3 w-3/4',
    heading: 'h-6 w-1/2',
    row: 'h-12 w-full',
    card: 'h-32 w-full',
  };

  if (count === 1) {
    return (
      <div
        role="status"
        aria-label={label}
        className={`${base} ${variantClass[variant]} ${className}`}
      >
        <span className="sr-only">{label}</span>
      </div>
    );
  }

  return (
    <div role="status" aria-label={label} className="space-y-2">
      <span className="sr-only">{label}</span>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className={`${base} ${variantClass[variant]} ${className}`}
          aria-hidden="true"
        />
      ))}
    </div>
  );
}

/**
 * TableSkeleton — 테이블 형태 전용 로더
 */
export function TableSkeleton({ rows = 5, columns = 4 }: { rows?: number; columns?: number }) {
  return (
    <div role="status" aria-label="테이블 로딩 중" className="bg-surface rounded-lg border border-border overflow-hidden">
      <span className="sr-only">테이블 로딩 중</span>
      {/* 헤더 */}
      <div className="bg-surface-raised border-b border-border px-4 py-3 flex gap-4">
        {Array.from({ length: columns }).map((_, i) => (
          <div
            key={i}
            className="animate-pulse bg-gray-200 rounded h-3 flex-1"
            aria-hidden="true"
          />
        ))}
      </div>
      {/* 행 */}
      <div className="divide-y divide-border">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="px-4 py-4 flex gap-4 items-center">
            {Array.from({ length: columns }).map((_, j) => (
              <div
                key={j}
                className="animate-pulse bg-gray-100 rounded h-4 flex-1"
                style={{ animationDelay: `${(i + j) * 50}ms` }}
                aria-hidden="true"
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * CardListSkeleton — 카드 그리드 형태 로더
 */
export function CardListSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div role="status" aria-label="목록 로딩 중" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <span className="sr-only">목록 로딩 중</span>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="bg-surface rounded-lg border border-border p-4 space-y-3"
          aria-hidden="true"
        >
          <div
            className="animate-pulse bg-gray-100 rounded h-5 w-2/3"
            style={{ animationDelay: `${i * 50}ms` }}
          />
          <div
            className="animate-pulse bg-gray-100 rounded h-3 w-full"
            style={{ animationDelay: `${i * 50 + 100}ms` }}
          />
          <div
            className="animate-pulse bg-gray-100 rounded h-3 w-4/5"
            style={{ animationDelay: `${i * 50 + 200}ms` }}
          />
        </div>
      ))}
    </div>
  );
}
