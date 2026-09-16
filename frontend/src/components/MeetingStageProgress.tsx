'use client';

import React from 'react';

import type { MeetingType } from '@/types';
import {
  LIST_SEGMENT_CLASS,
  LIST_STAGE_LEGEND,
  MEETING_STAGES,
  STAGE_NODE_CLASS,
  getListSegments,
  getMeetingStage,
  type MeetingStageInfo,
} from '@/utils/meetingStage';

/** 단계별 아이콘 — 마이크(실시간) / 영상(VOD) / 반짝임(AI 자막).
 *  마지막 칸은 끝나면 체크로 바뀐다(showCheck) — 진행 중일 때 체크가 보이면 안 된다. */
const STAGE_ICON_PATH: Record<string, string> = {
  live: 'M12 18.75a6 6 0 006-6v-1.5m-6 7.5a6 6 0 01-6-6v-1.5m6 7.5v3.75m0 0h3.75m-3.75 0H8.25M12 15.75a3 3 0 01-3-3V4.5a3 3 0 116 0v8.25a3 3 0 01-3 3z',
  vod: 'M15.75 10.5l4.72-4.72a.75.75 0 011.28.53v11.38a.75.75 0 01-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 002.25-2.25v-9a2.25 2.25 0 00-2.25-2.25h-9A2.25 2.25 0 002.25 7.5v9a2.25 2.25 0 002.25 2.25z',
  ai_done:
    'M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z',
};

const CHECK_PATH = 'M4.5 12.75l6 6 9-13.5';

export interface MeetingStageProgressProps {
  meeting: Pick<MeetingType, 'status'> &
    Partial<Pick<MeetingType, 'subtitle_stage' | 'vod_url'>>;
  /** sm — 목록 카드 / md — 회의 상세 상단 */
  size?: 'sm' | 'md';
  /** 단계 라벨을 감춘다 (아주 좁은 자리) */
  hideLabels?: boolean;
  /**
   * 'stepper'  — 아이콘 3칸 + 라벨. 회의 상세 상단처럼 자리가 넉넉한 곳
   * 'segments' — 라벨 없는 2칸 막대. 회의 목록의 행처럼 이름을 반복하면 안 되는 곳
   *              (단계 이름은 목록 머리 범례에 한 번만 나온다 — 개선안 2f)
   */
  variant?: 'stepper' | 'segments';
  className?: string;
}

/**
 * 자막 처리 3단계 진행바 — 대시보드·회의 목록·회의 상세가 모두 이 컴포넌트 하나를 쓴다.
 *
 * 색 규칙:
 *  - AI 자막 완료 회의는 세 단계 모두 초록. "다 끝났다"가 한눈에 보여야 한다.
 *  - 진행 중이면 지난 단계는 회색 체크, 현재 단계만 단계 색(생중계 빨강 / 진행 파랑 / 생성 중 주황).
 */
export default function MeetingStageProgress({
  meeting,
  size = 'sm',
  hideLabels = false,
  variant = 'stepper',
  className = '',
}: MeetingStageProgressProps) {
  const info: MeetingStageInfo = getMeetingStage(meeting);
  const allDone = info.states.every((s) => s === 'done');

  if (variant === 'segments') {
    const segments = getListSegments(meeting);
    return (
      <span
        className={`flex gap-1.5 ${className}`.trim()}
        data-testid="meeting-stage-progress"
        data-stage={info.filterKey}
        aria-label={`자막 처리 단계: ${info.statusLabel}`}
      >
        {segments.map((tone, i) => (
          <span
            key={LIST_STAGE_LEGEND[i]?.key ?? i}
            className={`h-1.5 flex-1 rounded-full ${LIST_SEGMENT_CLASS[tone]}`}
            data-testid={`stage-segment-${LIST_STAGE_LEGEND[i]?.key ?? i}`}
            data-tone={tone}
            title={LIST_STAGE_LEGEND[i]?.tip}
          />
        ))}
      </span>
    );
  }

  const nodeSize = size === 'md' ? 'h-7 w-7' : 'h-5 w-5';
  const iconSize = size === 'md' ? 'h-4 w-4' : 'h-3 w-3';
  const labelSize = size === 'md' ? 'text-[11px] sm:text-xs' : 'text-[10px]';
  const lineTop = size === 'md' ? 'top-3.5' : 'top-2.5';

  // 연결선 — 완료 회의는 초록, 그 외 지나온 구간은 파랑
  const lineOn = allDone ? 'bg-success' : 'bg-primary-30';
  const lineOff = 'bg-gray-200';

  return (
    <div
      className={`grid grid-cols-3 ${className}`.trim()}
      data-testid="meeting-stage-progress"
      data-stage={info.filterKey}
      aria-label={`자막 처리 단계: ${info.statusLabel}`}
    >
      {MEETING_STAGES.map((stage, i) => {
        const state = info.states[i];
        const isCurrent = state === 'current';

        // 노드 색: 완료 회의는 전부 초록 / 지난 단계는 옅은 회색 체크 / 현재 단계만 단계 색
        const nodeClass = allDone
          ? 'bg-success text-white'
          : state === 'done'
            ? 'bg-gray-100 text-gray-500'
            : isCurrent
              ? `${STAGE_NODE_CLASS[info.tone]} ring-4 ring-primary-5`
              : 'border border-gray-200 bg-white text-gray-300';

        const showCheck = allDone || state === 'done';
        const path = showCheck ? CHECK_PATH : STAGE_ICON_PATH[stage.key];

        return (
          <div
            key={stage.key}
            className="relative flex min-w-0 flex-col items-center"
            aria-current={isCurrent ? 'step' : undefined}
            title={`${stage.label} — ${stage.description}`}
          >
            {/* 연결선 — 노드 뒤를 지나가므로 z-0 */}
            {i > 0 && (
              <span
                aria-hidden="true"
                className={`absolute left-0 ${lineTop} z-0 h-0.5 w-1/2 ${
                  state === 'pending' ? lineOff : lineOn
                }`}
              />
            )}
            {i < MEETING_STAGES.length - 1 && (
              <span
                aria-hidden="true"
                className={`absolute right-0 ${lineTop} z-0 h-0.5 w-1/2 ${
                  info.states[i + 1] === 'pending' ? lineOff : lineOn
                }`}
              />
            )}

            <span
              className={`relative z-10 flex ${nodeSize} shrink-0 items-center justify-center rounded-full ${nodeClass}`}
              data-testid={`stage-node-${stage.key}`}
              data-state={state}
            >
              <svg
                className={iconSize}
                fill="none"
                stroke="currentColor"
                strokeWidth={showCheck ? 2.5 : 1.8}
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <path strokeLinecap="round" strokeLinejoin="round" d={path} />
              </svg>
            </span>

            {!hideLabels && (
              <span
                className={`mt-1.5 whitespace-pre-line px-0.5 text-center leading-tight ${labelSize} ${
                  isCurrent ? 'font-semibold text-text' : 'text-text-muted'
                }`}
              >
                {stage.label}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
