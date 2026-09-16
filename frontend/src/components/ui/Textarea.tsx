'use client';

/**
 * Textarea — KRDS 표준 멀티라인 입력
 *
 * - label/error/help 지원 (Input과 동일 계약)
 */

import React, { forwardRef, useId } from 'react';

export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
  help?: string;
}

const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { label, error, help, id, className = '', rows = 4, ...rest },
  ref
) {
  const autoId = useId();
  const textareaId = id ?? autoId;
  const errorId = `${textareaId}-error`;
  const helpId = `${textareaId}-help`;
  const describedBy =
    [error ? errorId : null, help ? helpId : null].filter(Boolean).join(' ') || undefined;

  return (
    <div className="w-full">
      {label && (
        <label htmlFor={textareaId} className="mb-1 block text-sm font-medium text-gray-700">
          {label}
        </label>
      )}
      <textarea
        ref={ref}
        id={textareaId}
        rows={rows}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={`w-full rounded-md border ${
          error ? 'border-error' : 'border-gray-300'
        } bg-white px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:cursor-not-allowed disabled:bg-gray-50 disabled:text-gray-400 ${className}`
          .replace(/\s+/g, ' ')
          .trim()}
        {...rest}
      />
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

export default Textarea;
