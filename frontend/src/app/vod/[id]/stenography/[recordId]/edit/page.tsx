'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useRouter } from 'next/navigation';

import { useVirtualizer } from '@tanstack/react-virtual';

import { Button } from '@/components/ui';

import AudioPlayerPanel from '../../../../../../components/AudioPlayerPanel';
import FindReplaceBar from '../../../../../../components/FindReplaceBar';
import StenographyEditorToolbar from '../../../../../../components/StenographyEditorToolbar';
import StenographyLineEditor from '../../../../../../components/StenographyLineEditor';
import SttComparisonPanel from '../../../../../../components/SttComparisonPanel';
import { useBreadcrumb } from '../../../../../../contexts/BreadcrumbContext';
import useAudioKeyboardShortcuts from '../../../../../../hooks/useAudioKeyboardShortcuts';
import useStenographyEditor from '../../../../../../hooks/useStenographyEditor';
import {
  apiClient,
  getStenographyRecords,
  bootstrapStenographyFromSubtitles,
  importStenographyFromText,
} from '../../../../../../lib/api';

import type {
  MeetingType,
  StenographyRecord,
  SubtitleType,
} from '../../../../../../types';

// ============================================================
// Types
// ============================================================

interface StenographyEditorPageProps {
  params: { id: string; recordId: string };
}

// ============================================================
// Page Component
// ============================================================

export default function StenographyEditorPage({ params }: StenographyEditorPageProps) {
  const router = useRouter();
  const { setTitle } = useBreadcrumb();
  const { id: meetingId, recordId } = params;

  // ---- Data state ----
  const [meeting, setMeeting] = useState<MeetingType | null>(null);
  const [record, setRecord] = useState<StenographyRecord | null>(null);
  const [subtitles, setSubtitles] = useState<SubtitleType[]>([]);
  const [pageLoading, setPageLoading] = useState(true);
  const [pageError, setPageError] = useState<Error | null>(null);

  // ---- Editor hook ----
  const editor = useStenographyEditor({ meetingId, recordId });

  // ---- UI state ----
  const [showFindReplace, setShowFindReplace] = useState(false);
  const [showComparison, setShowComparison] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  // ---- Load initial data ----
  useEffect(() => {
    async function loadData() {
      try {
        setPageLoading(true);
        setPageError(null);

        const [meetingData, records, subtitleData] = await Promise.all([
          apiClient<MeetingType>(`/api/meetings/${meetingId}`),
          getStenographyRecords(meetingId),
          apiClient<SubtitleType[]>(`/api/meetings/${meetingId}/subtitles`),
        ]);

        setMeeting(meetingData);
        setTitle(meetingData.title);
        setSubtitles(Array.isArray(subtitleData) ? subtitleData : []);

        const foundRecord = records.find((r: StenographyRecord) => r.id === recordId);
        if (!foundRecord) {
          setPageError(new Error('속기록을 찾을 수 없습니다.'));
          return;
        }
        setRecord(foundRecord);
      } catch (err) {
        setPageError(err instanceof Error ? err : new Error('데이터 로드 실패'));
      } finally {
        setPageLoading(false);
      }
    }

    loadData();
  }, [meetingId, recordId, setTitle]);

  // ---- Speaker options (extracted from lines) ----
  const speakerOptions = useMemo(() => {
    const speakers = new Set<string>();
    for (const line of editor.lines) {
      if (line.speaker) speakers.add(line.speaker);
    }
    // Also include speakers from subtitles
    for (const sub of subtitles) {
      if (sub.speaker) speakers.add(sub.speaker);
    }
    return Array.from(speakers).sort();
  }, [editor.lines, subtitles]);

  // ---- Current active line (by playback time) ----
  const activeLineId = useMemo(() => {
    const timeMs = currentTime * 1000;
    for (const line of editor.lines) {
      if (
        line.start_ms !== null &&
        line.end_ms !== null &&
        timeMs >= line.start_ms &&
        timeMs < line.end_ms
      ) {
        return line.id;
      }
    }
    return null;
  }, [currentTime, editor.lines]);

  // ---- Focused line for comparison panel ----
  const focusedLine = useMemo(() => {
    const targetId = editor.focusedLineId || activeLineId;
    if (!targetId) return null;
    return editor.lines.find((l) => l.id === targetId) || null;
  }, [editor.focusedLineId, activeLineId, editor.lines]);

  // ---- Virtual scrolling ----
  const virtualizer = useVirtualizer({
    count: editor.lines.length,
    getScrollElement: () => scrollContainerRef.current,
    estimateSize: () => 44,
    overscan: 10,
  });

  // ---- Keyboard shortcuts ----
  const handleSave = useCallback(async () => {
    try {
      await editor.save();
    } catch (err) {
      alert(err instanceof Error ? err.message : '저장에 실패했습니다.');
    }
  }, [editor]);

  useAudioKeyboardShortcuts({
    videoRef,
    onSave: handleSave,
    enabled: true,
  });

  // ---- Seek audio ----
  const handleSeek = useCallback((timeMs: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime = timeMs / 1000;
    }
  }, []);

  // ---- Time update handler ----
  const handleTimeUpdate = useCallback((time: number) => {
    setCurrentTime(time);
  }, []);

  // ---- Video metadata (duration) ----
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const handleDurationChange = () => {
      if (video.duration && isFinite(video.duration)) {
        setDuration(video.duration);
      }
    };

    video.addEventListener('loadedmetadata', handleDurationChange);
    video.addEventListener('durationchange', handleDurationChange);

    return () => {
      video.removeEventListener('loadedmetadata', handleDurationChange);
      video.removeEventListener('durationchange', handleDurationChange);
    };
  }, [meeting]);

  // ---- Import handlers ----
  const handleImportFromText = useCallback(async () => {
    if (!confirm('기존 라인을 모두 삭제하고 텍스트에서 다시 가져옵니다. 계속하시겠습니까?')) return;
    try {
      const result = await importStenographyFromText(meetingId, recordId, record?.content || "");
      editor.setLines(result.lines);
    } catch (err) {
      alert(err instanceof Error ? err.message : '가져오기에 실패했습니다.');
    }
  }, [meetingId, recordId, editor]);

  const handleImportFromSubtitles = useCallback(async () => {
    if (!confirm('기존 라인을 모두 삭제하고 STT 자막에서 가져옵니다. 계속하시겠습니까?')) return;
    try {
      const result = await bootstrapStenographyFromSubtitles(meetingId, recordId);
      editor.setLines(result.lines);
    } catch (err) {
      alert(err instanceof Error ? err.message : '가져오기에 실패했습니다.');
    }
  }, [meetingId, recordId, editor]);

  // ---- Find/Replace handlers ----
  const [highlightedIds, setHighlightedIds] = useState<Set<string>>(new Set());
  const [_currentHighlightId, setCurrentHighlightId] = useState<string | null>(null);

  const handleFindReplaceHighlight = useCallback((matchedIds: Set<string>, currentId: string | null) => {
    setHighlightedIds(matchedIds);
    setCurrentHighlightId(currentId);
  }, []);

  const handleFindReplaceReplace = useCallback(
    (lineId: string, newText: string) => {
      editor.handleTextChange(lineId, newText);
    },
    [editor]
  );

  // ---- Navigation ----
  const handleBack = useCallback(() => {
    router.push(`/vod/${meetingId}/stenography`);
  }, [router, meetingId]);

  // ---- Loading state ----
  if (pageLoading || editor.isLoading) {
    return (
      <div data-testid="page-loading" className="flex items-center justify-center h-full">
        <div className="w-12 h-12 border-4 border-gray-200 border-t-primary rounded-full animate-spin" />
      </div>
    );
  }

  // ---- Error state ----
  if (pageError || !meeting || !record) {
    return (
      <div data-testid="page-error" className="flex items-center justify-center h-full">
        <div className="text-center">
          <p className="text-error mb-4">{pageError?.message || '오류가 발생했습니다.'}</p>
          <Button variant="primary" size="md" onClick={handleBack}>
            돌아가기
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="stenography-editor-page" className="flex flex-col h-full">
      {/* Toolbar */}
      <StenographyEditorToolbar
        record={record}
        isDirty={editor.isDirty}
        isSaving={editor.isSaving}
        lineCount={editor.lines.length}
        onSave={handleSave}
        onImportFromText={handleImportFromText}
        onImportFromSubtitles={handleImportFromSubtitles}
        onToggleFindReplace={() => setShowFindReplace((v) => !v)}
        onToggleComparison={() => setShowComparison((v) => !v)}
        isComparisonOpen={showComparison}
        onBack={handleBack}
      />

      {/* Find/Replace bar */}
      {showFindReplace && (
        <FindReplaceBar
          subtitles={editor.lines.map((l) => ({ id: l.id, text: l.text }))}
          onReplace={handleFindReplaceReplace}
          onHighlight={handleFindReplaceHighlight}
          onClose={() => setShowFindReplace(false)}
        />
      )}

      {/* Main content area */}
      <div className="flex-1 flex min-h-0">
        {/* Left panel: Audio player */}
        <div className="w-80 border-r border-gray-200 flex flex-col shrink-0">
          {meeting.vod_url ? (
            <AudioPlayerPanel
              vodUrl={meeting.vod_url}
              videoRef={videoRef}
              currentTime={currentTime}
              duration={duration}
              onTimeUpdate={handleTimeUpdate}
              currentSpeaker={focusedLine?.speaker}
            />
          ) : (
            <div className="flex items-center justify-center h-full text-gray-400 text-sm">
              영상 URL이 없습니다
            </div>
          )}
        </div>

        {/* Center: Line editor with virtual scrolling */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Empty state */}
          {editor.lines.length === 0 ? (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center">
                <p className="text-gray-500 mb-4">속기 라인이 없습니다.</p>
                <div className="flex gap-2 justify-center">
                  <Button variant="primary" size="md" onClick={handleImportFromSubtitles}>
                    STT 자막에서 가져오기
                  </Button>
                  <Button variant="secondary" size="md" onClick={handleImportFromText}>
                    텍스트에서 가져오기
                  </Button>
                </div>
              </div>
            </div>
          ) : (
            <div
              ref={scrollContainerRef}
              className="flex-1 overflow-y-auto"
            >
              <div
                style={{
                  height: `${virtualizer.getTotalSize()}px`,
                  width: '100%',
                  position: 'relative',
                }}
              >
                {virtualizer.getVirtualItems().map((virtualRow) => {
                  const line = editor.lines[virtualRow.index];
                  if (!line) return null;

                  return (
                    <div
                      key={line.id}
                      style={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        width: '100%',
                        transform: `translateY(${virtualRow.start}px)`,
                      }}
                      data-index={virtualRow.index}
                      ref={virtualizer.measureElement}
                    >
                      <StenographyLineEditor
                        line={line}
                        isActive={line.id === activeLineId || highlightedIds.has(line.id)}
                        speakerOptions={speakerOptions}
                        onTextChange={editor.handleTextChange}
                        onSpeakerChange={editor.handleSpeakerChange}
                        onTimingChange={editor.handleTimingChange}
                        onParagraphToggle={editor.handleParagraphToggle}
                        onSeek={handleSeek}
                        onFocus={editor.setFocusedLineId}
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Right panel: STT Comparison */}
        {showComparison && (
          <SttComparisonPanel
            subtitles={subtitles}
            currentTimeMs={focusedLine?.start_ms ?? null}
            currentLineText={focusedLine?.text ?? ''}
            isOpen={showComparison}
            onClose={() => setShowComparison(false)}
          />
        )}
      </div>
    </div>
  );
}
