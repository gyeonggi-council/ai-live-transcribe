'use client';

/**
 * AI 보조 패널 - 속기 편집기용
 *
 * @TASK P11C-T10 - AI 보조 패널
 * @SPEC docs/planning/02-trd.md#속기록
 *
 * 접힘/펼침 사이드 패널
 * 3개 기능: 화자 자동 구분 / 맞춤법 교정 / 문단 구분
 * 결과 미리보기 (diff 표시) + "적용" / "취소" 버튼
 */

import React, { useState } from 'react';

import { Button, Callout } from '@/components/ui';

import { aiDetectParagraphs, aiDetectSpeakers, aiProofread } from '../lib/api';

import type {
  ParagraphSuggestion,
  ProofreadCorrection,
  SpeakerSuggestion,
} from '../types';

type AiMode = 'speakers' | 'proofread' | 'paragraphs' | null;

interface StenographyAiPanelProps {
  meetingId: string;
  recordId: string;
  isOpen: boolean;
  onToggle: () => void;
  onApplySpeakers: (suggestions: SpeakerSuggestion[]) => void;
  onApplyProofread: (corrections: ProofreadCorrection[]) => void;
  onApplyParagraphs: (paragraphs: ParagraphSuggestion[]) => void;
}

export default function StenographyAiPanel({
  meetingId,
  recordId,
  isOpen,
  onToggle,
  onApplySpeakers,
  onApplyProofread,
  onApplyParagraphs,
}: StenographyAiPanelProps) {
  const [mode, setMode] = useState<AiMode>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Results
  const [speakerResults, setSpeakerResults] = useState<SpeakerSuggestion[]>([]);
  const [proofreadResults, setProofreadResults] = useState<ProofreadCorrection[]>([]);
  const [paragraphResults, setParagraphResults] = useState<ParagraphSuggestion[]>([]);

  const handleDetectSpeakers = async () => {
    setIsLoading(true);
    setError(null);
    setMode('speakers');
    try {
      const result = await aiDetectSpeakers(meetingId, recordId);
      setSpeakerResults(result.suggestions);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'AI 화자 구분 실패');
    } finally {
      setIsLoading(false);
    }
  };

  const handleProofread = async () => {
    setIsLoading(true);
    setError(null);
    setMode('proofread');
    try {
      const result = await aiProofread(meetingId, recordId);
      setProofreadResults(result.corrections);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'AI 맞춤법 교정 실패');
    } finally {
      setIsLoading(false);
    }
  };

  const handleDetectParagraphs = async () => {
    setIsLoading(true);
    setError(null);
    setMode('paragraphs');
    try {
      const result = await aiDetectParagraphs(meetingId, recordId);
      setParagraphResults(result.paragraphs);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'AI 문단 구분 실패');
    } finally {
      setIsLoading(false);
    }
  };

  const handleApply = () => {
    if (mode === 'speakers') onApplySpeakers(speakerResults);
    if (mode === 'proofread') onApplyProofread(proofreadResults);
    if (mode === 'paragraphs') onApplyParagraphs(paragraphResults);
    handleClear();
  };

  const handleClear = () => {
    setMode(null);
    setSpeakerResults([]);
    setProofreadResults([]);
    setParagraphResults([]);
    setError(null);
  };

  if (!isOpen) {
    return (
      <button
        onClick={onToggle}
        className="fixed right-0 top-1/2 -translate-y-1/2 bg-primary text-white px-2 py-4 rounded-l-lg text-xs font-medium hover:bg-primary-dark transition-colors z-20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        title="AI 보조 패널 열기"
      >
        AI
      </button>
    );
  }

  const hasResults =
    (mode === 'speakers' && speakerResults.length > 0) ||
    (mode === 'proofread' && proofreadResults.length > 0) ||
    (mode === 'paragraphs' && paragraphResults.length > 0);

  return (
    <div className="w-80 border-l border-gray-200 bg-white flex flex-col h-full" data-testid="ai-panel">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">AI 보조</h3>
        <button
          onClick={onToggle}
          className="text-gray-400 hover:text-gray-600 transition-colors"
          title="패널 닫기"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Action buttons */}
      <div className="p-4 space-y-2">
        <button
          onClick={handleDetectSpeakers}
          disabled={isLoading}
          className="w-full px-3 py-2 text-sm font-medium text-left bg-gray-50 border border-gray-200 rounded-lg hover:bg-gray-100 disabled:opacity-50 transition-colors"
        >
          화자 자동 구분
          <span className="block text-xs text-gray-400 mt-0.5">발언 패턴 분석으로 화자를 식별합니다</span>
        </button>
        <button
          onClick={handleProofread}
          disabled={isLoading}
          className="w-full px-3 py-2 text-sm font-medium text-left bg-gray-50 border border-gray-200 rounded-lg hover:bg-gray-100 disabled:opacity-50 transition-colors"
        >
          맞춤법 교정
          <span className="block text-xs text-gray-400 mt-0.5">맞춤법, 띄어쓰기, 의회 용어 교정</span>
        </button>
        <button
          onClick={handleDetectParagraphs}
          disabled={isLoading}
          className="w-full px-3 py-2 text-sm font-medium text-left bg-gray-50 border border-gray-200 rounded-lg hover:bg-gray-100 disabled:opacity-50 transition-colors"
        >
          문단 구분
          <span className="block text-xs text-gray-400 mt-0.5">주제 변경점을 자동 감지합니다</span>
        </button>
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="flex items-center justify-center py-8">
          <div className="w-6 h-6 border-2 border-gray-200 border-t-primary rounded-full animate-spin" />
          <span className="ml-2 text-sm text-gray-500">AI 분석 중...</span>
        </div>
      )}

      {/* Error */}
      {error && (
        <Callout variant="danger" className="mx-4">
          {error}
        </Callout>
      )}

      {/* Results */}
      {!isLoading && hasResults && (
        <div className="flex-1 overflow-y-auto px-4 pb-4">
          {mode === 'speakers' && (
            <div className="space-y-2">
              <h4 className="text-xs font-semibold text-gray-500 uppercase">화자 제안 ({speakerResults.length}건)</h4>
              {speakerResults.map((s) => (
                <div key={s.line_id} className="p-2 bg-primary-5 rounded text-xs">
                  <span className="font-medium text-primary-dark">{s.suggested_speaker}</span>
                  <span className="text-gray-400 ml-1">(line: {s.line_id.slice(0, 8)})</span>
                </div>
              ))}
            </div>
          )}

          {mode === 'proofread' && (
            <div className="space-y-2">
              <h4 className="text-xs font-semibold text-gray-500 uppercase">교정 ({proofreadResults.length}건)</h4>
              {proofreadResults.map((c) => (
                <div key={c.line_id} className="p-2 bg-warning-bg/10 rounded text-xs space-y-1">
                  <div className="line-through text-error">{c.original_text}</div>
                  <div className="text-success font-medium">{c.corrected_text}</div>
                  {c.changes.map((ch, i) => (
                    <span key={i} className="inline-block mr-1 px-1 bg-gray-100 rounded text-gray-500">{ch}</span>
                  ))}
                </div>
              ))}
            </div>
          )}

          {mode === 'paragraphs' && (
            <div className="space-y-2">
              <h4 className="text-xs font-semibold text-gray-500 uppercase">문단 구분 ({paragraphResults.length}건)</h4>
              {paragraphResults.map((p) => (
                <div key={p.line_id} className="p-2 bg-success/10 rounded text-xs">
                  새 문단 시작 (line: {p.line_id.slice(0, 8)})
                </div>
              ))}
            </div>
          )}

          {/* Apply / Cancel */}
          <div className="flex gap-2 mt-4">
            <Button onClick={handleApply} size="sm" className="flex-1">
              적용
            </Button>
            <Button onClick={handleClear} variant="outline" size="sm" className="flex-1">
              취소
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
