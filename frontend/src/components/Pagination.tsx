'use client';

import React from 'react';

export interface PaginationProps {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  className?: string;
}

/**
 * Calculate visible page numbers with ellipsis for large page counts.
 *
 * Returns an array of page numbers and 'ellipsis' strings.
 * Always includes first and last page, with surrounding pages
 * around the current page.
 */
function getPageNumbers(
  currentPage: number,
  totalPages: number
): (number | 'ellipsis')[] {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, i) => i + 1);
  }

  const pages: (number | 'ellipsis')[] = [];

  // Always show first page
  pages.push(1);

  // Calculate range around current page
  const rangeStart = Math.max(2, currentPage - 1);
  const rangeEnd = Math.min(totalPages - 1, currentPage + 1);

  // Add ellipsis before range if needed
  if (rangeStart > 2) {
    pages.push('ellipsis');
  }

  // Add pages in range
  for (let i = rangeStart; i <= rangeEnd; i++) {
    pages.push(i);
  }

  // Add ellipsis after range if needed
  if (rangeEnd < totalPages - 1) {
    pages.push('ellipsis');
  }

  // Always show last page
  pages.push(totalPages);

  return pages;
}

/**
 * Pagination Component
 *
 * Renders page navigation buttons with Previous/Next controls.
 * Supports ellipsis display for large page counts.
 */
export default function Pagination({
  currentPage,
  totalPages,
  onPageChange,
  className = '',
}: PaginationProps) {
  if (totalPages <= 0) {
    return null;
  }

  const isFirstPage = currentPage === 1;
  const isLastPage = currentPage === totalPages;
  const pageNumbers = getPageNumbers(currentPage, totalPages);

  const handlePrevious = () => {
    if (!isFirstPage) {
      onPageChange(currentPage - 1);
    }
  };

  const handleNext = () => {
    if (!isLastPage) {
      onPageChange(currentPage + 1);
    }
  };

  const handlePageClick = (page: number) => {
    if (page !== currentPage) {
      onPageChange(page);
    }
  };

  // KRDS: 활성 페이지 = primary 채움, 비활성 = 흰 배경 + gray 텍스트
  const baseButtonClass =
    'px-3 py-2 text-sm rounded-md border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary';
  const disabledClass = 'border-border bg-white text-gray-400 opacity-50 cursor-not-allowed';
  const activeClass = 'bg-primary text-white border-primary';
  const inactiveClass = 'bg-white text-gray-600 border-border hover:bg-gray-50';

  return (
    <nav
      aria-label="페이지네이션"
      className={`flex items-center justify-center gap-1 ${className}`.trim()}
    >
      {/* Previous Button */}
      <button
        onClick={handlePrevious}
        disabled={isFirstPage}
        className={`${baseButtonClass} ${isFirstPage ? disabledClass : inactiveClass}`}
        aria-label="이전"
      >
        이전
      </button>

      {/* Page Number Buttons */}
      {pageNumbers.map((pageItem, index) => {
        if (pageItem === 'ellipsis') {
          return (
            <span
              key={`ellipsis-${index}`}
              className="px-2 py-2 text-sm text-text-muted"
            >
              ...
            </span>
          );
        }

        const isActive = pageItem === currentPage;

        return (
          <button
            key={pageItem}
            onClick={() => handlePageClick(pageItem)}
            className={`${baseButtonClass} ${isActive ? activeClass : inactiveClass}`}
            aria-current={isActive ? 'page' : undefined}
          >
            {pageItem}
          </button>
        );
      })}

      {/* Next Button */}
      <button
        onClick={handleNext}
        disabled={isLastPage}
        className={`${baseButtonClass} ${isLastPage ? disabledClass : inactiveClass}`}
        aria-label="다음"
      >
        다음
      </button>
    </nav>
  );
}
