'use client';

import React from 'react';

interface SelectionToolbarProps {
  selectedCount: number;
  speakerOptions: Array<{ value: string; label: string }>;
  onMerge: () => void;
  onBulkSpeakerChange: (speaker: string) => void;
  onClearSelection: () => void;
  isMerging?: boolean;
}

export default function SelectionToolbar({
  selectedCount,
  speakerOptions,
  onMerge,
  onBulkSpeakerChange,
  onClearSelection,
  isMerging = false,
}: SelectionToolbarProps) {
  if (selectedCount === 0) return null;

  return (
    <div
      data-testid="selection-toolbar"
      className="sticky top-0 z-10 bg-primary text-white px-4 py-2.5 rounded-t-md flex items-center justify-between gap-3 shadow-md"
    >
      <div className="flex items-center gap-3">
        <span className="text-sm font-medium">{selectedCount}개 선택</span>

        {/* 병합 버튼 (2개 이상) */}
        {selectedCount >= 2 && (
          <button
            data-testid="merge-btn"
            onClick={onMerge}
            disabled={isMerging}
            className="flex items-center gap-1 px-3 py-1 text-xs bg-white bg-opacity-20 hover:bg-opacity-30 rounded-md transition-colors disabled:opacity-50"
          >
            {isMerging ? (
              <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
            ) : (
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
              </svg>
            )}
            병합
          </button>
        )}

        {/* 화자 일괄 변경 드롭다운 */}
        <div className="flex items-center gap-1">
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
          </svg>
          <select
            data-testid="bulk-speaker-select"
            onChange={(e) => {
              if (e.target.value !== '__placeholder__') {
                onBulkSpeakerChange(e.target.value);
                e.target.value = '__placeholder__';
              }
            }}
            defaultValue="__placeholder__"
            className="px-2 py-1 text-xs bg-white bg-opacity-20 hover:bg-opacity-30 text-white rounded-md cursor-pointer transition-colors [&>option]:text-gray-900"
          >
            <option value="__placeholder__" disabled>
              화자 변경
            </option>
            {speakerOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* 선택 해제 */}
      <button
        data-testid="clear-selection"
        onClick={onClearSelection}
        className="flex items-center gap-1 px-3 py-1 text-xs bg-white bg-opacity-20 hover:bg-opacity-30 rounded-md transition-colors"
      >
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
        선택 해제
      </button>
    </div>
  );
}
