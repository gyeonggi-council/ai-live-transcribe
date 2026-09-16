'use client';

/**
 * Select — KRDS 표준 셀렉트 박스
 *
 * - label/error/help 지원 (Input과 동일 계약)
 * - 커스텀 화살표(chevron) + appearance-none
 */

import React, { forwardRef, useId } from 'react';

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  error?: string;
  help?: string;
}

const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { label, error, help, id, className = '', children, ...rest },
  ref
) {
  const autoId = useId();
  const selectId = id ?? autoId;
  const errorId = `${selectId}-error`;
  const helpId = `${selectId}-help`;
  const describedBy =
    [error ? errorId : null, help ? helpId : null].filter(Boolean).join(' ') || undefined;

  return (
    <div className="w-full">
      {label && (
        <label htmlFor={selectId} className="mb-1 block text-sm font-medium text-gray-700">
          {label}
        </label>
      )}
      <div className="relative">
        <select
          ref={ref}
          id={selectId}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          className={`w-full appearance-none rounded-md border ${
            error ? 'border-error' : 'border-gray-300'
          } bg-white py-2 pl-3 pr-9 text-sm text-gray-900 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:cursor-not-allowed disabled:bg-gray-50 disabled:text-gray-400 ${className}`
            .replace(/\s+/g, ' ')
            .trim()}
          {...rest}
        >
          {children}
        </select>
        <svg
          className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </div>
      {help && (
        <p id={helpId} className="mt-1 text-xs text-gray-500">
          {help}
        </p>
      )}
      {error && (
        <p id={errorId} role="alert" className="mt-1 text-xs text-error">
          {error}
        </p>
      )}
    </div>
  );
});

export default Select;
