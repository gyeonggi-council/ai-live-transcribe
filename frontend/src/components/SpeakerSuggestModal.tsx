'use client';

import React, { useCallback, useEffect, useState } from 'react';

import { Button } from '@/components/ui';
import { suggestSpeakerNames } from '@/lib/api';

interface SpeakerSuggestion {
  speaker: string;
  speaker_label: string;
  suggested_name: string;
  name?: string;
  confidence: number;
  party?: string | null;
  role?: string | null;
  evidence?: string | null;
  councilor?: {
    profile_image_url?: string | null;
    party?: string | null;
    district?: string | null;
  } | null;
}

/** 정당별 컬러 매핑 */
function getPartyColor(party: string | null): string {
  if (!party) return 'bg-gray-100 text-gray-600';
  if (party.includes('민주')) return 'bg-party-dem/10 text-party-dem';
  if (party.includes('국민의힘')) return 'bg-party-pp/10 text-party-pp';
  if (party.includes('정의')) return 'bg-warning-bg/20 text-warning';
  return 'bg-gray-100 text-gray-600';
}

/** confidence 배지 스타일 */
function getConfidenceBadge(confidence?: 'high' | 'medium' | 'low'): {
  label: string;
  className: string;
} {
  switch (confidence) {
    case 'high':
      return { label: '높음', className: 'bg-success/10 text-success' };
    case 'medium':
      return { label: '보통', className: 'bg-warning-bg/20 text-warning' };
    case 'low':
      return { label: '낮음', className: 'bg-gray-100 text-gray-500' };
    default:
      return { label: '', className: '' };
  }
}

interface SpeakerSuggestModalProps {
  meetingId: string;
  onApply: (speakerLabel: string, newName: string) => void;
  onClose: () => void;
}

/**
 * AI 화자 추천 모달
 *
 * GPT가 자막에서 화자 이름을 추출하고, 의원 DB와 교차 매칭합니다.
 * 각 추천에 [적용] [무시] 버튼이 있습니다.
 */
export default function SpeakerSuggestModal({
  meetingId,
  onApply,
  onClose,
}: SpeakerSuggestModalProps) {
  const [suggestions, setSuggestions] = useState<SpeakerSuggestion[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [appliedLabels, setAppliedLabels] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        setIsLoading(true);
        setError(null);
        const result = await suggestSpeakerNames(meetingId);
        if (!cancelled) {
          const mapped = (result.suggestions || []).map((s) => ({
            ...s,
            speaker_label: s.speaker,
            name: s.suggested_name,
          }));
          setSuggestions(mapped);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'AI 화자 추천 실패');
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [meetingId]);

  const handleApply = useCallback(
    (suggestion: SpeakerSuggestion) => {
      if (!suggestion.name) return;
      onApply(suggestion.speaker_label, suggestion.name);
      setAppliedLabels((prev) => new Set(prev).add(suggestion.speaker_label));
    },
    [onApply]
  );

  const handleApplyAll = useCallback(() => {
    for (const s of suggestions) {
      if (s.name && !appliedLabels.has(s.speaker_label)) {
        onApply(s.speaker_label, s.name);
      }
    }
    setAppliedLabels(new Set(suggestions.filter((s) => s.name).map((s) => s.speaker_label)));
  }, [suggestions, appliedLabels, onApply]);

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div
        data-testid="speaker-suggest-modal"
        className="bg-white rounded-lg max-w-lg w-full mx-4 max-h-[80vh] flex flex-col"
      >
        {/* 헤더 */}
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900">AI 화자 추천</h2>
          <button
            onClick={onClose}
            aria-label="닫기"
            className="text-gray-400 hover:text-gray-600 transition-colors rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* 바디 */}
        <div className="flex-1 overflow-y-auto p-6">
          {isLoading ? (
            <div className="flex flex-col items-center justify-center py-12">
              <div className="w-8 h-8 border-4 border-gray-200 border-t-primary rounded-full animate-spin mb-3" />
              <p className="text-sm text-gray-500">AI가 화자를 분석 중입니다...</p>
            </div>
          ) : error ? (
            <div className="text-center py-8">
              <p className="text-sm text-error mb-2">{error}</p>
              <button
                onClick={onClose}
                className="text-sm text-primary hover:underline"
              >
                닫기
              </button>
            </div>
          ) : suggestions.length === 0 ? (
            <p className="text-center text-sm text-gray-500 py-8">
              추천할 화자를 찾지 못했습니다.
            </p>
          ) : (
            <div className="space-y-3">
              {suggestions.map((s) => {
                const isApplied = appliedLabels.has(s.speaker_label);
                return (
                  <div
                    key={s.speaker_label}
                    className={`border rounded-lg p-4 transition-colors ${
                      isApplied ? 'bg-success/5 border-success/30' : 'border-gray-200'
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      {/* 의원 프로필 사진 */}
                      {s.councilor?.profile_image_url ? (
                        <img
                          src={s.councilor.profile_image_url}
                          alt={s.name || ''}
                          className="w-10 h-10 rounded-full object-cover flex-shrink-0"
                          onError={(e) => {
                            (e.target as HTMLImageElement).style.display = 'none';
                          }}
                        />
                      ) : (
                        <div className="w-10 h-10 rounded-full bg-gray-200 flex items-center justify-center flex-shrink-0">
                          <span className="text-sm text-gray-500">
                            {(s.name || s.speaker_label).charAt(0)}
                          </span>
                        </div>
                      )}

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span className="text-xs text-gray-400">
                            {s.speaker_label}
                          </span>
                          <svg className="w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
                          </svg>
                          <span className="text-sm font-semibold text-gray-900">
                            {s.name || '(확인 불가)'}
                          </span>
                          {s.confidence && (() => {
                            const confLevel = s.confidence >= 0.8 ? 'high' : s.confidence >= 0.5 ? 'medium' : 'low';
                            const badge = getConfidenceBadge(confLevel);
                            return (
                              <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${badge.className}`}>
                                {badge.label}
                              </span>
                            );
                          })()}
                        </div>
                        {s.councilor && (
                          <div className="flex items-center gap-1.5 text-xs">
                            <span className={`px-1.5 py-0.5 rounded ${getPartyColor(s.councilor.party ?? null)}`}>
                              {s.councilor.party}
                            </span>
                            {s.councilor.district && (
                              <span className="text-gray-500">{s.councilor.district}</span>
                            )}
                          </div>
                        )}
                        {!s.councilor && s.role && (
                          <p className="text-xs text-gray-500">{s.role}</p>
                        )}
                        {s.evidence && (
                          <p className="text-[11px] text-gray-400 mt-1 italic line-clamp-1">
                            &ldquo;{s.evidence}&rdquo;
                          </p>
                        )}
                      </div>

                      {/* 적용 / 무시 버튼 */}
                      <div className="flex-shrink-0">
                        {isApplied ? (
                          <span className="text-xs text-success font-medium flex items-center gap-1">
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                            </svg>
                            적용됨
                          </span>
                        ) : s.name ? (
                          <Button
                            size="sm"
                            onClick={() => handleApply(s)}
                            className="text-xs"
                          >
                            적용
                          </Button>
                        ) : (
                          <span className="text-xs text-gray-400">확인 불가</span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* 푸터 */}
        {!isLoading && !error && suggestions.length > 0 && (
          <div className="px-6 py-3 border-t border-gray-200 flex items-center justify-between">
            <p className="text-xs text-gray-500">
              {appliedLabels.size}/{suggestions.filter((s) => s.name).length}개 적용됨
            </p>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={onClose}>
                닫기
              </Button>
              <Button
                size="sm"
                onClick={handleApplyAll}
                disabled={appliedLabels.size === suggestions.filter((s) => s.name).length}
              >
                전체 적용
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
