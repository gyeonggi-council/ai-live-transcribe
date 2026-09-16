'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { CouncilorType, SubtitleType } from '@/types';

import CouncilorPicker from './CouncilorPicker';


/**
 * 화자별 문단 구조
 */
interface SpeakerParagraph {
  speaker: string | null;
  subtitleIds: string[];
  startTime: number;
  endTime: number;
  fullText: string;
  subtitleBoundaries: number[];
  councilor?: CouncilorType;
}

/** 정당별 컬러 매핑 */
function getPartyBadgeClass(party: string | null): string {
  if (!party) return 'bg-gray-100 text-gray-600';
  if (party.includes('민주')) return 'bg-party-dem/10 text-party-dem';
  if (party.includes('국민의힘')) return 'bg-party-pp/10 text-party-pp';
  if (party.includes('정의')) return 'bg-warning-bg/20 text-warning';
  return 'bg-gray-100 text-gray-600';
}

interface ProseTranscriptEditorProps {
  subtitles: SubtitleType[];
  currentTime: number;
  councilors: CouncilorType[];
  onTextChange: (subtitleId: string, newText: string) => void;
  onSpeakerChange: (subtitleId: string, newSpeaker: string) => void;
  onSeek: (time: number) => void;
  committeeFilter?: string;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

/**
 * 자막을 화자별 문단으로 그룹핑합니다.
 */
const MAX_GROUP_DURATION = 150; // 2.5분 — 긴 발언을 가독성 있게 분할

function groupIntoParagraphs(
  subtitles: SubtitleType[],
  councilors: CouncilorType[]
): SpeakerParagraph[] {
  if (subtitles.length === 0) return [];

  const councilorByName = new Map<string, CouncilorType>();
  for (const c of councilors) {
    councilorByName.set(c.name, c);
  }

  const paragraphs: SpeakerParagraph[] = [];
  let current: SpeakerParagraph | null = null;

  for (const sub of subtitles) {
    const speaker = sub.speaker || null;
    const shouldSplit =
      current &&
      current.speaker === speaker &&
      (sub.start_time - current.startTime) >= MAX_GROUP_DURATION;

    if (!current || current.speaker !== speaker || shouldSplit) {
      // 새 문단 시작
      if (current) paragraphs.push(current);
      current = {
        speaker,
        subtitleIds: [sub.id],
        startTime: sub.start_time,
        endTime: sub.end_time,
        fullText: sub.text,
        subtitleBoundaries: [0],
        councilor: speaker ? councilorByName.get(speaker) : undefined,
      };
    } else {
      // 같은 화자 → 문단에 추가
      const separator = ' ';
      current.subtitleBoundaries.push(current.fullText.length + separator.length);
      current.fullText += separator + sub.text;
      current.subtitleIds.push(sub.id);
      current.endTime = sub.end_time;
    }
  }
  if (current) paragraphs.push(current);

  return paragraphs;
}

/**
 * 문단형 속기 편집기
 *
 * 자막을 화자별 문단으로 그룹핑하여 줄글 형태로 편집합니다.
 * 각 문단은 화자 헤더 + textarea로 구성됩니다.
 */
export default function ProseTranscriptEditor({
  subtitles,
  currentTime,
  councilors,
  onTextChange,
  onSpeakerChange,
  onSeek,
  committeeFilter,
}: ProseTranscriptEditorProps) {
  const paragraphs = useMemo(
    () => groupIntoParagraphs(subtitles, councilors),
    [subtitles, councilors]
  );

  // 문단별 로컬 텍스트 상태 (편집 중 원본과 분리)
  const [localTexts, setLocalTexts] = useState<Map<number, string>>(new Map());
  const paragraphRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  // paragraphs 변경 시 로컬 텍스트 리셋
  useEffect(() => {
    setLocalTexts(new Map());
  }, [paragraphs.length]);

  // 현재 재생 위치에 해당하는 문단으로 스크롤
  const activeParagraphIndex = useMemo(() => {
    return paragraphs.findIndex(
      (p) => currentTime >= p.startTime && currentTime < p.endTime
    );
  }, [currentTime, paragraphs]);

  useEffect(() => {
    if (activeParagraphIndex >= 0) {
      const el = paragraphRefs.current.get(activeParagraphIndex);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    }
  }, [activeParagraphIndex]);

  /**
   * 문단 텍스트 변경 → 원본 자막 단위로 역매핑
   */
  const handleParagraphTextChange = useCallback(
    (paragraphIndex: number, newFullText: string) => {
      const para = paragraphs[paragraphIndex];
      if (!para) return;

      // 로컬 상태 업데이트
      setLocalTexts((prev) => {
        const next = new Map(prev);
        next.set(paragraphIndex, newFullText);
        return next;
      });

      // 자막 단위로 역매핑
      const boundaries = para.subtitleBoundaries;
      const ids = para.subtitleIds;

      for (let i = 0; i < ids.length; i++) {
        const start = boundaries[i]!;
        const end = i + 1 < boundaries.length ? boundaries[i + 1]! - 1 : newFullText.length;
        const segmentText = newFullText.slice(start, end).trim();
        onTextChange(ids[i]!, segmentText);
      }
    },
    [paragraphs, onTextChange]
  );

  const handleSpeakerChange = useCallback(
    (paragraphIndex: number, newSpeaker: string) => {
      const para = paragraphs[paragraphIndex];
      if (!para) return;

      // 문단의 모든 자막 화자를 변경
      for (const subId of para.subtitleIds) {
        onSpeakerChange(subId, newSpeaker);
      }
    },
    [paragraphs, onSpeakerChange]
  );

  if (subtitles.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">
        자막이 없습니다.
      </div>
    );
  }

  return (
    <div
      data-testid="prose-transcript-editor"
      className="flex-1 overflow-y-auto space-y-4 pr-1"
    >
      {paragraphs.map((para, index) => {
        const isActive = index === activeParagraphIndex;
        const displayText = localTexts.get(index) ?? para.fullText;

        return (
          <div
            key={`${para.subtitleIds[0]}-${index}`}
            ref={(el) => {
              if (el) {
                paragraphRefs.current.set(index, el);
              } else {
                paragraphRefs.current.delete(index);
              }
            }}
            className={`rounded-lg border transition-colors ${
              isActive
                ? 'border-primary-30 bg-primary-5/30 border-l-4 border-l-primary'
                : 'border-gray-200 bg-white'
            }`}
          >
            {/* 화자 헤더 */}
            <div className="flex items-center gap-2 px-3 py-2.5 border-b border-gray-100">
              {/* 의원 아바타 (40px) */}
              {para.councilor?.profile_image_url ? (
                <img
                  src={para.councilor.profile_image_url}
                  alt={para.speaker || ''}
                  className="w-10 h-10 rounded-full object-cover flex-shrink-0"
                  onError={(e) => {
                    (e.target as HTMLImageElement).style.display = 'none';
                  }}
                />
              ) : para.speaker ? (
                <div className="w-10 h-10 rounded-full bg-gray-200 flex items-center justify-center flex-shrink-0">
                  <span className="text-sm text-gray-500">
                    {para.speaker.charAt(0)}
                  </span>
                </div>
              ) : null}

              {/* 화자 선택 + 의원 인라인 정보 */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <CouncilorPicker
                    value={para.speaker || ''}
                    onChange={(speaker) => handleSpeakerChange(index, speaker)}
                    placeholder="화자 선택"
                    className="max-w-[200px]"
                    committeeFilter={committeeFilter}
                  />
                  {/* 정당 컬러 배지 */}
                  {para.councilor?.party && (
                    <span className={`px-1.5 py-0.5 rounded text-xs font-medium flex-shrink-0 ${getPartyBadgeClass(para.councilor.party)}`}>
                      {para.councilor.party}
                    </span>
                  )}
                </div>
                {/* 선거구 + 위원회 역할 */}
                {para.councilor && (
                  <p className="text-xs text-gray-400 mt-0.5 truncate">
                    {[
                      para.councilor.district,
                      para.councilor.committee,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </p>
                )}
              </div>

              {/* 시간 범위 */}
              <button
                onClick={() => onSeek(para.startTime)}
                className="text-xs text-gray-400 hover:text-primary transition-colors ml-auto flex-shrink-0"
              >
                {formatTime(para.startTime)} ~ {formatTime(para.endTime)}
              </button>
            </div>

            {/* 텍스트 편집 영역 (대형) */}
            <textarea
              data-testid={`prose-paragraph-${index}`}
              value={displayText}
              onChange={(e) => {
                handleParagraphTextChange(index, e.target.value);
                // Auto-resize
                e.target.style.height = 'auto';
                e.target.style.height = e.target.scrollHeight + 'px';
              }}
              onFocus={(e) => {
                e.target.style.height = 'auto';
                e.target.style.height = e.target.scrollHeight + 'px';
              }}
              rows={3}
              className="w-full px-4 py-3 text-base leading-relaxed border-0 resize-none focus:outline-none focus:ring-0 bg-transparent"
              style={{ minHeight: '6rem' }}
            />
          </div>
        );
      })}
    </div>
  );
}
