import React, { useCallback, useState } from 'react';

import { highlightText as highlightTextUtil } from '../utils/highlight';


export interface SubtitleItemProps {
  startTime: number;
  /** 종료 시간(초). 설정 시 "시작~종료" 범위로 표시 */
  endTime?: number;
  text: string;
  speaker?: string | null;
  isCurrent?: boolean;
  highlightQuery?: string;
  onClick?: (startTime: number) => void;
  /** ▶(시간 칩) 클릭 시 이 구간의 녹음 음성 재생 콜백 */
  onPlayAudio?: () => void;
  /** 지금 이 구간의 음성이 재생 중인가 — 칩을 ■(정지)로 바꾸고 눈에 띄게 표시한다 */
  isPlayingAudio?: boolean;
  /** 실제 시계 시간 (ISO string 또는 Date). 설정 시 경과 시간 옆에 표시 */
  clockTime?: string | null;
  /** 실시간 모드 여부. true면 클릭 시 시점 이동 불가 안내 */
  isLive?: boolean;
  /** 실시간 클릭 시 안내 콜백 */
  onLiveClickNotice?: () => void;
  /** AI 교정 완료 여부 */
  isCorrected?: boolean;
  /** 같은 화자의 연속 자막일 때 true → 화자 배지 숨김 + 상단 패딩 축소 */
  isGroupContinuation?: boolean;
  /**
   * 실시간 화면의 '지금 발언'. 목록의 한 줄이 아니라 카드로 크게 띄운다 —
   * 회의를 보면서 읽는 화면이라 현재 발언이 과거 발언과 같은 크기면 눈이 헤맨다.
   */
  isLatestLive?: boolean;
  /** 교정 상태: pending=AI 교정 대기, corrected=교정 완료 직후, none=안정 */
  correctionState?: 'pending' | 'corrected' | 'none';
  /** 교정 전 원본 텍스트. corrected 상태에서 단어 수준 diff 표시에 사용 */
  originalText?: string;
}

/**
 * Returns Tailwind CSS classes for speaker badge based on speaker name
 */
const SPEAKER_COLORS = [
  { bg: 'bg-blue-50', text: 'text-blue-700' },
  { bg: 'bg-green-50', text: 'text-green-700' },
  { bg: 'bg-purple-50', text: 'text-purple-700' },
  { bg: 'bg-orange-50', text: 'text-orange-700' },
  { bg: 'bg-pink-50', text: 'text-pink-700' },
  { bg: 'bg-teal-50', text: 'text-teal-700' },
  { bg: 'bg-indigo-50', text: 'text-indigo-700' },
  { bg: 'bg-red-50', text: 'text-red-700' },
];

function getSpeakerColor(speaker: string | null): { bg: string; text: string } {
  if (!speaker) {
    return { bg: 'bg-surface-raised', text: 'text-text-secondary' };
  }
  // Hash speaker name to get consistent color
  let hash = 0;
  for (let i = 0; i < speaker.length; i++) {
    hash = ((hash << 5) - hash + speaker.charCodeAt(i)) | 0;
  }
  return SPEAKER_COLORS[Math.abs(hash) % SPEAKER_COLORS.length]!;
}

function formatTime(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);

  return [hours, minutes, secs]
    .map((v) => v.toString().padStart(2, '0'))
    .join(':');
}

/**
 * Renders text with optional query highlighting
 * Uses the shared highlight utility for XSS-safe highlighting
 */
function renderHighlightedText(text: string, query?: string): React.ReactNode {
  if (!query || query.trim() === '') {
    return text;
  }

  const result = highlightTextUtil(text, query);

  if (!result.hasMatch) {
    return text;
  }

  // Using dangerouslySetInnerHTML is safe here because highlightTextUtil
  // properly escapes all HTML in the input text before adding highlight marks
  // Convert \n to <br/> since dangerouslySetInnerHTML bypasses whitespace-pre-line
  return (
    <span
      dangerouslySetInnerHTML={{ __html: result.html.replace(/\n/g, '<br/>') }}
    />
  );
}

export default function SubtitleItem({
  startTime,
  endTime,
  text,
  speaker,
  isCurrent = false,
  highlightQuery,
  onClick,
  onPlayAudio,
  isPlayingAudio = false,
  clockTime,
  isLive = false,
  onLiveClickNotice,
  isCorrected = false,
  isGroupContinuation = false,
  isLatestLive = false,
  correctionState,
  originalText: _originalText,
}: SubtitleItemProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [text]);

  const paddingStyles = isLatestLive
    ? 'px-4 py-4'
    : isGroupContinuation
      ? 'px-4 pt-1.5 pb-3'
      : 'px-4 py-3';
  const separatorStyles = isGroupContinuation && !isLatestLive
    ? 'border-b border-dashed border-border'
    : 'border-b border-border';
  const baseStyles = `group w-full text-left ${paddingStyles} ${separatorStyles} cursor-pointer transition-colors hover:bg-surface-raised relative`;
  const currentStyles = isLatestLive
    ? 'bg-primary-5 ring-1 ring-inset ring-brand/30'
    : isCurrent
      ? 'bg-primary-5 border-l-4 border-brand'
      : '';

  const handleClick = () => {
    if (isLive) {
      onLiveClickNotice?.();
      return;
    }
    onClick?.(startTime);
  };

  const speakerColors = getSpeakerColor(speaker ?? null);
  const showSpeaker = speaker && !isGroupContinuation;

  // 교정 이벤트 직후 text가 null/undefined로 잠시 올 수 있으므로 null-safe
  const safeText = text ?? '';
  const lines = safeText.split('\n');

  return (
    <button
      type="button"
      onClick={handleClick}
      className={`${baseStyles} ${currentStyles}`.trim()}
      title="클릭하여 해당 시점으로 이동"
      data-testid="subtitle-item"
    >
      <span className="flex items-center gap-2 mb-1">
        {isLatestLive && (
          <span
            className="inline-flex items-center gap-1 rounded bg-live px-1.5 py-0.5 text-[11px] font-bold tracking-wide text-white"
            data-testid="latest-live-badge"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-white animate-live-pulse" aria-hidden="true" />
            LIVE
          </span>
        )}
        <span
          role={onPlayAudio ? 'button' : undefined}
          tabIndex={onPlayAudio ? 0 : undefined}
          onClick={
            onPlayAudio
              ? (e: React.MouseEvent) => {
                  e.stopPropagation();
                  onPlayAudio();
                }
              : undefined
          }
          className={`inline-flex items-center gap-1 font-mono text-xs rounded px-1.5 py-0.5 transition-colors ${
            isPlayingAudio
              ? 'bg-brand text-white font-bold ring-2 ring-brand/40'
              : 'text-brand bg-brand/10 hover:bg-brand/20'
          }`}
          data-testid="time-chip"
          data-playing={isPlayingAudio ? 'true' : undefined}
          aria-pressed={onPlayAudio ? isPlayingAudio : undefined}
          title={
            onPlayAudio
              ? isPlayingAudio
                ? '재생 중 — 누르면 멈춥니다'
                : '이 구간 음성 듣기'
              : undefined
          }
        >
          {/* 재생 중에는 ■(정지)로 바뀌고 점이 깜빡인다 — '지금 이 구간이 들리는 중' */}
          {isPlayingAudio ? (
            <>
              <span
                className="h-1.5 w-1.5 shrink-0 rounded-full bg-white animate-live-pulse"
                aria-hidden="true"
              />
              <span className="text-[10px] leading-none" aria-hidden="true">■</span>
            </>
          ) : (
            <span className="text-[10px] leading-none" aria-hidden="true">▶</span>
          )}
          {formatTime(startTime)}
          {endTime != null && endTime > startTime && `~${formatTime(endTime)}`}
          {isPlayingAudio && <span className="ml-0.5 text-[10px] font-sans">재생 중</span>}
        </span>
        {clockTime && (
          <span className="font-mono text-xs text-text-muted" title="실제 시각">
            ({clockTime})
          </span>
        )}
        {showSpeaker && (
          <span
            className={`rounded-full px-2 py-0.5 font-medium ${
              isLatestLive ? 'text-base font-bold' : 'text-sm'
            } ${speakerColors.bg} ${speakerColors.text}`}
          >
            {speaker?.replace(/^화자\s*/, '') || speaker}
          </span>
        )}
      </span>
      {/* 현재 텍스트 (보정 후 최종 텍스트만 표시) — 모바일에선 한 단계 크게,
          실시간 '지금 발언'은 한 단계 더 크게 (영상 보며 읽는 거리)
          data-subtitle-text — 자막 패널의 '글자 크기(Aa)' 가 이 표식을 잡아 키운다.
          크기를 prop 으로 내리면 목록의 모든 항목에 값을 흘려야 하고, 그 값이
          SubtitlePanel·LiveViewer·VOD 상세 세 곳에서 각자 관리된다. */}
      <span
        data-subtitle-text
        className={`block text-text leading-relaxed ${
          isLatestLive ? 'text-[21px] font-medium sm:text-lg' : 'text-[17px] sm:text-base'
        }${correctionState === 'pending' ? ' text-text-muted' : ''}`}
        data-correction-state={correctionState || 'none'}
      >
        {lines.map((line, i) => (
          <span key={i} className="block mb-2 last:mb-0">
            {renderHighlightedText(line, highlightQuery)}
            {correctionState === 'pending' && i === lines.length - 1 && (
              <>
                <span
                  className="inline-block ml-1.5 w-3 h-3 border-2 border-warning-bg border-t-transparent rounded-full animate-spin align-middle"
                  data-testid="correction-spinner"
                  title="AI 교정 대기 중"
                />
                <span className="ml-1 text-xs text-warning align-middle" data-testid="correction-label">교정 중</span>
              </>
            )}
            {(isCorrected || correctionState === 'corrected') && i === lines.length - 1 && (
              <>
                <span className="inline-block ml-1 text-xs text-success" title="AI 교정됨" data-testid="correction-check">
                  &#10003;
                </span>
                <span className="ml-0.5 text-xs text-success align-middle" data-testid="correction-label">교정됨</span>
              </>
            )}
          </span>
        ))}
      </span>
      {/* Copy button (visible on hover) */}
      <span
        role="button"
        tabIndex={-1}
        onClick={handleCopy}
        className="absolute top-2 right-2 p-1 rounded text-text-muted hover:text-text hover:bg-surface-raised opacity-0 group-hover:opacity-100 transition-opacity"
        title="텍스트 복사"
        data-testid="copy-button"
      >
        {copied ? (
          <svg className="w-4 h-4 text-success" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        ) : (
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3" />
          </svg>
        )}
      </span>
    </button>
  );
}
