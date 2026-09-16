'use client';

import React, { useEffect, useRef, useState } from 'react';

import Button from './ui/Button';

import type { StenographyRecord } from '../types';

interface StenographyEditorToolbarProps {
  record: StenographyRecord;
  isDirty: boolean;
  isSaving: boolean;
  lineCount: number;
  onSave: () => void;
  onImportFromText: () => void;
  onImportFromSubtitles: () => void;
  onToggleFindReplace: () => void;
  onToggleComparison: () => void;
  isComparisonOpen: boolean;
  onBack: () => void;
}

const STATUS_CONFIG: Record<StenographyRecord['status'], { label: string; className: string }> = {
  draft: {
    label: '임시',
    className: 'bg-warning-bg/20 text-warning',
  },
  submitted: {
    label: '제출됨',
    className: 'bg-primary-10 text-primary-dark',
  },
  approved: {
    label: '승인됨',
    className: 'bg-success/10 text-success',
  },
};

export default function StenographyEditorToolbar({
  record,
  isDirty,
  isSaving,
  lineCount,
  onSave,
  onImportFromText,
  onImportFromSubtitles,
  onToggleFindReplace,
  onToggleComparison,
  isComparisonOpen,
  onBack,
}: StenographyEditorToolbarProps) {
  const [isImportOpen, setIsImportOpen] = useState(false);
  const [isFindReplaceOpen, setIsFindReplaceOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleOutsideClick = (event: MouseEvent) => {
      if (!dropdownRef.current) {
        return;
      }

      if (!dropdownRef.current.contains(event.target as Node)) {
        setIsImportOpen(false);
      }
    };

    document.addEventListener('mousedown', handleOutsideClick);

    return () => {
      document.removeEventListener('mousedown', handleOutsideClick);
    };
  }, []);

  const statusConfig = STATUS_CONFIG[record.status];
  const saveDisabled = isSaving || !isDirty;

  const handleImportFromText = () => {
    onImportFromText();
    setIsImportOpen(false);
  };

  const handleImportFromSubtitles = () => {
    onImportFromSubtitles();
    setIsImportOpen(false);
  };

  const handleToggleFindReplace = () => {
    setIsFindReplaceOpen((prev) => !prev);
    onToggleFindReplace();
  };

  return (
    <div data-testid="steno-toolbar" className="bg-white border-b border-gray-200 px-4 py-2 flex items-center gap-3">
      <button
        type="button"
        onClick={onBack}
        className="bg-gray-100 text-gray-700 hover:bg-gray-200 px-3 py-1.5 text-sm rounded-md inline-flex items-center gap-1.5"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
        </svg>
        돌아가기
      </button>

      <div className="flex items-center gap-2 min-w-0">
        <span className="text-base font-semibold text-gray-900">속기록 편집</span>
        <span className="text-sm text-gray-500 truncate">- {record.stenographer_name}</span>
      </div>

      <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${statusConfig.className}`}>
        {statusConfig.label}
      </span>

      <div className="w-px h-6 bg-gray-200" />

      <span className="text-sm text-gray-500">{lineCount}줄</span>

      <div className="w-px h-6 bg-gray-200" />

      <div className="ml-auto flex items-center gap-2">
        <Button
          variant="primary"
          size="sm"
          data-testid="steno-save-btn"
          onClick={onSave}
          disabled={saveDisabled}
        >
          {isSaving ? '저장 중...' : `${isDirty ? '● ' : ''}저장`}
        </Button>

        <div ref={dropdownRef} data-testid="steno-import-dropdown" className="relative">
          <button
            type="button"
            onClick={() => setIsImportOpen((prev) => !prev)}
            className="bg-gray-100 text-gray-700 hover:bg-gray-200 px-3 py-1.5 text-sm rounded-md inline-flex items-center gap-1"
          >
            가져오기
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {isImportOpen && (
            <div className="absolute top-full left-0 mt-1 bg-white border border-gray-200 rounded-md shadow-lg py-1 z-20 min-w-[200px]">
              <button
                type="button"
                onClick={handleImportFromText}
                className="px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 cursor-pointer w-full text-left"
              >
                텍스트에서 가져오기
              </button>
              <button
                type="button"
                onClick={handleImportFromSubtitles}
                className="px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 cursor-pointer w-full text-left"
              >
                STT 자막에서 가져오기
              </button>
            </div>
          )}
        </div>

        <button
          type="button"
          data-testid="steno-find-btn"
          onClick={handleToggleFindReplace}
          className={`px-3 py-1.5 text-sm rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
            isFindReplaceOpen ? 'bg-primary-10 text-primary-dark' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
          }`}
        >
          찾기/바꾸기
        </button>

        <button
          type="button"
          data-testid="steno-compare-btn"
          onClick={onToggleComparison}
          className={`px-3 py-1.5 text-sm rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
            isComparisonOpen ? 'bg-primary-10 text-primary-dark' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
          }`}
        >
          STT 비교
        </button>
      </div>
    </div>
  );
}
