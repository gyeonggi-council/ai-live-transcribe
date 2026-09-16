'use client';

import React, { useMemo } from 'react';

import type { SubtitleType } from '../types';

interface SttComparisonPanelProps {
  subtitles: SubtitleType[];
  currentTimeMs: number | null;
  currentLineText: string;
  isOpen: boolean;
  onClose: () => void;
}

interface NearbySubtitle {
  subtitle: SubtitleType;
  startMs: number;
  endMs: number;
  distanceMs: number;
}

function formatMs(ms: number): string {
  const totalSec = ms / 1000;
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m.toString().padStart(2, '0')}:${s.toFixed(1).padStart(4, '0')}`;
}

function getDistanceToRange(currentMs: number, startMs: number, endMs: number): number {
  if (currentMs >= startMs && currentMs <= endMs) {
    return 0;
  }

  return Math.min(Math.abs(currentMs - startMs), Math.abs(currentMs - endMs));
}

export default function SttComparisonPanel({
  subtitles,
  currentTimeMs,
  currentLineText,
  isOpen,
  onClose,
}: SttComparisonPanelProps) {
  const nearbySubtitles = useMemo<NearbySubtitle[]>(() => {
    if (currentTimeMs === null) {
      return [];
    }

    const windowMs = 30000;

    return subtitles
      .map((subtitle) => {
        const startMs = subtitle.start_time * 1000;
        const endMs = subtitle.end_time * 1000;
        const distanceMs = getDistanceToRange(currentTimeMs, startMs, endMs);

        return {
          subtitle,
          startMs,
          endMs,
          distanceMs,
        };
      })
      .filter(({ startMs, endMs }) => {
        const isInWindowByStart = Math.abs(startMs - currentTimeMs) <= windowMs;
        const isInWindowByEnd = Math.abs(endMs - currentTimeMs) <= windowMs;
        const containsCurrent = startMs <= currentTimeMs && endMs >= currentTimeMs;

        return isInWindowByStart || isInWindowByEnd || containsCurrent;
      })
      .sort((a, b) => a.startMs - b.startMs);
  }, [currentTimeMs, subtitles]);

  const closestSubtitleId = useMemo(() => {
    if (nearbySubtitles.length === 0 || currentTimeMs === null) {
      return null;
    }

    let closest = nearbySubtitles[0]!;
    for (let i = 1; i < nearbySubtitles.length; i += 1) {
      if (nearbySubtitles[i]!.distanceMs < closest.distanceMs) {
        closest = nearbySubtitles[i]!;
      }
    }

    return closest?.subtitle.id ?? null;
  }, [currentTimeMs, nearbySubtitles]);

  if (!isOpen) {
    return null;
  }

  return (
    <aside className="fixed top-0 right-0 z-30 w-80 h-full bg-gray-50 border-l border-gray-200 flex flex-col">
      <div className="px-4 py-3 border-b font-semibold text-sm flex items-center justify-between">
        <span>STT 자막 비교</span>
        <button
          type="button"
          onClick={onClose}
          className="text-gray-400 hover:text-gray-600"
          aria-label="비교 패널 닫기"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div className="px-4 py-3 border-b border-gray-200">
        <p className="text-xs text-gray-500 mb-1">현재 속기</p>
        <p className="text-sm text-gray-800 break-words">&quot;{currentLineText || '내용 없음'}&quot;</p>
      </div>

      {currentTimeMs === null ? (
        <div className="px-4 py-4 text-sm text-gray-500">시간 정보 없음</div>
      ) : (
        <div className="flex-1 overflow-y-auto">
          {nearbySubtitles.length === 0 ? (
            <div className="px-4 py-4 text-sm text-gray-500">주변 STT 자막이 없습니다.</div>
          ) : (
            <ul>
              {nearbySubtitles.map(({ subtitle, startMs, endMs }) => {
                const isActive = subtitle.id === closestSubtitleId;

                return (
                  <li
                    key={subtitle.id}
                    className={
                      isActive
                        ? 'px-4 py-3 bg-warning-bg/10 border-l-2 border-warning-bg'
                        : 'px-4 py-3 border-l-2 border-transparent'
                    }
                  >
                    <p className="text-sm text-gray-800 whitespace-pre-wrap break-words">{subtitle.text}</p>
                    <p className="text-xs font-mono text-gray-400 mt-1">
                      {formatMs(startMs)} - {formatMs(endMs)}
                    </p>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </aside>
  );
}
