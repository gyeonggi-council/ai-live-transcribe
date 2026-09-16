'use client';

/**
 * AI 요약 모달 컴포넌트
 *
 * @TASK P11B - AI Assistant summary modal
 *
 * 2026-09-14 — 정본 경로 /api/meetings/{id}/summary(generateSummary/getSummary, MeetingSummaryType) 로 이관.
 * 옛 /api/ai/summary 는 action_items·안건별 요약 본문을 버렸다.
 * - 열리면 저장된 요약을 읽고(비용 0), 없을 때만 [요약 만들기] 버튼. 실패해도 스스로 다시 부르지 않는다
 *   (예전엔 실패 → summary=null → effect 가 다시 생성 → 무한 재요청).
 * - "다시 만들기" 는 앞부분만 본 옛 요약(complete=false)에만 뜬다(서버 ?refresh=1). 완전한 요약은 회의당 1회다.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';

import Button from '@/components/ui/Button';
import Modal from '@/components/ui/Modal';
import { ApiError, generateSummary, getSummary } from '@/lib/api';
import type { MeetingSummaryType } from '@/types';

interface AiSummaryModalProps {
  meetingId: string;
  isOpen: boolean;
  onClose: () => void;
}

export default function AiSummaryModal({ meetingId, isOpen, onClose }: AiSummaryModalProps) {
  const [summary, setSummary] = useState<MeetingSummaryType | null>(null);
  const loadedFor = useRef<string | null>(null); // state 로 두면 deps 가 바뀌어 effect 가 재실행·취소된다
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 열릴 때 저장된 요약 읽기 — 회의당 한 번만(loadedFor). 생성은 버튼으로만.
  useEffect(() => {
    if (!isOpen || loadedFor.current === meetingId) return undefined;
    let cancelled = false;
    loadedFor.current = meetingId;
    setSummary(null);
    setError(null);
    setLoading(true);
    getSummary(meetingId)
      .then((s) => {
        if (!cancelled) setSummary(s);
      })
      .catch(() => {
        /* 404 = 아직 없음 */
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      // 조회가 끝나기 전에 닫혔으면 표식을 풀어 다음에 다시 읽는다 — 안 그러면 로딩 표시가 영구히 남는다(Codex 검토)
      if (loadedFor.current === meetingId) loadedFor.current = null;
    };
  }, [isOpen, meetingId]);

  const generate = useCallback(
    async (refresh: boolean) => {
      setLoading(true);
      setError(null);
      try {
        setSummary(await generateSummary(meetingId, refresh));
      } catch (err) {
        setError(
          err instanceof ApiError && err.status === 429
            ? '오늘 요약 생성 한도를 다 썼습니다. 내일 다시 시도해 주세요.'
            : err instanceof Error
              ? err.message
              : '요약 생성 중 오류가 발생했습니다.'
        );
      } finally {
        setLoading(false);
      }
    },
    [meetingId]
  );

  const partial = summary?.complete === false;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="AI 회의 요약"
      size="md"
      footer={
        <>
          <Button variant="outline" size="sm" onClick={onClose}>
            닫기
          </Button>
          {!summary && !loading && (
            <Button variant="primary" size="sm" onClick={() => generate(false)} data-testid="ai-summary-generate">
              요약 만들기
            </Button>
          )}
          {partial && !loading && (
            <Button variant="primary" size="sm" onClick={() => generate(true)} data-testid="ai-summary-refresh">
              다시 만들기
            </Button>
          )}
        </>
      }
    >
      <div className="max-h-96 overflow-y-auto">
        {loading && (
          <div className="flex items-center justify-center py-8" role="status">
            <span className="inline-block h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
            <span className="ml-2 text-sm text-gray-500">요약을 확인하는 중...</span>
          </div>
        )}

        {error && (
          <p className="text-sm text-error" role="alert">
            {error}
          </p>
        )}

        {!summary && !loading && !error && (
          <p className="py-6 text-center text-sm text-gray-500">아직 요약이 없습니다. [요약 만들기]를 누르면 회의 전체 자막으로 만듭니다.</p>
        )}

        {summary && !loading && (
          <div className="space-y-4">
            {partial && (
              <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800" data-testid="ai-summary-partial">
                앞부분만 보고 만든 예전 요약입니다. [다시 만들기]를 누르면 회의 전체로 다시 만듭니다.
              </p>
            )}
            <div>
              <h3 className="mb-1 text-sm font-medium text-gray-700">요약</h3>
              <p className="whitespace-pre-wrap text-sm text-gray-800">{summary.summary_text}</p>
            </div>

            {summary.key_decisions?.length > 0 && (
              <div>
                <h3 className="mb-1 text-sm font-medium text-gray-700">주요 결정</h3>
                <ul className="list-disc space-y-1 pl-5 text-sm text-gray-800">
                  {summary.key_decisions.map((point, i) => (
                    <li key={i}>{point}</li>
                  ))}
                </ul>
              </div>
            )}

            {summary.action_items?.length > 0 && (
              <div>
                <h3 className="mb-1 text-sm font-medium text-gray-700">후속 조치</h3>
                <ul className="list-disc space-y-1 pl-5 text-sm text-gray-800">
                  {summary.action_items.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              </div>
            )}

            {summary.agenda_summaries?.length > 0 && (
              <div>
                <h3 className="mb-1 text-sm font-medium text-gray-700">안건별 요약</h3>
                <ul className="space-y-2 text-sm text-gray-800">
                  {summary.agenda_summaries.map((a, i) => (
                    <li key={i}>
                      <span className="font-semibold">
                        {a.order_num}. {a.title}
                      </span>
                      {a.summary && <p className="mt-0.5 whitespace-pre-wrap text-gray-700">{a.summary}</p>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}
