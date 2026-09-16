'use client';

import React from 'react';

import { formatBytes, formatLen } from '@/utils/clipTime';

/** 추출 옵션 — 데스크톱 추출기 #opt-card + #ex-segs 하단 옵션의 웹판 (한 벌만 둔다) */
export interface ClipExtractFormValue {
  padBefore: number;
  padAfter: number;
  merge: boolean;
  withSrt: boolean;
  label: string;
}

export interface ClipExtractFormProps {
  value: ClipExtractFormValue;
  onChange: (v: ClipExtractFormValue) => void;
  /** 선택 구간 총 길이(초) — 예상 용량 표시용 */
  totalSeconds: number;
  segmentCount: number;
  /** 요약 줄에 쓸 의원 이름 (예: "윤충식 위원") — 무엇이 잘리는지 버튼 위에서 읽히게 */
  speakerLabel?: string | null;
  onSubmit: () => void;
  submitting?: boolean;
  disabled?: boolean;
  /** 이 회의에 진행 중인 추출이 있을 때의 버튼 라벨 — 있으면 버튼을 잠근다 (연타 방지, 2026-09-08) */
  busyLabel?: string | null;
  bytesPerSecond?: number;
}

const DEFAULT_BPS = 250_000;

/** 여유 1초·1초 — 담당자 요청(2026-09-08). 키프레임 단위 복사라 어차피 앞뒤 ±수 초가 붙는다 */
export const DEFAULT_EXTRACT_FORM: ClipExtractFormValue = {
  padBefore: 1,
  padAfter: 1,
  merge: false,
  withSrt: true,
  label: '',
};

export default function ClipExtractForm(p: ClipExtractFormProps) {
  const v = p.value;
  const set = (patch: Partial<ClipExtractFormValue>) => p.onChange({ ...v, ...patch });
  const est = (p.totalSeconds + p.segmentCount * (v.padBefore + v.padAfter)) * (p.bytesPerSecond ?? DEFAULT_BPS);
  const num = 'w-14 rounded-md border border-border px-1.5 py-1 text-[13px] text-center tabular-nums';
  const seg =
    'px-2.5 py-1 text-[13px] rounded-md border transition-colors';

  return (
    <form
      data-testid="clip-extract-form"
      className="flex flex-col gap-2 border-t border-border pt-2.5"
      onSubmit={(e) => {
        e.preventDefault();
        if (!p.disabled && !p.submitting && !p.busyLabel) p.onSubmit();
      }}
    >
      <div data-testid="extract-summary" className="text-[13px] text-text">
        {p.segmentCount ? (
          <>
            {p.speakerLabel ? <b>{p.speakerLabel}</b> : null}
            {p.speakerLabel ? ' · ' : ''}선택한 구간 <b>{p.segmentCount}개</b> · 총 {formatLen(p.totalSeconds)}
            <span className="ml-2 text-text-muted">
              앞 여유 {v.padBefore}초 · 뒤 여유 {v.padAfter}초
            </span>
          </>
        ) : (
          <span className="text-text-muted">추출할 구간을 위에서 고르세요</span>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[13px] text-text">
        <label className="flex items-center gap-1">
          앞 여유
          <input
            type="number"
            min={0}
            max={120}
            value={v.padBefore}
            onChange={(e) => set({ padBefore: Math.max(0, Math.min(120, Number(e.target.value) || 0)) })}
            className={num}
            data-testid="pad-before"
          />
          초
        </label>
        <label className="flex items-center gap-1">
          뒤 여유
          <input
            type="number"
            min={0}
            max={120}
            value={v.padAfter}
            onChange={(e) => set({ padAfter: Math.max(0, Math.min(120, Number(e.target.value) || 0)) })}
            className={num}
            data-testid="pad-after"
          />
          초
        </label>
        <div className="inline-flex rounded-md overflow-hidden border border-border" role="group" aria-label="저장 방식">
          <button
            type="button"
            data-testid="merge-on"
            className={`${seg} border-0 ${v.merge ? 'bg-primary text-white' : 'bg-white text-text-muted'}`}
            onClick={() => set({ merge: true })}
          >
            하나로 합치기
          </button>
          <button
            type="button"
            data-testid="merge-off"
            className={`${seg} border-0 border-l border-border ${!v.merge ? 'bg-primary text-white' : 'bg-white text-text-muted'}`}
            onClick={() => set({ merge: false })}
          >
            구간별 저장
          </button>
        </div>
        <label className="flex items-center gap-1.5">
          <input type="checkbox" checked={v.withSrt} onChange={(e) => set({ withSrt: e.target.checked })} data-testid="with-srt" />
          SRT 자막 함께
        </label>
        <label className="flex items-center gap-1 flex-1 min-w-[180px]">
          파일 라벨
          <input
            value={v.label}
            onChange={(e) => set({ label: e.target.value })}
            placeholder="예: 윤충식 (회의명·날짜·시작 시각은 자동으로 붙습니다)"
            className="flex-1 min-w-0 rounded-md border border-border px-2 py-1 text-[13px]"
            data-testid="label-input"
          />
        </label>
      </div>
      <div className="flex items-center gap-3">
        <button
          type="submit"
          data-testid="btn-extract"
          disabled={p.disabled || p.submitting || !!p.busyLabel || p.segmentCount === 0}
          className="inline-flex h-10 items-center justify-center rounded-md bg-primary px-4 text-sm font-semibold text-white hover:bg-primary-dark disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {p.submitting
            ? '요청 중…'
            : p.busyLabel ||
              (p.segmentCount === 0
                ? '✂ 영상 추출하기'
                : v.merge && p.segmentCount > 1
                  ? '✂ 합본 1개 추출하기'
                  : `✂ 영상 ${p.segmentCount}개 추출하기`)}
        </button>
        <span className="text-[12px] text-text-muted">
          총 {formatLen(p.totalSeconds)} · 예상 {formatBytes(est)} · 무손실(키프레임 단위)이라 앞뒤 ±수 초 여유가 생깁니다
        </span>
      </div>
    </form>
  );
}
