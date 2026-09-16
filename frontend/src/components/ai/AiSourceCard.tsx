'use client';

/**
 * AI 답변의 참조 발언 카드 — `/ai` 와 AiChatPanel 이 같이 쓴다(2026-09-14, 전에는 두 벌이 시간 형식까지 달랐다).
 * 시간 칩(▶ 00:12:41)은 자막 패널·통합검색과 같은 모양. 누르면 그 시각으로 간다:
 *  - onPlayAt 이 있으면 그 자리에서 재생(회의록 화면), 없으면 /vod/{id}?t={초} 로 이동(통합검색과 같은 규칙).
 */

import React from 'react';

import Link from 'next/link';

import type { AiSourceReference } from '@/types';

/** 초 → "00:12:41" */
export function formatSourceAt(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
}

export interface AiSourceCardProps {
  source: AiSourceReference;
  onPlayAt?: (seconds: number) => void;
  /** 작은 글씨(드로어 패널) */
  compact?: boolean;
}

export default function AiSourceCard({ source, onPlayAt, compact }: AiSourceCardProps) {
  const at = source.start_time != null ? formatSourceAt(source.start_time) : null;
  const title = source.meeting_title || (source.meeting_id ? `회의 ${source.meeting_id.slice(0, 8)}` : '참조');
  const titleCls = compact ? 'text-[12px]' : 'text-[12.5px]';
  const bodyCls = compact ? 'text-xs' : 'text-[13px]';

  const body = (
    <>
      {at && (
        <span className="mt-px inline-flex shrink-0 items-center gap-1 rounded bg-primary/10 px-1.5 py-0.5 font-mono text-[11.5px] text-primary">
          <span className="text-[9px] leading-none" aria-hidden="true">
            ▶
          </span>
          {at}
        </span>
      )}
      <span className="min-w-0 flex-1 text-left">
        <span className={`block font-semibold text-primary ${titleCls}`}>{title}</span>
        {source.text_snippet && (
          <span className={`mt-0.5 block leading-relaxed text-text-secondary ${bodyCls}`}>{source.text_snippet}</span>
        )}
      </span>
    </>
  );

  const shell = `flex w-full items-start gap-3 rounded-lg border border-border bg-surface ${compact ? 'px-2.5 py-2' : 'px-3.5 py-2.5'}`;
  const hover = 'transition-colors hover:border-primary-20 hover:bg-primary-5/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary';

  if (onPlayAt && source.start_time != null) {
    return (
      <button
        type="button"
        onClick={() => onPlayAt(source.start_time as number)}
        className={`${shell} ${hover}`}
        title="이 시간대 재생"
        data-testid="ai-source-card"
      >
        {body}
      </button>
    );
  }
  if (!source.meeting_id) {
    return <div className={shell}>{body}</div>;
  }
  const href = source.start_time != null ? `/vod/${source.meeting_id}?t=${Math.floor(source.start_time)}` : `/vod/${source.meeting_id}`;
  return (
    <Link href={href} className={`${shell} ${hover}`} data-testid="ai-source-card" title="회의 영상의 이 시각으로 이동">
      {body}
    </Link>
  );
}
