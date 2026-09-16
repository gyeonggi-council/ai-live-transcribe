'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';

import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { Button, Card } from '@/components/ui';

import AiChatPanel from '../../../../components/AiChatPanel';
import EditableTranscriptBlock from '../../../../components/EditableTranscriptBlock';
import MinutesPreviewModal from '../../../../components/MinutesPreviewModal';
import { KMS_EXPORT_ENABLED } from '../../../../config/features';
import { useAuth } from '../../../../contexts/AuthContext';
import { useBreadcrumb } from '../../../../contexts/BreadcrumbContext';
import {
  apiClient,
  deleteAgendaFile,
  downloadTranscript,
  downloadKmsScript,
  downloadVideoMinutes,
  generateAgendaDraft,
  getAgendaFiles,
  getMinutesByAgenda,
  updateMeetingStatus,
  uploadAgendaFile,
} from '../../../../lib/api';
import { loadEdits, loadHistory, resetEdit, saveEdit } from '../../../../lib/minutesLocalEdits';

import type { MinutesEdit } from '../../../../lib/minutesLocalEdits';
import type {
  AgendaFileType,
  AgendaMinutesItem,
  MeetingSummaryType,
  MeetingType,
  MinutesByAgendaResponse,
  SubtitleType,
} from '../../../../types';

interface MinutesPageProps {
  params: { id: string };
}

/**
 * 시간 포맷: HH:MM:SS
 */
function formatTime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) {
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  }
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

/**
 * 화자별로 자막을 그룹화
 */
const MAX_GROUP_DURATION = 150; // 2.5분 — 긴 발언 시간 기준 분할
const MAX_GROUP_CHARS = 300; // 한 문단 최대 글자수 — 긴 발언을 읽기 좋게 문단 단위로 분할

function groupBySpeaker(subtitles: SubtitleType[]): Array<{
  speaker: string;
  texts: string[];
  startTime: number;
  endTime: number;
}> {
  const groups: Array<{
    speaker: string;
    texts: string[];
    startTime: number;
    endTime: number;
  }> = [];

  let current: (typeof groups)[0] | null = null;

  for (const sub of subtitles) {
    // 화자구분이 없으면(transcribe 자막) 빈 라벨 — 블록이 시각으로 대체 표시.
    // 빈 라벨끼리는 시간/글자 기준으로만 분할되어 자연스러운 문단이 된다.
    const speaker = sub.speaker || '';
    const curLen = current ? current.texts.join(' ').length : 0;
    const shouldSplit =
      !!current &&
      current.speaker === speaker &&
      (sub.start_time - current.startTime >= MAX_GROUP_DURATION ||
        curLen + (sub.text?.length || 0) > MAX_GROUP_CHARS);

    if (current && current.speaker === speaker && !shouldSplit) {
      current.texts.push(sub.text);
      current.endTime = sub.end_time;
    } else {
      if (current) groups.push(current);
      current = {
        speaker,
        texts: [sub.text],
        startTime: sub.start_time,
        endTime: sub.end_time,
      };
    }
  }
  if (current) groups.push(current);

  return groups;
}

/**
 * 회의록 상태 배지 컴포넌트 (드롭다운 포함)
 */
function TranscriptStatusDropdown({
  meetingId,
  status,
  onStatusChange,
}: {
  meetingId: string;
  status: 'draft' | 'reviewing' | 'final';
  onStatusChange: (newStatus: 'draft' | 'reviewing' | 'final') => void;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);

  const statusConfig = {
    draft: { label: '임시', color: 'bg-warning-bg/20 text-warning border-warning-bg/40' },
    reviewing: { label: '검토중', color: 'bg-primary-10 text-primary-dark border-primary-30' },
    final: { label: '최종', color: 'bg-success/10 text-success border-success/30' },
  };

  const handleStatusChange = async (newStatus: 'draft' | 'reviewing' | 'final') => {
    if (newStatus === status) {
      setIsOpen(false);
      return;
    }

    try {
      setIsUpdating(true);
      await updateMeetingStatus(meetingId, newStatus);
      onStatusChange(newStatus);
      setIsOpen(false);
    } catch (err) {
      alert(err instanceof Error ? err.message : '상태 변경에 실패했습니다.');
    } finally {
      setIsUpdating(false);
    }
  };

  const currentConfig = statusConfig[status];

  return (
    <div className="relative">
      <button
        data-testid="status-badge"
        onClick={() => {
          if (status !== 'final') setIsOpen(!isOpen);
        }}
        disabled={status === 'final' || isUpdating}
        className={`px-3 py-1.5 text-xs font-medium rounded-md border ${currentConfig.color} ${
          status === 'final' ? 'cursor-not-allowed opacity-75' : 'cursor-pointer hover:opacity-80'
        } transition-opacity`}
      >
        {isUpdating ? '업데이트 중...' : currentConfig.label}
        {status !== 'final' && (
          <svg className="w-3 h-3 ml-1 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        )}
      </button>

      {isOpen && status !== 'final' && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setIsOpen(false)} />
          <div className="absolute right-0 mt-1 w-32 bg-white border border-gray-200 rounded-md shadow-lg z-20">
            {Object.entries(statusConfig).map(([key, config]) => (
              <button
                key={key}
                onClick={() => handleStatusChange(key as 'draft' | 'reviewing' | 'final')}
                className={`w-full px-3 py-2 text-left text-sm hover:bg-gray-50 ${
                  key === status ? 'font-medium bg-gray-50' : ''
                }`}
              >
                {config.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/**
 * 수정 이력 모달 (간단 버전)
 */
function HistoryModal({
  subtitles,
  localHistory,
  onClose,
}: {
  subtitles: SubtitleType[];
  localHistory: MinutesEdit[];
  onClose: () => void;
}) {
  const correctedSubtitles = subtitles.filter(
    (s) => s.is_corrected || s.original_text
  );

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg max-w-2xl w-full mx-4 max-h-[80vh] flex flex-col">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900">수정 이력</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* 내 수정 (이 브라우저, localStorage) */}
          <div>
            <h3 className="text-sm font-semibold text-gray-900 mb-2">내 수정 (이 브라우저)</h3>
            {localHistory.length === 0 ? (
              <p className="text-xs text-gray-400">이 브라우저에서 수정한 내역이 없습니다.</p>
            ) : (
              <div className="space-y-3">
                {localHistory.map((h, i) => (
                  <div
                    key={`${h.blockKey}-${h.editedAt}-${i}`}
                    className="border border-warning-bg/40 rounded-lg p-3 bg-warning-bg/10"
                  >
                    <div className="flex items-center gap-2 mb-2 text-xs text-gray-500">
                      <span className="font-medium text-gray-700">{h.speaker}</span>
                      <span>
                        {formatTime(h.startTime)} ~ {formatTime(h.endTime)}
                      </span>
                      <span className="ml-auto">{new Date(h.editedAt).toLocaleString()}</span>
                    </div>
                    <p className="text-xs text-gray-500 mb-1">이전:</p>
                    <p className="text-sm text-gray-700 line-through mb-2 whitespace-pre-wrap">{h.original}</p>
                    <p className="text-xs text-gray-500 mb-1">수정:</p>
                    <p className="text-sm text-gray-900 whitespace-pre-wrap">{h.edited}</p>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* AI 교정 이력 */}
          <div>
            <h3 className="text-sm font-semibold text-gray-900 mb-2">AI 교정 이력</h3>
            {correctedSubtitles.length === 0 ? (
              <p className="text-xs text-gray-400">AI 교정된 자막이 없습니다.</p>
            ) : (
              <div className="space-y-4">
                {correctedSubtitles.map((subtitle) => (
                  <div key={subtitle.id} className="border border-gray-200 rounded-lg p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-xs text-gray-500">
                        {formatTime(subtitle.start_time)} ~ {formatTime(subtitle.end_time)}
                      </span>
                      {subtitle.is_corrected && (
                        <span className="px-2 py-0.5 bg-primary-10 text-primary-dark text-xs rounded">
                          AI 교정됨
                        </span>
                      )}
                    </div>
                    {subtitle.original_text && (
                      <div className="mb-2">
                        <p className="text-xs text-gray-500 mb-1">원본:</p>
                        <p className="text-sm text-gray-700 line-through">{subtitle.original_text}</p>
                      </div>
                    )}
                    <div>
                      <p className="text-xs text-gray-500 mb-1">수정됨:</p>
                      <p className="text-sm text-gray-900">{subtitle.text}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
        <div className="px-6 py-4 border-t border-gray-200">
          <button
            onClick={onClose}
            className="w-full px-4 py-2 bg-gray-100 text-gray-700 rounded-md hover:bg-gray-200 transition-colors"
          >
            닫기
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * 안건별 아코디언 아이템
 */
function AgendaAccordionItem({
  meetingId,
  agenda,
  isExpanded,
  onToggle,
  summary,
}: {
  meetingId: string;
  agenda: AgendaMinutesItem;
  isExpanded: boolean;
  onToggle: () => void;
  summary?: { summary: string };
}) {
  const [files, setFiles] = useState<AgendaFileType[]>([]);
  const [isFilesLoading, setIsFilesLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load files when expanded
  useEffect(() => {
    if (!isExpanded) return;

    const loadFiles = async () => {
      setIsFilesLoading(true);
      try {
        const fileList = await getAgendaFiles(meetingId, agenda.order_num.toString());
        setFiles(fileList);
      } catch (error) {
        console.error('파일 목록 조회 실패:', error);
      } finally {
        setIsFilesLoading(false);
      }
    };

    void loadFiles();
  }, [isExpanded, meetingId, agenda.order_num]);

  const handleFileSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = event.target.files?.[0];
    if (!selectedFile) return;

    setIsUploading(true);
    try {
      const uploadedFile = await uploadAgendaFile(meetingId, agenda.order_num.toString(), selectedFile);
      setFiles((prev) => [...prev, uploadedFile]);
      alert('파일이 업로드되었습니다.');
    } catch (error) {
      alert(error instanceof Error ? error.message : '파일 업로드 실패');
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleFileDelete = async (fileId: string) => {
    if (!window.confirm('파일을 삭제하시겠습니까?')) return;

    try {
      await deleteAgendaFile(meetingId, agenda.order_num.toString(), fileId);
      setFiles((prev) => prev.filter((f) => f.id !== fileId));
    } catch (error) {
      alert(error instanceof Error ? error.message : '파일 삭제 실패');
    }
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full px-4 py-3 bg-gray-50 flex items-center justify-between text-left hover:bg-gray-100 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-primary">
            {agenda.order_num}. {agenda.title}
          </span>
          <span className="text-xs text-gray-500">
            발언 {agenda.speaker_groups.length}개
          </span>
        </div>
        <svg
          className={`w-5 h-5 text-gray-400 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isExpanded && (
        <div className="p-4 space-y-4">
          {/* AI 요약 (있으면) */}
          {summary && (
            <div className="bg-primary-5 border border-primary-20 rounded-lg p-3">
              <h4 className="text-xs font-medium text-primary-dark mb-1">AI 요약</h4>
              <p className="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap">
                {summary.summary}
              </p>
            </div>
          )}

          {/* 화자별 발언 */}
          <div className="space-y-3">
            {agenda.speaker_groups.map((group, index) => (
              <div key={index} className="border-b border-gray-100 pb-3 last:border-b-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-sm font-semibold text-gray-900">{group.speaker}</span>
                  <span className="text-xs text-gray-400">
                    {formatTime(group.start_time)} ~ {formatTime(group.end_time)}
                  </span>
                </div>
                <p className="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap">
                  {group.texts.join(' ')}
                </p>
              </div>
            ))}
          </div>

          {/* 첨부파일 섹션 */}
          <div className="border-t border-gray-200 pt-4">
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-sm font-semibold text-gray-900">첨부파일</h4>
              <Button
                size="sm"
                onClick={() => fileInputRef.current?.click()}
                disabled={isUploading}
                className="text-xs"
              >
                {isUploading ? '업로드 중...' : '파일 추가'}
              </Button>
              <input
                ref={fileInputRef}
                type="file"
                className="hidden"
                onChange={handleFileSelect}
              />
            </div>

            {isFilesLoading ? (
              <div className="flex items-center justify-center py-4">
                <div className="w-5 h-5 border-2 border-gray-200 border-t-primary rounded-full animate-spin" />
              </div>
            ) : files.length === 0 ? (
              <p className="text-xs text-gray-500 py-2">첨부파일이 없습니다.</p>
            ) : (
              <div className="space-y-2">
                {files.map((file) => (
                  <div
                    key={file.id}
                    className="flex items-center justify-between p-2 bg-gray-50 rounded border border-gray-200"
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-gray-900 truncate">{file.filename}</p>
                      <p className="text-xs text-gray-500">
                        {formatFileSize(file.file_size)} · {new Date(file.created_at).toLocaleDateString()}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 ml-2">
                      <a
                        href={`/api/meetings/${meetingId}/agendas/${agenda.order_num}/files/${file.id}/download`}
                        download
                        className="p-1 text-primary hover:text-primary-dark transition-colors"
                        title="다운로드"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                        </svg>
                      </a>
                      <button
                        onClick={() => handleFileDelete(file.id)}
                        className="p-1 text-error hover:text-error/80 transition-colors"
                        title="삭제"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function MinutesPage({ params }: MinutesPageProps) {
  const router = useRouter();
  const { setTitle } = useBreadcrumb();
  const { user } = useAuth();
  const { id } = params;

  const [meeting, setMeeting] = useState<MeetingType | null>(null);
  const [subtitles, setSubtitles] = useState<SubtitleType[]>([]);
  // 자막 종류 비교: 'live'(실시간) vs 'ai'(VOD 화자구분). 둘 다 있으면 토글 노출.
  const [subtitleKind, setSubtitleKind] = useState<'live' | 'ai'>('ai');
  const [kindCounts, setKindCounts] = useState<{ live: number; ai: number }>({ live: 0, ai: 0 });
  // KMS 다운로드(전자회의록 hwpx / 영상회의록 html) 진행 표시.
  const [kmsBusy, setKmsBusy] = useState<'hwpx' | 'video' | 'js' | null>(null);
  // 전자회의록 미리보기·편집 모달 (로그인 사용자 전용)
  const [showMinutesPreview, setShowMinutesPreview] = useState(false);
  const [summary, setSummary] = useState<MeetingSummaryType | null>(null);
  // 안건 초안 생성 완료 여부 — 최초 1회만 허용 (중복 AI 호출 방지)
  const [draftDone, setDraftDone] = useState(false);
  const [agendaMinutes, setAgendaMinutes] = useState<MinutesByAgendaResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [isSummaryLoading, setIsSummaryLoading] = useState(false);
  const [isDraftLoading, setIsDraftLoading] = useState(false);
  const [isAgendaLoading, setIsAgendaLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'minutes' | 'summary' | 'agenda'>('minutes');
  const [showHistory, setShowHistory] = useState(false);
  const [expandedAgendas, setExpandedAgendas] = useState<Set<number>>(new Set());

  // 로컬(브라우저) 자막 수정 — 로그인 없이 localStorage에 저장
  const [localEdits, setLocalEdits] = useState<Record<string, MinutesEdit>>({});
  const [localHistory, setLocalHistory] = useState<MinutesEdit[]>([]);

  // 음성 재생 + 현재 재생 위치 하이라이트
  const audioRef = useRef<HTMLAudioElement>(null);
  const [audioCurrentTime, setAudioCurrentTime] = useState<number>(-1);
  const [isAudioPlaying, setIsAudioPlaying] = useState(false);
  const groupRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  // 초기 데이터 로드
  useEffect(() => {
    async function fetchData() {
      try {
        setIsLoading(true);
        setError(null);

        const [meetingData, subtitlesResponse] = await Promise.all([
          apiClient<MeetingType>(`/api/meetings/${id}`),
          apiClient<{ items: SubtitleType[]; kind?: 'live' | 'ai'; kind_counts?: { live: number; ai: number } }>(
            `/api/meetings/${id}/subtitles?limit=1000`
          ),
        ]);

        setMeeting(meetingData);
        setTitle(meetingData.title);
        setSubtitles(subtitlesResponse.items ?? []);
        if (subtitlesResponse.kind_counts) setKindCounts(subtitlesResponse.kind_counts);
        if (subtitlesResponse.kind) setSubtitleKind(subtitlesResponse.kind);
        // 시도 마커(migration 026) — 0개 추출로 끝난 생성 시도도 1회 정책에 포함
        if (meetingData.agenda_draft_at) setDraftDone(true);

        // 기존 요약 로드 시도
        try {
          const summaryData = await apiClient<MeetingSummaryType>(
            `/api/meetings/${id}/summary`
          );
          setSummary(summaryData);
        } catch {
          // 요약이 없을 수 있음
        }

        // 기존 안건 존재 여부 — 안건 초안은 최초 1회만 생성 가능
        try {
          const agendasResp = await apiClient<unknown>(`/api/meetings/${id}/agendas`);
          const list = Array.isArray(agendasResp)
            ? agendasResp
            : (agendasResp as { items?: unknown[]; agendas?: unknown[] })?.items ||
              (agendasResp as { agendas?: unknown[] })?.agendas ||
              [];
          if (Array.isArray(list) && list.length > 0) setDraftDone(true);
        } catch {
          // 안건 조회 실패는 무시 (버튼 활성 유지)
        }
      } catch (err) {
        setError(err instanceof Error ? err : new Error('Unknown error'));
      } finally {
        setIsLoading(false);
      }
    }

    fetchData();
  }, [id, setTitle]);

  // 로컬 수정/이력 로드 (이 브라우저)
  useEffect(() => {
    setLocalEdits(loadEdits(id));
    setLocalHistory(loadHistory(id));
  }, [id]);

  // 실시간↔AI 자막 종류 전환 (비교)
  const switchKind = useCallback(
    async (k: 'live' | 'ai') => {
      if (k === subtitleKind) return;
      setSubtitleKind(k);
      try {
        const res = await apiClient<{ items: SubtitleType[] }>(
          `/api/meetings/${id}/subtitles?limit=1000&kind=${k}`,
        );
        setSubtitles(res.items ?? []);
      } catch (e) {
        console.error('자막 종류 전환 실패:', e);
      }
    },
    [id, subtitleKind],
  );

  const handleSaveBlockEdit = (
    group: { speaker: string; startTime: number; endTime: number },
    blockKey: string,
    original: string,
    editedText: string,
    editedSpeaker: string,
  ) => {
    const edit: MinutesEdit = {
      blockKey,
      speaker: group.speaker,
      startTime: group.startTime,
      endTime: group.endTime,
      original,
      edited: editedText,
      editedSpeaker:
        editedSpeaker && editedSpeaker !== group.speaker ? editedSpeaker : undefined,
      editedAt: Date.now(),
    };
    setLocalEdits(saveEdit(id, edit));
    setLocalHistory(loadHistory(id));
  };

  const handleResetBlockEdit = (blockKey: string) => {
    setLocalEdits(resetEdit(id, blockKey));
  };

  // 안건별 탭 활성화 시 데이터 로드
  useEffect(() => {
    if (activeTab === 'agenda' && !agendaMinutes) {
      const fetchAgendaMinutes = async () => {
        try {
          setIsAgendaLoading(true);
          const data = await getMinutesByAgenda(id);
          setAgendaMinutes(data);
        } catch (err) {
          console.error('안건별 회의록 조회 실패:', err);
        } finally {
          setIsAgendaLoading(false);
        }
      };
      fetchAgendaMinutes();
    }
  }, [activeTab, id, agendaMinutes]);

  // 실제 AI 요약 호출 (admin 확인 후 실행)
  const runGenerateSummary = async () => {
    try {
      setIsSummaryLoading(true);
      const summaryData = await apiClient<MeetingSummaryType>(
        `/api/meetings/${id}/summary`,
        { method: 'POST' }
      );
      setSummary(summaryData);
      setActiveTab('summary');
    } catch (err) {
      alert(err instanceof Error ? err.message : 'AI 요약 생성에 실패했습니다.');
    } finally {
      setIsSummaryLoading(false);
    }
  };

  // AI 요약 생성 — 로그인 불필요. 회의당 1회만 생성(서버에서 기존 요약 재사용).
  const handleGenerateSummary = () => {
    void runGenerateSummary();
  };

  // 안건/의사일정 자동초안 생성 — AI 자막에서 안건 추출 + 안건별 요약으로 의사일정 내용 채움
  const handleGenerateAgendaDraft = async () => {
    try {
      setIsDraftLoading(true);
      const result = await generateAgendaDraft(id);
      // 요약·안건별 정리 갱신
      try {
        setSummary(await apiClient<MeetingSummaryType>(`/api/meetings/${id}/summary`));
      } catch {
        /* 요약 없을 수 있음 */
      }
      try {
        setAgendaMinutes(await getMinutesByAgenda(id));
      } catch {
        /* 안건 분류 실패 무시 */
      }
      setActiveTab('agenda');
      setDraftDone(true);
      alert(
        `안건 초안 생성 완료\n- 안건 ${result.agendas.length}개 (신규 추출 ${result.created_agendas}개)\n- 각 안건의 의사일정 내용(요약) 초안이 채워졌습니다.`
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : '안건 초안 생성에 실패했습니다.';
      if (msg.includes('이미')) setDraftDone(true); // 서버 1회 가드(409)
      alert(msg);
    } finally {
      setIsDraftLoading(false);
    }
  };

  // PDF 내보내기 (회의록 형식)
  const handleExportPdf = async () => {
    try {
      const response = await fetch(
        `/api/meetings/${id}/export?format=official`
      );
      if (!response.ok) throw new Error('내보내기 실패');

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `회의록_${meeting?.title || id}.md`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      alert(err instanceof Error ? err.message : '내보내기에 실패했습니다.');
    }
  };

  // KMS 전자회의록(hwpx) 다운로드 — 공식 회의록 양식
  const handleDownloadHwpx = async () => {
    try {
      setKmsBusy('hwpx');
      await downloadTranscript(id, 'hwpx');
    } catch (err) {
      alert(err instanceof Error ? err.message : '전자회의록 다운로드에 실패했습니다.');
    } finally {
      setKmsBusy(null);
    }
  };

  // KMS 영상회의록(html) 다운로드 — 안건시간/발언 챕터 (생성에 수 초)
  const handleDownloadVideoMinutes = async () => {
    try {
      setKmsBusy('video');
      await downloadVideoMinutes(id);
    } catch (err) {
      alert(err instanceof Error ? err.message : '영상회의록 다운로드에 실패했습니다.');
    } finally {
      setKmsBusy(null);
    }
  };

  // KMS 자동입력(js) 다운로드 — 편집기 콘솔 붙여넣기용 스크립트 (생성에 수 초)
  const handleDownloadKmsScript = async () => {
    try {
      setKmsBusy('js');
      await downloadKmsScript(id);
    } catch (err) {
      alert(err instanceof Error ? err.message : 'KMS 자동입력 스크립트 다운로드에 실패했습니다.');
    } finally {
      setKmsBusy(null);
    }
  };

  // 인쇄
  const handlePrint = () => {
    window.print();
  };

  // 재생 핸들러: 클릭한 구간 재생/일시정지 토글
  const handlePlayGroup = (startTime: number, endTime: number) => {
    const audio = audioRef.current;
    if (!audio || !meeting?.vod_url) return;

    // 현재 재생 중이고 클릭한 그룹 시간 범위 내에 있으면 → 일시정지
    if (isAudioPlaying && audio.currentTime >= startTime && audio.currentTime < endTime) {
      audio.pause();
      return;
    }

    audio.currentTime = startTime;
    audio.play().catch(() => {});
  };

  const speakerGroups = groupBySpeaker(subtitles);
  // 렌더 단위: 화자가 있으면(diarize/실시간) 화자별 문단, 없으면(transcribe) 문장 단위.
  // 문장 단위는 사용자가 문장을 눌러 그 지점부터 재생하고 현재 문장을 강조하기 위함.
  // (화자구분이 들어오면 자동으로 읽기 좋은 문단 묶음으로 전환된다.)
  const hasSpeakers = subtitles.some((s) => !!s.speaker);
  const minutesBlocks = hasSpeakers
    ? speakerGroups.map((g, i) => ({
        key: String(g.startTime),
        speaker: g.speaker,
        startTime: g.startTime,
        endTime: g.endTime,
        text: g.texts.join(' '),
        isContinuation: i > 0 && speakerGroups[i - 1]?.speaker === g.speaker,
      }))
    : subtitles.map((s) => ({
        key: String(s.id),
        speaker: s.speaker || '',
        startTime: s.start_time,
        endTime: s.end_time,
        text: s.text,
        isContinuation: false,
      }));

  // 현재 재생 중인 블록(문단/문장) 인덱스
  const activeBlockIndex = audioCurrentTime >= 0
    ? minutesBlocks.findIndex(b => audioCurrentTime >= b.startTime && audioCurrentTime < b.endTime)
    : -1;

  // 재생 중 활성 블록 자동 스크롤
  useEffect(() => {
    if (activeBlockIndex >= 0) {
      groupRefs.current.get(activeBlockIndex)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [activeBlockIndex]);

  // 로딩
  if (isLoading) {
    return (
      <div
        data-testid="page-loading"
        className="min-h-screen flex items-center justify-center"
      >
        <div className="w-12 h-12 border-4 border-gray-200 border-t-primary rounded-full animate-spin" />
      </div>
    );
  }

  // 에러
  if (error || !meeting) {
    return (
      <div
        data-testid="page-error"
        className="min-h-screen flex items-center justify-center"
      >
        <div className="text-center">
          <p className="text-error mb-4">오류가 발생했습니다.</p>
          <Button onClick={() => router.push('/')}>홈으로 이동</Button>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="minutes-page" className="flex flex-col h-full">
      {/* 상단 툴바 */}
      <div className="bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between gap-3 print:hidden">
        <div className="flex items-center gap-3 shrink-0">
          <Link
            href={`/vod/${id}`}
            className="flex items-center gap-1.5 text-sm text-gray-600 hover:text-gray-900 transition-colors whitespace-nowrap"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
            돌아가기
          </Link>
          <h1 className="text-lg font-semibold text-gray-900 whitespace-nowrap">회의록 작성</h1>
          <TranscriptStatusDropdown
            meetingId={id}
            status={meeting.transcript_status || 'draft'}
            onStatusChange={(newStatus) =>
              setMeeting((prev) => (prev ? { ...prev, transcript_status: newStatus } : prev))
            }
          />
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Button
            data-testid="history-button"
            variant="outline"
            onClick={() => setShowHistory(true)}
            className="gap-1.5"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            수정 이력
          </Button>
          <Button
            data-testid="print-button"
            variant="outline"
            onClick={handlePrint}
            className="gap-1.5"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z" />
            </svg>
            인쇄
          </Button>
          <Button
            data-testid="generate-agenda-draft-button"
            onClick={handleGenerateAgendaDraft}
            disabled={isDraftLoading || subtitles.length === 0 || draftDone}
            title={
              draftDone
                ? '안건 초안은 회의당 1회만 생성됩니다 (이미 생성됨)'
                : 'AI 자막에서 안건 + 의사일정 내용 초안을 자동 생성합니다 (회의당 1회)'
            }
            loading={isDraftLoading}
          >
            {isDraftLoading ? '안건 초안 생성 중...' : draftDone ? '안건 초안 생성됨 ✓' : '안건 초안 생성'}
          </Button>
          <Button
            data-testid="generate-summary-button"
            onClick={handleGenerateSummary}
            disabled={isSummaryLoading || subtitles.length === 0 || summary !== null}
            title={
              summary !== null
                ? 'AI 요약은 회의당 1회만 생성됩니다 (이미 생성됨)'
                : '자막을 AI로 분석해 회의 요약을 생성합니다 (회의당 1회)'
            }
            loading={isSummaryLoading}
          >
            {isSummaryLoading ? 'AI 요약 생성 중...' : summary !== null ? 'AI 요약 생성됨 ✓' : 'AI 요약 생성'}
          </Button>
          <button
            data-testid="export-pdf-button"
            onClick={handleExportPdf}
            className="px-4 py-2 bg-success text-white rounded-md text-sm font-medium whitespace-nowrap hover:bg-success/90 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            PDF 내보내기
          </button>
          {/* KMS 등록용 다운로드 — AI 자막이 있고, 백엔드 배포 완료 시에만 노출 */}
          {KMS_EXPORT_ENABLED && kindCounts.ai > 0 && (
            <>
              <Button
                data-testid="download-hwpx-button"
                onClick={handleDownloadHwpx}
                disabled={kmsBusy !== null}
                loading={kmsBusy === 'hwpx'}
                title="KMS 공식 양식의 전자회의록(한글 hwpx)을 다운로드합니다."
              >
                {kmsBusy === 'hwpx' ? '생성 중...' : '전자회의록 (HWPX)'}
              </Button>
              <Button
                data-testid="download-video-minutes-button"
                variant="secondary"
                onClick={handleDownloadVideoMinutes}
                disabled={kmsBusy !== null}
                loading={kmsBusy === 'video'}
                title="KMS 영상회의록 등록용 안건시간(챕터) HTML을 다운로드합니다. 생성에 수 초 걸립니다."
              >
                {kmsBusy === 'video' ? '영상회의록 생성 중...' : '영상회의록 (HTML)'}
              </Button>
              <Button
                data-testid="download-kms-script-button"
                variant="outline"
                onClick={handleDownloadKmsScript}
                disabled={kmsBusy !== null}
                loading={kmsBusy === 'js'}
                title="KMS 영상회의록 편집기 콘솔에 붙여넣으면 안건시간이 자동 입력되는 JS 스크립트를 다운로드합니다. (다운로드 → 편집기에서 해당 영상 열기 → F12 콘솔에 붙여넣기 → 저장)"
              >
                {kmsBusy === 'js' ? 'KMS 스크립트 생성 중...' : 'KMS 자동입력 (JS)'}
              </Button>
              {/* 전자회의록 미리보기·편집 — 마크다운 중간층은 로그인 사용자 전용(401) */}
              {user && (
                <button
                  data-testid="minutes-preview-button"
                  onClick={() => setShowMinutesPreview(true)}
                  disabled={kmsBusy !== null}
                  title="전자회의록 마크다운을 미리보고 편집한 뒤 kordoc 공문서 서식(HWPX)으로 다운로드합니다."
                  className="px-4 py-2 bg-success text-white rounded-md text-sm font-medium whitespace-nowrap hover:bg-success/90 transition-colors disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                >
                  미리보기·편집
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {/* 탭 네비게이션 */}
      <div className="bg-white border-b border-gray-200 px-4 print:hidden">
        <div className="flex gap-4">
          {[
            { key: 'minutes' as const, label: '회의록' },
            { key: 'summary' as const, label: 'AI 요약' },
            { key: 'agenda' as const, label: '안건별 정리' },
          ].map((tab) => (
            <button
              key={tab.key}
              data-testid={`tab-${tab.key}`}
              onClick={() => setActiveTab(tab.key)}
              className={`py-3 px-1 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.key
                  ? 'border-primary text-primary'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* 메인 콘텐츠 */}
      <div className="flex-1 overflow-y-auto p-4">
        {/* 회의 정보 (인쇄 시에도 표시) */}
        <Card padding="md" className="mb-4 print:border-0 print:shadow-none">
          <h2 className="text-base font-semibold text-gray-900 mb-2">{meeting.title}</h2>
          <div className="flex gap-4 text-sm text-gray-500">
            <span>일시: {meeting.meeting_date}</span>
            {meeting.committee && <span>위원회: {meeting.committee}</span>}
            <span>자막 수: {subtitles.length}개</span>
          </div>
        </Card>

        {/* 실시간↔AI 자막 비교 토글 — 두 종류가 모두 있을 때만 노출 */}
        {activeTab === 'minutes' && kindCounts.live > 0 && kindCounts.ai > 0 && (
          <div className="mb-3 flex items-center gap-2 print:hidden" data-testid="subtitle-kind-toggle">
            <span className="text-sm text-gray-500">자막 보기:</span>
            <div className="inline-flex rounded-lg border border-gray-200 overflow-hidden">
              <button
                onClick={() => switchKind('live')}
                className={`px-3 py-1.5 text-sm font-medium transition-colors ${
                  subtitleKind === 'live' ? 'bg-brand text-white' : 'bg-white text-gray-600 hover:bg-gray-50'
                }`}
              >
                실시간 자막 ({kindCounts.live})
              </button>
              <button
                onClick={() => switchKind('ai')}
                className={`px-3 py-1.5 text-sm font-medium transition-colors border-l border-gray-200 ${
                  subtitleKind === 'ai' ? 'bg-brand text-white' : 'bg-white text-gray-600 hover:bg-gray-50'
                }`}
              >
                AI 자막 (화자구분, {kindCounts.ai})
              </button>
            </div>
            <span className="text-xs text-gray-400">
              {subtitleKind === 'live'
                ? '실시간 방송 중 생성 — 정확한 텍스트(화자구분 없음)'
                : 'VOD 재전사 — 화자구분 포함'}
            </span>
          </div>
        )}

        {/* 회의록 탭 */}
        {activeTab === 'minutes' && (
          <Card data-testid="minutes-content" padding="lg" className="print:border-0 print:shadow-none">
            {subtitles.length === 0 ? (
              <p className="text-gray-500 text-center py-8">자막 데이터가 없습니다. STT를 먼저 실행해주세요.</p>
            ) : (
              <div className="space-y-4">
                {minutesBlocks.map((b, index) => (
                  <EditableTranscriptBlock
                    key={b.key}
                    speaker={b.speaker}
                    startTime={b.startTime}
                    endTime={b.endTime}
                    originalText={b.text}
                    edit={localEdits[b.key]}
                    isContinuation={b.isContinuation}
                    isActive={subtitleKind === 'ai' && activeBlockIndex === index}
                    showPlayButton={!!meeting.vod_url && subtitleKind === 'ai'}
                    isPlaying={isAudioPlaying}
                    onPlay={() => handlePlayGroup(b.startTime, b.endTime)}
                    onSave={(editedText, editedSpeaker) =>
                      handleSaveBlockEdit(
                        { speaker: b.speaker, startTime: b.startTime, endTime: b.endTime },
                        b.key,
                        b.text,
                        editedText,
                        editedSpeaker,
                      )
                    }
                    onReset={() => handleResetBlockEdit(b.key)}
                    registerRef={(el) => {
                      if (el) groupRefs.current.set(index, el);
                    }}
                  />
                ))}
              </div>
            )}
          </Card>
        )}

        {/* AI 요약 탭 */}
        {activeTab === 'summary' && (
          <Card data-testid="summary-content" padding="lg">
            {summary ? (
              <div className="space-y-6">
                <div>
                  <h3 className="text-base font-semibold text-gray-900 mb-2">회의 요약</h3>
                  <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">
                    {summary.summary_text}
                  </p>
                </div>
                {summary.key_decisions && summary.key_decisions.length > 0 && (
                  <div>
                    <h3 className="text-base font-semibold text-gray-900 mb-2">주요 결정사항</h3>
                    <ul className="list-disc list-inside space-y-1">
                      {summary.key_decisions.map((decision, i) => (
                        <li key={i} className="text-sm text-gray-700">{decision}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {summary.action_items && summary.action_items.length > 0 && (
                  <div>
                    <h3 className="text-base font-semibold text-gray-900 mb-2">후속 조치</h3>
                    <ul className="list-disc list-inside space-y-1">
                      {summary.action_items.map((item, i) => (
                        <li key={i} className="text-sm text-gray-700">{item}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ) : (
              <div className="text-center py-8">
                <p className="text-gray-500 mb-4">AI 요약이 아직 생성되지 않았습니다.</p>
                <Button
                  onClick={handleGenerateSummary}
                  disabled={isSummaryLoading || subtitles.length === 0}
                >
                  AI 요약 생성하기
                </Button>
              </div>
            )}
          </Card>
        )}

        {/* 안건별 정리 탭 */}
        {activeTab === 'agenda' && (
          <Card data-testid="agenda-content" padding="lg">
            {isAgendaLoading ? (
              <div className="flex items-center justify-center py-8">
                <div className="w-8 h-8 border-4 border-gray-200 border-t-primary rounded-full animate-spin" />
              </div>
            ) : agendaMinutes && agendaMinutes.agendas.length > 0 ? (
              <div className="space-y-3">
                {agendaMinutes.agendas.map((agenda) => {
                  const agendaSummary = summary?.agenda_summaries.find(
                    (s) => s.order_num === agenda.order_num && s.title === agenda.title
                  );
                  return (
                    <AgendaAccordionItem
                      key={agenda.order_num}
                      meetingId={id}
                      agenda={agenda}
                      isExpanded={expandedAgendas.has(agenda.order_num)}
                      onToggle={() => {
                        setExpandedAgendas((prev) => {
                          const newSet = new Set(prev);
                          if (newSet.has(agenda.order_num)) {
                            newSet.delete(agenda.order_num);
                          } else {
                            newSet.add(agenda.order_num);
                          }
                          return newSet;
                        });
                      }}
                      summary={agendaSummary}
                    />
                  );
                })}

                {/* 미할당 자막 (있을 경우) */}
                {agendaMinutes.unassigned_subtitles.length > 0 && (
                  <div className="mt-4 p-4 bg-gray-50 border border-gray-200 rounded-lg">
                    <h4 className="text-sm font-medium text-gray-700 mb-2">
                      안건 미할당 자막 ({agendaMinutes.unassigned_subtitles.length}개)
                    </h4>
                    <p className="text-xs text-gray-500">
                      안건에 포함되지 않은 발언입니다.
                    </p>
                  </div>
                )}
              </div>
            ) : (
              <div className="text-center py-8">
                <p className="text-gray-500 mb-4">안건이 등록되지 않았습니다.</p>
                <p className="text-sm text-gray-400">
                  회의 관리에서 안건을 등록하거나 AI 요약을 생성해주세요.
                </p>
              </div>
            )}
          </Card>
        )}
      </div>

      {/* 수정 이력 모달 */}
      {showHistory && (
        <HistoryModal
          subtitles={subtitles}
          localHistory={localHistory}
          onClose={() => setShowHistory(false)}
        />
      )}

      {/* 전자회의록 미리보기·편집 모달 */}
      <MinutesPreviewModal
        meetingId={id}
        isOpen={showMinutesPreview}
        onClose={() => setShowMinutesPreview(false)}
      />

      {/* Hidden audio player */}
      {meeting.vod_url && (
        <audio
          ref={audioRef}
          src={meeting.vod_url}
          preload="metadata"
          onTimeUpdate={() => {
            if (audioRef.current) setAudioCurrentTime(audioRef.current.currentTime);
          }}
          onEnded={() => { setIsAudioPlaying(false); setAudioCurrentTime(-1); }}
          onPause={() => setIsAudioPlaying(false)}
          onPlay={() => setIsAudioPlaying(true)}
          className="hidden"
        />
      )}

      {/* 인쇄 스타일 */}
      <style jsx global>{`
        @media print {
          /* 사이드바, 헤더, 탭 숨김 */
          .print\\:hidden {
            display: none !important;
          }

          /* A4 크기 최적화 */
          @page {
            size: A4;
            margin: 20mm;
          }

          body {
            font-size: 12pt;
            line-height: 1.6;
          }

          /* 페이지 브레이크 제어 */
          .print\\:break-inside-avoid {
            break-inside: avoid;
            page-break-inside: avoid;
          }

          /* 경계선, 그림자 제거 */
          .print\\:border-0 {
            border: 0 !important;
          }

          .print\\:shadow-none {
            box-shadow: none !important;
          }

          /* 여백 조정 */
          .p-4, .p-6 {
            padding: 1rem !important;
          }
        }
      `}</style>

      {/* AI 대화 (회의 컨텍스트) — 우측 하단 플로팅 패널, 로그인 불필요 */}
      <AiChatPanel
        meetingContextId={id}
        onPlayAt={(sec) => {
          const audio = audioRef.current;
          if (!audio || !meeting?.vod_url) return;
          audio.currentTime = sec;
          audio.play().catch(() => {});
        }}
      />
    </div>
  );
}
