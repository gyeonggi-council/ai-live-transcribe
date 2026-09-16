'use client';

import React from 'react';

import type { ClipItem } from '@/components/clips/clipJobView';
import ClipThumb from '@/components/clips/ClipThumb';
import type { ClipJobType } from '@/types';
import { formatBytes, formatHMS, formatLen } from '@/utils/clipTime';

/**
 * 클립 한 개 = 카드 한 장. 추출 기록 세 탭이 모두 이 카드를 격자로 깐다(2026-09-16).
 *
 * 그 전에는 `#1 01:29:52 · 1분 28초 · [받기 2.5 MB] · [자막]` 이 한 줄씩 쌓여, 한 회의
 * (의원 12명 × 구간 8개)면 100줄이 똑같이 생긴 목록이 됐다. 어느 줄이 누구의 어느 장면인지
 * 화면만 보고는 알 수 없었다.
 */

export interface ClipFileCardProps {
  job: ClipJobType;
  item: ClipItem;
  /** 이 파일을 모달에서 재생해 확인 */
  onCheck: (item: ClipItem) => void;
  /** 파일 하나 받기 */
  onDownload: (name: string) => void;
  /** 받는 중인 파일 이름 (버튼 잠금) */
  busy?: string | null;
  /** 워크벤치 영상을 이 구간 시작으로 옮긴다 (워크벤치 안에서만) */
  onSeek?: (start: number) => void;
}

export default function ClipFileCard({
  job,
  item,
  onCheck,
  onDownload,
  busy,
  onSeek,
}: ClipFileCardProps) {
  const { file, srt, seg } = item;
  const no = seg?.no ?? item.index + 1;
  const length = seg ? formatLen(seg.end - seg.start) : '';

  return (
    <div
      data-testid="clip-file-card"
      className="flex flex-col gap-1.5 rounded-lg border border-border bg-white p-2"
    >
      <button
        type="button"
        data-testid="clip-file-check-thumb"
        onClick={() => onCheck(item)}
        title={`${file.name} — 눌러서 재생 확인`}
        className="group relative block w-full rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
      >
        <ClipThumb
          meetingId={job.meeting_id}
          jobId={job.job_id}
          fileName={file.name}
          durationLabel={length}
        />
        <span className="pointer-events-none absolute inset-0 flex items-center justify-center rounded-md bg-black/0 text-2xl text-white/0 transition group-hover:bg-black/30 group-hover:text-white/90">
          ▶
        </span>
      </button>

      <div className="flex items-baseline gap-1.5 text-[12px] text-text-muted tabular-nums">
        <span className="font-bold text-text">#{no}</span>
        {seg && <span>{formatHMS(seg.start)}</span>}
      </div>

      <div className="flex flex-wrap items-center gap-1">
        <button
          type="button"
          data-testid="clip-file-check"
          onClick={() => onCheck(item)}
          className="rounded-md border border-border bg-white px-2 py-1 text-[12px] hover:bg-gray-50"
        >
          ▶ 재생 확인
        </button>
        <button
          type="button"
          data-testid="clip-file-download"
          title={file.name}
          onClick={() => onDownload(file.name)}
          disabled={!!busy}
          className="inline-flex items-center gap-1 rounded-md border border-border bg-white px-2 py-1 text-[12px] hover:bg-gray-50 disabled:opacity-50"
        >
          {busy === file.name ? '⏳' : '⬇'} 받기
          <span className="text-text-muted tabular-nums">{formatBytes(file.bytes)}</span>
        </button>
        {srt && (
          <button
            type="button"
            data-testid="clip-file-srt"
            onClick={() => onDownload(srt.name)}
            disabled={!!busy}
            className="text-[11px] text-text-muted underline disabled:opacity-50"
          >
            📄 자막
          </button>
        )}
        {onSeek && seg && (
          <button
            type="button"
            data-testid="auto-clip-preview"
            onClick={() => onSeek(seg.start)}
            className="text-[11px] text-text-muted underline"
          >
            원본에서 보기
          </button>
        )}
      </div>
    </div>
  );
}
