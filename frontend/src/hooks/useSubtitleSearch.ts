'use client';

import { useMemo, useState, useEffect, useCallback } from 'react';

import type { SubtitleType } from '../types';

/**
 * Filter mode options for subtitle search
 */
export type FilterMode = 'match' | 'all';

/**
 * Options for useSubtitleSearch hook
 */
export interface UseSubtitleSearchOptions {
  /** Array of subtitles to search through */
  subtitles: SubtitleType[];
  /** Search query string */
  query: string;
  /**
   * Filter mode:
   * - 'match': Return only matching subtitles (default)
   * - 'all': Return all subtitles, but track matches
   */
  filterMode?: FilterMode;
}

/**
 * Return type for useSubtitleSearch hook
 */
export interface UseSubtitleSearchReturn {
  /** Filtered subtitles based on query and filterMode */
  filteredSubtitles: SubtitleType[];
  /** Indices of matching subtitles in original array */
  matchIndices: number[];
  /** Total number of matches */
  matchCount: number;
  /** First matching subtitle or null */
  firstMatch: SubtitleType | null;
  /** Currently selected match subtitle or null */
  currentMatch: SubtitleType | null;
  /** Index of current match (0-based), -1 if no matches */
  currentMatchIndex: number;
  /** Navigate to next match (wraps around) */
  goToNextMatch: () => void;
  /** Navigate to previous match (wraps around) */
  goToPrevMatch: () => void;
  /** Check if a subtitle id is in the match set */
  isMatch: (id: string) => boolean;
}

/**
 * Hook for searching and filtering subtitles
 *
 * Provides filtered results, match navigation, and helpers for
 * integrating with subtitle display components.
 *
 * @example
 * ```tsx
 * const {
 *   filteredSubtitles,
 *   matchCount,
 *   currentMatch,
 *   goToNextMatch,
 *   goToPrevMatch,
 * } = useSubtitleSearch({
 *   subtitles,
 *   query: searchQuery,
 *   filterMode: 'match',
 * });
 * ```
 */
export function useSubtitleSearch({
  subtitles,
  query,
  filterMode = 'match',
}: UseSubtitleSearchOptions): UseSubtitleSearchReturn {
  const [currentMatchIndex, setCurrentMatchIndex] = useState(0);

  // Normalize query (trim whitespace)
  const normalizedQuery = query?.trim() || '';

  // Find matching subtitles and their indices
  const { matchingSubtitles, matchIndices, matchIdSet } = useMemo(() => {
    if (!normalizedQuery) {
      return {
        matchingSubtitles: [],
        matchIndices: [] as number[],
        matchIdSet: new Set<string>(),
      };
    }

    const lowerQuery = normalizedQuery.toLowerCase();
    const matches: SubtitleType[] = [];
    const indices: number[] = [];
    const idSet = new Set<string>();

    subtitles.forEach((subtitle, index) => {
      if (subtitle.text.toLowerCase().includes(lowerQuery)) {
        matches.push(subtitle);
        indices.push(index);
        idSet.add(subtitle.id);
      }
    });

    return {
      matchingSubtitles: matches,
      matchIndices: indices,
      matchIdSet: idSet,
    };
  }, [subtitles, normalizedQuery]);

  // Determine filtered subtitles based on filter mode
  const filteredSubtitles = useMemo(() => {
    if (!normalizedQuery) {
      return subtitles;
    }

    if (filterMode === 'all') {
      return subtitles;
    }

    return matchingSubtitles;
  }, [subtitles, normalizedQuery, filterMode, matchingSubtitles]);

  // Reset current match index when query changes
  useEffect(() => {
    if (matchingSubtitles.length > 0) {
      setCurrentMatchIndex(0);
    } else {
      setCurrentMatchIndex(-1);
    }
  }, [normalizedQuery, matchingSubtitles.length]);

  // Initialize current match index
  useEffect(() => {
    if (matchingSubtitles.length > 0 && currentMatchIndex === -1) {
      setCurrentMatchIndex(0);
    }
  }, [matchingSubtitles.length, currentMatchIndex]);

  // Navigation functions
  const goToNextMatch = useCallback(() => {
    if (matchingSubtitles.length === 0) return;

    setCurrentMatchIndex((prev) => {
      const next = prev + 1;
      return next >= matchingSubtitles.length ? 0 : next;
    });
  }, [matchingSubtitles.length]);

  const goToPrevMatch = useCallback(() => {
    if (matchingSubtitles.length === 0) return;

    setCurrentMatchIndex((prev) => {
      const next = prev - 1;
      return next < 0 ? matchingSubtitles.length - 1 : next;
    });
  }, [matchingSubtitles.length]);

  // Helper to check if an id matches
  const isMatch = useCallback(
    (id: string): boolean => {
      return matchIdSet.has(id);
    },
    [matchIdSet]
  );

  // Computed values
  const matchCount = matchingSubtitles.length;
  const firstMatch: SubtitleType | null =
    matchingSubtitles.length > 0 ? matchingSubtitles[0] ?? null : null;
  const currentMatch: SubtitleType | null =
    currentMatchIndex >= 0 && currentMatchIndex < matchingSubtitles.length
      ? matchingSubtitles[currentMatchIndex] ?? null
      : null;

  return {
    filteredSubtitles,
    matchIndices,
    matchCount,
    firstMatch,
    currentMatch,
    currentMatchIndex: matchingSubtitles.length > 0 ? currentMatchIndex : -1,
    goToNextMatch,
    goToPrevMatch,
    isMatch,
  };
}

export default useSubtitleSearch;
