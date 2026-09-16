'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';

import Link from 'next/link';

import { Button } from '@/components/ui';

import type { VodRegisterFormType } from '../types';

interface RegisterSuccessResult {
  meetingId: string;
  title: string;
}

interface VodRegisterModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (data: VodRegisterFormType) => void;
  isLoading?: boolean;
  errorMessage?: string;
  successResult?: RegisterSuccessResult | null;
  duplicateMeetingId?: string | null;
}

function isValidUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:';
  } catch {
    return false;
  }
}

export default function VodRegisterModal({ isOpen, onClose, onSubmit, isLoading, errorMessage, successResult, duplicateMeetingId }: VodRegisterModalProps) {
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const lastActiveElementRef = useRef<HTMLElement | null>(null);

  const getFocusableElements = useCallback((): HTMLElement[] => {
    if (!dialogRef.current) {
      return [];
    }

    const selectors = [
      'a[href]',
      'button:not([disabled])',
      'input:not([disabled])',
      'textarea:not([disabled])',
      'select:not([disabled])',
      '[tabindex]:not([tabindex="-1"])',
    ];

    return Array.from(dialogRef.current.querySelectorAll<HTMLElement>(selectors.join(','))).filter(
      (el) => !el.hasAttribute('disabled') && !el.getAttribute('aria-hidden')
    );
  }, []);

  useEffect(() => {
    if (!isOpen) {
      setUrl('');
      setError('');
      return;
    }

    lastActiveElementRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    inputRef.current?.focus();

    const handleKeydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isLoading) {
        event.preventDefault();
        onClose();
        return;
      }

      if (event.key !== 'Tab') {
        return;
      }

      const focusableElements = getFocusableElements();
      if (focusableElements.length === 0) {
        return;
      }

      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];
      const activeElement = document.activeElement as HTMLElement | null;

      if (event.shiftKey) {
        if (!activeElement || activeElement === firstElement) {
          event.preventDefault();
          lastElement?.focus();
        }
        return;
      }

      if (!activeElement || activeElement === lastElement) {
        event.preventDefault();
        firstElement?.focus();
      }
    };

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    window.addEventListener('keydown', handleKeydown);

    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', handleKeydown);
      lastActiveElementRef.current?.focus();
    };
  }, [getFocusableElements, isOpen, isLoading, onClose]);

  if (!isOpen) {
    return null;
  }

  function validate(): string {
    if (!url.trim()) {
      return 'VOD URL을 입력해주세요.';
    }
    if (!isValidUrl(url.trim())) {
      return '올바른 URL 형식을 입력해주세요.';
    }
    return '';
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }

    onSubmit({ url: url.trim() });
  }

  function handleUrlChange(e: React.ChangeEvent<HTMLInputElement>) {
    setUrl(e.target.value);
    if (error) {
      setError('');
    }
  }

  function handleOverlayClick(e: React.MouseEvent<HTMLDivElement>) {
    if (e.target === e.currentTarget && !isLoading) {
      onClose();
    }
  }

  return (
    <div
      data-testid="modal-overlay"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={handleOverlayClick}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-label="VOD 등록"
        aria-modal="true"
        aria-describedby="vod-register-description"
        className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl"
      >
        {successResult ? (
          <>
            <div className="flex items-center gap-2 mb-2">
              <svg className="w-6 h-6 text-success shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <h2 className="text-xl font-semibold text-gray-900">등록 완료</h2>
            </div>
            <p className="mb-6 text-sm text-gray-700">
              <strong>{successResult.title}</strong>
            </p>
            <div className="flex justify-end gap-3">
              <Button type="button" variant="outline" onClick={onClose}>
                닫기
              </Button>
              <Link
                href={`/vod/${successResult.meetingId}`}
                onClick={onClose}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-light active:bg-primary-dark transition-colors inline-flex items-center gap-1.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-1"
              >
                VOD 바로가기
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
                </svg>
              </Link>
            </div>
          </>
        ) : (
          <>
            <h2 className="mb-2 text-xl font-semibold text-gray-900">VOD 등록</h2>
            <p id="vod-register-description" className="mb-6 text-sm text-gray-500">
              KMS URL을 입력하면 제목, 날짜, 영상 정보가 자동으로 추출됩니다.
            </p>

            <form onSubmit={handleSubmit} noValidate>
              <div className="mb-6">
                <label htmlFor="vod-url" className="mb-1 block text-sm font-medium text-gray-700">
                  VOD URL
                </label>
                <input
                  ref={inputRef}
                  id="vod-url"
                  type="url"
                  value={url}
                  onChange={handleUrlChange}
                  placeholder="http://kms.ggc.go.kr/caster/player/vodViewer.do?midx=..."
                  disabled={isLoading}
                  aria-invalid={Boolean(error || errorMessage)}
                  aria-describedby={error || errorMessage ? 'vod-url-error' : undefined}
                  className={`w-full rounded-md border px-3 py-2 text-sm focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/30 ${
                    error || errorMessage ? 'border-error' : 'border-gray-300'
                  } ${isLoading ? 'bg-gray-100' : ''}`}
                />
                {error && (
                  <p id="vod-url-error" className="mt-1 text-sm text-error">{error}</p>
                )}
                {errorMessage && !error && (
                  <div id="vod-url-error" className="mt-1">
                    <p className="text-sm text-error">{errorMessage}</p>
                    {duplicateMeetingId && (
                      <Link
                        href={`/vod/${duplicateMeetingId}`}
                        onClick={onClose}
                        className="inline-flex items-center gap-1 mt-1.5 text-sm text-primary hover:text-primary-dark hover:underline font-medium"
                      >
                        기존 VOD 보기
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
                        </svg>
                      </Link>
                    )}
                  </div>
                )}
              </div>

              <div className="flex justify-end gap-3">
                <Button type="button" variant="outline" onClick={onClose} disabled={isLoading}>
                  취소
                </Button>
                <Button type="submit" disabled={isLoading}>
                  {isLoading ? '등록 중...' : '등록'}
                </Button>
              </div>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
