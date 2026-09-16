'use client';

import React from 'react';

import type { MeetingType } from '@/types';

import MeetingStageBadge from './MeetingStageBadge';
import MeetingStageProgress from './MeetingStageProgress';
import MeetingThumbnail from './MeetingThumbnail';

export interface MeetingCardProps {
  meeting: MeetingType;
  /** 행 클릭(또는 Enter/Space) 시 이동 */
  onOpen: (id: string) => void;
  /** AI 자막 생성 대상 선택 모드 (관리자) */
  selectable?: boolean;
  selected?: boolean;
  /** 선택 가능한 회의인지 — 불가면 체크박스 대신 안내 */
  selectableReason?: { ok: boolean; reason: string };
  onToggleSelect?: (id: string) => void;
  /** 제목 아래 부가 영역 (KMS JS 버튼 등) */
  footer?: React.ReactNode;
}

export function formatMeetingDate(dateString: string): string {
  if (!dateString) return '-';
  return dateString.slice(0, 10);
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '-';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  return `${hours}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

/**
 * 회의의 위원회명 — DB 값이 우선이고 없으면 제목에서 뽑는다.
 * (목록 API 가 committee 를 대부분 비워 보내서 제목 폴백이 없으면 썸네일이 전부 빈다)
 */
export function committeeLabel(
  meeting: Pick<MeetingType, 'title'> & { committee?: string | null },
): string {
  if (meeting.committee) return meeting.committee;
  const matches = (meeting.title || '').match(/[가-힣]{2,}위원회|본회의/g);
  return matches?.[matches.length - 1] ?? '회의';
}

/**
 * 회의 목록의 한 행 — PC·모바일 공통.
 *
 * 2026-08-25 개선안 2f 로 **2열 카드 격자에서 1열 목록**이 됐다. 카드는 회의명이
 * 2줄로 잘리고 날짜·길이가 카드마다 다른 높이에 놓여 위아래로 훑을 수가 없었다.
 * 행으로 펴면 같은 값이 같은 세로선에 온다.
 *
 * 단계 표시가 둘로 나뉘어 있다 — 이것이 이 화면의 핵심이다.
 *   · 배지 = 지금 어느 단계인가 (글자)
 *   · 막대 = 어디까지 왔나 (2칸, 이름 없음)
 * 단계 **이름은 목록 머리 범례에 한 번만** 나온다(VodTable). 행마다 이름을 반복하면
 * 10px 글자 24개가 화면을 덮어 정작 회의명이 안 읽힌다.
 *
 * ⚠ 배지·막대는 **DOM 에 한 번만** 있다. 모바일에서는 제목 아래 한 줄로 접히고
 *   PC 에서는 고정폭 두 열로 서는데, 그 전환을 `lg:contents` 한 줄이 한다 —
 *   래퍼가 격자에서 사라지면서 자식이 곧바로 격자 칸이 된다. 반응형마다 마크업을
 *   복제하면 배지가 두 개가 되어 스크린리더가 단계를 두 번 읽는다.
 */
export default function MeetingCard({
  meeting,
  onOpen,
  selectable = false,
  selected = false,
  selectableReason,
  onToggleSelect,
  footer,
}: MeetingCardProps) {
  const canSelect = selectableReason?.ok ?? true;
  const isLive = meeting.status === 'live';
  const committee = committeeLabel(meeting);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onOpen(meeting.id);
    }
  };

  // 체크박스 유무가 열 하나를 더한다 — 격자 정의를 한 곳에서 만든다.
  const cols = selectable
    ? 'grid-cols-[auto_5.5rem_minmax(0,1fr)] lg:grid-cols-[auto_7rem_minmax(0,1fr)_132px_132px_2rem]'
    : 'grid-cols-[5.5rem_minmax(0,1fr)] lg:grid-cols-[7rem_minmax(0,1fr)_132px_132px_2rem]';

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpen(meeting.id)}
      onKeyDown={handleKeyDown}
      className={`grid cursor-pointer items-center gap-x-3 gap-y-1.5 border-b border-border-subtle px-3 py-2.5 transition-colors last:border-b-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary sm:px-4 lg:gap-x-3.5 ${cols} ${
        isLive ? 'bg-live/[0.04] hover:bg-live/[0.07]' : 'hover:bg-primary-5/50'
      }`}
      data-testid="meeting-card"
      data-title={meeting.title}
      data-date={formatMeetingDate(meeting.meeting_date)}
      data-duration={formatDuration(meeting.duration_seconds)}
      data-status={meeting.status}
    >
      {selectable && (
        <span
          onClick={(e) => e.stopPropagation()}
          className="row-span-2 flex items-center justify-center lg:row-span-1"
        >
          {canSelect ? (
            <input
              type="checkbox"
              checked={selected}
              onChange={() => onToggleSelect?.(meeting.id)}
              className="h-4 w-4 cursor-pointer accent-primary"
              title="AI 자막 생성 대상으로 선택"
              aria-label={`${meeting.title} AI 자막 생성 대상 선택`}
              data-testid={`select-checkbox-${meeting.id}`}
            />
          ) : (
            <span
              className="inline-block w-4 text-center text-text-muted"
              title={selectableReason?.reason}
              aria-hidden="true"
            >
              ―
            </span>
          )}
        </span>
      )}

      {/* 썸네일 — 서버 캐시 JPEG. VOD 없는 회의(생중계·등록 전)는 위원회명 자리표시 */}
      <MeetingThumbnail
        meeting={meeting}
        label={committee}
        className="row-span-2 lg:row-span-1"
      />

      <div className="flex min-w-0 flex-col gap-1">
        {/* 윗줄 — 위원회 · 재생시간 */}
        <div className="flex items-baseline gap-2">
          <span className="min-w-0 truncate text-[10.5px] font-bold tracking-[0.06em] text-primary-dark lg:text-[11px]">
            {committee}
          </span>
          <span className="ml-auto shrink-0 font-mono text-[11px] tabular-nums text-text-dim lg:text-xs">
            {formatDuration(meeting.duration_seconds)}
          </span>
        </div>

        {/* 아랫줄 — 번호 · 제목 · 날짜. 날짜는 제목과 같은 크기로 우측 정렬한다:
            회의 목록에서 제목 다음으로 자주 보는 값이 날짜다. */}
        <div className="flex items-baseline gap-2 lg:gap-2.5">
          {meeting.kms_no != null && (
            <span
              className="hidden shrink-0 text-xs tabular-nums text-text-dim lg:inline"
              title="의회 홈페이지(최근회의영상) 목록 번호"
            >
              #{meeting.kms_no}
            </span>
          )}
          <p className="line-clamp-2 min-w-0 flex-1 break-keep text-[13.5px] font-semibold leading-snug text-text lg:truncate lg:text-[15px] lg:leading-normal">
            {meeting.title}
          </p>
          <span className="shrink-0 text-[13.5px] font-semibold tabular-nums text-text-secondary lg:text-[15px]">
            {formatMeetingDate(meeting.meeting_date)}
          </span>
        </div>

        {footer && (
          <div className="pt-0.5" onClick={(e) => e.stopPropagation()}>
            {footer}
          </div>
        )}
      </div>

      {/* 모바일: 제목 아래 한 줄 / PC: 고정폭 두 열 (lg:contents 가 래퍼를 지운다) */}
      <div className="flex min-w-0 items-center gap-2 lg:contents">
        <MeetingStageBadge meeting={meeting} className="lg:justify-self-start" />
        <MeetingStageProgress
          meeting={meeting}
          variant="segments"
          className="w-24 shrink-0 lg:w-full"
        />
      </div>

      <span
        className="hidden h-8 w-8 place-items-center rounded-full border border-primary-20 text-primary lg:grid"
        aria-hidden="true"
      >
        <svg className="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 24 24">
          <path d="M8 5v14l11-7z" />
        </svg>
      </span>
    </div>
  );
}
