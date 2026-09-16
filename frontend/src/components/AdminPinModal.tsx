'use client';

/**
 * AdminPinModal — 비로그인 사용자가 관리자 전용 기능(AI 교정 등)을 쓸 때
 * 4자리 PIN으로 admin JWT를 받아오기 위한 모달. (KRDS 토큰 적용)
 *
 * 동작:
 * - 4자리 숫자 입력칸
 * - `useAuth().pinLogin(pin)` → 성공 시 onSuccess() 콜백 호출
 * - 실패 시 에러 메시지 표시
 * - ESC / 백드롭 클릭으로 닫기
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { Button } from '@/components/ui';
import { useAuth } from '@/contexts/AuthContext';

export interface AdminPinModalProps {
  open: boolean;
  onClose: () => void;
  /** 로그인 성공 시 호출 — 호출 측에서 원래 액션(AI 교정 등) 재실행 가능 */
  onSuccess?: () => void;
  /** 화면에 보일 설명 메시지 */
  description?: string;
}

export default function AdminPinModal({
  open,
  onClose,
  onSuccess,
  description = '이 기능은 관리자 권한이 필요합니다. 4자리 PIN을 입력해 주세요.',
}: AdminPinModalProps) {
  const { pinLogin } = useAuth();
  const [pin, setPin] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // 모달 열릴 때 input autofocus + ESC로 닫기
  useEffect(() => {
    if (!open) return;
    setPin('');
    setErr(null);
    setTimeout(() => inputRef.current?.focus(), 50);

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const handleSubmit = useCallback(async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (submitting) return;
    if (pin.length < 4) {
      setErr('4자리 PIN을 입력해 주세요.');
      return;
    }
    setSubmitting(true);
    setErr(null);
    try {
      await pinLogin(pin);
      onSuccess?.();
      onClose();
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : 'PIN 확인에 실패했습니다.');
    } finally {
      setSubmitting(false);
    }
  }, [pin, submitting, pinLogin, onSuccess, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 animate-fade-in"
      onClick={onClose}
      data-testid="admin-pin-modal-backdrop"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="bg-white rounded-lg shadow-xl w-full max-w-sm mx-4 p-6"
        role="dialog"
        aria-modal="true"
        aria-labelledby="pin-modal-title"
        data-testid="admin-pin-modal"
      >
        <h2 id="pin-modal-title" className="text-lg font-bold text-gray-900 mb-1">
          관리자 PIN
        </h2>
        <p className="text-sm text-gray-600 mb-4 leading-relaxed">{description}</p>

        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            ref={inputRef}
            type="password"
            inputMode="numeric"
            autoComplete="off"
            maxLength={6}
            pattern="[0-9]*"
            value={pin}
            onChange={(e) => {
              setPin(e.target.value.replace(/\D/g, ''));
              setErr(null);
            }}
            aria-label="관리자 PIN 입력"
            aria-invalid={err ? true : undefined}
            className="w-full px-4 py-3 text-center text-xl tracking-[0.5em] font-mono border border-gray-300 rounded-md focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/30"
            placeholder="••••"
            data-testid="admin-pin-input"
          />

          {err && (
            <p role="alert" className="text-sm text-error" data-testid="admin-pin-error">
              {err}
            </p>
          )}

          <div className="flex gap-2 pt-2">
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
              disabled={submitting}
              className="flex-1"
            >
              취소
            </Button>
            <Button
              type="submit"
              loading={submitting}
              disabled={pin.length < 4}
              className="flex-1"
              data-testid="admin-pin-submit"
            >
              {submitting ? '확인 중...' : '확인'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
