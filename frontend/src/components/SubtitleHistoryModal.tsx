'use client';

import React, { useEffect, useState } from 'react';

import { getSubtitleHistory } from '../lib/api';
import { getWordDiff } from '../utils/wordDiff';

import type { SubtitleHistoryType } from '../types';

interface SubtitleHistoryModalProps {
  meetingId: string;
  subtitleId: string;
  onClose: () => void;
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleString('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

const FIELD_LABELS: Record<string, string> = {
  text: '텍스트',
  speaker: '화자',
};

export default function SubtitleHistoryModal({
  meetingId,
  subtitleId,
  onClose,
}: SubtitleHistoryModalProps) {
  const [history, setHistory] = useState<SubtitleHistoryType[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        setIsLoading(true);
        const data = await getSubtitleHistory(meetingId, subtitleId);
        setHistory(data);
      } catch {
        // ignore
      } finally {
        setIsLoading(false);
      }
    }
    load();
  }, [meetingId, subtitleId]);

  return (
    <div
      data-testid="subtitle-history-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="bg-white rounded-lg shadow-xl w-full max-w-lg max-h-[80vh] flex flex-col mx-4">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
          <h3 className="font-semibold text-gray-900">변경 이력</h3>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none"
          >
            &times;
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <div className="w-8 h-8 border-4 border-gray-200 border-t-primary rounded-full animate-spin" />
            </div>
          ) : history.length === 0 ? (
            <p className="text-center text-gray-500 py-8">변경 이력이 없습니다.</p>
          ) : (
            <div className="relative">
              {/* Timeline line */}
              <div className="absolute left-3 top-2 bottom-2 w-0.5 bg-gray-200" />

              <div className="space-y-4">
                {history.map((item) => (
                  <div key={item.id} className="relative pl-8">
                    {/* Timeline dot */}
                    <div className="absolute left-1.5 top-1.5 w-3 h-3 bg-primary rounded-full border-2 border-white shadow" />

                    <div className="bg-gray-50 rounded-md p-3">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-medium text-primary">
                          {FIELD_LABELS[item.field_name] || item.field_name} 수정
                        </span>
                        <span className="text-xs text-gray-400">
                          {formatDate(item.created_at)}
                        </span>
                      </div>

                      {item.changed_by && (
                        <p className="text-xs text-gray-500 mb-1">
                          수정자: {item.changed_by}
                        </p>
                      )}

                      <div className="space-y-1">
                        {item.old_value && item.new_value ? (
                          <div className="text-sm leading-relaxed">
                            {getWordDiff(item.old_value, item.new_value).map((d, di) => (
                              <span
                                key={di}
                                className={
                                  d.type === 'removed'
                                    ? 'bg-error/10 text-error line-through'
                                    : d.type === 'added'
                                    ? 'bg-success/10 text-success font-medium'
                                    : 'text-gray-500'
                                }
                              >
                                {d.text}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <>
                            {item.old_value && (
                              <div className="text-sm">
                                <span className="text-error text-xs mr-1">-</span>
                                <span className="line-through text-gray-400">
                                  {item.old_value}
                                </span>
                              </div>
                            )}
                            {item.new_value && (
                              <div className="text-sm">
                                <span className="text-success text-xs mr-1">+</span>
                                <span className="text-gray-800">{item.new_value}</span>
                              </div>
                            )}
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
