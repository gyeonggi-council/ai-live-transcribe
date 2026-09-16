'use client';

/**
 * Modal — KRDS 표준 모달 다이얼로그
 *
 * 접근성 표준 (VodRegisterModal/AiSummaryModal 패턴을 범용화):
 * - 오버레이 bg-black/50, 오버레이 클릭 시 닫기
 * - ESC 키 닫기 (closeDisabled 시 차단)
 * - 초점 트랩: 열릴 때 첫 포커서블로 이동 + Tab 순환 + 닫힐 때 원위치 복원
 * - role="dialog" + aria-modal + aria-labelledby(제목)
 * - 우측 상단 닫기(X) 버튼
 *
 * size: sm(max-w-sm) | md(max-w-lg) | lg(max-w-2xl) | full(화면 대부분)
 */

import React, { useCallback, useEffect, useId, useRef } from 'react';

export type ModalSize = 'sm' | 'md' | 'lg' | 'full';

export interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** 모달 제목 (aria-labelledby 대상) */
  title: React.ReactNode;
  children: React.ReactNode;
  size?: ModalSize;
  /** 하단 고정 푸터 슬롯 (버튼 영역 등) */
  footer?: React.ReactNode;
  /** true면 ESC/오버레이/X 닫기 차단 (로딩 중 등) */
  closeDisabled?: boolean;
  className?: string;
}

const SIZE_CLASSES: Record<ModalSize, string> = {
  sm: 'max-w-sm',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
  full: 'max-w-[95vw] h-[90vh]',
};

export default function Modal({
  isOpen,
  onClose,
  title,
  children,
  size = 'md',
  footer,
  closeDisabled = false,
  className = '',
}: ModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const lastActiveElementRef = useRef<HTMLElement | null>(null);
  const titleId = useId();

  // onClose/closeDisabled는 ref로 참조 — 소비자가 인라인 onClose를 넘겨도
  // 초점 트랩 effect가 리렌더마다 cleanup/재실행되어 초점을 강탈하지 않도록 함.
  const onCloseRef = useRef(onClose);
  const closeDisabledRef = useRef(closeDisabled);

  useEffect(() => {
    onCloseRef.current = onClose;
    closeDisabledRef.current = closeDisabled;
  }, [onClose, closeDisabled]);

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

    return Array.from(
      dialogRef.current.querySelectorAll<HTMLElement>(selectors.join(','))
    ).filter(
      (el) => !el.hasAttribute('disabled') && el.getAttribute('aria-hidden') !== 'true'
    );
  }, []);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    lastActiveElementRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;

    // 첫 포커서블 요소로 초점 이동 (없으면 다이얼로그 자체)
    const focusables = getFocusableElements();
    if (focusables.length > 0) {
      focusables[0]?.focus();
    } else {
      dialogRef.current?.focus();
    }

    const handleKeydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !closeDisabledRef.current) {
        event.preventDefault();
        onCloseRef.current();
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

      // 초점이 다이얼로그 밖으로 벗어난 경우: Tab을 가로채 첫 포커서블로 복귀
      if (
        activeElement &&
        dialogRef.current &&
        !dialogRef.current.contains(activeElement)
      ) {
        event.preventDefault();
        firstElement?.focus();
        return;
      }

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
    // isOpen에만 키잉: onClose/closeDisabled는 ref로 읽으므로 의존성에서 제외
    // (리렌더마다 트랩 재설치 → 초점 이탈/강탈 버그 방지)
  }, [isOpen, getFocusableElements]);

  if (!isOpen) {
    return null;
  }

  const handleOverlayMouseDown = (event: React.MouseEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget && !closeDisabled) {
      onClose();
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onMouseDown={handleOverlayMouseDown}
      data-testid="modal-overlay"
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={`flex w-full ${SIZE_CLASSES[size]} max-h-[90vh] flex-col rounded-lg bg-white shadow-xl ${className}`
          .replace(/\s+/g, ' ')
          .trim()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <h2 id={titleId} className="text-lg font-semibold text-gray-900">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            disabled={closeDisabled}
            className="rounded-md p-1 text-gray-400 transition-colors hover:bg-gray-50 hover:text-gray-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-50"
            aria-label="닫기"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-4">{children}</div>

        {/* Footer */}
        {footer && (
          <div className="flex items-center justify-end gap-2 border-t border-border px-6 py-4">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
