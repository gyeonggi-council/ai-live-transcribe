'use client';

import React from 'react';

import type { SubtitleType } from '@/types';

export interface CurrentUtteranceCardProps {
  subtitle?: SubtitleType;
  /** STT 미확정 텍스트 — 확정 자막이 아직 없을 때 자리를 채운다 */
  interimText?: string;
  /** 생중계 중이면 LIVE 표시를 붙인다 */
  isLive?: boolean;
  /** STT 시작 시각(ms) — 있으면 실제 시계 시각도 함께 보여준다 */
  sttStartedAt?: number | null;
  className?: string;
}

function formatElapsed(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(h)}:${pad(m)}:${pad(sec)}`;
}

function formatClock(sttStartedAt: number, startTime: number): string {
  const d = new Date(sttStartedAt + startTime * 1000);
  return [d.getHours(), d.getMinutes(), d.getSeconds()].map((v) => String(v).padStart(2, '0')).join(':');
}

/**
 * '지금 발언' 카드 — PC 실시간 자막 화면에서 **영상 바로 아래**에 놓는다.
 *
 * 2026-08-25 개선안 2e: 예전에는 이것이 자막 목록의 마지막 항목을 키운 것이라,
 * 영상을 보던 눈이 지금 무슨 말이 나오는지 확인하려면 우측 목록 맨 끝까지
 * 내려가야 했다. 목록은 '지나간 발언' 전용으로 두고 현재 발언만 여기로 올린다.
 *
 * 모바일에서는 쓰지 않는다 — 세로 화면에서는 영상 바로 아래가 곧 목록의 끝이라
 * 카드를 하나 더 두면 자막 두 줄을 잡아먹기만 한다.
 */
export default function CurrentUtteranceCard({
  subtitle,
  interimText,
  isLive = false,
  sttStartedAt = null,
  className = '',
}: CurrentUtteranceCardProps) {
  const text = subtitle?.text || interimText;
  if (!text) return null;

  const speaker = subtitle?.speaker?.replace(/^화자\s*/, '') || subtitle?.speaker;

  return (
    <div
      data-testid="current-utterance"
      className={`rounded-lg border border-primary-20 bg-primary-5 px-4 py-3.5 ${className}`.trim()}
    >
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span
          className={`inline-flex items-center gap-1.5 rounded px-1.5 py-0.5 text-[10.5px] font-bold tracking-[0.06em] ${
            isLive ? 'bg-live text-white' : 'bg-gray-200 text-text-secondary'
          }`}
        >
          {isLive && <span className="h-[5px] w-[5px] animate-live-pulse rounded-full bg-white" />}
          지금 발언
        </span>
        {speaker && (
          <span className="rounded-full bg-white px-2.5 py-0.5 text-sm font-bold text-blue-700">
            {speaker}
          </span>
        )}
        {subtitle && (
          <span className="font-mono text-xs text-text-muted">
            {formatElapsed(subtitle.start_time)}
            {sttStartedAt ? ` · ${formatClock(sttStartedAt, subtitle.start_time)}` : ''}
          </span>
        )}
        {!subtitle && interimText && (
          <span className="text-xs text-text-muted">받아쓰는 중…</span>
        )}
      </div>
      <p className="text-xl font-medium leading-relaxed text-text">
        {text}
        {!subtitle && interimText && (
          <span
            className="ml-0.5 inline-block h-5 w-0.5 animate-blink align-middle bg-brand"
            aria-hidden="true"
          />
        )}
      </p>
    </div>
  );
}
