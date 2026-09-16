'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';

import { getCouncilors } from '@/lib/api';
import type { CouncilorType } from '@/types';

interface CouncilorPickerProps {
  value: string;
  onChange: (speaker: string, councilor?: CouncilorType) => void;
  placeholder?: string;
  className?: string;
  committeeFilter?: string;
}

/**
 * 의원 선택 드롭다운 (검색 가능, 직접 입력 지원)
 *
 * - 의원 목록에서 선택하거나 직접 입력 가능
 * - 프로필 사진 + 이름 + 정당 + 선거구 표시
 */
export default function CouncilorPicker({
  value,
  onChange,
  placeholder = '화자 선택 또는 입력',
  className = '',
  committeeFilter,
}: CouncilorPickerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [councilors, setCouncilors] = useState<CouncilorType[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [inputValue, setInputValue] = useState(value);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // 의원 목록 로드
  useEffect(() => {
    let cancelled = false;
    async function load() {
      setIsLoading(true);
      try {
        const data = await getCouncilors(query ? { q: query } : undefined);
        if (!cancelled) setCouncilors(data);
      } catch {
        // ignore
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }
    if (isOpen) {
      load();
    }
    return () => { cancelled = true; };
  }, [isOpen, query]);

  // 외부 value 변경 반영
  useEffect(() => {
    setInputValue(value);
  }, [value]);

  // 외부 클릭으로 닫기
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleSelect = useCallback(
    (councilor: CouncilorType) => {
      setInputValue(councilor.name);
      onChange(councilor.name, councilor);
      setIsOpen(false);
      setQuery('');
    },
    [onChange]
  );

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const v = e.target.value;
      setInputValue(v);
      setQuery(v);
      if (!isOpen) setIsOpen(true);
    },
    [isOpen]
  );

  const handleInputBlur = useCallback(() => {
    // 약간의 지연 후 직접 입력 확정 (의원 클릭 이벤트가 먼저 처리되도록)
    setTimeout(() => {
      if (inputValue !== value) {
        onChange(inputValue);
      }
    }, 200);
  }, [inputValue, value, onChange]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        onChange(inputValue);
        setIsOpen(false);
      } else if (e.key === 'Escape') {
        setIsOpen(false);
      }
    },
    [inputValue, onChange]
  );

  return (
    <div ref={containerRef} className={`relative ${className}`}>
      <input
        ref={inputRef}
        type="text"
        value={inputValue}
        onChange={handleInputChange}
        onFocus={() => setIsOpen(true)}
        onBlur={handleInputBlur}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
      />

      {isOpen && (
        <div className="absolute z-50 mt-1 w-full max-h-60 overflow-y-auto bg-white border border-gray-200 rounded-md shadow-lg">
          {/* 미지정 옵션 */}
          <button
            type="button"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => {
              setInputValue('');
              onChange('');
              setIsOpen(false);
            }}
            className="w-full px-3 py-2 text-left text-sm text-gray-500 hover:bg-gray-50"
          >
            (화자 미지정)
          </button>

          {isLoading ? (
            <div className="px-3 py-4 text-center text-sm text-gray-500">
              로딩 중...
            </div>
          ) : councilors.length === 0 ? (
            <div className="px-3 py-4 text-center text-sm text-gray-500">
              {query ? '일치하는 의원 없음' : '의원 데이터 없음'}
            </div>
          ) : (() => {
            // 위원회 필터가 있으면 2-tier: 해당 위원회 의원 먼저, 나머지 후
            let sortedCouncilors = councilors;
            let showDivider = false;
            if (committeeFilter) {
              const inCommittee = councilors.filter((c) =>
                c.committee?.includes(committeeFilter)
              );
              const others = councilors.filter(
                (c) => !c.committee?.includes(committeeFilter)
              );
              if (inCommittee.length > 0 && others.length > 0) {
                showDivider = true;
                sortedCouncilors = [...inCommittee, ...others];
              }
            }
            const dividerIdx = showDivider
              ? councilors.filter((c) =>
                  c.committee?.includes(committeeFilter || '')
                ).length
              : -1;
            return sortedCouncilors.map((c, idx) => (
              <React.Fragment key={c.id}>
                {idx === dividerIdx && (
                  <div className="border-t border-gray-200 mx-2 my-1">
                    <span className="text-[10px] text-gray-400 px-1">기타 의원</span>
                  </div>
                )}
                <button
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => handleSelect(c)}
                  className="w-full px-3 py-2 text-left hover:bg-primary-5 flex items-center gap-2"
                >
                  {c.profile_image_url ? (
                    <img
                      src={c.profile_image_url}
                      alt={c.name}
                      className="w-8 h-8 rounded-full object-cover flex-shrink-0"
                      onError={(e) => {
                        (e.target as HTMLImageElement).style.display = 'none';
                      }}
                    />
                  ) : (
                    <div className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center flex-shrink-0">
                      <span className="text-xs text-gray-500">
                        {c.name.charAt(0)}
                      </span>
                    </div>
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1">
                      <span className="text-sm font-medium text-gray-900">
                        {c.name}
                      </span>
                      {c.party && (
                        <span className="text-xs text-gray-500">({c.party})</span>
                      )}
                    </div>
                    {c.district && (
                      <p className="text-xs text-gray-400 truncate">{c.district}</p>
                    )}
                  </div>
                </button>
              </React.Fragment>
            ));
          })()}
        </div>
      )}
    </div>
  );
}
