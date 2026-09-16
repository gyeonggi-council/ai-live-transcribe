'use client';

/**
 * Input — KRDS 표준 텍스트 입력
 *
 * - label: 연결된 라벨 (htmlFor 자동 연결)
 * - error: text-error 메시지 + aria-invalid + aria-describedby
 * - help: 보조 설명 텍스트 (aria-describedby 연결)
 */

import React, { forwardRef, useId } from 'react';

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  help?: string;
}

const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, error, help, id, className = '', ...rest },
  ref
) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const errorId = `${inputId}-error`;
  const helpId = `${inputId}-help`;
  const describedBy =
    [error ? errorId : null, help ? helpId : null].filter(Boolean).join(' ') || undefined;

  return (
    <div className="w-full">
      {label && (
        <label htmlFor={inputId} className="mb-1 block text-sm font-medium text-gray-700">
          {label}
        </label>
      )}
      <input
        ref={ref}
        id={inputId}
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

export default Input;
