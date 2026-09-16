'use client';

import React, { useState } from 'react';

import { SOURCE_LABEL } from '@/components/clips/SpeakerPicker';
import { logAccess } from '@/hooks/useAccessLog';
import { useClipJobs } from '@/hooks/useClipJobs';
import { deleteClipJob, downloadClipJobFile } from '@/lib/api';
import type { ClipJobType } from '@/types';
import { formatBytes, formatLen } from '@/utils/clipTime';

/**
 * 추출 기록 — 진행 중 잡의 진행률 + 완료 잡의 재다운로드(7일) + 삭제.
 * 진행 중 잡이 있으면 useClipJobs 가 3초마다 다시 읽는다.
 */
export interface ClipJobsPanelProps {
  scope?: 'mine' | 'all';
  meetingId?: string | null;
  /** 회의 화면 안의 작은 패널(제목·저장소 막대 생략) */
  compact?: boolean;
  days?: number;
}

const STATUS_LABEL: Record<string, string> = {
  queued: '대기',
  running: '추출 중',
  done: '완료',
  failed: '실패',
  cancelled: '취소됨',
  expired: '삭제됨',
};

const EVICT_LABEL: Record<string, string> = {
  ttl: '보존 기간(7일) 지남',
  capacity: '저장 공간 부족으로 오래된 것부터 삭제',
  manual: '사용자가 삭제',
  restart: '서버 재시작으로 중단',
};

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function JobRow({
  job,
  showMeeting,
  onChanged,
}: {
  job: ClipJobType;
  showMeeting: boolean;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const active = job.status === 'queued' || job.status === 'running';

  const download = async (name: string) => {
    logAccess('download', { meetingId: job.meeting_id });  // 접속 통계(2026-09-16)
    setBusy(name);
    setErr(null);
    try {
      await downloadClipJobFile(job.meeting_id, job.job_id, name);
    } catch (e) {
      setErr(e instanceof Error ? e.message : '다운로드 실패');
      onChanged();
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    setBusy('delete');
    try {
      await deleteClipJob(job.meeting_id, job.job_id);
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : '삭제 실패');
    } finally {
      setBusy(null);
    }
  };

  return (
    <li data-testid="clip-job-row" className="rounded-lg border border-border bg-white p-2 text-[13px] flex flex-col gap-1">
      <div className="flex items-center gap-2 flex-wrap">
        <span
          data-testid="clip-job-status"
          className={`rounded px-1.5 py-0.5 text-[11px] font-semibold ${
            job.status === 'done'
              ? 'bg-green-100 text-green-800'
              : active
                ? 'bg-blue-100 text-blue-800'
                : job.status === 'expired'
                  ? 'bg-gray-100 text-gray-600'
                  : 'bg-red-100 text-red-800'
          }`}
        >
          {STATUS_LABEL[job.status] ?? job.status}
        </span>
        <span className="font-semibold text-text truncate">{job.label || '클립'}</span>
        <span className="text-[11px] text-text-muted">{SOURCE_LABEL[job.source_kind] ?? job.source_kind}</span>
        <span className="text-[11px] text-text-muted tabular-nums">
          {job.segment_count}구간 · {formatLen(job.total_seconds)}
          {job.bytes_total > 0 && ` · ${formatBytes(job.bytes_total)}`}
        </span>
        <span className="ml-auto text-[11px] text-text-muted tabular-nums">{fmtDate(job.created_at)}</span>
      </div>
      {showMeeting && job.meeting_title && (
        <div className="text-[12px] text-text-muted truncate">
          {job.meeting_title} {job.meeting_date ? `(${job.meeting_date})` : ''}
          {job.owner_username ? ` · ${job.owner_username}` : ''}
        </div>
      )}
      {active && (
        <div className="flex items-center gap-2">
          <div className="flex-1 h-2 rounded bg-gray-200 overflow-hidden">
            {/* 진행률은 구간 단위라 1구간 잡은 끝날 때까지 0 — 그동안은 움직이는 막대로 "돌고 있다" 를 보인다 */}
            {job.status === 'running' && !(job.progress > 0) ? (
              <div data-testid="clip-job-progress-indeterminate" className="h-full w-full bg-primary/60 animate-pulse" />
            ) : (
              <div
                data-testid="clip-job-progress"
                className="h-full bg-primary transition-all"
                style={{ width: `${Math.round((job.progress || 0) * 100)}%` }}
              />
            )}
          </div>
          <span className="text-[11px] text-text-muted tabular-nums w-24 text-right">
            {job.status !== 'running'
              ? '대기 중'
              : job.progress > 0
                ? `${Math.round(job.progress * 100)}%${job.current_segment ? ` · ${job.current_segment}/${job.segment_count}` : ''}`
                : `추출 중…${job.segment_count > 1 && job.current_segment ? ` ${job.current_segment}/${job.segment_count}` : ''}`}
          </span>
          <button type="button" className="text-[11px] underline text-text-muted" onClick={remove} disabled={busy !== null}>
            중지
          </button>
        </div>
      )}
      {job.status === 'done' && (
        <div className="flex flex-wrap items-center gap-1">
          {job.files.map((f) => (
            <button
              key={f.name}
              type="button"
              data-testid="clip-job-download"
              onClick={() => download(f.name)}
              disabled={busy !== null}
              title={f.name}
              className="inline-flex items-center gap-1 rounded-md border border-border bg-white px-2 py-1 text-[12px] hover:bg-gray-50 disabled:opacity-50 max-w-full"
            >
              {busy === f.name ? '⏳' : f.kind === 'srt' ? '📄' : '⬇'}
              <span className="truncate max-w-[260px]">{f.name}</span>
              <span className="text-text-muted">{formatBytes(f.bytes)}</span>
            </button>
          ))}
          <span className="text-[11px] text-text-muted ml-auto">
            {job.expires_at ? `${fmtDate(job.expires_at)}까지 보관` : ''}
          </span>
          <button type="button" className="text-[11px] underline text-text-muted" onClick={remove} disabled={busy !== null}>
            삭제
          </button>
        </div>
      )}
      {job.status === 'failed' && <div className="text-[12px] text-red-700">{job.error || '추출에 실패했습니다.'}</div>}
      {job.status === 'expired' && (
        <div data-testid="clip-job-evicted" className="text-[12px] text-text-muted">
          {EVICT_LABEL[job.evicted_reason ?? ''] ?? '파일이 삭제되었습니다'} — 필요하면 다시 추출하세요.
        </div>
      )}
      {err && <div className="text-[12px] text-red-700">{err}</div>}
    </li>
  );
}

export default function ClipJobsPanel({ scope = 'mine', meetingId, compact, days = 7 }: ClipJobsPanelProps) {
  const { jobs, store, isLoading, error, refresh } = useClipJobs({ scope, meetingId, days });
  const usedPct = store && store.max_bytes > 0 ? Math.min(100, Math.round((store.used_bytes / store.max_bytes) * 100)) : 0;

  return (
    <section data-testid="clip-jobs-panel" className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[14px] font-bold text-text">
          {compact ? '이 회의의 추출 기록' : `추출 기록 (최근 ${days}일)`}
          <span className="ml-2 text-[12px] font-normal text-text-muted">{jobs.length}건</span>
        </h3>
        <button type="button" className="text-[12px] underline text-text-muted" onClick={refresh}>
          새로고침
        </button>
      </div>
      {!compact && store && (
        <div className="text-[12px] text-text-muted flex items-center gap-2">
          <div className="flex-1 h-1.5 rounded bg-gray-200 overflow-hidden">
            <div className={`h-full ${usedPct > 85 ? 'bg-red-500' : 'bg-primary'}`} style={{ width: `${usedPct}%` }} />
          </div>
          <span className="tabular-nums" data-testid="clip-store-usage">
            저장 공간 {formatBytes(store.used_bytes)} / {formatBytes(store.max_bytes)} · {store.ttl_days}일 보관
          </span>
        </div>
      )}
      {error && <div className="text-[12px] text-red-700">기록을 불러오지 못했습니다: {error.message}</div>}
      {isLoading && !jobs.length && <div className="text-[12px] text-text-muted">불러오는 중…</div>}
      {!isLoading && !jobs.length && !error && (
        <div data-testid="clip-jobs-empty" className="text-[12px] text-text-muted">아직 추출한 클립이 없습니다.</div>
      )}
      <ul className="flex flex-col gap-1.5">
        {jobs.map((j) => (
          <JobRow key={j.job_id} job={j} showMeeting={!compact} onChanged={refresh} />
        ))}
      </ul>
    </section>
  );
}
