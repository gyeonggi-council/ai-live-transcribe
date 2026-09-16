'use client';

import React, { useEffect, useMemo, useState } from 'react';

import { getMinutesByAgenda } from '@/lib/api';
import type { AgendaMinutesItem } from '@/types';

export interface LiveAgendaRow {
  orderNum: number;
  title: string;
  /** 이 안건의 첫 자막 경과 시간(초). 아직 발언이 없으면 null */
  startTime: number | null;
  /** 이 안건의 첫 자막 id — 목록 스크롤 이동에 쓴다 */
  firstSubtitleId: string | null;
  subtitleCount: number;
}

export interface LiveAgendaPanelProps {
  /** 회의 UUID. 없으면 패널을 그리지 않는다 (KMS 미등록 생중계 스텁 등) */
  meetingId?: string | null;
  /** 지금 재생 위치(초) — 어느 안건을 다루는 중인지 판정한다 */
  currentTime?: number;
  /** 항목 클릭 — 그 안건의 첫 자막으로 이동 */
  onJump?: (row: LiveAgendaRow) => void;
  /** 자막이 늘어날 때마다 다시 읽게 하는 트리거 (건수 등) */
  refreshKey?: number;
  className?: string;
}

function formatElapsed(seconds: number | null): string {
  if (seconds === null) return '—';
  const s = Math.max(0, Math.floor(seconds));
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
}

function toRows(agendas: AgendaMinutesItem[]): LiveAgendaRow[] {
  return agendas
    .slice()
    .sort((a, b) => a.order_num - b.order_num)
    .map((a) => {
      const first = a.subtitles
        .slice()
        .sort((x, y) => x.start_time - y.start_time)[0];
      return {
        orderNum: a.order_num,
        title: a.title,
        startTime: first ? first.start_time : null,
        firstSubtitleId: first ? first.id : null,
        subtitleCount: a.subtitles.length,
      };
    });
}

/**
 * 의사일정 — PC 실시간 자막 화면 좌측 아래.
 *
 * 2026-08-25 개선안 2e 로 생긴 자리다. '지금 발언'을 영상 아래로 올리고 마이크·
 * 내보내기를 좌측으로 옮기면서 왼쪽 아래가 비었는데, 회의를 따라가는 데 가장 자주
 * 필요한 문맥이 **"지금 몇 번 안건인가"** 라서 그 자리를 의사일정으로 채운다.
 *
 * 데이터는 `/api/meetings/{id}/minutes/by-agenda` 가 이미 안건별 자막을 내려주므로
 * 새 API 없이 첫 자막 시각만 뽑아 쓴다. 안건이 하나도 없으면(등록 전) 패널 자체를
 * 그리지 않는다 — 빈 상자는 자리만 먹는다.
 */
export default function LiveAgendaPanel({
  meetingId,
  currentTime,
  onJump,
  refreshKey = 0,
  className = '',
}: LiveAgendaPanelProps) {
  const [rows, setRows] = useState<LiveAgendaRow[]>([]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!meetingId) {
      setRows([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await getMinutesByAgenda(meetingId);
        if (!cancelled) {
          setRows(toRows(res.agendas ?? []));
          setFailed(false);
        }
      } catch {
        // 안건이 없거나 조회에 실패하면 조용히 감춘다 — 시청을 막는 오류가 아니다
        if (!cancelled) {
          setRows([]);
          setFailed(true);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [meetingId, refreshKey]);

  /** 지금 다루는 안건 = 시작 시각이 현재 시각 이하인 것 중 마지막 */
  const activeIndex = useMemo(() => {
    if (currentTime == null) return -1;
    let idx = -1;
    rows.forEach((r, i) => {
      if (r.startTime !== null && r.startTime <= currentTime) idx = i;
    });
    return idx;
  }, [rows, currentTime]);

  if (!meetingId || failed || rows.length === 0) return null;

  return (
    <section
      data-testid="live-agenda-panel"
      aria-label="의사일정"
      className={`flex min-h-0 flex-col overflow-hidden rounded-lg border border-border bg-surface ${className}`.trim()}
    >
      <div className="flex h-[38px] shrink-0 items-center justify-between border-b border-border bg-surface-raised px-4">
        <h3 className="text-[13px] font-bold tracking-heading text-text">의사일정</h3>
        <span className="text-xs text-text-muted">누르면 해당 자막으로 이동</span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {rows.map((row, i) => {
          const on = i === activeIndex;
          const jumpable = row.firstSubtitleId !== null;
          return (
            <button
              key={`${row.orderNum}-${row.title}`}
              type="button"
              disabled={!jumpable}
              onClick={() => jumpable && onJump?.(row)}
              data-testid={`agenda-row-${row.orderNum}`}
              aria-current={on ? 'step' : undefined}
              title={row.title}
              className={`flex w-full items-center gap-3 border-b border-border-subtle px-4 py-2.5 text-left transition-colors last:border-b-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary ${
                on ? 'bg-primary-5' : jumpable ? 'hover:bg-surface-raised' : 'cursor-default'
              }`}
            >
              <span
                className={`grid h-5 w-[26px] shrink-0 place-items-center rounded text-[11px] font-bold tabular-nums ${
                  on ? 'bg-primary text-white' : 'bg-gray-100 text-text-muted'
                }`}
              >
                {row.orderNum}
              </span>
              <span
                className={`min-w-0 flex-1 truncate text-[13.5px] ${
                  on ? 'font-semibold text-text' : 'font-medium text-text-secondary'
                }`}
              >
                {row.title}
              </span>
              <span className="shrink-0 font-mono text-[11.5px] text-text-dim">
                {formatElapsed(row.startTime)}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
