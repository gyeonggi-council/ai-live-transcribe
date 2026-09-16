'use client';

import React, { useEffect, useState } from 'react';

import { formatHMS, formatLen, parseHMS } from '@/utils/clipTime';

/**
 * 오른쪽 세로 컨트롤 레일 — 4:3 영상 옆 빈 자리에 이동·마킹을 모은다.
 *
 * 담당자 요청(2026-09-03): 버튼 7개 + 단축키 안내 한 줄이 화면을 너무 먹었다.
 * → 단축키를 버튼 라벨에 넣고 안내 줄은 없앤다. 시작·종료 지정이 핵심 동작이다.
 */
export interface ClipControlRailProps {
  currentTime: number;
  duration: number;
  isPaused: boolean;
  selStart: number;
  selEnd: number;
  onSeekRel: (sec: number) => void;
  onSeekTo: (sec: number) => void;
  onFrameStep: (n: 1 | -1) => void;
  onTogglePlay: () => void;
  onMarkStart: () => void;
  onMarkEnd: () => void;
  onEditStart: (sec: number) => void;
  onEditEnd: (sec: number) => void;
  onPlaySelection: () => void;
  onExtractSelection: () => void;
  extractDisabled?: boolean;
  extractLabel?: string;
}

const btnBase =
  'inline-flex items-center justify-center gap-1 rounded-md border px-2 py-1.5 text-[13px] font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-40';
const btn = `${btnBase} border-border bg-white text-text hover:bg-gray-50 active:bg-gray-100`;
// 주 버튼은 따로 쓴다 — btn 뒤에 bg-primary·text-white 를 덧붙이면 둘 다 같은 속성이라 CSS 순서로 이기는 쪽이 정해져
// bg-white + text-white(흰 바탕에 흰 글씨)가 되어 「이 구간 추출」 글자가 사라졌다(2026-09-11 담당자 화면)
const btnPrimary = `${btnBase} border-primary bg-primary text-white hover:bg-primary-dark`;
const kbd = 'rounded border border-gray-300 bg-gray-100 px-1 text-[11px] font-semibold text-gray-600';

function TimeField({
  label,
  testId,
  value,
  onCommit,
  tone,
}: {
  label: string;
  testId: string;
  value: number;
  onCommit: (sec: number) => void;
  tone: 'start' | 'end';
}) {
  const [text, setText] = useState(formatHMS(value));
  useEffect(() => setText(formatHMS(value)), [value]);
  const commit = () => {
    const t = parseHMS(text);
    if (t === null) {
      setText(formatHMS(value));
      return;
    }
    onCommit(t);
  };
  return (
    <label className="flex items-center gap-1.5 text-[12px] text-text-muted">
      <span className={`w-7 font-semibold ${tone === 'start' ? 'text-green-700' : 'text-red-700'}`}>
        {label}
      </span>
      <input
        data-testid={testId}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            commit();
            (e.target as HTMLInputElement).blur();
          }
        }}
        className={`w-[92px] rounded-md border px-1.5 py-1 text-[13px] tabular-nums font-semibold text-center ${
          tone === 'start' ? 'border-green-300 bg-green-50 text-green-800' : 'border-red-300 bg-red-50 text-red-800'
        }`}
      />
    </label>
  );
}

export default function ClipControlRail(p: ClipControlRailProps) {
  const [jump, setJump] = useState('');
  const len = Math.max(0, p.selEnd - p.selStart);

  const doJump = () => {
    const t = parseHMS(jump);
    if (t === null) return;
    p.onSeekTo(t);
    setJump('');
  };

  return (
    <div data-testid="clip-control-rail" className="flex flex-col gap-2 text-sm">
      {/* 시각 입력 이동 — "몇 분쯤"을 아는 사람이 바로 뛰어간다 */}
      <div className="flex items-center gap-1">
        <input
          data-testid="jump-input"
          value={jump}
          placeholder="시:분:초 입력 후 Enter"
          onChange={(e) => setJump(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && doJump()}
          className="flex-1 min-w-0 rounded-md border border-border px-2 py-1.5 text-[13px]"
        />
        <button type="button" className={btn} onClick={doJump} title="입력한 시각으로 이동">
          이동
        </button>
      </div>

      {/* 이동 버튼 — 단축키를 라벨에 */}
      <div className="grid grid-cols-2 gap-1">
        <button type="button" className={btn} onClick={() => p.onSeekRel(-60)} title="1분 뒤로">
          <kbd className={kbd}>PgUp</kbd> -1분
        </button>
        <button type="button" className={btn} onClick={() => p.onSeekRel(60)} title="1분 앞으로">
          +1분 <kbd className={kbd}>PgDn</kbd>
        </button>
        <button type="button" className={btn} onClick={() => p.onSeekRel(-5)} title="5초 뒤로">
          <kbd className={kbd}>←</kbd> -5초
        </button>
        <button type="button" className={btn} onClick={() => p.onSeekRel(5)} title="5초 앞으로">
          +5초 <kbd className={kbd}>→</kbd>
        </button>
        <button type="button" className={btn} onClick={() => p.onSeekRel(-1)} title="1초 뒤로">
          <kbd className={kbd}>↑</kbd> -1초
        </button>
        <button type="button" className={btn} onClick={() => p.onSeekRel(1)} title="1초 앞으로">
          +1초 <kbd className={kbd}>↓</kbd>
        </button>
        <button type="button" className={btn} onClick={() => p.onFrameStep(-1)} title="한 프레임 뒤로">
          <kbd className={kbd}>,</kbd> ◀프레임
        </button>
        <button type="button" className={btn} onClick={() => p.onFrameStep(1)} title="한 프레임 앞으로">
          프레임▶ <kbd className={kbd}>.</kbd>
        </button>
      </div>
      <button
        type="button"
        data-testid="btn-play"
        className={`${btn} py-2 text-[14px]`}
        onClick={p.onTogglePlay}
        title="재생/정지"
      >
        {p.isPaused ? '▶ 재생' : '❚❚ 정지'} <kbd className={kbd}>Space</kbd>
      </button>

      {/* 시작·종료 마킹 */}
      <div className="mt-1 rounded-lg border border-border bg-surface p-2 flex flex-col gap-1.5">
        <div className="flex items-center gap-1">
          <TimeField label="시작" testId="sel-start" value={p.selStart} onCommit={p.onEditStart} tone="start" />
          <button
            type="button"
            data-testid="btn-mark-start"
            className={`${btn} flex-1`}
            onClick={p.onMarkStart}
            title="현재 재생 위치를 시작으로"
          >
            현재 위치 <kbd className={kbd}>[</kbd>
          </button>
        </div>
        <div className="flex items-center gap-1">
          <TimeField label="종료" testId="sel-end" value={p.selEnd} onCommit={p.onEditEnd} tone="end" />
          <button
            type="button"
            data-testid="btn-mark-end"
            className={`${btn} flex-1`}
            onClick={p.onMarkEnd}
            title="현재 재생 위치를 종료로"
          >
            현재 위치 <kbd className={kbd}>]</kbd>
          </button>
        </div>
        <div className="flex items-center justify-between text-[12px] text-text-muted px-0.5">
          <span>
            구간 길이 <b data-testid="sel-length" className="text-text">{formatLen(len)}</b>
          </span>
          <span className="tabular-nums">지금 {formatHMS(p.currentTime)}</span>
        </div>
        <div className="grid grid-cols-2 gap-1">
          <button type="button" className={btn} onClick={p.onPlaySelection} disabled={len <= 0}>
            ▶ 구간 재생
          </button>
          <button
            type="button"
            data-testid="btn-extract-selection"
            className={btnPrimary}
            onClick={p.onExtractSelection}
            disabled={p.extractDisabled || len < 0.3}
          >
            ✂ {p.extractLabel ?? '이 구간 추출'}
          </button>
        </div>
      </div>
    </div>
  );
}
