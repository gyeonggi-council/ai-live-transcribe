import React from 'react';

import Link from 'next/link';

import { Button } from '@/components/ui';

import Badge from './Badge';

export interface HeaderProps {
  title?: string;
  showSearch?: boolean;
  showLiveBadge?: boolean;
  showVodBadge?: boolean;
  showRegisterButton?: boolean;
  onRegisterClick?: () => void;
  children?: React.ReactNode;
}

export default function Header({
  title,
  showSearch = false,
  showLiveBadge = false,
  showVodBadge = false,
  showRegisterButton = false,
  onRegisterClick,
  children,
}: HeaderProps) {
  return (
    <header className="h-16 bg-white border-b border-border px-4 flex items-center justify-between">
      <div className="flex items-center gap-4">
        <Link href="/" className="text-xl font-bold text-gray-900 hover:text-primary transition-colors">
          경기도의회 자막
        </Link>

        {title && (
          <span className="text-gray-500" aria-hidden="true">|</span>
        )}

        {title && (
          <span className="text-lg font-medium text-gray-700">{title}</span>
        )}

        {showLiveBadge && (
          <Badge variant="live">Live</Badge>
        )}

        {showVodBadge && (
          <Badge variant="secondary">VOD</Badge>
        )}
      </div>

      <div className="flex items-center gap-4">
        {showSearch && children}

        <Link
          href="/search"
          className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-50 rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          title="통합 검색"
          aria-label="통합 검색"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
        </Link>

        {showRegisterButton && (
          <Button onClick={onRegisterClick}>VOD 등록</Button>
        )}
      </div>
    </header>
  );
}
