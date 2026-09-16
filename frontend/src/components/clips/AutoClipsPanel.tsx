'use client';

import React, { useMemo, useState } from 'react';

import { useAutoClips } from '@/hooks/useAutoClips';
import { downloadClipJobFile } from '@/lib/api';
import type { ClipJobFileType, ClipJobType } from '@/types';
import { formatBytes, formatHMS, formatLen } from '@/utils/clipTime';

/**
 * 자동으로 잘라 둔 영상 — AI 자막이 끝난 회의의 의원 전원 영상을 서버가 720p 로 미리 잘라 둔다(2026-09-10 사용자 결정).
 *
 * 「확인 후 추출」 없이 받기만 하면 된다. 다만 의원 구간 정확도가 99% 가 아니라(392회 위원회 전수 약 81%)
 * 공유 전에 한 번 재생해 보라는 안내를 늘 붙인다(사용자 선택). 파일 이름은 워크벤치·설치형과 같다
 * (이름_회의명_번호.mp4) — 담당자가 세 경로로 받은 파일을 한 폴더에 모은다.
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

const STATUS_LABEL: Record<string, string> = {
  queued: '자르기 대기',
  running: '자르는 중',
  done: '준비됨',
  failed: '실패',
  cancelled: '취소됨',
  expired: '보관 끝남',
};

interface ClipItem {
  file: ClipJobFileType;
  srt?: ClipJobFileType;
  seg?: { start: number; end: number; no?: number };
}

/** 구간별 파일(merge=false) — mp4 가 구간 순서대로 놓이고 같은 이름의 srt 가 짝이다 */
function itemsOf(job: ClipJobType): ClipItem[] {
  const files = job.files ?? [];
  return files
    .filter((f) => f.kind === 'mp4')
    .map((f, i) => ({
      file: f,
      srt: files.find((x) => x.kind === 'srt' && x.name.replace(/\.srt$/i, '') === f.name.replace(/\.mp4$/i, '')),
      seg: job.segments?.[i],
    }));
}

function AutoJob({
  job,
  showSpeaker,
  onPreview,
}: {
  job: ClipJobType;
  showSpeaker: boolean;
  onPreview?: (start: number) => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const items = itemsOf(job);
  const active = job.status === 'queued' || job.status === 'running';

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
    <li data-testid="auto-clip-job" className="rounded-lg border border-border bg-white p-2 text-[13px] flex flex-col gap-1">
      <div className="flex items-center gap-2 flex-wrap">
        {showSpeaker && <span className="font-semibold text-text">{job.speaker_name || job.label}</span>}
        <span
          data-testid="auto-clip-status"
          className={`rounded px-1.5 py-0.5 text-[11px] font-semibold ${
            job.status === 'done'
              ? 'bg-green-100 text-green-800'
              : active
                ? 'bg-blue-100 text-blue-800'
                : 'bg-gray-100 text-gray-600'
          }`}
        >
          {STATUS_LABEL[job.status] ?? job.status}
          {job.status === 'running' && job.segment_count > 1 && job.current_segment
            ? ` ${job.current_segment}/${job.segment_count}`
            : ''}
        </span>
        <span className="text-[11px] text-text-muted tabular-nums">
          {job.segment_count}구간 · {formatLen(job.total_seconds)}
          {job.bytes_total > 0 && ` · ${formatBytes(job.bytes_total)}`}
        </span>
        {job.status === 'done' && items.length > 1 && (
          <button
            type="button"
            data-testid="auto-clip-download-all"
            onClick={downloadAll}
            disabled={busy !== null}
            className="ml-auto rounded-md border border-border bg-white px-2 py-0.5 text-[12px] hover:bg-gray-50 disabled:opacity-50"
          >
            ⬇ 전부 받기
          </button>
        )}
      </div>
      {active && (
        <div className="h-1.5 rounded bg-gray-200 overflow-hidden">
          {job.status === 'running' && job.progress > 0 ? (
            <div className="h-full bg-primary transition-all" style={{ width: `${Math.round(job.progress * 100)}%` }} />
          ) : (
            <div className={`h-full w-full ${job.status === 'running' ? 'bg-primary/60 animate-pulse' : 'bg-gray-300'}`} />
          )}
        </div>
      )}
      {job.status === 'done' && (
        <ul className="flex flex-col gap-1">
          {items.map((it, i) => (
            <li key={it.file.name} className="flex items-center gap-2 flex-wrap">
              <span className="w-8 text-[12px] text-text-muted tabular-nums">#{it.seg?.no ?? i + 1}</span>
              {it.seg && (
                <span className="text-[12px] text-text-muted tabular-nums">
                  {formatHMS(it.seg.start)} · {formatLen(it.seg.end - it.seg.start)}
                </span>
              )}
              {onPreview && it.seg && (
                <button
                  type="button"
                  data-testid="auto-clip-preview"
                  onClick={() => it.seg && onPreview(it.seg.start)}
                  className="rounded-md border border-border bg-white px-2 py-0.5 text-[12px] hover:bg-gray-50"
                >
                  ▶ 보기
                </button>
              )}
              <button
                type="button"
                data-testid="auto-clip-download"
                title={it.file.name}
                onClick={() => download(it.file.name)}
                disabled={busy !== null}
                className="inline-flex items-center gap-1 rounded-md border border-border bg-white px-2 py-0.5 text-[12px] hover:bg-gray-50 disabled:opacity-50"
              >
                {busy === it.file.name ? '⏳' : '⬇'} 받기
                <span className="text-text-muted">{formatBytes(it.file.bytes)}</span>
              </button>
              {it.srt && (
                <button
                  type="button"
                  onClick={() => it.srt && download(it.srt.name)}
                  disabled={busy !== null}
                  className="text-[11px] underline text-text-muted disabled:opacity-50"
                >
                  📄 자막
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {job.status === 'failed' && <div className="text-[12px] text-red-700">{job.error || '자르지 못했습니다.'}</div>}
      {job.status === 'expired' && (
        <div className="text-[12px] text-text-muted">보관 기간이 지나 지웠습니다 — 필요하면 아래에서 직접 자르세요.</div>
      )}
      {err && <div className="text-[12px] text-red-700">{err}</div>}
    </li>
  );
}

export default function AutoClipsPanel({ meetingId = null, speakerName = null, days = 3, onPreview }: AutoClipsPanelProps) {
  const { jobs, notice, ttlDays, isLoading, error } = useAutoClips({ meetingId, days });
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

  return (
    <section
      data-testid="auto-clips-panel"
      className="rounded-lg border border-warning-bg/40 bg-warning-bg/10 p-3 flex flex-col gap-2"
    >
      <div className="flex items-baseline gap-2 flex-wrap">
        <h3 className="text-[14px] font-bold text-text">🎬 자동으로 잘라 둔 영상</h3>
        <span className="text-[12px] text-text-muted">
          {meetingId ? `${people}명` : `최근 ${days}일 · ${groups.length}회의`}
          {ttlDays ? ` · ${ttlDays}일 보관` : ''} · 720p(공유용)
        </span>
      </div>
      <p data-testid="auto-clips-notice" className="text-[12px] leading-relaxed text-warning-dark">
        ⚠ {notice || DEFAULT_NOTICE}
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
      {meetingId ? (
        <ul className="flex flex-col gap-1.5">
          {shown.map((j) => (
            <AutoJob key={j.job_id} job={j} showSpeaker={!speakerName} onPreview={onPreview} />
          ))}
        </ul>
      ) : (
        groups.map((g) => (
          <div key={g.id} data-testid="auto-clips-meeting" className="flex flex-col gap-1.5">
            <div className="text-[13px] font-semibold text-text truncate">
              {g.title} {g.date ? <span className="font-normal text-text-muted">({g.date})</span> : null}
            </div>
            <ul className="flex flex-col gap-1.5">
              {g.jobs.map((j) => (
                <AutoJob key={j.job_id} job={j} showSpeaker onPreview={onPreview} />
              ))}
            </ul>
          </div>
        ))
      )}
    </section>
  );
}
