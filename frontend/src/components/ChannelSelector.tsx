'use client';

import React, { useMemo } from 'react';

import LiveChannelCard from '@/components/LiveChannelCard';
import PageHeader from '@/components/PageHeader';
import { useChannelAlerts } from '@/hooks/useChannelAlerts';
import { useUpcomingSchedule } from '@/hooks/useUpcomingSchedule';
import type { ChannelType, ScheduleItemType, UpcomingScheduleType } from '@/types';

export interface ChannelSelectorProps {
  channels: ChannelType[];
  isLoading: boolean;
  onSelect: (channel: ChannelType) => void;
}

/** 상태별 정렬 우선순위 (낮을수록 앞) */
const STATUS_PRIORITY: Record<number, number> = {
  1: 0, // 방송중
  2: 1, // 정회중
  0: 2, // 방송전
  3: 3, // 종료
  4: 4, // 생중계없음
};

const BELL_OUTLINE =
  'M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0';

/** 🔔 방송 시작 알람 토글 — 예정 목록과 전체 채널 목록에서 함께 쓴다 */
function AlertBellButton({
  channelId,
  channelName,
  isOn,
  onToggle,
  permission,
  className = '',
}: {
  channelId: string;
  channelName: string;
  isOn: boolean;
  onToggle: () => void;
  permission: NotificationPermission | 'unsupported';
  className?: string;
}) {
  const title = isOn
    ? `${channelName} 방송 시작 알람 해제`
    : permission === 'denied'
      ? '브라우저 알림 권한이 차단되어 있습니다. 주소창 좌측 자물쇠 아이콘에서 권한을 허용해 주세요.'
      : `${channelName} 방송이 시작되면 브라우저 알림으로 알려드립니다`;

  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onToggle();
      }}
      aria-label={title}
      aria-pressed={isOn}
      title={title}
      data-testid={`alert-toggle-${channelId}`}
      className={`grid shrink-0 place-items-center rounded-full transition-colors ${
        isOn
          ? 'bg-warning-bg/20 text-warning-dark hover:bg-warning-bg/30'
          : 'text-text-dim hover:bg-gray-100 hover:text-text-secondary'
      } ${className}`.trim()}
    >
      {isOn ? (
        <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 22c1.1 0 2-.9 2-2h-4a2 2 0 002 2zm6-6V11c0-3.07-1.63-5.64-4.5-6.32V4a1.5 1.5 0 00-3 0v.68C7.64 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z" />
        </svg>
      ) : (
        <svg
          className="h-4 w-4"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.75}
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d={BELL_OUTLINE} />
        </svg>
      )}
    </button>
  );
}

/** 예정 목록의 상태 알약 — status_text 가 있으면 그 문구를 그대로 쓴다 */
function ScheduleStatusPill({ channel }: { channel: ChannelType }) {
  const status = channel.livestatus ?? 0;
  const label =
    channel.status_text?.trim() ||
    (status === 2 ? '정회중' : status === 3 ? '종료' : '방송전');

  const tone =
    status === 2
      ? 'bg-warning-bg/20 text-warning-dark'
      : status === 3
        ? 'bg-gray-100 text-text-muted'
        : 'bg-primary-5 text-primary';

  return (
    <span
      className={`inline-flex w-[88px] shrink-0 items-center justify-center rounded-full px-2.5 py-[3px] text-xs font-medium ${tone}`}
    >
      {label}
    </span>
  );
}

const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토'];

/** 'YYYY-MM-DD' → '9월 1일 (화)'. 서버가 KST 날짜 문자열을 주므로 파싱만 한다. */
function formatScheduleDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number);
  if (!y || !m || !d) return iso;
  const dow = WEEKDAYS[new Date(y, m - 1, d).getDay()];
  return `${m}월 ${d}일 (${dow})`;
}

/** '제393회 임시회 제1차' — 없는 조각은 조용히 뺀다 */
function sessionLabelOf(item: {
  session_no: number | null;
  session_order: number | null;
  session_kind: string | null;
}): string {
  const parts: string[] = [];
  if (item.session_no) parts.push(`제${item.session_no}회`);
  if (item.session_kind) parts.push(item.session_kind);
  if (item.session_order) parts.push(`제${item.session_order}차`);
  return parts.join(' ');
}

/** '3분 전' — 안건이 언제 기준인지 보여주려는 것이라 분 단위면 충분하다 */
function timeAgo(iso: string | null): string | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  const min = Math.floor((Date.now() - then) / 60000);
  if (min < 1) return '방금';
  if (min < 60) return `${min}분 전`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}시간 전`;
  return `${Math.floor(hr / 24)}일 전`;
}

/**
 * 예정 회의 한 줄 — 누르면 그날 다룰 안건이 펼쳐진다.
 *
 * `<details>` 를 쓴 이유: 펼침 상태는 이 줄 하나의 일이라 상위 상태로 끌어올릴 이유가 없고,
 * 키보드·스크린리더 동작이 공짜로 따라온다.
 */
function UpcomingItem({ item }: { item: ScheduleItemType }) {
  const session = sessionLabelOf(item);
  const agenda = item.agenda_items ?? [];

  return (
    <details
      className="group border-b border-border-subtle last:border-b-0"
      data-testid={`upcoming-item-${item.committee_code}`}
    >
      <summary
        className={`flex cursor-pointer list-none items-center gap-3 px-4 py-3 hover:bg-surface-hover sm:gap-4 ${
          item.is_cancelled ? 'opacity-60' : ''
        }`}
      >
        <span className="w-[52px] shrink-0 text-[13px] tabular-nums text-text-muted">
          {item.start_time ?? '—'}
        </span>
        <span
          className={`min-w-0 flex-1 truncate text-[15px] font-medium text-text ${
            item.is_cancelled ? 'line-through' : ''
          }`}
        >
          {item.committee_name}
        </span>
        {item.is_cancelled && (
          <span className="shrink-0 rounded-full bg-gray-100 px-2.5 py-[3px] text-xs font-medium text-text-muted">
            취소
          </span>
        )}
        {session && (
          <span className="hidden shrink-0 text-[13px] tabular-nums text-text-muted sm:block">
            {session}
          </span>
        )}
        {agenda.length > 0 && (
          <span className="shrink-0 text-[13px] text-text-muted">
            안건 {agenda.length}
            <span className="ml-1 inline-block transition-transform group-open:rotate-90" aria-hidden="true">
              ›
            </span>
          </span>
        )}
      </summary>
      {agenda.length > 0 && (
        <ol className="list-decimal space-y-1 bg-surface-inset px-4 py-3 pl-10 text-[14px] text-text-secondary">
          {agenda.map((text, i) => (
            <li key={`${item.committee_code}-${i}`}>{text}</li>
          ))}
        </ol>
      )}
    </details>
  );
}

/**
 * 다가오는 일정 — 의회 홈페이지 의정캘린더에서 가져온다.
 *
 * 오늘은 위쪽 '오늘 예정'이 담당하므로 여기는 **내일부터**다. 회의가 없으면 섹션 자체를
 * 그리지 않는다 — 휴회 기간에 빈 상자가 자리를 차지하면 안 된다.
 */
function UpcomingScheduleSection({ schedule }: { schedule: UpcomingScheduleType | null }) {
  const days = (schedule?.days ?? []).filter((d) => d.items.length > 0);
  if (days.length === 0) return null;

  const checked = timeAgo(schedule?.synced_at ?? null);
  const total = days.reduce((n, d) => n + d.items.length, 0);

  return (
    <section className="flex flex-col gap-3" aria-label="다가오는 일정" data-testid="upcoming-schedule">
      <SectionHeading count={total} note="경기도의회 의정캘린더 기준 — 안건은 회기 중 바뀔 수 있습니다">
        다가오는 일정
      </SectionHeading>
      <div className="overflow-hidden rounded-[10px] border border-border bg-white">
        {days.map((day) => (
          <div key={day.date}>
            <div className="flex items-baseline gap-2 border-b border-border-subtle bg-surface-inset px-4 py-2">
              <span className="text-[14px] font-bold text-text">{formatScheduleDate(day.date)}</span>
              <span className="text-[13px] text-text-muted">{day.items.length}건</span>
            </div>
            {day.items.map((item) => (
              <UpcomingItem key={`${day.date}-${item.committee_code}`} item={item} />
            ))}
          </div>
        ))}
      </div>
      {checked && (
        <p className="px-1 text-[12px] text-text-muted">의회 홈페이지 {checked} 확인</p>
      )}
    </section>
  );
}

function SectionHeading({
  children,
  count,
  live = false,
  note,
}: {
  children: React.ReactNode;
  count?: number;
  live?: boolean;
  note?: string;
}) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
      <h2 className="flex items-center gap-2 text-[15px] font-bold tracking-heading text-text">
        {live && (
          <span className="h-2 w-2 shrink-0 animate-live-pulse rounded-full bg-live" aria-hidden="true" />
        )}
        {children}
      </h2>
      {count != null && <span className="text-[13px] font-medium text-text-muted">{count}</span>}
      {note && <span className="text-xs text-text-dim">{note}</span>}
    </div>
  );
}

/**
 * 실시간 방송 목록 (/live 의 채널 미선택 화면).
 *
 * 2026-08-25 개선안 2b: 896px 안에 18칸을 균등하게 깔던 격자를 **방송 중 · 오늘 예정 ·
 * 전체 채널** 세 단으로 나눴다. 예전 격자는 지금 보러 온 방송 한두 개가 안 열리는
 * 채널 16개와 같은 크기·같은 자리에 있어서 눈이 매번 전체를 훑어야 했다.
 *
 *   · 방송 중 — 16:9 자리를 가진 큰 카드. 화면 맨 위, 가장 크다
 *   · 오늘 예정 — **시간표처럼 세로 목록**. 일정은 격자가 아니라 순서로 읽힌다
 *   · 전체 채널 — 6열 조밀 목록. 여기서 할 일은 알람을 거는 것뿐이라 벨만 남긴다
 */
export default function ChannelSelector({ channels, isLoading, onSelect }: ChannelSelectorProps) {
  // 방송 시작 알람 구독 관리 (localStorage 영속)
  const { isSubscribed, subscribe, unsubscribe, permission, subscribed } = useChannelAlerts({
    channels,
  });

  // 다가오는 일정 (내일부터 7일) — 서버가 의정캘린더를 30분마다 다시 맞춘다
  const { schedule } = useUpcomingSchedule(7, false);

  const handleAlertToggle = (channelId: string) => {
    if (isSubscribed(channelId)) unsubscribe(channelId);
    else void subscribe(channelId);
  };

  const { liveChannels, scheduledChannels, allChannels } = useMemo(() => {
    const byStatus = (a: ChannelType, b: ChannelType) => {
      const pa = STATUS_PRIORITY[a.livestatus ?? 0] ?? 9;
      const pb = STATUS_PRIORITY[b.livestatus ?? 0] ?? 9;
      if (pa !== pb) return pa - pb;
      if (a.has_schedule !== b.has_schedule) return a.has_schedule ? -1 : 1;
      return 0;
    };

    return {
      liveChannels: channels.filter((c) => c.livestatus === 1),
      // 정회중(2)도 '오늘 있는 회의'다 — 속개하면 다시 방송 중으로 올라간다.
      scheduledChannels: channels
        .filter((c) => c.livestatus !== 1 && (c.has_schedule || c.livestatus === 2))
        .sort(byStatus),
      allChannels: [...channels].sort(byStatus),
    };
  }, [channels]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="h-12 w-12 animate-spin rounded-full border-4 border-gray-200 border-t-primary" />
      </div>
    );
  }

  const today = new Date();
  const dayNames = ['일', '월', '화', '수', '목', '금', '토'];
  const todayStr = `${today.getFullYear()}년 ${today.getMonth() + 1}월 ${today.getDate()}일 (${dayNames[today.getDay()]})`;

  // 오늘 어느 회기가 도는지 — 채널 상태의 회차(생중계 일정 API)가 정본이고,
  // 회기 종류(임시회/정례회)는 의정캘린더에만 있어 수집분에서 채운다.
  const todaySessionNo = channels.find((c) => c.has_schedule && c.session_no)?.session_no ?? null;
  const sessionKind =
    schedule?.days.flatMap((d) => d.items).find((i) => i.session_no === todaySessionNo)
      ?.session_kind ?? null;
  const headerMeta = todaySessionNo
    ? `${todayStr} · 제${todaySessionNo}회${sessionKind ? ` ${sessionKind}` : ''} 진행 중`
    : todayStr;

  return (
    <div data-testid="channel-selector" className="mx-auto flex max-w-[1360px] flex-col gap-7 px-4 py-6 sm:px-6">
      <PageHeader
        title="실시간 방송"
        meta={headerMeta}
        className="mb-0"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {liveChannels.length > 0 && (
              <span className="inline-flex h-8 items-center gap-1.5 rounded-md bg-live/10 px-3 text-[13px] font-semibold text-live">
                <span className="h-[7px] w-[7px] animate-live-pulse rounded-full bg-live" aria-hidden="true" />
                {liveChannels.length}개 방송 중
              </span>
            )}
            <span className="inline-flex h-8 items-center rounded-md bg-primary-5 px-3 text-[13px] font-semibold text-primary-dark">
              {scheduledChannels.length > 0 ? `오늘 ${scheduledChannels.length}개 예정` : '오늘 예정 없음'}
            </span>
            {subscribed.size > 0 && (
              <span
                className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border-strong bg-white px-3 text-[13px] font-medium text-text-secondary"
                title={
                  permission === 'denied'
                    ? '브라우저 알림 권한이 차단되어 있어 팝업이 뜨지 않습니다. 주소창 왼쪽 자물쇠 → 알림 허용으로 변경해 주세요.'
                    : permission === 'default'
                      ? '첫 방송 시작 시 알림 권한 요청 창이 뜹니다.'
                      : '등록해 둔 방송 시작 알람 개수'
                }
              >
                <svg className="h-[15px] w-[15px]" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24" aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" d={BELL_OUTLINE} />
                </svg>
                알람 {subscribed.size}개
              </span>
            )}
          </div>
        }
      />

      {/* ── 지금 방송 중 ───────────────────────────────────────────────── */}
      {liveChannels.length > 0 && (
        <section className="flex flex-col gap-3" aria-label="지금 방송 중">
          <SectionHeading live count={liveChannels.length}>
            지금 방송 중
          </SectionHeading>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {liveChannels.map((ch) => (
              <LiveChannelCard
                key={ch.id}
                channel={ch}
                onSelect={onSelect}
                thumbClassName="w-[180px] sm:w-[240px]"
                showStt
              />
            ))}
          </div>
        </section>
      )}

      {/* ── 오늘 예정 ─────────────────────────────────────────────────── */}
      {scheduledChannels.length > 0 && (
        <section className="flex flex-col gap-3" aria-label="오늘 예정">
          <SectionHeading count={scheduledChannels.length}>오늘 예정</SectionHeading>
          <div className="overflow-hidden rounded-[10px] border border-border bg-white">
            {scheduledChannels.map((ch) => (
              <div
                key={ch.id}
                className="flex items-center gap-3 border-b border-border-subtle px-4 py-3 last:border-b-0 sm:gap-4"
              >
                <button
                  type="button"
                  onClick={() => onSelect(ch)}
                  data-testid={`channel-${ch.id}`}
                  className="min-w-0 flex-1 truncate text-left text-[15px] font-medium text-text transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                >
                  {ch.name}
                </button>
                {ch.session_no != null && (
                  <span className="hidden w-[130px] shrink-0 text-[13px] tabular-nums text-text-muted sm:block">
                    제{ch.session_no}회 제{ch.session_order ?? 1}차
                  </span>
                )}
                <ScheduleStatusPill channel={ch} />
                <AlertBellButton
                  channelId={ch.id}
                  channelName={ch.name}
                  isOn={isSubscribed(ch.id)}
                  onToggle={() => handleAlertToggle(ch.id)}
                  permission={permission}
                  className="h-7 w-7"
                />
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ── 다가오는 일정 (내일부터) ──────────────────────────────────── */}
      <UpcomingScheduleSection schedule={schedule} />

      {/* ── 전체 채널 ─────────────────────────────────────────────────── */}
      <section className="flex flex-col gap-3" aria-label="전체 채널">
        <SectionHeading count={allChannels.length} note="방송 예정이 없는 채널도 알람을 걸어둘 수 있습니다">
          전체 채널
        </SectionHeading>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
          {allChannels.map((ch) => {
            const status = ch.livestatus ?? 0;
            const dot =
              status === 1 ? 'bg-live' : ch.has_schedule || status === 2 ? 'bg-primary' : 'bg-gray-200';
            return (
              <div
                key={ch.id}
                className={`flex items-center gap-1.5 rounded-md border border-border px-2.5 py-2 ${
                  status === 1 ? 'bg-live/[0.05]' : 'bg-white'
                }`}
              >
                <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} aria-hidden="true" />
                <button
                  type="button"
                  onClick={() => onSelect(ch)}
                  data-testid={`channel-all-${ch.id}`}
                  title={ch.name}
                  className={`min-w-0 flex-1 truncate text-left text-[12.5px] font-medium transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
                    status === 1 || ch.has_schedule ? 'text-text' : 'text-text-muted'
                  }`}
                >
                  {ch.name}
                </button>
                <AlertBellButton
                  channelId={`all-${ch.id}`}
                  channelName={ch.name}
                  isOn={isSubscribed(ch.id)}
                  onToggle={() => handleAlertToggle(ch.id)}
                  permission={permission}
                  className="h-5 w-5"
                />
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
