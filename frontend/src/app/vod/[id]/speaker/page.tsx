'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import Link from 'next/link';
import { useRouter } from 'next/navigation';

import CouncilorPicker from '../../../../components/CouncilorPicker';
import Mp4Player from '../../../../components/Mp4Player';
import TranscriptStatusBadge from '../../../../components/TranscriptStatusBadge';
import Button from '../../../../components/ui/Button';
import VideoControls from '../../../../components/VideoControls';
import { useBreadcrumb } from '../../../../contexts/BreadcrumbContext';
import {
  apiClient,
  createClipJob,
  downloadClipJobResult,
  downloadSpeechClip,
  getClipJob,
  getSpeakersTimeline,
  mergeSpeakers,
  updateSubtitlesBatch,
} from '../../../../lib/api';

import type { SubtitleBatchItem } from '../../../../lib/api';
import type { MeetingType, SpeakersTimelineResponse, SpeakerSummary, SubtitleType } from '../../../../types';

interface SpeakerPageProps {
  params: { id: string };
}

/**
 * 동기 클립 응답 상한(초) — 동기 clip API 는 TTFB ≈ 구간 길이라 Vercel/ngrok
 * 프록시가 타임아웃된다. 초과 구간은 clip-jobs(단일 세그먼트 잡) 경로를 사용.
 * (clips 페이지와 동일 정책)
 */
const SYNC_CLIP_MAX_SECONDS = 60;

/** 클립 잡 상태 폴링 간격 (ms) */
const CLIP_JOB_POLL_MS = 3000;

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) {
    return `${h}시간 ${m}분 ${s}초`;
  }
  if (m > 0) {
    return `${m}분 ${s}초`;
  }
  return `${s}초`;
}

/** 화자별 고유 색상 */
const DEFAULT_COLOR = { bg: 'bg-gray-50', border: 'border-gray-300', text: 'text-gray-700', bar: 'bg-gray-500' };
const SPEAKER_COLORS = [
  { bg: 'bg-blue-50', border: 'border-blue-300', text: 'text-blue-700', bar: 'bg-blue-500' },
  { bg: 'bg-green-50', border: 'border-green-300', text: 'text-green-700', bar: 'bg-green-500' },
  { bg: 'bg-purple-50', border: 'border-purple-300', text: 'text-purple-700', bar: 'bg-purple-500' },
  { bg: 'bg-orange-50', border: 'border-orange-300', text: 'text-orange-700', bar: 'bg-orange-500' },
  { bg: 'bg-pink-50', border: 'border-pink-300', text: 'text-pink-700', bar: 'bg-pink-500' },
  { bg: 'bg-teal-50', border: 'border-teal-300', text: 'text-teal-700', bar: 'bg-teal-500' },
  { bg: 'bg-red-50', border: 'border-red-300', text: 'text-red-700', bar: 'bg-red-500' },
  { bg: 'bg-indigo-50', border: 'border-indigo-300', text: 'text-indigo-700', bar: 'bg-indigo-500' },
  { bg: 'bg-yellow-50', border: 'border-yellow-300', text: 'text-yellow-700', bar: 'bg-yellow-500' },
  { bg: 'bg-cyan-50', border: 'border-cyan-300', text: 'text-cyan-700', bar: 'bg-cyan-500' },
];

function buildSpeakerOptions(subtitles: SubtitleType[]): { value: string; label: string }[] {
  const options = [{ value: '', label: '(미지정)' }];
  const speakerSet = new Set<string>();
  for (const sub of subtitles) {
    if (sub.speaker) speakerSet.add(sub.speaker);
  }
  for (const speaker of Array.from(speakerSet).sort()) {
    options.push({ value: speaker, label: speaker });
  }
  for (let i = 1; i <= 10; i++) {
    const label = `화자 ${i}`;
    if (!speakerSet.has(label)) {
      options.push({ value: label, label });
    }
  }
  return options;
}

// ─────────────────────────────────────────────────
// 클립 다운로드 버튼 컴포넌트
// ─────────────────────────────────────────────────
function ClipDownloadButton({
  meetingId,
  startTime,
  endTime,
}: {
  meetingId: string;
  startTime: number;
  endTime: number;
}) {
  const [isDownloading, setIsDownloading] = useState(false);

  const handleDownload = async () => {
    if (isDownloading) return;
    try {
      setIsDownloading(true);
      if (endTime - startTime > SYNC_CLIP_MAX_SECONDS) {
        // 60초 초과 구간: 동기 clip API 는 TTFB ≈ 구간 길이 → 프록시 타임아웃.
        // 단일 세그먼트 잡 생성 → 폴링 → 결과 다운로드 (clips 페이지와 동일).
        const { job_id: jobId } = await createClipJob(meetingId, [
          { start: startTime, end: endTime },
        ]);
        for (;;) {
          const job = await getClipJob(meetingId, jobId);
          const jobStatus = String(job.status);
          if (jobStatus === 'completed' || jobStatus === 'done') {
            await downloadClipJobResult(meetingId, jobId);
            break;
          }
          if (jobStatus === 'failed') {
            throw new Error(job.error || '클립 작업이 실패했습니다.');
          }
          await new Promise<void>((resolve) => {
            window.setTimeout(resolve, CLIP_JOB_POLL_MS);
          });
        }
      } else {
        // clip API 는 로그인 필수(401) — 인증 헤더 없는 <a download> 직링크 대신
        // Authorization 헤더를 붙이는 downloadSpeechClip(fetch)으로 다운로드한다.
        await downloadSpeechClip(meetingId, startTime, endTime);
      }
    } catch (err) {
      alert(err instanceof Error ? err.message : '클립 다운로드 실패');
    } finally {
      setIsDownloading(false);
    }
  };

  return (
    <button
      data-testid="clip-download-button"
      onClick={handleDownload}
      disabled={isDownloading}
      className="flex items-center gap-1 px-2 py-1 text-xs border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      title="클립 다운로드"
    >
      {isDownloading ? (
        <div className="w-3 h-3 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" />
      ) : (
        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
        </svg>
      )}
      <span>클립</span>
    </button>
  );
}

// ─────────────────────────────────────────────────
// 타임라인 탭 컴포넌트
// ─────────────────────────────────────────────────
function SpeakerTimelineTab({
  meetingId,
  timeline,
  isTimelineLoading,
  currentTime,
  onSeek,
  onTimelineRefresh,
}: {
  meetingId: string;
  timeline: SpeakersTimelineResponse | null;
  isTimelineLoading: boolean;
  currentTime: number;
  onSeek: (time: number) => void;
  onTimelineRefresh: () => void;
}) {
  const [expandedSpeaker, setExpandedSpeaker] = useState<string | null>(null);
  const [mergeTarget, setMergeTarget] = useState<{ source: string } | null>(null);
  const [isMerging, setIsMerging] = useState(false);

  const handleMerge = async (source: string, target: string) => {
    if (!confirm(`"${source}"의 모든 자막을 "${target}"로 병합합니다. 계속할까요?`)) return;
    try {
      setIsMerging(true);
      const result = await mergeSpeakers(meetingId, source, target);
      alert(`${result.updated}개 자막이 병합되었습니다.`);
      setMergeTarget(null);
      onTimelineRefresh();
    } catch (err) {
      alert(err instanceof Error ? err.message : '병합 실패');
    } finally {
      setIsMerging(false);
    }
  };

  if (isTimelineLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="w-8 h-8 border-4 border-gray-200 border-t-primary rounded-full animate-spin" />
      </div>
    );
  }

  if (!timeline || timeline.speakers.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">
        화자 데이터가 없습니다.
      </div>
    );
  }

  const totalSpeakingTime = timeline.speakers.reduce((sum, s) => sum + s.total_time, 0);

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* 전체 통계 요약 */}
      <div className="mb-3 p-3 bg-gray-50 rounded-lg border border-gray-200">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-gray-700">화자 통계</span>
          <span className="text-xs text-gray-500">{timeline.speakers.length}명</span>
        </div>
        {/* 비율 바 */}
        <div className="flex h-3 rounded-full overflow-hidden bg-gray-200">
          {timeline.speakers.map((speaker, i) => {
            const pct = totalSpeakingTime > 0 ? (speaker.total_time / totalSpeakingTime) * 100 : 0;
            const color = SPEAKER_COLORS[i % SPEAKER_COLORS.length] ?? DEFAULT_COLOR;
            return (
              <div
                key={speaker.speaker}
                className={`${color.bar} transition-all`}
                style={{ width: `${pct}%` }}
                title={`${speaker.speaker}: ${pct.toFixed(1)}%`}
              />
            );
          })}
        </div>
      </div>

      {/* 화자 목록 */}
      <div data-testid="speaker-timeline-list" className="flex-1 overflow-y-auto space-y-2">
        {timeline.speakers.map((speaker: SpeakerSummary, index: number) => {
          const color = SPEAKER_COLORS[index % SPEAKER_COLORS.length] ?? DEFAULT_COLOR;
          const pct = totalSpeakingTime > 0 ? (speaker.total_time / totalSpeakingTime) * 100 : 0;
          const isExpanded = expandedSpeaker === speaker.speaker;
          const isMergeSource = mergeTarget?.source === speaker.speaker;

          return (
            <div
              key={speaker.speaker}
              className={`border rounded-lg overflow-hidden ${color.border}`}
            >
              {/* 화자 헤더 (클릭으로 펼치기/접기) */}
              <button
                data-testid={`speaker-card-${index}`}
                onClick={() => setExpandedSpeaker(isExpanded ? null : speaker.speaker)}
                className={`w-full px-3 py-2.5 ${color.bg} flex items-center justify-between text-left`}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className={`w-2 h-2 rounded-full ${color.bar} flex-shrink-0`} />
                  <span className={`text-sm font-medium ${color.text} truncate`}>
                    {speaker.speaker}
                  </span>
                </div>
                <div className="flex items-center gap-3 flex-shrink-0">
                  <span className="text-xs text-gray-500">
                    {formatDuration(speaker.total_time)} ({pct.toFixed(1)}%)
                  </span>
                  <span className="text-xs text-gray-400">
                    {speaker.segment_count}회
                  </span>
                  <svg
                    className={`w-4 h-4 text-gray-400 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </div>
              </button>

              {/* 병합 드롭다운 */}
              {isExpanded && timeline.speakers.length > 1 && (
                <div className="px-3 py-1.5 bg-gray-50 border-b border-gray-100 flex items-center gap-2">
                  {isMergeSource ? (
                    <>
                      <span className="text-xs text-gray-500">병합 대상:</span>
                      <select
                        className="text-xs border border-gray-300 rounded px-1.5 py-0.5"
                        defaultValue=""
                        onChange={(e) => {
                          if (e.target.value) {
                            handleMerge(speaker.speaker, e.target.value);
                          }
                        }}
                        disabled={isMerging}
                      >
                        <option value="">선택...</option>
                        {timeline.speakers
                          .filter((s) => s.speaker !== speaker.speaker)
                          .map((s) => (
                            <option key={s.speaker} value={s.speaker}>
                              {s.speaker}
                            </option>
                          ))}
                      </select>
                      <button
                        onClick={() => setMergeTarget(null)}
                        className="text-xs text-gray-400 hover:text-gray-600"
                      >
                        취소
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setMergeTarget({ source: speaker.speaker });
                      }}
                      className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1"
                    >
                      <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
                      </svg>
                      다른 화자로 병합
                    </button>
                  )}
                </div>
              )}

              {/* 발언 구간 목록 */}
              {isExpanded && (
                <div className="divide-y divide-gray-100 max-h-60 overflow-y-auto">
                  {speaker.segments.map((seg) => {
                    const isActive = currentTime >= seg.start_time && currentTime < seg.end_time;
                    return (
                      <div
                        key={seg.id}
                        className={`px-3 py-2 hover:bg-gray-50 transition-colors ${
                          isActive ? 'bg-primary-5' : ''
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2 mb-0.5">
                          <button
                            onClick={() => onSeek(seg.start_time)}
                            className="flex items-center gap-2 min-w-0 flex-1 text-left"
                          >
                            <span className={`text-xs font-mono ${isActive ? 'text-primary font-medium' : 'text-gray-500'}`}>
                              {formatTime(seg.start_time)} ~ {formatTime(seg.end_time)}
                            </span>
                            {isActive && (
                              <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                            )}
                          </button>
                          <ClipDownloadButton
                            meetingId={meetingId}
                            startTime={seg.start_time}
                            endTime={seg.end_time}
                          />
                        </div>
                        <p className="text-sm text-gray-700 line-clamp-2">{seg.text}</p>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────
// 화자 지정 탭 컴포넌트
// ─────────────────────────────────────────────────
function SpeakerAssignTab({
  editableSubtitles,
  currentSubtitleIndex,
  autoScroll,
  speakerFilter,
  bulkSpeaker,
  filteredSubtitles,
  unassignedCount,
  availableSpeakers,
  speakerAssignOptions: _speakerAssignOptions,
  subtitleRefs,
  committee,
  onAutoScrollToggle,
  onSpeakerFilterChange,
  onBulkSpeakerChange,
  onBulkApply,
  onSpeakerChange,
  onSeek,
}: {
  editableSubtitles: SubtitleType[];
  currentSubtitleIndex: number;
  autoScroll: boolean;
  speakerFilter: string;
  bulkSpeaker: string;
  filteredSubtitles: SubtitleType[];
  unassignedCount: number;
  availableSpeakers: Array<{ value: string; label: string }>;
  speakerAssignOptions: Array<{ value: string; label: string }>;
  subtitleRefs: React.MutableRefObject<Map<string, HTMLDivElement>>;
  committee?: string | null;
  onAutoScrollToggle: () => void;
  onSpeakerFilterChange: (v: string) => void;
  onBulkSpeakerChange: (v: string) => void;
  onBulkApply: () => void;
  onSpeakerChange: (id: string, speaker: string) => void;
  onSeek: (time: number) => void;
}) {
  // 공유 팝오버 패턴: 하나의 CouncilorPicker 팝오버를 활성 자막에만 표시
  const [pickerSubtitleId, setPickerSubtitleId] = useState<string | null>(null);

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="mb-2 flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-600">필터</label>
          <select
            value={speakerFilter}
            onChange={(e) => onSpeakerFilterChange(e.target.value)}
            className="px-2 py-1.5 border border-gray-300 rounded-md text-sm"
          >
            {availableSpeakers.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <p className="text-xs text-gray-500">미지정 {unassignedCount}개</p>
      </div>

      <div className="mb-2 flex items-center gap-2">
        <div className="flex-1">
          <CouncilorPicker
            value={bulkSpeaker}
            onChange={(speaker) => onBulkSpeakerChange(speaker)}
            placeholder="일괄 지정할 화자 선택"
            committeeFilter={committee || undefined}
          />
        </div>
        <Button variant="outline" size="sm" onClick={onBulkApply} disabled={!bulkSpeaker}>
          일괄 지정
        </Button>
      </div>

      <div className="mb-2 flex items-center justify-between">
        <button
          onClick={onAutoScrollToggle}
          className={`inline-flex h-6 w-11 items-center rounded-full transition-colors ${
            autoScroll ? 'bg-primary' : 'bg-gray-300'
          }`}
        >
          <span
            className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
              autoScroll ? 'translate-x-6' : 'translate-x-1'
            }`}
          />
        </button>
        <span className="text-xs text-gray-600">자동 스크롤</span>
      </div>

      <div className="flex-1 overflow-y-auto border border-gray-200 rounded-md bg-white">
        {filteredSubtitles.length === 0 ? (
          <div className="p-6 text-center text-gray-500">표시할 자막이 없습니다.</div>
        ) : (
          <div className="divide-y divide-gray-200">
            {filteredSubtitles.map((subtitle) => {
              const isActive = subtitle.id === editableSubtitles[currentSubtitleIndex]?.id;
              const isPickerOpen = pickerSubtitleId === subtitle.id;

              return (
                <div
                  key={subtitle.id}
                  ref={(element) => {
                    if (element) {
                      subtitleRefs.current.set(subtitle.id, element);
                    } else {
                      subtitleRefs.current.delete(subtitle.id);
                    }
                  }}
                  className={`p-3 transition-colors ${
                    isActive
                      ? 'bg-primary-5 border-l-4 border-primary'
                      : 'bg-white hover:bg-gray-50 border-l-4 border-transparent'
                  }`}
                >
                  <button
                    onClick={() => onSeek(subtitle.start_time)}
                    className="text-xs text-gray-500 hover:text-primary transition-colors"
                  >
                    {formatTime(subtitle.start_time)} ~ {formatTime(subtitle.end_time)}
                  </button>

                  {/* 화자 선택: 클릭 시 CouncilorPicker 팝오버 토글 */}
                  <div className="mt-2 relative">
                    {isPickerOpen ? (
                      <CouncilorPicker
                        value={subtitle.speaker || ''}
                        onChange={(speaker) => {
                          onSpeakerChange(subtitle.id, speaker);
                          setPickerSubtitleId(null);
                        }}
                        committeeFilter={committee || undefined}
                        placeholder="화자 선택 또는 입력"
                      />
                    ) : (
                      <button
                        onClick={() => setPickerSubtitleId(subtitle.id)}
                        className="w-full text-left px-2 py-1 text-sm border border-gray-300 rounded-md hover:border-primary transition-colors flex items-center justify-between"
                      >
                        <span className={subtitle.speaker ? 'text-gray-900' : 'text-gray-400'}>
                          {subtitle.speaker || '(미지정)'}
                        </span>
                        <svg className="w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                        </svg>
                      </button>
                    )}
                  </div>

                  <p className="mt-2 text-sm text-gray-900 truncate">{subtitle.text}</p>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="mt-2 text-xs text-gray-500">
        총 {editableSubtitles.length}개 / 표시 {filteredSubtitles.length}개
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────
// 메인 페이지
// ─────────────────────────────────────────────────
export default function SpeakerManagementPage({ params }: SpeakerPageProps) {
  const router = useRouter();
  const { setTitle } = useBreadcrumb();
  const { id } = params;

  const videoRef = useRef<HTMLVideoElement>(null);
  const subtitleRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  const [meeting, setMeeting] = useState<MeetingType | null>(null);
  const [subtitles, setSubtitles] = useState<SubtitleType[]>([]);
  const [editableSubtitles, setEditableSubtitles] = useState<SubtitleType[]>([]);
  const [originalSubtitles, setOriginalSubtitles] = useState<SubtitleType[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [isSaving, setIsSaving] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const [speakerFilter, setSpeakerFilter] = useState('all');
  const [bulkSpeaker, setBulkSpeaker] = useState('');

  // 탭 상태
  const [activeTab, setActiveTab] = useState<'timeline' | 'assign'>('timeline');

  // 타임라인 데이터
  const [timeline, setTimeline] = useState<SpeakersTimelineResponse | null>(null);
  const [isTimelineLoading, setIsTimelineLoading] = useState(false);

  const changesMap = useRef<Map<string, { speaker: string }>>(new Map());

  useEffect(() => {
    async function fetchData() {
      try {
        setIsLoading(true);
        setError(null);

        const [meetingData, subtitleResponse] = await Promise.all([
          apiClient<MeetingType>(`/api/meetings/${id}`),
          apiClient<{ items: SubtitleType[] }>(`/api/meetings/${id}/subtitles?limit=1000`),
        ]);

        setMeeting(meetingData);
        setTitle(meetingData.title);

        const items = subtitleResponse.items ?? [];
        setSubtitles(items);
        setEditableSubtitles(items);
        setOriginalSubtitles(items);

        if (meetingData.duration_seconds) {
          setDuration(meetingData.duration_seconds);
        }

        // 타임라인 데이터 로드
        setIsTimelineLoading(true);
        try {
          const timelineData = await getSpeakersTimeline(id);
          setTimeline(timelineData);
        } catch {
          // 타임라인 로드 실패는 무시
        } finally {
          setIsTimelineLoading(false);
        }
      } catch (err) {
        setError(err instanceof Error ? err : new Error('Unknown error'));
      } finally {
        setIsLoading(false);
      }
    }

    fetchData();
  }, [id, setTitle]);

  const hasChanges = changesMap.current.size > 0;

  const currentSubtitleIndex = useMemo(
    () =>
      editableSubtitles.findIndex(
        (subtitle) => currentTime >= subtitle.start_time && currentTime < subtitle.end_time
      ),
    [currentTime, editableSubtitles]
  );

  const availableSpeakers = useMemo(() => {
    const speakerSet = new Set<string>();
    subtitles.forEach((subtitle) => {
      const speaker = subtitle.speaker?.trim();
      if (speaker) {
        speakerSet.add(speaker);
      }
    });

    const dynamicOptions = Array.from(speakerSet)
      .sort((a, b) => a.localeCompare(b, 'ko-KR'))
      .map((speaker) => ({ value: speaker, label: speaker }));

    return [{ value: 'all', label: '전체' }, { value: 'unassigned', label: '미지정만' }, ...dynamicOptions];
  }, [subtitles]);

  // 화자 지정용 옵션 (실제 이름 + 기본 "화자 N")
  const speakerAssignOptions = useMemo(
    () => buildSpeakerOptions(subtitles),
    [subtitles]
  );

  const filteredSubtitles = useMemo(() => {
    if (speakerFilter === 'all') {
      return editableSubtitles;
    }
    if (speakerFilter === 'unassigned') {
      return editableSubtitles.filter((subtitle) => !subtitle.speaker);
    }
    return editableSubtitles.filter((subtitle) => subtitle.speaker === speakerFilter);
  }, [editableSubtitles, speakerFilter]);

  const unassignedCount = editableSubtitles.filter((subtitle) => !subtitle.speaker).length;

  useEffect(() => {
    if (activeTab !== 'assign') return;
    if (autoScroll && currentSubtitleIndex >= 0) {
      const currentSubtitle = editableSubtitles[currentSubtitleIndex];
      if (!currentSubtitle) return;

      const element = subtitleRefs.current.get(currentSubtitle.id);
      if (element && typeof element.scrollIntoView === 'function') {
        element.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }
  }, [activeTab, autoScroll, currentSubtitleIndex, editableSubtitles]);

  const handleTimeUpdate = useCallback((time: number) => {
    setCurrentTime(time);
    if (videoRef.current) {
      setDuration(videoRef.current.duration || 0);
    }
  }, []);

  const handleSeek = useCallback((startTime: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime = startTime;
      videoRef.current.play();
    }
  }, []);

  const handleSpeakerChange = useCallback((subtitleId: string, newSpeaker: string) => {
    const normalizedSpeaker = newSpeaker === '' ? '' : newSpeaker;

    setEditableSubtitles((prev) =>
      prev.map((subtitle) =>
        subtitle.id === subtitleId
          ? { ...subtitle, speaker: normalizedSpeaker }
          : subtitle
      )
    );

    const original = originalSubtitles.find((subtitle) => subtitle.id === subtitleId);
    if (original && (original.speaker ?? '') !== normalizedSpeaker) {
      changesMap.current.set(subtitleId, { speaker: normalizedSpeaker });
      return;
    }

    changesMap.current.delete(subtitleId);
  }, [originalSubtitles]);

  const handleBulkSpeakerApply = async () => {
    if (!bulkSpeaker || filteredSubtitles.length === 0) return;

    const targetSpeaker = bulkSpeaker;

    const updates = filteredSubtitles.filter((subtitle) => {
      if (subtitle.speaker === targetSpeaker) {
        return false;
      }
      const original = originalSubtitles.find((item) => item.id === subtitle.id);
      return !!original && (original.speaker ?? null) !== targetSpeaker;
    });

    if (updates.length === 0) {
      return;
    }

    setEditableSubtitles((prev) =>
      prev.map((subtitle) => {
        const changed = updates.find((candidate) => candidate.id === subtitle.id);
        if (!changed) {
          return subtitle;
        }
        return { ...subtitle, speaker: targetSpeaker };
      })
    );

    updates.forEach((subtitle) => {
      changesMap.current.set(subtitle.id, { speaker: targetSpeaker });
    });
  };

  const handleSave = async () => {
    if (!hasChanges) return;

    const items: SubtitleBatchItem[] = Array.from(changesMap.current.entries()).map(
      ([subtitleId, changes]) => ({ id: subtitleId, speaker: changes.speaker })
    );

    try {
      setIsSaving(true);
      await updateSubtitlesBatch(id, items);

      setOriginalSubtitles([...editableSubtitles]);
      changesMap.current.clear();

      // 타임라인 새로고침
      try {
        const timelineData = await getSpeakersTimeline(id);
        setTimeline(timelineData);
      } catch {
        // ignore
      }

      alert('화자 변경이 저장되었습니다.');
    } catch (err) {
      const message = err instanceof Error ? err.message : '저장에 실패했습니다.';
      alert(`저장 실패: ${message}`);
    } finally {
      setIsSaving(false);
    }
  };

  const handleBack = () => {
    if (hasChanges) {
      const confirmed = window.confirm('저장하지 않은 화자 변경사항이 있습니다. 이동할까요?');
      if (!confirmed) return;
    }
    router.push(`/vod/${id}`);
  };

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="w-12 h-12 border-4 border-gray-200 border-t-primary rounded-full animate-spin" />
      </div>
    );
  }

  if (error || !meeting) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <p className="text-error mb-4">회의 정보를 불러오지 못했습니다.</p>
          <Button variant="primary" onClick={() => router.push('/')}>
            홈으로 이동
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="speaker-page" className="flex flex-col h-full">
      {/* 상단 툴바 */}
      <div className="bg-white border-b border-gray-200 px-4 py-2 flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 min-w-0">
          <button
            onClick={handleBack}
            className="flex items-center gap-1.5 text-sm text-gray-600 hover:text-gray-900"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
            돌아가기
          </button>
          <span className="text-sm text-gray-500">|</span>
          <span className="text-sm text-gray-900 font-medium truncate">{meeting.title}</span>
        </div>

        <div className="flex items-center gap-2">
          <TranscriptStatusBadge
            meetingId={meeting.id}
            status={meeting.transcript_status || 'draft'}
            editable
            onStatusChange={(newStatus) =>
              setMeeting((prev) => (prev ? { ...prev, transcript_status: newStatus } : prev))
            }
          />
          {activeTab === 'assign' && (
            <Button
              variant="primary"
              size="sm"
              onClick={handleSave}
              disabled={!hasChanges}
              loading={isSaving}
            >
              {isSaving ? '저장 중...' : `변경 저장${hasChanges ? ` (${changesMap.current.size})` : ''}`}
            </Button>
          )}
          <Link
            href={`/vod/${id}/edit`}
            className="px-3 py-2 rounded-md border border-gray-300 text-sm text-gray-700 hover:bg-gray-50"
          >
            교정/편집으로 이동
          </Link>
        </div>
      </div>

      {/* 메인 레이아웃 */}
      <div className="flex-1 flex flex-col lg:flex-row gap-4 p-4 min-h-0">
        {/* 좌: 비디오 플레이어 */}
        <div className="w-full lg:w-3/5 bg-black flex items-center justify-center">
          <div className="w-full">
            <Mp4Player
              vodUrl={meeting.vod_url || ''}
              videoRef={videoRef}
              onTimeUpdate={handleTimeUpdate}
              onError={(err) => console.error('Video Error:', err)}
            />
            <VideoControls videoRef={videoRef} currentTime={currentTime} duration={duration} />
          </div>
        </div>

        {/* 우: 탭 패널 */}
        <div className="w-full lg:w-2/5 flex flex-col min-h-0">
          {/* 탭 전환 */}
          <div className="flex border-b border-gray-200 mb-3">
            <button
              data-testid="tab-timeline"
              onClick={() => setActiveTab('timeline')}
              className={`flex-1 py-2 text-sm font-medium text-center transition-colors ${
                activeTab === 'timeline'
                  ? 'text-primary border-b-2 border-primary'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              발언 타임라인
            </button>
            <button
              data-testid="tab-assign"
              onClick={() => setActiveTab('assign')}
              className={`flex-1 py-2 text-sm font-medium text-center transition-colors ${
                activeTab === 'assign'
                  ? 'text-primary border-b-2 border-primary'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              화자 지정
            </button>
          </div>

          {/* 탭 콘텐츠 */}
          {activeTab === 'timeline' ? (
            <SpeakerTimelineTab
              meetingId={id}
              timeline={timeline}
              isTimelineLoading={isTimelineLoading}
              currentTime={currentTime}
              onSeek={handleSeek}
              onTimelineRefresh={async () => {
                try {
                  const timelineData = await getSpeakersTimeline(id);
                  setTimeline(timelineData);
                } catch {
                  // ignore
                }
              }}
            />
          ) : (
            <SpeakerAssignTab
              editableSubtitles={editableSubtitles}
              currentSubtitleIndex={currentSubtitleIndex}
              autoScroll={autoScroll}
              speakerFilter={speakerFilter}
              bulkSpeaker={bulkSpeaker}
              filteredSubtitles={filteredSubtitles}
              unassignedCount={unassignedCount}
              availableSpeakers={availableSpeakers}
              speakerAssignOptions={speakerAssignOptions}
              subtitleRefs={subtitleRefs}
              committee={meeting?.committee}
              onAutoScrollToggle={() => setAutoScroll((prev) => !prev)}
              onSpeakerFilterChange={setSpeakerFilter}
              onBulkSpeakerChange={setBulkSpeaker}
              onBulkApply={handleBulkSpeakerApply}
              onSpeakerChange={handleSpeakerChange}
              onSeek={handleSeek}
            />
          )}
        </div>
      </div>
    </div>
  );
}
