'use client';

import React, { useCallback, useRef, useState } from 'react';

import { Button, Card } from '@/components/ui';

import AdminPinModal from './AdminPinModal';
import { useAuth } from '../contexts/AuthContext';
import {
  applyGrammarCorrections,
  applyTerminology,
  checkGrammar,
  checkTerminology,
} from '../lib/api';

import type {
  GrammarCheckResult,
  GrammarIssue,
  TermCheckResult,
} from '../lib/api';

interface ProofreadingToolbarProps {
  meetingId: string;
  onCorrectionsApplied?: () => void;
}

export default function ProofreadingToolbar({
  meetingId,
  onCorrectionsApplied,
}: ProofreadingToolbarProps) {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  // PIN 모달 + 원래 액션 재실행 (로그인 성공 후)
  const [pinOpen, setPinOpen] = useState(false);
  const pendingActionRef = useRef<(() => void) | null>(null);

  /** admin 권한이 있으면 바로 실행, 없으면 PIN 모달을 열고 성공 시 재실행 */
  const requireAdmin = useCallback((action: () => void) => {
    if (isAdmin) {
      action();
    } else {
      pendingActionRef.current = action;
      setPinOpen(true);
    }
  }, [isAdmin]);

  // "조회형" AI 교정(check-*)은 최초 1회 한해 비로그인도 허용.
  // 같은 meetingId에 대해 2회 이상 시도 시 admin 확인 요구. localStorage로 관리.
  const aiCheckUsedKey = `ai_check_used_${meetingId}`;
  const consumeFreeCheck = useCallback(() => {
    if (typeof window === 'undefined') return false;
    if (localStorage.getItem(aiCheckUsedKey) === '1') return false;
    localStorage.setItem(aiCheckUsedKey, '1');
    return true;
  }, [aiCheckUsedKey]);
  const requireCheckQuota = useCallback((action: () => void) => {
    if (isAdmin) { action(); return; }
    if (consumeFreeCheck()) { action(); return; }
    // 이미 1회 사용 → 관리자 PIN 필요
    pendingActionRef.current = action;
    setPinOpen(true);
  }, [isAdmin, consumeFreeCheck]);

  // Terminology state
  const [termLoading, setTermLoading] = useState(false);
  const [termApplying, setTermApplying] = useState(false);
  const [termResult, setTermResult] = useState<TermCheckResult | null>(null);
  const [showTermResult, setShowTermResult] = useState(false);

  // Grammar state
  const [grammarLoading, setGrammarLoading] = useState(false);
  const [grammarApplying, setGrammarApplying] = useState(false);
  const [grammarResult, setGrammarResult] = useState<GrammarCheckResult | null>(null);
  const [showGrammarResult, setShowGrammarResult] = useState(false);
  const [selectedCorrections, setSelectedCorrections] = useState<Set<string>>(new Set());

  // ─── Terminology ───

  // check-* 은 최초 1회 비로그인 허용. apply-* 는 admin 전용 유지.
  const handleTermCheck = () => requireCheckQuota(async () => {
    try {
      setTermLoading(true);
      const result = await checkTerminology(meetingId);
      setTermResult(result);
      setShowTermResult(true);
    } catch {
      alert('용어 점검에 실패했습니다.');
    } finally {
      setTermLoading(false);
    }
  });

  const handleTermApply = () => requireAdmin(async () => {
    if (!termResult || termResult.total_issues === 0) return;

    const confirmed = window.confirm(
      `${termResult.total_issues}건의 용어 표기를 일괄 교정합니다. 계속하시겠습니까?`
    );
    if (!confirmed) return;

    try {
      setTermApplying(true);
      const result = await applyTerminology(meetingId);
      alert(`${result.updated}건 교정 완료`);
      setShowTermResult(false);
      setTermResult(null);
      onCorrectionsApplied?.();
    } catch {
      alert('용어 교정 적용에 실패했습니다.');
    } finally {
      setTermApplying(false);
    }
  });

  // ─── Grammar ───

  const handleGrammarCheck = () => requireCheckQuota(async () => {
    try {
      setGrammarLoading(true);
      const result = await checkGrammar(meetingId);
      setGrammarResult(result);
      setShowGrammarResult(true);
      // Select all by default
      const allIds = new Set(result.issues.map((i) => i.subtitle_id));
      setSelectedCorrections(allIds);
    } catch {
      alert('AI 문장 검사에 실패했습니다. (API 키 확인 필요)');
    } finally {
      setGrammarLoading(false);
    }
  });

  const toggleGrammarSelection = (subtitleId: string) => {
    setSelectedCorrections((prev) => {
      const next = new Set(prev);
      if (next.has(subtitleId)) {
        next.delete(subtitleId);
      } else {
        next.add(subtitleId);
      }
      return next;
    });
  };

  const handleGrammarApply = () => requireAdmin(async () => {
    if (!grammarResult || selectedCorrections.size === 0) return;

    const corrections = grammarResult.issues
      .filter((i) => selectedCorrections.has(i.subtitle_id))
      .map((i) => ({
        subtitle_id: i.subtitle_id,
        corrected_text: i.corrected_text,
      }));

    try {
      setGrammarApplying(true);
      const result = await applyGrammarCorrections(meetingId, corrections);
      alert(`${result.updated}건 교정 완료`);
      setShowGrammarResult(false);
      setGrammarResult(null);
      setSelectedCorrections(new Set());
      onCorrectionsApplied?.();
    } catch {
      alert('문장 교정 적용에 실패했습니다.');
    } finally {
      setGrammarApplying(false);
    }
  });

  return (
    <div data-testid="proofreading-toolbar" className="space-y-2">
      {/* 용어 점검 */}
      <Button
        data-testid="term-check-button"
        variant="secondary"
        onClick={handleTermCheck}
        disabled={termApplying}
        loading={termLoading}
        className="w-full border border-primary-20"
      >
        {termLoading ? '점검 중...' : '용어 표기 점검'}
      </Button>

      {showTermResult && termResult && (
        <Card padding="sm">
          {termResult.total_issues === 0 ? (
            <p className="text-sm text-success">용어 표기 문제가 없습니다.</p>
          ) : (
            <>
              <p className="text-sm text-primary font-medium mb-2">
                {termResult.total_issues}건의 용어 표기 불일치
              </p>
              <div className="max-h-40 overflow-y-auto space-y-1 mb-2">
                {termResult.issues.map((issue, idx) => (
                  <div key={idx} className="text-xs bg-primary-5 p-2 rounded flex items-center gap-1">
                    <span className="text-error line-through">{issue.wrong_term}</span>
                    <span className="text-gray-400">&rarr;</span>
                    <span className="text-success font-medium">{issue.correct_term}</span>
                    {issue.category && (
                      <span className="ml-auto text-gray-400">[{issue.category}]</span>
                    )}
                  </div>
                ))}
              </div>
              <div className="flex gap-2">
                <Button
                  data-testid="term-apply-button"
                  variant="primary"
                  size="sm"
                  onClick={handleTermApply}
                  loading={termApplying}
                  className="flex-1"
                >
                  {termApplying ? '적용 중...' : '일괄 교정'}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowTermResult(false)}
                >
                  닫기
                </Button>
              </div>
            </>
          )}
        </Card>
      )}

      {/* AI 문장 검사 */}
      <Button
        data-testid="grammar-check-button"
        variant="secondary"
        onClick={handleGrammarCheck}
        disabled={grammarApplying}
        loading={grammarLoading}
        className="w-full border border-primary-20"
      >
        {grammarLoading ? 'AI 검사 중...' : 'AI 문장 검사'}
      </Button>

      {showGrammarResult && grammarResult && (
        <Card padding="sm">
          {grammarResult.total_issues === 0 ? (
            <p className="text-sm text-success">교정이 필요한 문장이 없습니다.</p>
          ) : (
            <>
              <p className="text-sm text-primary font-medium mb-2">
                {grammarResult.total_issues}건 교정 제안 ({selectedCorrections.size}건 선택)
              </p>
              <div className="max-h-60 overflow-y-auto space-y-2 mb-2">
                {grammarResult.issues.map((issue: GrammarIssue) => (
                  <label
                    key={issue.subtitle_id}
                    className={`block text-xs p-2 rounded cursor-pointer border transition-colors ${
                      selectedCorrections.has(issue.subtitle_id)
                        ? 'bg-primary-5 border-primary-30'
                        : 'bg-gray-50 border-gray-200'
                    }`}
                  >
                    <div className="flex items-start gap-2">
                      <input
                        type="checkbox"
                        checked={selectedCorrections.has(issue.subtitle_id)}
                        onChange={() => toggleGrammarSelection(issue.subtitle_id)}
                        className="mt-0.5 rounded accent-primary focus-visible:ring-2 focus-visible:ring-primary"
                      />
                      <div className="flex-1 min-w-0">
                        <div className="text-error line-through break-words">
                          {issue.original_text}
                        </div>
                        <div className="text-success font-medium break-words mt-0.5">
                          {issue.corrected_text}
                        </div>
                        {issue.changes.length > 0 && (
                          <div className="text-gray-400 mt-0.5">
                            {issue.changes.join(', ')}
                          </div>
                        )}
                      </div>
                    </div>
                  </label>
                ))}
              </div>
              <div className="flex gap-2">
                <Button
                  data-testid="grammar-apply-button"
                  variant="primary"
                  size="sm"
                  onClick={handleGrammarApply}
                  disabled={selectedCorrections.size === 0}
                  loading={grammarApplying}
                  className="flex-1"
                >
                  {grammarApplying
                    ? '적용 중...'
                    : `선택 항목 적용 (${selectedCorrections.size}건)`}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowGrammarResult(false)}
                >
                  닫기
                </Button>
              </div>
            </>
          )}
        </Card>
      )}

      {/* 관리자 PIN 모달 — admin 권한 없이 AI 교정 버튼 누르면 열림 */}
      <AdminPinModal
        open={pinOpen}
        onClose={() => {
          setPinOpen(false);
          pendingActionRef.current = null;
        }}
        onSuccess={() => {
          // 성공 후 원래 시도하던 작업 재실행
          const pending = pendingActionRef.current;
          pendingActionRef.current = null;
          if (pending) pending();
        }}
        description="AI 자막 교정 기능은 관리자 권한이 필요합니다. 4자리 관리자 PIN을 입력해 주세요."
      />
    </div>
  );
}
