'use client';

import React, { useEffect, useState } from 'react';

import Link from 'next/link';

import { getVisitorStats, recordVisit } from '@/lib/api';
import type { VisitorStatsType } from '@/types';

/**
 * VisitorCounter — 상단 접속자 수 표시 (오늘 / 누적)
 *
 * 브라우저당 하루 1회만 방문으로 집계한다.
 * - 오늘 첫 접속: POST /api/stats/visit (방문자 +1) 후 localStorage 플래그 기록
 * - 오늘 재접속: GET /api/stats/visits (조회만)
 *
 * 개인정보(IP 등)는 저장하지 않으며, 중복 제거는 브라우저 localStorage로 처리한다.
 */
function todayKey(): string {
  const d = new Date();
  const m = `${d.getMonth() + 1}`.padStart(2, '0');
  const day = `${d.getDate()}`.padStart(2, '0');
  return `ggc_visit_${d.getFullYear()}-${m}-${day}`;
}

interface VisitorCounterProps {
  /**
   * 'chip'   — 테두리 있는 독립 칩 (기본, 예전 모양)
   * 'inline' — 테두리 없이 한 줄에 녹아드는 모양.
   *            사이드바 하단이 구분선 4개로 겹쳐 있던 것을 한 줄로 합치면서 생겼다
   *            (2026-08-25 개선안 2c).
   */
  variant?: 'chip' | 'inline';
}

export default function VisitorCounter({ variant = 'chip' }: VisitorCounterProps = {}) {
  const [stats, setStats] = useState<VisitorStatsType | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const key = todayKey();
        const alreadyVisitedToday =
          typeof window !== 'undefined' && window.localStorage.getItem(key);

        // 오늘 첫 접속이면 방문 기록(+1), 아니면 조회만
        const data = alreadyVisitedToday ? await getVisitorStats() : await recordVisit();

        if (!alreadyVisitedToday && typeof window !== 'undefined') {
          try {
            window.localStorage.setItem(key, '1');
          } catch {
            // 사생활 보호 모드 등 localStorage 불가 — 집계는 그대로 진행
          }
        }

        if (!cancelled) setStats(data);
      } catch {
        // 집계 실패 시 조용히 숨김 (핵심 기능 아님)
        if (!cancelled) setStats(null);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (!stats) return null;

  const inline = variant === 'inline';

  return (
    <Link
      href="/visits"
      data-testid="visitor-counter"
      className={
        inline
          ? 'flex min-w-0 items-center gap-1.5 text-xs text-text-muted hover:text-text-secondary hover:underline'
          : 'flex items-center gap-2 px-3 py-1.5 text-xs bg-surface border border-border rounded-md text-text-secondary hover:bg-surface-raised'
      }
      title={`오늘 접속자 ${stats.today.toLocaleString()}명 · 누적 ${stats.total.toLocaleString()}명 — 눌러서 접속 통계 보기`}
    >
      <svg
        className={inline ? 'w-3.5 h-3.5 flex-shrink-0 text-text-dim' : 'w-4 h-4 text-text-muted'}
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
        strokeWidth={inline ? 1.8 : 2}
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z"
        />
      </svg>
      <span className="flex items-center gap-1">
        <span className="text-text-muted">오늘</span>
        <span className="font-semibold text-text tabular-nums">{stats.today.toLocaleString()}</span>
      </span>
      <span className={inline ? 'text-text-dim' : 'text-border'}>{inline ? '·' : '|'}</span>
      <span className="flex items-center gap-1">
        <span className="text-text-muted">누적</span>
        <span className="font-semibold text-text tabular-nums">{stats.total.toLocaleString()}</span>
      </span>
    </Link>
  );
}
