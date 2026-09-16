'use client';

import React, { useCallback, useRef } from 'react';

import { formatHMS } from '@/utils/clipTime';

/**
 * 클립 타임라인 — 데스크톱 추출기 app.html 의 #tl(updateTl/bindHandleDrag) 이식
 *
 * - 막대 클릭 = 그 위치로 시크
 * - 선택 의원의 발언 구간 = 빨간 눈금(선택 중인 구간은 진하게)
 * - 초록(시작)·빨강(종료) 핸들 드래그 = 수동 자르기 구간 미세조정
 *   (핸들은 stopPropagation 으로 막대 시킹과 충돌하지 않는다)
 */
export interface ClipTimelineMark {
  start: number;
  end: number;
  active?: boolean;
}

export interface ClipTimelineProps {
  duration: number;
  currentTime: number;
  selStart: number;
  selEnd: number;
  marks: ClipTimelineMark[];
  onSeek: (sec: number) => void;
  onChangeSelection: (sel: { start: number; end: number }) => void;
}

function pct(t: number, d: number): number {
  if (!d || d <= 0) return 0;
  return Math.min(100, Math.max(0, (t / d) * 100));
}

export default function ClipTimeline({
  duration,
  currentTime,
  selStart,
  selEnd,
  marks,
  onSeek,
  onChangeSelection,
}: ClipTimelineProps) {
  const barRef = useRef<HTMLDivElement>(null);

  const timeAtClientX = useCallback(
    (clientX: number): number => {
      const el = barRef.current;
      if (!el || !duration || !Number.isFinite(clientX)) return 0;
      const rect = el.getBoundingClientRect();
      const ratio = rect.width > 0 ? (clientX - rect.left) / rect.width : 0;
      return Math.min(duration, Math.max(0, ratio * duration));
    },
    [duration]
  );

  const handleBarClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!duration) return;
    onSeek(timeAtClientX(e.clientX));
  };

  const beginDrag = (which: 'start' | 'end') => (e: React.PointerEvent<HTMLDivElement>) => {
    e.stopPropagation();
    e.preventDefault();
    const target = e.currentTarget;
    try {
      target.setPointerCapture(e.pointerId);
    } catch {
      /* jsdom 등 */
    }
    const move = (ev: PointerEvent) => {
      const t = timeAtClientX(ev.clientX);
      if (which === 'start') {
        onChangeSelection({ start: Math.min(t, selEnd), end: selEnd });
      } else {
        onChangeSelection({ start: selStart, end: Math.max(t, selStart) });
      }
    };
    const up = () => {
      target.removeEventListener('pointermove', move);
      target.removeEventListener('pointerup', up);
      target.removeEventListener('pointercancel', up);
    };
    target.addEventListener('pointermove', move);
    target.addEventListener('pointerup', up);
    target.addEventListener('pointercancel', up);
  };

  const hasSel = duration > 0 && selEnd > selStart;

  return (
    <div data-testid="clip-timeline" className="select-none">
      <div
        ref={barRef}
        data-testid="clip-timeline-bar"
        role="slider"
        aria-label="영상 위치"
        aria-valuemin={0}
        aria-valuemax={Math.floor(duration || 0)}
        aria-valuenow={Math.floor(currentTime || 0)}
        tabIndex={-1}
        onClick={handleBarClick}
        className="relative h-9 rounded-lg bg-gray-200 cursor-pointer overflow-visible"
      >
        {/* 발언 구간 눈금 */}
        {marks.map((m, i) => (
          <div
            key={`${m.start}-${m.end}-${i}`}
            data-testid="clip-timeline-mark"
            className={`absolute top-1 bottom-1 rounded-sm ${
              m.active ? 'bg-red-500/80' : 'bg-red-300/60'
            }`}
            style={{
              left: `${pct(m.start, duration)}%`,
              width: `${Math.max(0.4, pct(m.end, duration) - pct(m.start, duration))}%`,
            }}
          />
        ))}
        {/* 선택 구간 */}
        {hasSel && (
          <div
            data-testid="clip-timeline-selection"
            className="absolute top-0 bottom-0 bg-primary/25 border-x-2 border-primary/60"
            style={{
              left: `${pct(selStart, duration)}%`,
              width: `${pct(selEnd, duration) - pct(selStart, duration)}%`,
            }}
          />
        )}
        {/* 현재 위치 */}
        <div
          data-testid="clip-timeline-cursor"
          className="absolute top-0 bottom-0 w-0.5 bg-gray-900"
          style={{ left: `${pct(currentTime, duration)}%` }}
        />
        {/* 핸들 */}
        {hasSel && (
          <>
            <div
              data-testid="clip-handle-start"
              title="구간 시작 — 드래그로 조절"
              onPointerDown={beginDrag('start')}
              onClick={(e) => e.stopPropagation()}
              className="absolute -top-1 -bottom-1 w-3 -ml-1.5 rounded bg-green-600 cursor-ew-resize shadow"
              style={{ left: `${pct(selStart, duration)}%` }}
            />
            <div
              data-testid="clip-handle-end"
              title="구간 종료 — 드래그로 조절"
              onPointerDown={beginDrag('end')}
              onClick={(e) => e.stopPropagation()}
              className="absolute -top-1 -bottom-1 w-3 -ml-1.5 rounded bg-red-600 cursor-ew-resize shadow"
              style={{ left: `${pct(selEnd, duration)}%` }}
            />
          </>
        )}
      </div>
      <div className="flex justify-between text-[11px] text-text-muted tabular-nums mt-1">
        <span>00:00:00</span>
        <span data-testid="clip-timeline-current">{formatHMS(currentTime)}</span>
        <span>{formatHMS(duration)}</span>
      </div>
    </div>
  );
}
