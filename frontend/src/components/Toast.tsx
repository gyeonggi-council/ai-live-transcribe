'use client';

import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';

export type ToastVariant = 'success' | 'error' | 'warning' | 'info';

interface ToastState {
  id: number;
  variant: ToastVariant;
  message: string;
}

interface ToastContextValue {
  showToast: (variant: ToastVariant, message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

// KRDS: 흰 카드 + 좌측 시맨틱 액센트 보더 + 시맨틱 아이콘 색
const variantStyles: Record<ToastVariant, string> = {
  success: 'border-l-success',
  error: 'border-l-error',
  warning: 'border-l-warning',
  info: 'border-l-info',
};

const variantIconColors: Record<ToastVariant, string> = {
  success: 'text-success',
  error: 'text-error',
  warning: 'text-warning',
  info: 'text-info',
};

const variantIcons: Record<ToastVariant, string> = {
  success: 'M5 13l4 4L19 7',
  error: 'M6 18L18 6M6 6l12 12',
  warning: 'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z',
  info: 'M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastState[]>([]);

  const showToast = useCallback((variant: ToastVariant, message: string) => {
    const id = Date.now();
    setToasts((prev) => [...prev, { id, variant, message }]);
  }, []);

  const removeToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <ToastContainer toasts={toasts} onRemove={removeToast} />
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
}

interface ToastContainerProps {
  toasts: ToastState[];
  onRemove: (id: number) => void;
}

function ToastContainer({ toasts, onRemove }: ToastContainerProps) {
  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      {toasts.map((toast) => (
        <Toast key={toast.id} {...toast} onClose={() => onRemove(toast.id)} />
      ))}
    </div>
  );
}

interface ToastProps {
  id: number;
  variant: ToastVariant;
  message: string;
  onClose: () => void;
}

export default function Toast({ variant, message, onClose }: ToastProps) {
  useEffect(() => {
    const timer = setTimeout(() => {
      onClose();
    }, 3000);

    return () => clearTimeout(timer);
  }, [onClose]);

  const variantStyle = variantStyles[variant];
  const iconPath = variantIcons[variant];

  return (
    <div
      role="alert"
      className={`${variantStyle} bg-white text-gray-900 border border-border border-l-4 flex items-center gap-3 px-4 py-3 rounded-lg shadow-lg min-w-[300px] max-w-md`}
    >
      <svg
        className={`${variantIconColors[variant]} w-5 h-5 flex-shrink-0`}
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
        xmlns="http://www.w3.org/2000/svg"
      >
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={iconPath} />
      </svg>
      <span className="flex-1">{message}</span>
      <button
        onClick={onClose}
        className="flex-shrink-0 text-gray-400 hover:text-gray-600 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded"
        aria-label="Close"
      >
        <svg
          className="w-4 h-4"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  );
}
