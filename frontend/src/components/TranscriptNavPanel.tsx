'use client';

import React, { useMemo } from 'react';

import type { AgendaType, MeetingType, SubtitleType } from '@/types';

import { buildChapters } from './ChapterIndexPanel';


interface TranscriptNavPanelProps {
  subtitles: SubtitleType[];
  agendas: AgendaType[];
  meeting: MeetingType;
  currentTime: number;
  onChapterClick: (startTime: number) => void;
  onSpeakerClick?: (speaker: string) => void;
}

function formatTime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const pad = (n: number) => n.toString().padStart(2, '0');
  return h > 0 ? `${pad(h)}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

const BADGE_STYLES: Record<string, string> = {
  flow: 'bg-primary-10 text-primary-dark',
  agenda: 'bg-error/10 text-error',
  speaker: 'bg-success/10 text-success',
};

/**
 * 속기 편집 좌측 네비게이션 패널
 *
 * 3개 섹션: 진행순서 / 화자 요약 / 회의 정보
 */
export default function TranscriptNavPanel({
  subtitles,
  agendas,
  meeting,
  currentTime,
  onChapterClick,
  onSpeakerClick,
}: TranscriptNavPanelProps) {
  const chapters = useMemo(
    () => buildChapters(subtitles, agendas),
    [subtitles, agendas]
  );

  // 현재 재생 위치에 해당하는 챕터 인덱스
  const activeChapterIdx = useMemo(() => {
    let active = 0;
    for (let i = 0; i < chapters.length; i++) {
      if (chapters[i]!.startTime <= currentTime) {
        active = i;
      }
    }
    return active;
  }, [chapters, currentTime]);

  // 화자별 발언 통계
  const speakerStats = useMemo(() => {
    const map = new Map<string, { count: number; totalTime: number; firstTime: number }>();
    for (const sub of subtitles) {
      const speaker = sub.speaker || '(미지정)';
      const existing = map.get(speaker);
      const duration = Math.max(0, sub.end_time - sub.start_time);
      if (existing) {
        existing.count += 1;
        existing.totalTime += duration;
      } else {
        map.set(speaker, { count: 1, totalTime: duration, firstTime: sub.start_time });
      }
    }
    return Array.from(map.entries())
      .sort((a, b) => b[1].totalTime - a[1].totalTime);
  }, [subtitles]);

  return (
    <div
      data-testid="transcript-nav-panel"
      className="h-full flex flex-col overflow-hidden bg-white border-r border-gray-200"
    >
      {/* 회의 정보 */}
      <div className="p-3 border-b border-gray-200">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
          회의 정보
        </h3>
        <p className="text-sm font-medium text-gray-900 leading-snug mb-1 line-clamp-2">
          {meeting.title}
        </p>
        <div className="space-y-0.5 text-xs text-gray-500">
          {meeting.committee && <p>{meeting.committee}</p>}
          <p>{meeting.meeting_date}</p>
          <span
            className={`inline-block px-1.5 py-0.5 rounded text-xs font-medium ${
              meeting.status === 'ended'
                ? 'bg-gray-100 text-gray-600'
                : meeting.status === 'live'
                ? 'bg-error/10 text-error'
                : 'bg-warning-bg/20 text-warning'
            }`}
          >
            {meeting.status === 'ended' ? '종료' : meeting.status === 'live' ? 'LIVE' : meeting.status}
          </span>
        </div>
      </div>

      {/* 화자 요약 */}
      <div className="p-3 border-b border-gray-200">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
          화자 요약
        </h3>
        <div className="space-y-1 max-h-40 overflow-y-auto">
          {speakerStats.map(([speaker, stats]) => (
            <button
              key={speaker}
              onClick={() => onSpeakerClick?.(speaker)}
              className="w-full text-left flex items-center justify-between py-1 px-1.5 rounded hover:bg-gray-50 transition-colors"
            >
              <span className="text-xs font-medium text-gray-800 truncate flex-1">
                {speaker}
              </span>
              <span className="text-xs text-gray-400 ml-1 flex-shrink-0">
                {stats.count}회
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* 진행순서 */}
      <div className="flex-1 overflow-y-auto p-2">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2 px-1">
          진행순서
        </h3>
        <div className="space-y-0.5">
          {chapters.map((ch, idx) => {
            const isActive = idx === activeChapterIdx;
            return (
              <button
                key={`${ch.type}-${ch.startTime}-${idx}`}
                onClick={() => onChapterClick(ch.startTime)}
                className={`w-full text-left p-2 rounded transition-colors hover:bg-gray-50 ${
                  isActive ? 'bg-primary-5 ring-1 ring-primary-20' : ''
                }`}
              >
                <div className="flex items-center gap-1.5 mb-0.5">
                  <span
                    className={`inline-block px-1 py-0.5 rounded text-[10px] font-medium ${BADGE_STYLES[ch.type] || ''}`}
                  >
                    {ch.label}
                  </span>
                  <span className="text-[10px] text-gray-400 tabular-nums">
                    {formatTime(ch.startTime)}
                  </span>
                </div>
                <p className="text-xs font-medium text-gray-800 leading-snug truncate">
                  {ch.title}
                </p>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
