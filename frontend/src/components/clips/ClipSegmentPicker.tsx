'use client';

import React from 'react';

import type { ClipSpeakerType } from '@/types';
import { formatHMS, formatLen } from '@/utils/clipTime';

/**
 * 선택한 의원의 발언 구간 목록 — 행 클릭 = 선택/해제, ▶ = 그 위치 재생.
 * 회색 "의사진행" 항목(named=false: 안건 상정 등)은 기본 해제.
 */
export interface ClipSegmentPickerProps {
  speaker: ClipSpeakerType | null;
  checked: Set<number>;
  onToggle: (idx: number) => void;
  onPreview: (start: number) => void;
  /** 표시·재생용 보정(초) */
  shift: number;
  onSelectAll?: (named: boolean) => void;
}

export default function ClipSegmentPicker({ speaker, checked, onToggle, onPreview, shift, onSelectAll }: ClipSegmentPickerProps) {
  if (!speaker) {
    return (
      <div data-testid="segment-picker-empty" className="text-xs text-text-muted py-3">
        가운데에서 의원을 고르면 발언 구간이 여기에 나타납니다. 의원 목록이 없거나 원하는 구간이 없으면
        위 타임라인에서 시작·종료를 직접 지정해 추출하세요.
      </div>
    );
  }
  const total = speaker.segments
    .filter((s) => checked.has(s.idx))
    .reduce((acc, s) => acc + (s.end - s.start), 0);

  return (
    <div data-testid="segment-picker" className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[14px] font-bold text-text">
          ✂ {speaker.name} {speaker.role || '의원'} 발언 구간
          <span className="ml-2 text-[12px] font-normal text-text-muted">
            선택 {checked.size}/{speaker.segments.length} · {formatLen(total)}
          </span>
        </h3>
        {onSelectAll && (
          <div className="flex gap-1 text-[12px]">
            <button type="button" className="underline text-primary" onClick={() => onSelectAll(true)}>
              발언만
            </button>
            <button type="button" className="underline text-text-muted" onClick={() => onSelectAll(false)}>
              전부
            </button>
          </div>
        )}
      </div>
      <ul className="max-h-56 overflow-y-auto flex flex-col gap-1">
        {speaker.segments.map((seg) => {
          const on = checked.has(seg.idx);
          return (
            <li
              key={seg.idx}
              data-testid="segment-row"
              className={`flex items-center gap-2 rounded-md border px-2 py-1 text-[13px] cursor-pointer ${
                on ? 'border-primary/50 bg-primary/5' : 'border-border bg-white'
              } ${seg.named ? '' : 'text-text-muted'}`}
              onClick={() => onToggle(seg.idx)}
            >
              <input
                type="checkbox"
                checked={on}
                onChange={() => onToggle(seg.idx)}
                onClick={(e) => e.stopPropagation()}
                aria-label={`구간 ${formatHMS(seg.start + shift)} 선택`}
              />
              {/* 번호 = 파일 이름 끝 번호(이름_회의명_번호) — 설치형 목록과 같은 순번 */}
              <span
                data-testid="segment-no"
                title="파일 이름 끝 번호"
                className="tabular-nums text-[12px] font-bold text-text-muted min-w-[22px] text-center rounded bg-gray-100 px-1"
              >
                {seg.idx + 1}
              </span>
              <span className="tabular-nums font-semibold text-primary w-[70px]">{formatHMS(seg.start + shift)}</span>
              <span className="tabular-nums text-text-muted w-[64px]">{formatLen(seg.seconds)}</span>
              <span className="flex-1 truncate">
                {seg.title}
                {!seg.named && <span className="ml-1 text-[11px]">(의사진행)</span>}
              </span>
              <button
                type="button"
                className="rounded border border-border px-1.5 py-0.5 text-[12px] hover:bg-gray-50"
                onClick={(e) => {
                  e.stopPropagation();
                  onPreview(seg.start + shift);
                }}
                title="그 위치 재생"
              >
                ▶ 보기
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
