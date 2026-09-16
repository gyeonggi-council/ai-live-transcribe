'use client';

/**
 * 선택한 회의의 브리프 카드(2026-09-14) — 대화 위에 짧게. 요약이 있으면 요약·결정·조치 수를 보이고,
 * 없으면 [요약 만들기]. 생성은 회의당 1회 캐시(서버)라 두 번째부터는 즉시 온다.
 * 실패해도 스스로 다시 부르지 않는다(AiSummaryModal 의 무한 재요청 루프를 반복하지 않는다).
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';

import MeetingDocumentsModal from '@/components/ai/MeetingDocumentsModal';
import { ApiError, generateSummary, getSummary } from '@/lib/api';
import type { MeetingSummaryType, MeetingType } from '@/types';

export interface AiMeetingBriefProps {
  meeting: MeetingType;
  /** 요약을 새로 만들 수 있는가(로그인 AI 역할·의회망 손님) */
  canGenerate: boolean;
  /** 빠른 질문 클릭 */
  onAsk: (question: string) => void;
  collapsed?: boolean;
  onToggle?: () => void;
}

export function quickQuestionsFor(meeting: Pick<MeetingType, 'title'>): string[] {
  const base = ['이 회의를 요약해 줘', '주요 결정사항은 무엇인가', '안건별로 논의 내용을 정리해 줘', '자료 요구나 후속 조치가 있었나'];
  if (/본회의/.test(meeting.title ?? '')) base.splice(2, 1, '도정질문에서 어떤 질의가 있었나');
  return base;
}

export default function AiMeetingBrief({ meeting, canGenerate, onAsk, collapsed, onToggle }: AiMeetingBriefProps) {
  const [summary, setSummary] = useState<MeetingSummaryType | null>(null);
  const [state, setState] = useState<'idle' | 'loading' | 'generating' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);
  const [docsOpen, setDocsOpen] = useState(false);
  const currentId = useRef(meeting.id);
  currentId.current = meeting.id;

  useEffect(() => {
    let cancelled = false;
    setSummary(null);
    setError(null);
    setState('loading');
    getSummary(meeting.id)
      .then((s) => {
        if (!cancelled) {
          setSummary(s && s.summary_text ? s : null);
          setState('idle');
        }
      })
      .catch(() => {
        if (!cancelled) setState('idle'); // 404 = 아직 없음
      });
    return () => {
      cancelled = true;
    };
  }, [meeting.id]);

  const generate = useCallback(async (refresh = false) => {
    const id = meeting.id;
    setState('generating');
    setError(null);
    try {
      const s = await generateSummary(id, refresh);
      if (currentId.current !== id) return; // 그 사이 다른 회의로 옮겨갔다 — A 의 요약을 B 아래 붙이지 않는다
      setSummary(s);
      setState('idle');
    } catch (err) {
      if (currentId.current !== id) return;
      setState('error');
      setError(
        err instanceof ApiError
          ? err.status === 429
            ? '오늘 요약 생성 한도를 다 썼습니다. 내일 다시 시도해 주세요.'
            : err.message
          : '요약을 만들지 못했습니다.'
      );
    }
  }, [meeting.id]);

  const decisions = summary?.key_decisions?.length ?? 0;
  const actions = summary?.action_items?.length ?? 0;
  const agendas = summary?.agenda_summaries?.length ?? 0;

  return (
    <section
      data-testid="ai-meeting-brief"
      className="rounded-lg border border-border bg-surface-raised/60 px-4 py-3"
      aria-label="회의 브리프"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="truncate text-[14px] font-bold text-text">{meeting.title}</h2>
          <p className="text-[12px] tabular-nums text-text-muted">
            {meeting.meeting_date}
            {meeting.committee ? ` · ${meeting.committee}` : ''}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          {canGenerate && (
            <button type="button" onClick={() => setDocsOpen(true)} data-testid="ai-brief-documents"
              className="rounded-md border border-primary-20 px-2 py-0.5 text-[12px] font-semibold text-primary hover:bg-primary-5">
              문서 만들기
            </button>
          )}
          {onToggle && (
            <button type="button" onClick={onToggle} className="text-[12px] text-text-muted underline">
              {collapsed ? '브리프 펼치기' : '접기'}
            </button>
          )}
        </div>
      </div>
      <MeetingDocumentsModal meetingId={meeting.id} open={docsOpen} onClose={() => setDocsOpen(false)} />

      {!collapsed && (
        <>
          <div className="mt-2 text-[13.5px] leading-relaxed text-text">
            {state === 'loading' && <span className="text-text-muted">요약을 확인하는 중…</span>}
            {state !== 'loading' && summary && (
              <>
                {summary.complete === false && (
                  <p className="mb-1.5 flex flex-wrap items-center gap-2 rounded-md bg-amber-50 px-2.5 py-1.5 text-[12px] text-amber-800" data-testid="ai-brief-partial">
                    <span>앞부분만 보고 만든 예전 요약입니다.</span>
                    {canGenerate && (
                      <button
                        type="button"
                        data-testid="ai-brief-refresh"
                        onClick={() => generate(true)}
                        disabled={state === 'generating'}
                        className="rounded border border-amber-300 bg-white px-2 py-0.5 font-semibold hover:bg-amber-100 disabled:opacity-50"
                      >
                        {state === 'generating' ? '다시 만드는 중…' : '회의 전체로 다시 만들기'}
                      </button>
                    )}
                  </p>
                )}
                <p className="line-clamp-4 whitespace-pre-wrap">{summary.summary_text}</p>
                <p className="mt-1.5 text-[12px] text-text-muted">
                  결정 {decisions} · 조치 {actions} · 안건 {agendas}
                </p>
              </>
            )}
            {state !== 'loading' && !summary && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-text-muted">아직 요약이 없습니다.</span>
                {canGenerate ? (
                  <button
                    type="button"
                    data-testid="ai-brief-generate"
                    onClick={() => generate(false)}
                    disabled={state === 'generating'}
                    className="rounded-md bg-primary px-2.5 py-1 text-[12.5px] font-semibold text-white hover:bg-primary-light disabled:opacity-50"
                  >
                    {state === 'generating' ? '요약 만드는 중…' : '요약 만들기'}
                  </button>
                ) : (
                  <span className="text-[12px] text-text-dim">요약 생성은 로그인하거나 의회망에서 할 수 있습니다.</span>
                )}
              </div>
            )}
            {error && (
              <p className="mt-1 text-[12.5px] text-red-700" role="alert">
                {error}
              </p>
            )}
          </div>
          <div className="mt-2.5 flex flex-wrap gap-1.5" data-testid="ai-quick-questions">
            {quickQuestionsFor(meeting).map((qq) => (
              <button
                key={qq}
                type="button"
                onClick={() => onAsk(qq)}
                className="inline-flex h-7 items-center rounded-full border border-border-strong px-3 text-[12.5px] text-text-secondary transition-colors hover:bg-surface-raised"
              >
                {qq}
              </button>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
