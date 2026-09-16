'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import SubtitleItem from './SubtitleItem';

import type { SubtitleType } from '../types';

export interface SubtitlePanelProps {
  subtitles: SubtitleType[];
  searchQuery?: string;
  currentTime?: number;
  autoScroll?: boolean;
  onSubtitleClick?: (startTime: number) => void;
  /** STT interim (미확정) 텍스트 - 확정 전 실시간 미리보기 */
  interimText?: string;
  /** 데이터 로딩 중 여부 (false이고 자막이 없으면 '자막 없음' 표시) */
  isLoading?: boolean;
  /** 자막이 없을 때 표시할 안내 문구 (isLoading=false일 때만 사용). 미지정 시 기본 문구. */
  emptyMessage?: string;
  /** 실시간 모드 여부. true면 클릭 시 시점 이동 불가 안내 */
  isLive?: boolean;
  /**
   * 가장 최근 자막을 '지금 발언' 카드로 크게 강조 (실시간 자막 탭 전용).
   * 검색결과처럼 목록의 마지막이 '현재'가 아닌 화면에서는 꺼야 한다.
   */
  highlightLatestLive?: boolean;
  /** STT 시작 시각 (ms timestamp). 설정 시 각 자막에 실제 시계 시간 표시 */
  sttStartedAt?: number | null;
  /** 실시간 클릭 시 안내 콜백 */
  onLiveClickNotice?: () => void;
  /** 자막 시간 칩(▶) 클릭 시 해당 구간 녹음 음성 재생 */
  onPlaySegment?: (subtitle: SubtitleType) => void;
  /** 지금 음성이 재생 중인 자막 ID — 그 칩만 '재생 중'으로 표시한다 */
  playingSubtitleId?: string | null;
  /** 스크롤 이동할 자막 ID (검색 네비게이션/요구자료 점프용) */
  scrollToSubtitleId?: string;
  /** 같은 ID로 재요청 시에도 재스크롤되도록 하는 트리거 카운터 */
  scrollNonce?: number;
  /** 자막 패널 확대 상태 (라이브 뷰어: 영상 숨기고 자막 전체폭) */
  expanded?: boolean;
  /** 확대 토글 콜백. 제공 시 헤더에 확대/축소 버튼 표시 */
  onToggleExpand?: () => void;
  /**
   * 헤더 왼쪽('자막' 제목) 자리를 대체할 내용.
   * 자막 종류 토글처럼 별도 줄이 필요했던 것을 이 자리에 넣어 띠 하나를 없앤다 —
   * 모바일에서는 줄 하나가 자막 3~4줄과 맞먹는다.
   */
  headerLeft?: React.ReactNode;
  /**
   * 헤더 줄을 통째로 없앤다 (2026-08-25 개선안 2a·2e).
   * 컨트롤은 탭 줄 오른쪽(`ViewerTabs.rightSlot`)으로 올라가므로, 화면을 부르는 쪽이
   * `autoFollow`/`sortOrder` 를 제어 상태로 넘겨받아 그린다.
   */
  hideHeader?: boolean;
  /** 테두리·라운드를 없앤다 — 모바일 풀블리드 배치용 */
  borderless?: boolean;
  /** 자동 따라가기 (제어 모드). 주지 않으면 패널이 스스로 관리한다 */
  autoFollow?: boolean;
  onAutoFollowChange?: (next: boolean) => void;
  /** 정렬 (제어 모드) */
  sortOrder?: 'newest' | 'oldest';
  onSortOrderChange?: (next: 'newest' | 'oldest') => void;
  /** 자막 본문 글자 크기 — 'md' 기본 / 'lg' / 'xl' */
  fontScale?: 'md' | 'lg' | 'xl';
}

/**
 * 글자 크기 — 자막 본문(`[data-subtitle-text]`)만 키운다.
 * 시각·화자 배지까지 함께 커지면 한 줄에 들어가는 글자 수가 오히려 줄어든다.
 */
const FONT_SCALE_CLASS: Record<'md' | 'lg' | 'xl', string> = {
  md: '',
  lg: '[&_[data-subtitle-text]]:!text-[19px]',
  xl: '[&_[data-subtitle-text]]:!text-[23px]',
};

/**
 * 시계 시간 포맷 (ms timestamp + 경과 초 → "HH:MM:SS")
 */
function formatClockTime(sttStartedAt: number, startTime: number): string {
  const date = new Date(sttStartedAt + startTime * 1000);
  return [date.getHours(), date.getMinutes(), date.getSeconds()]
    .map((v) => v.toString().padStart(2, '0'))
    .join(':');
}

/**
 * 긴 자막을 2~3문장 단위로 시각적 청크로 분할.
 * 각 청크에 텍스트 길이 비율로 보간된 타임스탬프 부여.
 */
const MAX_LINES_PER_CHUNK = 3;

function splitLongSubtitle(subtitle: SubtitleType): SubtitleType[] {
  const lines = subtitle.text.split('\n').filter(line => line.trim());

  if (lines.length <= MAX_LINES_PER_CHUNK) {
    return [subtitle];
  }

  const duration = subtitle.end_time - subtitle.start_time;
  const totalLength = lines.reduce((sum, l) => sum + l.length, 0);
  const chunks: SubtitleType[] = [];
  let charsSoFar = 0;

  for (let i = 0; i < lines.length; i += MAX_LINES_PER_CHUNK) {
    const chunkLines = lines.slice(i, i + MAX_LINES_PER_CHUNK);
    const chunkText = chunkLines.join('\n');
    const chunkLength = chunkLines.reduce((sum, l) => sum + l.length, 0);

    const startRatio = totalLength > 0 ? charsSoFar / totalLength : 0;
    const endRatio = totalLength > 0 ? (charsSoFar + chunkLength) / totalLength : 1;

    chunks.push({
      ...subtitle,
      id: `${subtitle.id}_chunk_${Math.floor(i / MAX_LINES_PER_CHUNK)}`,
      start_time: subtitle.start_time + duration * startRatio,
      end_time: subtitle.start_time + duration * endRatio,
      text: chunkText,
    });

    charsSoFar += chunkLength;
  }

  return chunks;
}

const SubtitlePanel = React.memo(function SubtitlePanel({
  subtitles,
  searchQuery,
  currentTime,
  autoScroll: _autoScroll = true,
  onSubtitleClick,
  interimText,
  isLoading = true,
  emptyMessage,
  isLive = false,
  highlightLatestLive = false,
  sttStartedAt = null,
  onLiveClickNotice,
  onPlaySegment,
  playingSubtitleId = null,
  scrollToSubtitleId,
  scrollNonce,
  expanded = false,
  onToggleExpand,
  headerLeft,
  hideHeader = false,
  borderless = false,
  autoFollow: autoFollowProp,
  onAutoFollowChange,
  sortOrder: sortOrderProp,
  onSortOrderChange,
  fontScale = 'md',
}: SubtitlePanelProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const prevSubtitleCountRef = useRef(subtitles.length);
  // 실시간: 시간순(oldest) 고정 — 국회 AI 자막처럼 아래로 쌓이게
  // ★제어/비제어 두 모드다. 컨트롤이 탭 줄로 올라간 화면(라이브)은 값을 내려주고,
  //   헤더를 그대로 쓰는 화면(VOD 상세 등)은 패널이 스스로 관리한다.
  const [sortOrderInner, setSortOrderInner] = useState<'newest' | 'oldest'>('oldest');
  const sortOrder = sortOrderProp ?? sortOrderInner;
  const setSortOrder = useCallback(
    (next: 'newest' | 'oldest') => {
      if (onSortOrderChange) onSortOrderChange(next);
      else setSortOrderInner(next);
    },
    [onSortOrderChange],
  );

  // 자동 스크롤 follow 모드. 사용자가 위로 스크롤하면 자동으로 꺼지고,
  // "최신으로" 버튼 클릭 시 다시 켜짐. 수동 토글도 가능.
  const [autoFollowInner, setAutoFollowInner] = useState(true);
  const autoFollow = autoFollowProp ?? autoFollowInner;
  const setAutoFollow = useCallback(
    (next: boolean) => {
      if (onAutoFollowChange) onAutoFollowChange(next);
      else setAutoFollowInner(next);
    },
    [onAutoFollowChange],
  );
  // 사용자가 직접 스크롤한 직후 1초간은 auto-scroll을 무시 (사용자 우선)
  const userScrollAtRef = useRef(0);
  // 새 자막 미확인 카운터 (follow OFF일 때만 증가)
  const [unseenCount, setUnseenCount] = useState(0);

  // 긴 자막을 2~3문장 청크로 분할 (시각적 분할, 원본 데이터 불변)
  const chunkedSubtitles = useMemo(
    () => subtitles.flatMap(splitLongSubtitle),
    [subtitles]
  );

  // 스크롤 위치 감시 — 바닥에서 멀어지면 follow OFF, 바닥 근처면 ON
  useEffect(() => {
    const el = listRef.current;
    if (!el) return;

    function onScroll() {
      userScrollAtRef.current = Date.now();
      if (!el) return;
      // 바닥까지 남은 거리 (px). 40px 이내는 "거의 바닥"으로 간주.
      const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
      if (distanceFromBottom <= 40) {
        setAutoFollow(true);
        setUnseenCount(0);
      } else {
        setAutoFollow(false);
      }
    }
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, []);

  // Auto-scroll: 새 자막 추가 시 follow ON이면 맨 아래로 스크롤,
  // OFF면 건드리지 않고 unseen 카운터만 증가
  useEffect(() => {
    const added = subtitles.length - prevSubtitleCountRef.current;
    prevSubtitleCountRef.current = subtitles.length;

    if (added <= 0 && !interimText) return;

    // 사용자가 직전 500ms 내 스크롤했으면 작업 스킵 (의도 존중)
    const recentlyUserScrolled = Date.now() - userScrollAtRef.current < 500;
    if (recentlyUserScrolled && !autoFollow) {
      if (added > 0) setUnseenCount((c) => c + added);
      return;
    }

    if (autoFollow && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
      setUnseenCount(0);
    } else if (added > 0) {
      // follow OFF + 새 자막 N개 도착 → 카운터만 증가
      setUnseenCount((c) => c + added);
    }
  }, [subtitles.length, interimText, autoFollow]);

  // "최신으로" 점프 버튼 핸들러
  const jumpToLatest = () => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
    setAutoFollow(true);
    setUnseenCount(0);
  };

  // 자동 팔로우 수동 토글 (헤더/탭 줄 버튼)
  const toggleAutoFollow = () => {
    const next = !autoFollow;
    if (next && listRef.current) {
      // ON으로 전환 시 즉시 맨 아래로 이동
      listRef.current.scrollTop = listRef.current.scrollHeight;
      setUnseenCount(0);
    }
    setAutoFollow(next);
  };

  // 검색 네비게이션/요구자료 점프: scrollToSubtitleId(또는 nonce) 변경 시 해당 자막으로 스크롤.
  // 긴 자막은 splitLongSubtitle이 id를 `${id}_chunk_N`으로 재작성하므로 prefix 폴백 필요.
  useEffect(() => {
    if (scrollToSubtitleId && listRef.current) {
      const esc = CSS.escape(scrollToSubtitleId);
      const el =
        listRef.current.querySelector(`[data-subtitle-id="${esc}"]`) ??
        listRef.current.querySelector(`[data-subtitle-id^="${esc}_chunk_"]`);
      el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [scrollToSubtitleId, scrollNonce]);

  // Determine current chunk based on currentTime
  const getCurrentChunkId = () => {
    if (currentTime === undefined) return null;
    const current = chunkedSubtitles.find(
      (s) => currentTime >= s.start_time && currentTime < s.end_time
    );
    return current?.id ?? null;
  };

  const currentChunkId = getCurrentChunkId();

  return (
    <div
      data-testid="subtitle-panel"
      className={`relative flex h-full flex-col overflow-hidden bg-surface ${
        borderless ? '' : 'rounded-lg border border-border'
      }`}
    >
      {/* Header — 모바일에서는 얇게. headerLeft 가 있으면 '자막' 제목 대신 그것을 쓴다.
          hideHeader 면 이 줄 자체가 없다(컨트롤은 탭 줄로 올라간다). */}
      {!hideHeader && (
      <div className="flex items-center justify-between gap-2 border-b border-border bg-surface-raised px-2 py-1.5 sm:px-4 sm:py-3">
        {headerLeft ?? <h2 className="font-semibold text-text">자막</h2>}
        <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
          {/* 자막 패널 확대/축소 (라이브 뷰어에서 영상 숨기고 자막 전체폭) */}
          {onToggleExpand && (
            <button
              type="button"
              onClick={onToggleExpand}
              className="inline-flex items-center gap-1 px-2 py-1 text-xs text-text-secondary bg-surface border border-border rounded-md hover:bg-surface-raised transition-colors"
              title={expanded ? '기본 보기로 전환' : '자막 패널 확대'}
              data-testid="subtitle-expand-toggle"
              aria-pressed={expanded}
            >
              {expanded ? (
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 9V4.5M9 9H4.5M9 9L3.75 3.75M9 15v4.5M9 15H4.5M9 15l-5.25 5.25M15 9h4.5M15 9V4.5M15 9l5.25-5.25M15 15h4.5M15 15v4.5m0-4.5l5.25 5.25" />
                </svg>
              ) : (
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15" />
                </svg>
              )}
              <span className="hidden sm:inline">{expanded ? '축소' : '확대'}</span>
            </button>
          )}
          {/* 자동 스크롤(따라가기) 토글 */}
          {isLive && (
            <button
              type="button"
              onClick={toggleAutoFollow}
              className={`inline-flex items-center gap-1 px-2 py-1 text-xs border rounded-md transition-colors ${
                autoFollow
                  ? 'bg-brand text-white border-brand hover:bg-brand/90'
                  : 'bg-surface text-text-secondary border-border hover:bg-surface-raised'
              }`}
              title={autoFollow ? '자동 따라가기 끄기 (이전 자막 보기)' : '자동 따라가기 켜기 (새 자막 자동 스크롤)'}
              data-testid="auto-follow-toggle"
              aria-pressed={autoFollow}
            >
              {autoFollow ? (
                <>
                  <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 2a10 10 0 100 20 10 10 0 000-20zm0 18a8 8 0 110-16 8 8 0 010 16zm-1-8.5L15.5 14 14 15.5 9 12V7h2v5z" />
                  </svg>
                  자동
                </>
              ) : (
                <>
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M10 9v6M14 9v6M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  일시정지
                </>
              )}
            </button>
          )}
          <button
            type="button"
            onClick={() => setSortOrder(sortOrder === 'newest' ? 'oldest' : 'newest')}
            className="inline-flex items-center gap-1 px-2 py-1 text-xs text-text-secondary bg-surface border border-border rounded-md hover:bg-surface-raised transition-colors"
            title={sortOrder === 'newest' ? '시간순으로 변경' : '최신순으로 변경'}
            data-testid="sort-toggle"
          >
            {sortOrder === 'newest' ? '↓ 최신순' : '↑ 시간순'}
          </button>
          <span className="inline-flex items-center justify-center min-w-[1.5rem] h-6 px-1 text-xs font-medium text-text-secondary bg-surface-raised rounded-full">
            {subtitles.length}
          </span>
        </div>
      </div>
      )}

      {/* Subtitle list */}
      <div ref={listRef} className={`flex-1 overflow-y-auto ${FONT_SCALE_CLASS[fontScale]}`.trim()}>
        {subtitles.length === 0 && !interimText ? (
          <div className="flex flex-col items-center justify-center h-full py-12 text-text-muted">
            {isLoading ? (
              <>
                <div
                  data-testid="loading-spinner"
                  className="w-8 h-8 border-4 border-border border-t-brand rounded-full animate-spin mb-4"
                />
                <p className="text-sm">자막을 불러오는 중...</p>
              </>
            ) : (
              <p className="text-sm">{emptyMessage ?? '등록된 자막이 없습니다.'}</p>
            )}
          </div>
        ) : (
          <>
            {/* 확정된 자막 목록 — 시간순으로 위에서 아래로 쌓임 */}
            {(() => {
              const ordered = sortOrder === 'newest' ? [...chunkedSubtitles].reverse() : chunkedSubtitles;
              // '지금 발언' = 시간상 마지막 자막 (정렬 방향과 무관하게 같은 항목)
              const latestId = highlightLatestLive
                ? chunkedSubtitles[chunkedSubtitles.length - 1]?.id
                : undefined;
              return ordered.map((subtitle, idx) => {
                const prevSpeaker = idx > 0 ? ordered[idx - 1]?.speaker ?? null : null;
                const sameSpeaker = !!subtitle.speaker && subtitle.speaker === prevSpeaker;
                return (
                  <div key={subtitle.id} data-subtitle-id={subtitle.id}>
                    <SubtitleItem
                      startTime={subtitle.start_time}
                      endTime={subtitle.end_time}
                      text={subtitle.text}
                      speaker={subtitle.speaker}
                      isCurrent={currentChunkId === subtitle.id}
                      highlightQuery={searchQuery}
                      onClick={onSubtitleClick}
                      onPlayAudio={onPlaySegment ? () => onPlaySegment(subtitle) : undefined}
                      isPlayingAudio={playingSubtitleId === subtitle.id}
                      isLive={isLive}
                      onLiveClickNotice={onLiveClickNotice}
                      clockTime={sttStartedAt ? formatClockTime(sttStartedAt, subtitle.start_time) : null}
                      isCorrected={subtitle.is_corrected}
                      isGroupContinuation={sameSpeaker}
                      isLatestLive={latestId != null && subtitle.id === latestId}
                      correctionState={subtitle.correction_state ?? undefined}
                      originalText={subtitle.original_text}
                    />
                  </div>
                );
              });
            })()}
            {/* Interim (미확정) 실시간 자막 — 맨 아래에 표시 (국회 AI 자막 스타일) */}
            {interimText && (
              <div
                data-testid="interim-subtitle"
                className="px-4 py-3 border-t border-border bg-primary-5"
              >
                <span className="block text-base text-brand leading-relaxed">
                  {interimText}
                  <span className="inline-block w-0.5 h-4 bg-brand animate-blink align-middle ml-0.5" data-testid="typing-cursor" />
                </span>
              </div>
            )}
          </>
        )}
      </div>

      {/* 플로팅 "최신으로" 점프 버튼 — 자동 따라가기 꺼진 상태에서만 노출.
          사용자가 이전 자막을 보는 동안 새 자막이 쌓이면 미확인 개수 표시.
          실시간 모드(isLive)에서만 의미가 있음 — VOD는 수동 탐색. */}
      {isLive && !autoFollow && (
        <button
          type="button"
          onClick={jumpToLatest}
          className="absolute bottom-4 left-1/2 -translate-x-1/2 inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold text-white bg-brand rounded-full shadow-lg hover:bg-brand/90 transition-all animate-fade-in"
          data-testid="jump-to-latest"
          aria-label={`최신 자막으로 이동${unseenCount > 0 ? ` — 새 자막 ${unseenCount}개` : ''}`}
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 14l-7 7m0 0l-7-7m7 7V3" />
          </svg>
          {unseenCount > 0 ? `새 자막 ${unseenCount}개 · 최신으로` : '최신으로'}
        </button>
      )}
    </div>
  );
});

export default SubtitlePanel;
