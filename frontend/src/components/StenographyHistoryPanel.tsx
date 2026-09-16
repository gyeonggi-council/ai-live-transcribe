'use client';

/**
 * 속기록 수정 이력 패널
 *
 * @TASK P11C-T11 - 수정 이력 패널
 * @SPEC docs/planning/02-trd.md#속기록
 *
 * 오른쪽 슬라이드 패널
 * 라인별 diff (빨강=삭제, 초록=추가)
 * 에디터명, 수정 시각
 */

import React, { useEffect, useState } from 'react';

import { getStenographyHistory } from '../lib/api';

import type { StenographyEditHistoryEntry } from '../types';

interface StenographyHistoryPanelProps {
  meetingId: string;
  recordId: string;
  isOpen: boolean;
  onClose: () => void;
}

const FIELD_LABELS: Record<string, string> = {
  text: '텍스트',
  speaker: '화자',
  start_ms: '시작 시간',
  end_ms: '종료 시간',
  paragraph: '문단 구분',
};

export default function StenographyHistoryPanel({
  meetingId,
  recordId,
  isOpen,
  onClose,
}: StenographyHistoryPanelProps) {
  const [entries, setEntries] = useState<StenographyEditHistoryEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (!isOpen) return;

    async function loadHistory() {
      setIsLoading(true);
      try {
        const result = await getStenographyHistory(meetingId, recordId);
        setEntries(result.items);
      } catch {
        setEntries([]);
      } finally {
        setIsLoading(false);
      }
    }

    loadHistory();
  }, [isOpen, meetingId, recordId]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-y-0 right-0 w-96 bg-white shadow-xl border-l border-gray-200 z-30 flex flex-col" data-testid="history-panel">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">수정 이력</h3>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-gray-600 transition-colors rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <div className="w-6 h-6 border-2 border-gray-200 border-t-primary rounded-full animate-spin" />
          </div>
        ) : entries.length === 0 ? (
          <div className="text-center py-12 text-sm text-gray-500">
            수정 이력이 없습니다.
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {entries.map((entry) => (
              <div key={entry.id} className="px-4 py-3">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-medium text-gray-700">
                    {entry.editor_name}
                  </span>
                  <span className="text-xs text-gray-400">
                    {new Date(entry.created_at).toLocaleString()}
                  </span>
                </div>
                <div className="text-xs text-gray-500 mb-1">
                  {FIELD_LABELS[entry.field_changed] || entry.field_changed} 변경
                </div>
                <div className="space-y-1">
                  {entry.old_value && (
                    <div className="px-2 py-1 bg-error/10 border-l-2 border-error/30 text-xs text-error rounded-r">
                      {entry.old_value}
                    </div>
                  )}
                  <div className="px-2 py-1 bg-success/10 border-l-2 border-success/30 text-xs text-success rounded-r">
                    {entry.new_value}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
