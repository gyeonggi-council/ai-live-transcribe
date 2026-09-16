'use client';

import React, { useEffect, useRef, useState } from 'react';

export interface SearchInputProps {
  onSearch: (query: string) => void;
  onClear?: () => void;
  placeholder?: string;
  initialValue?: string;
  debounceMs?: number;
}

export default function SearchInput({
  onSearch,
  onClear,
  placeholder = '키워드 검색...',
  initialValue = '',
  debounceMs = 300,
}: SearchInputProps) {
  const [value, setValue] = useState(initialValue);
  const debounceRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    // Cleanup debounce on unmount
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    };
  }, []);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newValue = e.target.value;
    setValue(newValue);

    // Clear previous debounce
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }

    // Set new debounce
    debounceRef.current = setTimeout(() => {
      onSearch(newValue);
    }, debounceMs);
  };

  const handleClear = () => {
    setValue('');
    onClear?.();

    // Clear previous debounce
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }

    // Trigger search with empty string
    debounceRef.current = setTimeout(() => {
      onSearch('');
    }, debounceMs);
  };

  return (
    <div
      data-testid="search-input-container"
      className="relative flex items-center border border-gray-300 rounded-lg bg-white focus-within:border-primary focus-within:ring-1 focus-within:ring-primary/20"
    >
      <svg
        data-testid="search-icon"
        className="absolute left-3 w-5 h-5 text-gray-400"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
        />
      </svg>

      <input
        type="search"
        role="searchbox"
        value={value}
        onChange={handleChange}
        placeholder={placeholder}
        className="w-full py-2 pl-10 pr-10 text-sm bg-transparent outline-none"
      />

      {value && (
        <button
          type="button"
          data-testid="clear-button"
          onClick={handleClear}
          aria-label="검색어 지우기"
          className="absolute right-2 p-1 text-gray-400 hover:text-gray-600 transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </button>
      )}
    </div>
  );
}
