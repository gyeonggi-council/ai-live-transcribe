'use client';

import React from 'react';

import { useRouter } from 'next/navigation';

import type { MeetingType } from '@/types';

export interface RecentVodListProps {
  vods: MeetingType[];
  className?: string;
}

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}.${m}.${d}`;
}

function formatDuration(seconds: number | null): string {
  // 생중계·변환 전 회의는 길이가 0/null — 00:00:00 대신 '-' 표시
  if (!seconds) return '-';

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;

  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

function StatusBadge({ status }: { status: MeetingType['status'] }) {
  // whitespace-nowrap: 좁은 셀에서 배지 글자가 세로로 꺾이는 것 방지 (모바일)
  const base = 'text-[10px] px-2 py-1 rounded-full font-bold whitespace-nowrap';
  switch (status) {
    case 'ended':
      return <span className={`bg-success/10 text-success ${base}`}>자막완료</span>;
    case 'processing':
      return <span className={`bg-warning-bg/20 text-warning ${base}`}>자막생성중</span>;
    case 'live':
      return <span className={`bg-danger/10 text-danger ${base}`}>진행중</span>;
    case 'scheduled':
      return <span className={`bg-gray-100 text-gray-500 ${base}`}>대기중</span>;
    default:
      return <span className={`bg-gray-100 text-gray-500 ${base}`}>확인필요</span>;
  }
}

export default function RecentVodList({ vods, className = '' }: RecentVodListProps) {
  const router = useRouter();

  return (
    <section className={`bg-white rounded-lg p-4 sm:p-6 border border-border ${className}`.trim()}>
      <h2 className="text-lg font-bold text-gray-900 mb-4">최근 회의</h2>

      {vods.length === 0 ? (
        <div className="py-8 text-center">
          <p className="text-sm text-text-muted">등록된 회의가 없습니다</p>
        </div>
      ) : (
        <>
          {/* 모바일: 카드형 목록 — 좁은 화면에서 표가 깨지는 문제(제목 잘림·배지 세로꺾임) 해소 */}
          <ul className="sm:hidden divide-y divide-border-subtle" data-testid="recent-vod-cards">
            {vods.map((vod) => (
              <li key={vod.id}>
                <button
                  type="button"
                  onClick={() => router.push(`/vod/${vod.id}`)}
                  className="w-full text-left py-3 flex items-start justify-between gap-3 active:bg-gray-50"
                >
                  <div className="min-w-0">
                    <p className="text-sm font-bold text-gray-800 break-keep line-clamp-2">
                      {vod.title}
                    </p>
                    <p className="text-xs text-gray-500 mt-1">
                      {formatDate(vod.meeting_date)}
                      {formatDuration(vod.duration_seconds) !== '-' && (
                        <span className="font-mono"> · {formatDuration(vod.duration_seconds)}</span>
                      )}
                    </p>
                  </div>
                  <div className="shrink-0 pt-0.5">
                    <StatusBadge status={vod.status} />
                  </div>
                </button>
              </li>
            ))}
          </ul>

          {/* 태블릿 이상: 기존 표 */}
          <div className="hidden sm:block overflow-x-auto">
            <table className="w-full text-left">
              <thead className="bg-gray-50 text-[10px] uppercase tracking-widest text-gray-500 font-bold border-b border-border">
                <tr>
                  <th className="py-3 px-4">날짜</th>
                  <th className="py-3 px-4 w-full">회의명</th>
                  <th className="py-3 px-4">시간</th>
                  <th className="py-3 px-4">상태</th>
                </tr>
              </thead>
              <tbody className="text-sm divide-y divide-border-subtle">
                {vods.map((vod) => (
                  <tr
                    key={vod.id}
                    onClick={() => router.push(`/vod/${vod.id}`)}
                    className="hover:bg-gray-50 transition-colors cursor-pointer group"
                  >
                    <td className="py-4 px-4 text-gray-500 whitespace-nowrap">
                      {formatDate(vod.meeting_date)}
                    </td>
                    <td className="py-4 px-4 font-bold text-gray-700 group-hover:text-primary transition-colors">
                      <span className="line-clamp-1">{vod.title}</span>
                    </td>
                    <td className="py-4 px-4 text-gray-500 font-mono whitespace-nowrap">
                      {formatDuration(vod.duration_seconds)}
                    </td>
                    <td className="py-4 px-4">
                      <StatusBadge status={vod.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
