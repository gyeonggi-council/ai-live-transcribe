'use client';

import React, { useEffect, useRef, useState } from 'react';

import { formatWallClock } from '@/utils/meetingClock';

export interface VideoClockBadgeProps {
  /**
   * 지금 화면에 보이는 장면의 실제 시각(epoch ms)을 읽는 함수. 아직 모르면 null.
   *
   * ★값이 아니라 **함수**를 받는 이유: 라이브는 영상이 1초에 1초씩 흐르는데 부모의
   *   렌더는 그보다 드물 수 있다. 배지가 스스로 주기적으로 읽어야 초가 멈추지 않는다.
   */
  getWallMs: () => number | null;
  /** 날짜까지 보일지 — 라이브는 오늘이 자명하므로 시각만, VOD 는 날짜까지 */
  withDate?: boolean;
  /** 서버 기준점이 추정치(estimated)일 때 — "약"을 붙여 근사임을 드러낸다 */
  approximate?: boolean;
  /** 갱신 주기(ms). 기본 500 — 초 단위 표기가 최대 0.5초 늦게 바뀐다 */
  tickMs?: number;
  className?: string;
}

/**
 * 영상 위 실제 시각 배지 — "지금 이 화면이 실제로 몇 시였나".
 *
 * 왜 필요했나(2026-09-16 담당자): 화면 어디에도 실제 시각이 없어서, 회의 중 "그 발언이
 * 몇 시였나"를 영상만 보고는 알 수 없었다. 자막 목록에는 시각이 있었지만 영상에는 없었다.
 *
 * 라이브 영상은 자막 동기화를 위해 방송보다 20초쯤 뒤로 늦춰 재생되므로, 여기 표시하는
 * 시각은 **PC 시계가 아니라 그 장면이 실제로 발언된 시각**이다(사용자 결정) — 그래야
 * 옆 자막 목록의 시각과 한 화면에서 맞아떨어진다.
 *
 * ★의원 영상 추출(클립) 화면에는 붙이지 않는다 — 추출본은 원본 영상 그대로여야 한다.
 */
export default function VideoClockBadge({
  getWallMs,
  withDate = false,
  approximate = false,
  tickMs = 500,
  className = '',
}: VideoClockBadgeProps) {
  // 함수 신원이 바뀌어도 타이머를 다시 만들지 않는다 (라이브는 매 렌더마다 새 클로저)
  const getRef = useRef(getWallMs);
  getRef.current = getWallMs;

  const [text, setText] = useState<string | null>(null);

  useEffect(() => {
    const read = () => setText(formatWallClock(getRef.current(), { withDate }));
    read();
    const t = setInterval(read, tickMs);
    return () => clearInterval(t);
  }, [withDate, tickMs]);

  if (!text) return null;

  return (
    <div
      data-testid="video-clock"
      title={approximate ? '이 장면의 실제 시각 (자막 기록 시각에서 추정 — 10초 내외 오차)' : '이 장면의 실제 시각'}
      className={
        'pointer-events-none absolute right-2 top-2 z-10 flex items-center gap-1.5 rounded-md ' +
        'bg-black/55 px-2 py-1 text-white shadow-sm backdrop-blur-sm ' +
        className
      }
    >
      <span className="text-[10px] leading-none opacity-70">실제 시각</span>
      <span className="font-mono text-sm leading-none tabular-nums">
        {approximate ? `약 ${text}` : text}
      </span>
    </div>
  );
}
