'use client';

import React from 'react';

import Link from 'next/link';

import type { ChannelType } from '@/types';

export interface LiveChannelCardProps {
  channel: ChannelType;
  /** 이동 방식 — 링크(대시보드) 또는 콜백(실시간 방송 목록의 채널 선택) */
  onSelect?: (channel: ChannelType) => void;
  /** 좌측 영상 자리의 폭 — 대시보드 216px / 실시간 방송 목록 240px */
  thumbClassName?: string;
  /** STT 가동 여부 칩을 함께 보여준다 (실시간 방송 목록에서만) */
  showStt?: boolean;
  className?: string;
}

/**
 * 방송 중인 채널 한 장 — 대시보드(2d)와 실시간 방송 목록(2b)이 함께 쓴다.
 *
 * 예전 카드는 네이비로 꽉 채운 20px 배지 칸 하나에 위원회명·회차·시청 링크를 눌러 담아
 * "지금 어느 회의가 어디까지 왔는지"가 안 읽혔다. 여기서는 16:9 영상 자리를 실제로 두고
 * 그 옆에 **상태 문구 → 위원회명 → 회차 → 시청 버튼** 순으로 펼친다
 * (2026-08-25 개선안 2b·2d).
 *
 * 영상 자리는 아직 미리보기 이미지가 없어 검은 판 + 아이콘이다. 자리를 미리 잡아 둬야
 * 나중에 썸네일이 생겨도 레이아웃이 흔들리지 않는다.
 */
export default function LiveChannelCard({
  channel,
  onSelect,
  thumbClassName = 'w-[216px]',
  showStt = false,
  className = '',
}: LiveChannelCardProps) {
  const statusText = channel.status_text || '방송 중';

  const shell = `group flex overflow-hidden rounded-[10px] border border-border bg-white text-left transition-colors hover:border-primary-20 hover:bg-primary-5/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${className}`.trim();

  const body = (
    <>
      <div
        className={`relative flex aspect-video shrink-0 items-center justify-center bg-gray-950 ${thumbClassName}`}
      >
        <svg
          className="h-8 w-8 text-white/25"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.25}
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="m15.75 10.5 4.72-4.72a.75.75 0 0 1 1.28.53v11.38a.75.75 0 0 1-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 0 0 2.25-2.25v-9a2.25 2.25 0 0 0-2.25-2.25h-9A2.25 2.25 0 0 0 2.25 7.5v9a2.25 2.25 0 0 0 2.25 2.25Z"
          />
        </svg>

        <span className="absolute left-2.5 top-2.5 inline-flex items-center gap-1.5 rounded bg-danger px-2 py-[3px] text-[10px] font-bold tracking-[0.06em] text-white">
          <span className="relative flex h-[5px] w-[5px]">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-white opacity-75" />
            <span className="relative inline-flex h-[5px] w-[5px] rounded-full bg-white" />
          </span>
          LIVE
        </span>

        {channel.viewers != null && (
          <span className="absolute bottom-2.5 right-2.5 rounded bg-black/70 px-1.5 py-0.5 text-[11px] font-semibold tabular-nums text-white">
            {channel.viewers}명
          </span>
        )}
      </div>

      <div className="flex min-w-0 flex-1 flex-col gap-1.5 px-4 py-3.5">
        <div className="text-[11px] font-semibold tracking-[0.06em] text-live">{statusText}</div>
        <div className="truncate text-[17px] font-bold leading-tight tracking-heading text-text">
          {channel.name}
        </div>
        {channel.session_no != null && (
          <div className="text-[13px] tabular-nums text-text-muted">
            제{channel.session_no}회 제{channel.session_order ?? 1}차
          </div>
        )}
        <div className="mt-auto flex items-center gap-2 pt-1.5">
          <span className="inline-flex h-[34px] items-center gap-1.5 rounded-md bg-primary px-3.5 text-sm font-semibold text-white transition-colors group-hover:bg-primary-light">
            <svg className="h-[15px] w-[15px]" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true">
              <path
                fillRule="evenodd"
                d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z"
                clipRule="evenodd"
              />
            </svg>
            자막 보기
          </span>
          {showStt && (
            <span
              className={`inline-flex items-center rounded-full px-2 py-[3px] text-[11px] font-semibold ${
                channel.stt_running ? 'bg-success/10 text-success' : 'bg-gray-100 text-text-muted'
              }`}
              title={
                channel.stt_running
                  ? '이 채널의 실시간 자막이 만들어지고 있습니다'
                  : '방송 중이지만 실시간 자막이 만들어지지 않고 있습니다'
              }
            >
              STT {channel.stt_running ? 'ON' : 'OFF'}
            </span>
          )}
        </div>
      </div>
    </>
  );

  // 대시보드는 링크로, 실시간 방송 목록은 콜백으로 채널을 연다 —
  // 목록 쪽은 선택 즉시 같은 화면에서 플레이어로 바뀌므로 라우팅 주체가 페이지다.
  if (onSelect) {
    return (
      <button
        type="button"
        onClick={() => onSelect(channel)}
        className={shell}
        data-testid={`channel-${channel.id}`}
        data-channel={channel.id}
      >
        {body}
      </button>
    );
  }

  return (
    <Link
      href={`/live?channel=${channel.id}`}
      className={shell}
      data-testid="live-channel-card"
      data-channel={channel.id}
    >
      {body}
    </Link>
  );
}
