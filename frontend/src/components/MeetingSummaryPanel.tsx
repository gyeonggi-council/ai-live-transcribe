'use client';

import React, { useCallback, useEffect, useState } from 'react';

import Button from '@/components/ui/Button';
import Callout from '@/components/ui/Callout';
import { generateSummary, getSummary } from '@/lib/api';
import type { MeetingSummaryType } from '@/types';

interface MeetingSummaryPanelProps {
  meetingId: string;
}

export default function MeetingSummaryPanel({ meetingId }: MeetingSummaryPanelProps) {
  const [summary, setSummary] = useState<MeetingSummaryType | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadSummary = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getSummary(meetingId);
      setSummary(data);
    } catch (err) {
      // 404 means no summary exists yet - not an error
      if (err instanceof Error && 'status' in err && (err as { status: number }).status === 404) {
        setSummary(null);
      } else {
        setError('요약을 불러올 수 없습니다.');
      }
    } finally {
      setLoading(false);
    }
  }, [meetingId]);

  // Load existing summary on mount
  useEffect(() => {
    loadSummary();
  }, [meetingId, loadSummary]);

  const handleGenerate = async () => {
    try {
      setGenerating(true);
      setError(null);
      const data = await generateSummary(meetingId);
      setSummary(data);
    } catch (err) {
      if (err instanceof Error) {
        if (err.message.includes('API 키')) {
          setError('API 키가 설정되지 않았습니다.');
        } else {
          setError('요약 생성에 실패했습니다: ' + err.message);
        }
      } else {
        setError('요약 생성에 실패했습니다.');
      }
    } finally {
      setGenerating(false);
    }
  };

  // 재생성 기능 제거 (사용자 정책: AI 요약은 회의당 최초 1회만 — 중복 비용 방지)

  return (
    <div className="space-y-4" data-testid="meeting-summary-panel">
      {/* Loading state */}
      {loading && (
        <div className="text-center py-8">
          <div className="w-8 h-8 border-2 border-primary-40 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-sm text-gray-500">요약 불러오는 중...</p>
        </div>
      )}

      {/* No summary state */}
      {!loading && !summary && !generating && !error && (
        <div className="text-center py-8">
          <p className="text-gray-500 mb-4">아직 요약이 생성되지 않았습니다.</p>
          <Button variant="primary" size="md" onClick={handleGenerate}>
            AI 요약 생성
          </Button>
        </div>
      )}

      {/* Generating state */}
      {generating && (
        <div className="text-center py-8">
          <div className="w-8 h-8 border-2 border-primary-40 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-primary font-medium">AI 요약 생성 중...</p>
          <p className="text-sm text-gray-400 mt-1">자막을 분석하고 있습니다</p>
        </div>
      )}

      {/* Summary display */}
      {summary && !generating && (
        <>
          {/* 전체 요약 */}
          <section>
            <h3 className="text-sm font-semibold text-gray-700 mb-2 flex items-center gap-1">
              📋 전체 요약
            </h3>
            <p className="text-sm text-gray-600 bg-primary-5 p-3 rounded-md leading-relaxed">
              {summary.summary_text}
            </p>
          </section>

          {/* 안건별 요약 */}
          {summary.agenda_summaries.length > 0 && (
            <section>
              <h3 className="text-sm font-semibold text-gray-700 mb-2">📌 안건별 요약</h3>
              <div className="space-y-2">
                {summary.agenda_summaries.map((agenda, i) => (
                  <div key={i} className="bg-gray-50 p-3 rounded-md">
                    <p className="text-xs font-medium text-gray-500">
                      안건 {agenda.order_num}. {agenda.title}
                    </p>
                    <p className="text-sm text-gray-600 mt-1">{agenda.summary}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* 핵심 결정사항 */}
          {summary.key_decisions.length > 0 && (
            <section>
              <h3 className="text-sm font-semibold text-gray-700 mb-2">✅ 핵심 결정사항</h3>
              <ul className="space-y-1">
                {summary.key_decisions.map((decision, i) => (
                  <li key={i} className="text-sm text-gray-600 flex items-start gap-2">
                    <span className="text-success mt-0.5">•</span>
                    {decision}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* 후속 조치 */}
          {summary.action_items.length > 0 && (
            <section>
              <h3 className="text-sm font-semibold text-gray-700 mb-2">🔄 후속 조치</h3>
              <ul className="space-y-1">
                {summary.action_items.map((item, i) => (
                  <li key={i} className="text-sm text-gray-600 flex items-start gap-2">
                    <span className="text-primary mt-0.5">→</span>
                    {item}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* 메타 정보 — AI 요약은 회의당 1회만 생성 (재생성 없음) */}
          <div className="flex items-center justify-between pt-2 border-t text-xs text-gray-400">
            <span>모델: {summary.model_used}</span>
          </div>
        </>
      )}

      {/* Error state */}
      {error && (
        <Callout variant="danger">
          {error}
          <button
            onClick={handleGenerate}
            className="ml-2 underline text-error hover:text-error/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded"
          >
            재시도
          </button>
        </Callout>
      )}
    </div>
  );
}
