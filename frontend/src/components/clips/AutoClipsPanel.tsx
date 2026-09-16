'use client';

import React, { useMemo, useState } from 'react';

import ClipFileCard from '@/components/clips/ClipFileCard';
import {
  ClipJobTimes,
  ClipStatusBadge,
  EVICT_LABEL,
  isActiveStatus,
  itemsOf,
  type ClipItem,
} from '@/components/clips/clipJobView';
import ClipPreviewModal, { type ClipPreviewTarget } from '@/components/clips/ClipPreviewModal';
import { useAutoClips } from '@/hooks/useAutoClips';
import { downloadClipJobFile } from '@/lib/api';
import type { ClipJobType } from '@/types';
import { formatBytes, formatLen } from '@/utils/clipTime';

/**
 * 자동으로 잘라 둔 영상 — AI 자막이 끝난 회의의 의원 전원 영상을 서버가 720p 로 미리 잘라 둔다(2026-09-10 사용자 결정).
 *
 * 「확인 후 추출」 없이 받기만 하면 된다. 다만 의원 구간 정확도가 99% 가 아니라(392회 위원회 전수 약 81%)
 * 공유 전에 한 번 재생해 보라는 안내를 늘 붙인다(사용자 선택). 파일 이름은 워크벤치·설치형과 같다
 * (이름_회의명_번호.mp4) — 담당자가 세 경로로 받은 파일을 한 폴더에 모은다.
 *
 * 2026-09-16 — 썸네일 격자 + 요청 시각 + 받기 전 재생 확인 모달(사용자 요청). 화면 조각은
 * `ClipFileCard`·`ClipThumb`·`ClipPreviewModal` 에 있고 「내 기록」·「전체」 탭과 공유한다.
 */
export interface AutoClipsPanelProps {
  /** 있으면 그 회의 것만(없으면 자리를 차지하지 않는다). 없으면 최근 days 일 전체를 회의별로 */
  meetingId?: string | null;
  /** 있으면 그 의원 것만 */
  speakerName?: string | null;
  days?: number;
  /** 워크벤치 영상을 그 구간 시작으로 옮긴다 */
  onPreview?: (start: number) => void;
}

const DEFAULT_NOTICE =
  'AI 가 자막으로 찾은 구간을 자동으로 자른 영상입니다. 드물게 다른 사람의 발언이 섞일 수 있으니 공유하기 전에 한 번 재생해 확인해 주세요.';

function AutoJob({
  job,
  showSpeaker,
  compactGrid,
  onPreview,
  onCheck,
}: {
  job: ClipJobType;
  showSpeaker: boolean;
  compactGrid: boolean;
  onPreview?: (start: number) => void;
  onCheck: (job: ClipJobType, item: ClipItem) => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const items = itemsOf(job);
  const active = isActiveStatus(job.status);

  const download = async (name: string) => {
    setBusy(name);
    setErr(null);
    try {
      await downloadClipJobFile(job.meeting_id, job.job_id, name);
    } catch (e) {
      setErr(e instanceof Error ? e.message : '다운로드 실패');
    } finally {
      setBusy(null);
    }
  };
  const downloadAll = async () => {
    for (const it of items) {
      // 한 번에 하나씩 — 브라우저가 여러 파일 동시 저장을 막는 경우가 있다
      await download(it.file.name);
    }
  };

  return (
    <li
      data-testid="auto-clip-job"
      className="flex flex-col gap-1.5 rounded-lg border border-border bg-white p-2.5 text-[13px]"
    >
      <div className="flex flex-wrap items-center gap-2">
        {showSpeaker && <span className="font-semibold text-text">{job.speaker_name || job.label}</span>}
        <span data-testid="auto-clip-status">
          <ClipStatusBadge job={job} />
        </span>
        <span className="text-[11px] text-text-muted tabular-nums">
          {job.segment_count}구간 · {formatLen(job.total_seconds)}
          {job.bytes_total > 0 && ` · ${formatBytes(job.bytes_total)}`}
        </span>
        <ClipJobTimes job={job} />
        {job.status === 'done' && items.length > 1 && (
          <button
            type="button"
            data-testid="auto-clip-download-all"
            onClick={downloadAll}
            disabled={busy !== null}
            className="ml-auto rounded-md border border-border bg-white px-2 py-1 text-[12px] hover:bg-gray-50 disabled:opacity-50"
          >
            ⬇ 전부 받기
          </button>
        )}
      </div>

      {active && (
        <div className="h-1.5 overflow-hidden rounded bg-gray-200">
          {job.status === 'running' && job.progress > 0 ? (
            <div className="h-full bg-primary transition-all" style={{ width: `${Math.round(job.progress * 100)}%` }} />
          ) : (
            <div className={`h-full w-full ${job.status === 'running' ? 'bg-primary/60 animate-pulse' : 'bg-gray-300'}`} />
          )}
        </div>
      )}

      {job.status === 'done' && (
        <div
          data-testid="clip-file-grid"
          className={`grid gap-2 ${
            compactGrid ? 'grid-cols-2' : 'grid-cols-2 sm:grid-cols-3 lg:grid-cols-4'
          }`}
        >
          {items.map((it) => (
            <ClipFileCard
              key={it.file.name}
              job={job}
              item={it}
              onCheck={(x) => onCheck(job, x)}
              onDownload={download}
              busy={busy}
              onSeek={onPreview}
            />
          ))}
        </div>
      )}

      {job.status === 'failed' && <div className="text-[12px] text-red-700">{job.error || '자르지 못했습니다.'}</div>}
      {job.status === 'expired' && (
        <div className="text-[12px] text-text-muted">
          {EVICT_LABEL[job.evicted_reason ?? ''] ?? '파일이 지워졌습니다'} — 필요하면 아래에서 직접 자르세요.
        </div>
      )}
      {err && <div className="text-[12px] text-red-700">{err}</div>}
    </li>
  );
}

export default function AutoClipsPanel({ meetingId = null, speakerName = null, days = 3, onPreview }: AutoClipsPanelProps) {
  const { jobs, notice, ttlDays, isLoading, error } = useAutoClips({ meetingId, days });
  const [target, setTarget] = useState<ClipPreviewTarget | null>(null);
  const shown = useMemo(
    () => (speakerName ? jobs.filter((j) => (j.speaker_name || j.label) === speakerName) : jobs),
    [jobs, speakerName]
  );
  // 최근 목록은 회의별로 묶는다(최근 회의 먼저)
  const groups = useMemo(() => {
    if (meetingId) return [];
    const by = new Map<string, { title: string; date: string; jobs: ClipJobType[] }>();
    for (const j of shown) {
      const g = by.get(j.meeting_id) ?? { title: j.meeting_title || '회의', date: j.meeting_date || '', jobs: [] };
      g.jobs.push(j);
      by.set(j.meeting_id, g);
    }
    return Array.from(by.entries())
      .map(([id, g]) => ({ id, ...g, jobs: [...g.jobs].sort((a, b) => (a.speaker_name || '').localeCompare(b.speaker_name || '', 'ko')) }))
      .sort((a, b) => b.date.localeCompare(a.date));
  }, [meetingId, shown]);

  // 이 회의에 자동 클립이 하나도 없으면(옛 회의·AI 자막 전) 자리를 차지하지 않는다
  if (meetingId && !jobs.length) return null;

  const people = new Set(shown.map((j) => j.speaker_name || j.label)).size;
  // 워크벤치 안(회의 지정)은 좁은 자리라 격자를 2열로 낮춘다
  const compactGrid = !!meetingId;

  const check = (job: ClipJobType, item: ClipItem) =>
    setTarget({
      job,
      fileName: item.file.name,
      bytes: item.file.bytes,
      no: item.seg?.no ?? item.index + 1,
      seg: item.seg,
    });

  const renderJobs = (list: ClipJobType[], showSpeaker: boolean) => (
    <ul className="flex flex-col gap-1.5">
      {list.map((j) => (
        <AutoJob
          key={j.job_id}
          job={j}
          showSpeaker={showSpeaker}
          compactGrid={compactGrid}
          onPreview={onPreview}
          onCheck={check}
        />
      ))}
    </ul>
  );

  return (
    <section
      data-testid="auto-clips-panel"
      className="flex flex-col gap-2 rounded-lg border border-warning-bg/40 bg-warning-bg/10 p-3"
    >
      <div className="flex flex-wrap items-baseline gap-2">
        <h3 className="text-[14px] font-bold text-text">🎬 자동으로 잘라 둔 영상</h3>
        <span className="text-[12px] text-text-muted">
          {meetingId ? `${people}명` : `최근 ${days}일 · ${groups.length}회의`}
          {ttlDays ? ` · ${ttlDays}일 보관` : ''} · 720p(공유용)
        </span>
      </div>
      <p data-testid="auto-clips-notice" className="text-[12px] leading-relaxed text-warning-dark">
        ⚠ {notice || DEFAULT_NOTICE} 썸네일이나 「▶ 재생 확인」을 누르면 받기 전에 이 화면에서 볼 수 있습니다.
      </p>
      {error && <div className="text-[12px] text-red-700">자동 클립을 불러오지 못했습니다: {error.message}</div>}
      {isLoading && !jobs.length && <div className="text-[12px] text-text-muted">불러오는 중…</div>}
      {!meetingId && !isLoading && !error && !jobs.length && (
        <div data-testid="auto-clips-empty" className="text-[12px] text-text-muted">
          최근 {days}일 동안 자동으로 자른 영상이 없습니다. AI 자막이 끝난 회의는 30분 안에 자르기 시작합니다.
        </div>
      )}
      {speakerName && !shown.length && (
        <div data-testid="auto-clips-none-for-speaker" className="text-[12px] text-text-muted">
          이 의원의 자동 영상은 없습니다 — 아래 「확인 후 추출」에서 직접 자를 수 있습니다.
        </div>
      )}
      {meetingId
        ? renderJobs(shown, !speakerName)
        : groups.map((g) => {
            const clips = g.jobs.reduce((n, j) => n + j.segment_count, 0);
            const bytes = g.jobs.reduce((n, j) => n + (j.bytes_total || 0), 0);
            return (
              <div
                key={g.id}
                data-testid="auto-clips-meeting"
                className="flex flex-col gap-1.5 rounded-lg border border-border bg-white/70 p-2"
              >
                <div className="flex flex-wrap items-baseline gap-2 border-b border-border pb-1.5">
                  <span className="text-[13px] font-semibold text-text">{g.title}</span>
                  {g.date && <span className="text-[12px] text-text-muted">({g.date})</span>}
                  <span className="ml-auto text-[11px] text-text-muted tabular-nums">
                    의원 {g.jobs.length}명 · 영상 {clips}개{bytes > 0 ? ` · ${formatBytes(bytes)}` : ''}
                  </span>
                </div>
                {renderJobs(g.jobs, true)}
              </div>
            );
          })}
      <ClipPreviewModal target={target} onClose={() => setTarget(null)} />
    </section>
  );
}
