'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';

interface FindReplaceBarProps {
  subtitles: Array<{ id: string; text: string }>;
  onReplace: (subtitleId: string, newText: string) => void;
  onHighlight: (matchedIds: Set<string>, currentId: string | null) => void;
  onClose: () => void;
}

export default function FindReplaceBar({
  subtitles,
  onReplace,
  onHighlight,
  onClose,
}: FindReplaceBarProps) {
  const [searchText, setSearchText] = useState('');
  const [replaceText, setReplaceText] = useState('');
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [currentMatchIndex, setCurrentMatchIndex] = useState(0);

  const searchRef = useRef<HTMLInputElement>(null);

  // Find all matches
  const matches = React.useMemo(() => {
    if (!searchText) return [];
    const result: Array<{ subtitleId: string; index: number }> = [];
    const flags = caseSensitive ? 'g' : 'gi';
    const escaped = searchText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(escaped, flags);

    for (const sub of subtitles) {
      let match;
      while ((match = regex.exec(sub.text)) !== null) {
        result.push({ subtitleId: sub.id, index: match.index });
      }
    }
    return result;
  }, [subtitles, searchText, caseSensitive]);

  const matchCount = matches.length;

  // Update highlight whenever matches change
  useEffect(() => {
    const matchedIds = new Set(matches.map((m) => m.subtitleId));
    const currentMatch = matches[currentMatchIndex];
    onHighlight(matchedIds, currentMatch?.subtitleId ?? null);
  }, [matches, currentMatchIndex, onHighlight]);

  // Reset current index when matches change
  useEffect(() => {
    setCurrentMatchIndex(0);
  }, [searchText, caseSensitive]);

  // Focus search input on mount
  useEffect(() => {
    searchRef.current?.focus();
  }, []);

  const goToNext = useCallback(() => {
    if (matchCount > 0) {
      setCurrentMatchIndex((prev) => (prev + 1) % matchCount);
    }
  }, [matchCount]);

  const goToPrev = useCallback(() => {
    if (matchCount > 0) {
      setCurrentMatchIndex((prev) => (prev - 1 + matchCount) % matchCount);
    }
  }, [matchCount]);

  // Replace current match
  const handleReplace = () => {
    if (matchCount === 0 || !searchText) return;
    const current = matches[currentMatchIndex];
    if (!current) return;

    const sub = subtitles.find((s) => s.id === current.subtitleId);
    if (!sub) return;

    const flags = caseSensitive ? '' : 'i';
    const escaped = searchText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(escaped, flags);
    const newText = sub.text.replace(regex, replaceText);
    onReplace(current.subtitleId, newText);
  };

  // Replace all matches
  const handleReplaceAll = () => {
    if (matchCount === 0 || !searchText) return;

    const flags = caseSensitive ? 'g' : 'gi';
    const escaped = searchText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(escaped, flags);

    const affectedIds = new Set(matches.map((m) => m.subtitleId));
    Array.from(affectedIds).forEach((sid) => {
      const sub = subtitles.find((s) => s.id === sid);
      if (!sub) return;
      const newText = sub.text.replace(regex, replaceText);
      if (newText !== sub.text) {
        onReplace(sid, newText);
      }
    });
  };

  // Keyboard shortcuts
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      onClose();
    } else if (e.key === 'Enter' && e.shiftKey) {
      e.preventDefault();
      goToPrev();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      goToNext();
    }
  };

  return (
    <div
      data-testid="find-replace-bar"
      className="bg-white border border-gray-200 rounded-md px-4 py-3 mb-2 shadow-sm"
      onKeyDown={handleKeyDown}
    >
      {/* Search row */}
      <div className="flex items-center gap-2 mb-2">
        <input
          ref={searchRef}
          data-testid="find-input"
          type="text"
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          placeholder="검색어"
          className="flex-1 px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
        />
        <span className="text-xs text-gray-500 min-w-[60px] text-center">
          {matchCount > 0
            ? `${currentMatchIndex + 1}/${matchCount}`
            : searchText
              ? '0건'
              : ''}
        </span>
        <button
          data-testid="find-prev"
          onClick={goToPrev}
          disabled={matchCount === 0}
          className="p-1.5 text-gray-500 hover:text-gray-700 disabled:text-gray-300"
          title="이전 (Shift+Enter)"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
          </svg>
        </button>
        <button
          data-testid="find-next"
          onClick={goToNext}
          disabled={matchCount === 0}
          className="p-1.5 text-gray-500 hover:text-gray-700 disabled:text-gray-300"
          title="다음 (Enter)"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>
        <button
          onClick={onClose}
          className="p-1.5 text-gray-400 hover:text-gray-600"
          title="닫기 (Esc)"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Replace row */}
      <div className="flex items-center gap-2">
        <input
          data-testid="replace-input"
          type="text"
          value={replaceText}
          onChange={(e) => setReplaceText(e.target.value)}
          placeholder="바꿀 텍스트"
          className="flex-1 px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
        />
        <label className="flex items-center gap-1 text-xs text-gray-600 cursor-pointer select-none">
          <input
            data-testid="case-sensitive-toggle"
            type="checkbox"
            checked={caseSensitive}
            onChange={(e) => setCaseSensitive(e.target.checked)}
            className="rounded border-gray-300 text-primary focus:ring-primary"
          />
          Aa
        </label>
        <button
          data-testid="replace-one"
          onClick={handleReplace}
          disabled={matchCount === 0}
          className="px-3 py-1.5 text-xs bg-gray-100 text-gray-700 rounded-md hover:bg-gray-200 disabled:text-gray-400 disabled:bg-gray-50 transition-colors"
        >
          바꾸기
        </button>
        <button
          data-testid="replace-all"
          onClick={handleReplaceAll}
          disabled={matchCount === 0}
          className="px-3 py-1.5 text-xs bg-primary text-white rounded-md hover:bg-primary-light disabled:bg-gray-300 transition-colors"
        >
          모두 바꾸기
        </button>
      </div>
    </div>
  );
}
