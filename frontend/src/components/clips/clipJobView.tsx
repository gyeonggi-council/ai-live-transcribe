'use client';

import React from 'react';

import type { ClipJobFileType, ClipJobType } from '@/types';

/**
 * 추출 기록 세 탭(내 기록 · 자동 클립 · 전체)이 **같은 말과 같은 색**을 쓰게 하는 공용 조각.
 *
 * 2026-09-16 이전에는 AutoClipsPanel 과 ClipJobsPanel 이 상태 라벨·색·파일 짝짓기를 각자
 * 복사해 갖고 있었고, 그래서 같은 `done` 이 한쪽은 「준비됨」 다른 쪽은 「완료」였다.
 * 탭만 옮겼는데 말이 달라지면 담당자는 다른 것을 보고 있다고 생각한다.
 */

export const STATUS_LABEL: Record<string, string> = {
  queued: '자르기 대기',
  running: '자르는 중',
  done: '준비됨',
  failed: '실패',
  cancelled: '취소됨',
  expired: '보관 끝남',
};

export const EVICT_LABEL: Record<string, string> = {
  ttl: '보관 기간이 지나 지웠습니다',
  capacity: '저장 공간이 모자라 오래된 것부터 지웠습니다',
  manual: '사용자가 지웠습니다',
  restart: '서버가 다시 시작돼 중단됐습니다',
};

export function isActiveStatus(status: string): boolean {
  return status === 'queued' || status === 'running';
}

/** 'M월 D일 HH:MM' — 목록은 최근 3~7일치라 연도를 적지 않는다 */
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('ko-KR', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** 'HH:MM' — 같은 줄에서 요청 뒤에 오는 완료 시각은 시·분만 */
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
}

export function ClipStatusBadge({ job }: { job: ClipJobType }) {
  const active = isActiveStatus(job.status);
  const tone =
    job.status === 'done'
      ? 'bg-green-100 text-green-800'
      : active
        ? 'bg-blue-100 text-blue-800'
        : job.status === 'expired' || job.status === 'cancelled'
          ? 'bg-gray-100 text-gray-600'
          : 'bg-red-100 text-red-800';
  return (
    <span
      data-testid="clip-job-status"
      className={`rounded px-1.5 py-0.5 text-[11px] font-semibold ${tone}`}
    >
      {STATUS_LABEL[job.status] ?? job.status}
      {job.status === 'running' && job.segment_count > 1 && job.current_segment
        ? ` ${job.current_segment}/${job.segment_count}`
        : ''}
    </span>
  );
}

/**
 * 「요청 9. 14. 11:32 · 완료 11:47」 — 사용자가 요청한 **추출을 요청한 시각**(2026-09-16).
 * 자동 클립은 서버가 큐에 넣은 시각이 곧 요청 시각이다(`created_at`).
 */
export function ClipJobTimes({ job }: { job: ClipJobType }) {
  const requested = fmtDateTime(job.created_at);
  if (!requested) return null;
  let tail = '';
  if (job.status === 'done' || job.status === 'failed') {
    const done = fmtTime(job.finished_at);
    if (done) tail = job.status === 'done' ? ` · 완료 ${done}` : ` · 중단 ${done}`;
  } else if (job.status === 'running') {
    tail = ' · 자르는 중';
  } else if (job.status === 'queued') {
    tail = ' · 순서 기다리는 중';
  }
  return (
    <span data-testid="clip-requested-at" className="text-[11px] text-text-muted tabular-nums">
      요청 {requested}
      {tail}
    </span>
  );
}

export interface ClipItem {
  file: ClipJobFileType;
  srt?: ClipJobFileType;
  seg?: { start: number; end: number; no?: number };
  /** 그 잡의 mp4 목록 안 순번 — 썸네일 인덱스와 같다 */
  index: number;
}

/**
 * 구간별 파일(merge=false) — mp4 가 구간 순서대로 놓이고 같은 이름의 srt 가 짝이다.
 * 서버의 썸네일 라우트도 **mp4 목록 안 순번**으로 인덱스를 매기므로 둘이 어긋나지 않는다.
 */
export function itemsOf(job: ClipJobType): ClipItem[] {
  const files = job.files ?? [];
  return files
    .filter((f) => f.kind === 'mp4')
    .map((f, i) => ({
      file: f,
      srt: files.find(
        (x) => x.kind === 'srt' && x.name.replace(/\.srt$/i, '') === f.name.replace(/\.mp4$/i, '')
      ),
      seg: job.segments?.[i],
      index: i,
    }));
}

/** mp4 와 짝지어지지 않은 srt (합본 잡 등) — 카드 밖에 따로 내보인다 */
export function looseSrtOf(job: ClipJobType, items: ClipItem[]): ClipJobFileType[] {
  const paired = new Set(items.map((it) => it.srt?.name).filter(Boolean) as string[]);
  return (job.files ?? []).filter((f) => f.kind === 'srt' && !paired.has(f.name));
}
