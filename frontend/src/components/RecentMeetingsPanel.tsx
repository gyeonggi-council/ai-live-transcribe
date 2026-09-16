'use client';

/**
 * RecentMeetingsPanel — 대시보드 '최근 회의 영상' 카드
 *
 * 회의 영상을 표가 아니라 썸네일 목록으로 보여준다(모바일에서 표는 잘린다).
 * 기본 3건만 펼치고 '더 보기'로 확장 — 대시보드는 훑는 화면이지 목록 화면이 아니다.
 *
 * 2026-08-25 개선안 2d:
 * - 바깥 `Card` 를 벗겨 테두리 두 겹(`Card > 목록`)을 한 겹으로 줄였다.
 * - 각 줄에 **현재 단계 배지**를 넣어 /vod 와 같은 어휘로 읽히게 했다. 대시보드에서
 *   본 회의를 목록에서 다시 찾을 때 같은 단어가 보여야 같은 것으로 인식된다.
 *
 * 썸네일은 공용 `MeetingThumbnail`(서버 캐시 JPEG) — 왜 브라우저에서 만들면 안 되는지는 그 파일에.
 */

import React, { useMemo, useState } from 'react';

import Link from 'next/link';

import MeetingStageBadge from '@/components/MeetingStageBadge';
import MeetingThumbnail from '@/components/MeetingThumbnail';
import type { MeetingType } from '@/types';

export interface RecentMeetingsPanelProps {
  meetings: MeetingType[];
  isLoading?: boolean;
  hasError?: boolean;
  /** 처음 보여줄 건수 (기본 3) */
  initialCount?: number;
  /** '더 보기' 로 펼쳤을 때 최대 건수 (기본 10) */
  expandedCount?: number;
}

const DAY_NAMES = ['일', '월', '화', '수', '목', '금', '토'];

/** "2026. 8. 20 (목)" — 회의는 날짜 단위라 시:분은 데이터에 없다 */
function formatMeetingDate(dateString: string): string {
  const date = new Date(`${dateString}T00:00:00`);
  if (Number.isNaN(date.getTime())) return dateString;
  return `${date.getFullYear()}. ${date.getMonth() + 1}. ${date.getDate()} (${DAY_NAMES[date.getDay()]})`;
}

/** 3650초 → "1시간 1분" · 517초 → "8분" · 없으면 null */
function formatDuration(seconds: number | null | undefined): string | null {
  if (!seconds || seconds <= 0) return null;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  if (hours > 0) return minutes > 0 ? `${hours}시간 ${minutes}분` : `${hours}시간`;
  return `${Math.max(1, minutes)}분`;
}

/** 제목 끝의 " [2026-07-23]" 은 바로 옆에 날짜를 따로 쓰므로 뗀다 */
function cleanTitle(title: string): string {
  return title.replace(/\s*\[\d{4}-\d{2}-\d{2}\]\s*$/, '').trim() || title;
}

export default function RecentMeetingsPanel({
  meetings,
  isLoading = false,
  hasError = false,
  initialCount = 3,
  expandedCount = 10,
}: RecentMeetingsPanelProps) {
  const [expanded, setExpanded] = useState(false);

  // 최신순 — 같은 날 회의는 KMS 목록번호가 큰 쪽(나중 등록)이 위로
  const ordered = useMemo(() => {
    return [...meetings].sort((a, b) => {
      if (a.meeting_date !== b.meeting_date) {
        return a.meeting_date < b.meeting_date ? 1 : -1;
      }
      return (b.kms_no ?? 0) - (a.kms_no ?? 0);
    });
  }, [meetings]);

  const visible = ordered.slice(0, expanded ? expandedCount : initialCount);
  const hasMore = ordered.length > visible.length;

  return (
    <section aria-label="최근 회의 영상" className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between gap-4">
        <h2 className="text-[15px] font-bold tracking-heading text-text">최근 회의 영상</h2>
        <Link href="/vod" className="shrink-0 text-[13px] font-semibold text-primary hover:underline">
          회의 목록 &rarr;
        </Link>
      </div>

      <div className="overflow-hidden rounded-[10px] border border-border bg-white">

        {isLoading ? (
          <div className="py-6 text-center text-sm text-text-muted">로딩 중...</div>
        ) : hasError ? (
          <p className="py-4 text-center text-sm text-error">데이터를 불러오지 못했습니다.</p>
        ) : visible.length === 0 ? (
          <div className="py-8 text-center">
            <p className="text-sm text-text-muted">등록된 회의가 없습니다</p>
          </div>
        ) : (
          <>
            <ul className="divide-y divide-border-subtle" data-testid="recent-meeting-list">
              {visible.map((meeting) => {
                const duration = formatDuration(meeting.duration_seconds);
                return (
                  <li key={meeting.id}>
                    <Link
                      href={`/vod/${meeting.id}`}
                      className="group flex items-center gap-3.5 px-4 py-3 transition-colors hover:bg-primary-5/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary"
                    >
                      <MeetingThumbnail
                        meeting={meeting}
                        label={meeting.committee || cleanTitle(meeting.title)}
                        className="w-24 shrink-0 sm:w-28"
                      />
                      <div className="min-w-0 flex-1">
                        {/* 윗줄 — 위원회 · 날짜 · 길이. 칩이 아니라 한 줄 메타로 둔다:
                            줄마다 칩이 붙으면 대시보드가 배지밭이 된다. */}
                        <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5">
                          {meeting.committee && (
                            <span className="shrink-0 text-[11px] font-bold tracking-[0.06em] text-primary-dark">
                              {meeting.committee}
                            </span>
                          )}
                          <span className="shrink-0 text-xs tabular-nums text-text-dim">
                            {formatMeetingDate(meeting.meeting_date)}
                            {duration && <span> · {duration}</span>}
                          </span>
                        </div>
                        <p className="mt-0.5 break-keep text-[14.5px] font-semibold leading-snug text-text line-clamp-2 group-hover:text-primary">
                          {cleanTitle(meeting.title)}
                        </p>
                      </div>
                      <MeetingStageBadge meeting={meeting} className="hidden sm:inline-flex" />
                      <span
                        aria-hidden="true"
                        className="grid h-8 w-8 shrink-0 place-items-center rounded-full border border-primary-20 text-primary transition-colors group-hover:bg-primary-5"
                      >
                        <svg className="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 24 24">
                          <path d="M8 5v14l11-7z" />
                        </svg>
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>

            {(hasMore || expanded) && (
              <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                data-testid="recent-meetings-toggle"
                className="flex w-full items-center justify-center gap-1.5 border-t border-border-subtle py-2.5 text-[13.5px] font-semibold text-primary transition-colors hover:bg-primary-5/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary"
              >
                {expanded ? '접기' : '더 보기'}
                <svg
                  className={`h-4 w-4 transition-transform ${expanded ? 'rotate-180' : ''}`}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                  viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="m19 9-7 7-7-7" />
                </svg>
              </button>
            )}
          </>
        )}
      </div>
    </section>
  );
}
