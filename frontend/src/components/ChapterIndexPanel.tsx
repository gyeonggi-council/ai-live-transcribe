'use client';

import React, { useMemo } from 'react';

import type { AgendaType, SubtitleType } from '../types';

// =============================================================================
// Chapter Types & Builder
// =============================================================================

export interface Chapter {
  type: 'flow' | 'agenda' | 'speaker';
  label: string;
  title: string;
  previewText: string;
  startTime: number;
}

const BADGE_STYLES: Record<Chapter['type'], string> = {
  flow: 'bg-primary-10 text-primary-dark',
  agenda: 'bg-error/10 text-error',
  speaker: 'bg-success/10 text-success',
};

const BADGE_LABELS: Record<Chapter['type'], string> = {
  flow: '회의진행',
  agenda: '안건',
  speaker: '발언',
};

function truncate(text: string, max = 30): string {
  return text.length > max ? text.slice(0, max) + '…' : text;
}

function formatTime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const pad = (n: number) => n.toString().padStart(2, '0');
  return h > 0 ? `${pad(h)}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

/**
 * 자막의 화자 변경 지점 + 안건 데이터를 조합하여 회의 챕터 목록을 생성한다.
 *
 * 로직:
 * 1. 자막을 시간순 정렬 후, 화자 변경마다 챕터 생성 (첫 항목은 flow)
 * 2. 안건이 있으면, 자막 텍스트에서 안건 제목 키워드를 매칭하여 해당 시점에 삽입
 *    매칭 실패 시 order_num 기준으로 speaker 챕터 사이에 균등 배치
 * 3. 최종 startTime 순 정렬
 */
export function buildChapters(
  subtitles: SubtitleType[],
  agendas: AgendaType[]
): Chapter[] {
  if (subtitles.length === 0) return [];

  const sorted = [...subtitles].sort((a, b) => a.start_time - b.start_time);
  const chapters: Chapter[] = [];

  // 1) 화자 변경 기반 챕터 생성
  let prevSpeaker: string | null = null;
  for (let i = 0; i < sorted.length; i++) {
    const sub = sorted[i]!;
    const speaker = sub.speaker || '알 수 없음';

    if (i === 0) {
      // 첫 번째 = flow 챕터
      chapters.push({
        type: 'flow',
        label: BADGE_LABELS.flow,
        title: '회의 개의',
        previewText: truncate(sub.text),
        startTime: sub.start_time,
      });
      prevSpeaker = speaker;
      continue;
    }

    if (speaker !== prevSpeaker) {
      chapters.push({
        type: 'speaker',
        label: BADGE_LABELS.speaker,
        title: speaker,
        previewText: truncate(sub.text),
        startTime: sub.start_time,
      });
      prevSpeaker = speaker;
    }
  }

  // 2) 안건 삽입
  if (agendas.length > 0) {
    const sortedAgendas = [...agendas].sort(
      (a, b) => a.order_num - b.order_num
    );

    for (const agenda of sortedAgendas) {
      // 안건 제목 키워드를 자막에서 검색하여 시점 매칭
      const keywords = agenda.title
        .replace(/[의건에관한]/g, '')
        .split(/\s+/)
        .filter((w) => w.length >= 2);

      let matchTime: number | null = null;

      if (keywords.length > 0) {
        for (const sub of sorted) {
          const matched = keywords.some((kw) => sub.text.includes(kw));
          if (matched) {
            matchTime = sub.start_time;
            break;
          }
        }
      }

      // 매칭 실패 시 speaker 챕터 사이에 균등 배치
      if (matchTime === null && chapters.length > 1) {
        const speakerChapters = chapters.filter((c) => c.type === 'speaker');
        const idx = Math.min(
          agenda.order_num - 1,
          speakerChapters.length - 1
        );
        if (idx >= 0 && speakerChapters[idx]) {
          matchTime = speakerChapters[idx].startTime;
        }
      }

      // 여전히 없으면 첫 번째 자막 시간 사용
      if (matchTime === null) {
        matchTime = sorted[0]?.start_time ?? 0;
      }

      chapters.push({
        type: 'agenda',
        label: BADGE_LABELS.agenda,
        title: agenda.title,
        previewText: `제${agenda.order_num}호`,
        startTime: matchTime,
      });
    }
  }

  // 3) 시간순 정렬 (같은 시간이면 agenda > flow > speaker 순)
  const typeOrder: Record<Chapter['type'], number> = {
    agenda: 0,
    flow: 1,
    speaker: 2,
  };
  chapters.sort(
    (a, b) => a.startTime - b.startTime || typeOrder[a.type] - typeOrder[b.type]
  );

  return chapters;
}

// =============================================================================
// Component
// =============================================================================

interface ChapterIndexPanelProps {
  subtitles: SubtitleType[];
  agendas: AgendaType[];
  onChapterClick: (startTime: number) => void;
  currentTime?: number;
}

export default function ChapterIndexPanel({
  subtitles,
  agendas,
  onChapterClick,
  currentTime = 0,
}: ChapterIndexPanelProps) {
  const chapters = useMemo(
    () => buildChapters(subtitles, agendas),
    [subtitles, agendas]
  );

  // 현재 재생 위치에 해당하는 챕터 인덱스
  const activeIdx = useMemo(() => {
    let active = 0;
    for (let i = 0; i < chapters.length; i++) {
      if (chapters[i]!.startTime <= currentTime) {
        active = i;
      }
    }
    return active;
  }, [chapters, currentTime]);

  if (chapters.length === 0) {
    return (
      <div className="p-4 text-center text-sm text-gray-500">
        자막 데이터가 없어 진행순서를 생성할 수 없습니다.
      </div>
    );
  }

  return (
    <div data-testid="chapter-index-panel" className="space-y-1 p-2">
      {chapters.map((ch, idx) => {
        const isActive = idx === activeIdx;
        return (
          <button
            key={`${ch.type}-${ch.startTime}-${idx}`}
            onClick={() => onChapterClick(ch.startTime)}
            className={`w-full text-left p-2.5 rounded-lg transition-colors hover:bg-gray-50 ${
              isActive ? 'bg-primary-5 ring-1 ring-primary-20' : ''
            }`}
          >
            <div className="flex items-center gap-2 mb-0.5">
              <span
                className={`inline-block px-1.5 py-0.5 rounded text-xs font-medium ${BADGE_STYLES[ch.type]}`}
              >
                {ch.label}
              </span>
              <span className="text-xs text-gray-400 tabular-nums">
                {formatTime(ch.startTime)}
              </span>
            </div>
            <p className="text-sm font-medium text-gray-800 leading-snug">
              {ch.title}
            </p>
            {ch.type === 'speaker' && (
              <p className="text-xs text-gray-500 mt-0.5 truncate">
                {ch.previewText}
              </p>
            )}
          </button>
        );
      })}
    </div>
  );
}
