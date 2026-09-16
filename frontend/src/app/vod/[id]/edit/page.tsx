'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';

import { useRouter } from 'next/navigation';

import { Button, Input } from '@/components/ui';

import AudioPlayerPanel from '../../../../components/AudioPlayerPanel';
import FindReplaceBar from '../../../../components/FindReplaceBar';
import Mp4Player from '../../../../components/Mp4Player';
import PiiMaskButton from '../../../../components/PiiMaskButton';
import ProofreadingToolbar from '../../../../components/ProofreadingToolbar';
import ProseTranscriptEditor from '../../../../components/ProseTranscriptEditor';
import SelectionToolbar from '../../../../components/SelectionToolbar';
import SpeakerSuggestModal from '../../../../components/SpeakerSuggestModal';
import SubtitleHistoryModal from '../../../../components/SubtitleHistoryModal';
import TranscriptNavPanel from '../../../../components/TranscriptNavPanel';
import TranscriptStatusBadge from '../../../../components/TranscriptStatusBadge';
import VideoControls from '../../../../components/VideoControls';
import { useBreadcrumb } from '../../../../contexts/BreadcrumbContext';
import useAudioKeyboardShortcuts from '../../../../hooks/useAudioKeyboardShortcuts';
import {
  apiClient,
  createEditSession,
  createSubtitleComment,
  deleteEditSession,
  getAgendas,
  getCouncilors,
  getEditSessions,
  getSubtitleComments,
  mergeSelectedSubtitles,
  splitSubtitle,
  toggleCommentResolved,
  updateEditSession,
  updateSubtitlesBatch,
} from '../../../../lib/api';
import { getWordDiff } from '../../../../utils/wordDiff';

import type { SubtitleBatchItem } from '../../../../lib/api';
import type {
  AgendaType,
  CouncilorType,
  EditSession,
  MeetingType,
  SubtitleComment,
  SubtitleType,
} from '../../../../types';

interface EditPageProps {
  params: { id: string };
}

/**
 * 시간 포맷: MM:SS
 */
function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

/**
 * 시간 포맷 (편집용): MM:SS.s
 */
function formatTimeEditable(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m.toString().padStart(2, '0')}:${s.toFixed(1).padStart(4, '0')}`;
}

/**
 * MM:SS.s 형식의 시간 문자열을 초(seconds)로 파싱
 */
function parseTimeInput(input: string): number | null {
  const trimmed = input.trim();
  // MM:SS.s or MM:SS
  const match = trimmed.match(/^(\d{1,3}):(\d{1,2}(?:\.\d{0,3})?)$/);
  if (!match) return null;
  const minutes = parseInt(match[1]!, 10);
  const secs = parseFloat(match[2]!);
  if (isNaN(minutes) || isNaN(secs) || secs >= 60) return null;
  return Math.round((minutes * 60 + secs) * 100) / 100;
}

/**
 * 기본 화자 옵션 + 자막에서 추출한 실제 화자 병합
 */
function buildSpeakerOptions(subtitles: SubtitleType[]): { value: string; label: string }[] {
  const options = [{ value: '', label: '(화자 미지정)' }];
  // 자막에서 고유 화자 추출
  const speakerSet = new Set<string>();
  for (const sub of subtitles) {
    if (sub.speaker) speakerSet.add(sub.speaker);
  }
  // 실제 화자 이름 추가
  for (const speaker of Array.from(speakerSet).sort()) {
    options.push({ value: speaker, label: speaker });
  }
  // 기본 화자 옵션 (1~10) — 아직 없는 것만
  for (let i = 1; i <= 10; i++) {
    const label = `화자 ${i}`;
    if (!speakerSet.has(label)) {
      options.push({ value: label, label });
    }
  }
  return options;
}

/**
 * 활성 편집자 표시 바
 */
function ActiveEditorsBar({
  sessions,
  onJoin,
}: {
  meetingId: string;
  sessions: EditSession[];
  onJoin: () => void;
  onRefresh: () => void;
}) {
  return (
    <div
      data-testid="active-editors"
      className="bg-white border-b border-gray-200 px-4 py-2 flex items-center justify-between"
    >
      <div className="flex items-center gap-3">
        <span className="text-sm text-gray-700">활성 편집자:</span>
        {sessions.length === 0 ? (
          <span className="text-xs text-gray-500">없음</span>
        ) : (
          <div className="flex items-center gap-2">
            {sessions.map((session) => (
              <div
                key={session.id}
                className="flex items-center gap-1.5 px-2 py-1 bg-primary-5 border border-primary-20 rounded-full"
              >
                <div className="w-2 h-2 bg-success rounded-full" />
                <span className="text-xs font-medium text-primary-dark">{session.editor_name}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      <Button
        data-testid="editor-join-btn"
        onClick={onJoin}
        size="sm"
        className="text-xs"
      >
        편집 시작
      </Button>
    </div>
  );
}

/**
 * 편집 시작 모달 (이름 입력)
 */
function EditorJoinModal({
  onJoin,
  onClose,
}: {
  onJoin: (name: string) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (name.trim()) {
      onJoin(name.trim());
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg max-w-md w-full mx-4">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">편집 시작</h2>
        </div>
        <form onSubmit={handleSubmit} className="p-6">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            이름 <span className="text-error">*</span>
          </label>
          <Input
            data-testid="editor-name-input"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="예: 홍길동"
            autoFocus
          />
          <div className="mt-4 flex items-center justify-end gap-2">
            <Button type="button" variant="outline" onClick={onClose}>
              취소
            </Button>
            <Button type="submit" disabled={!name.trim()}>
              시작
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

/**
 * 코멘트 패널
 */
function CommentPanel({
  meetingId,
  subtitleId,
  comments,
  onCommentAdded,
  onClose,
}: {
  meetingId: string;
  subtitleId: string;
  comments: SubtitleComment[];
  onCommentAdded: () => void;
  onClose: () => void;
}) {
  const [authorName, setAuthorName] = useState('');
  const [content, setContent] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!authorName.trim() || !content.trim()) return;

    setIsSubmitting(true);
    try {
      await createSubtitleComment(meetingId, subtitleId, authorName.trim(), content.trim());
      setContent('');
      onCommentAdded();
    } catch (err) {
      alert(err instanceof Error ? err.message : '코멘트 등록 실패');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleToggleResolved = async (commentId: string, currentResolved: boolean) => {
    try {
      await toggleCommentResolved(meetingId, commentId, !currentResolved);
      onCommentAdded();
    } catch (err) {
      alert(err instanceof Error ? err.message : '상태 변경 실패');
    }
  };

  return (
    <div
      data-testid="comment-panel"
      className="absolute top-0 right-0 w-80 h-full bg-white border-l border-gray-200 shadow-lg z-10 flex flex-col"
    >
      <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">코멘트</h3>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-gray-600 transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* 기존 코멘트 목록 */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {comments.length === 0 ? (
          <p className="text-xs text-gray-500 text-center py-4">코멘트가 없습니다.</p>
        ) : (
          comments.map((comment) => (
            <div
              key={comment.id}
              className={`p-3 rounded border ${
                comment.resolved
                  ? 'bg-gray-50 border-gray-300'
                  : 'bg-white border-gray-200'
              }`}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-medium text-gray-900">{comment.author_name}</span>
                <button
                  onClick={() => handleToggleResolved(comment.id, comment.resolved)}
                  className={`text-xs px-2 py-0.5 rounded ${
                    comment.resolved
                      ? 'bg-success/10 text-success'
                      : 'bg-warning-bg/20 text-warning'
                  }`}
                >
                  {comment.resolved ? '해결됨' : '미해결'}
                </button>
              </div>
              <p className="text-xs text-gray-700 whitespace-pre-wrap">{comment.content}</p>
              <p className="text-xs text-gray-400 mt-1">
                {new Date(comment.created_at).toLocaleString()}
              </p>
            </div>
          ))
        )}
      </div>

      {/* 새 코멘트 입력 */}
      <form onSubmit={handleSubmit} className="p-4 border-t border-gray-200">
        <input
          data-testid="comment-input"
          type="text"
          value={authorName}
          onChange={(e) => setAuthorName(e.target.value)}
          className="w-full px-3 py-1.5 mb-2 text-xs border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-primary"
          placeholder="작성자명"
        />
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={3}
          className="w-full px-3 py-2 text-xs border border-gray-300 rounded resize-none focus:outline-none focus:ring-2 focus:ring-primary"
          placeholder="코멘트 내용..."
        />
        <Button
          type="submit"
          size="sm"
          disabled={isSubmitting || !authorName.trim() || !content.trim()}
          className="w-full mt-2 text-xs"
        >
          {isSubmitting ? '등록 중...' : '코멘트 추가'}
        </Button>
      </form>
    </div>
  );
}

export default function SubtitleEditPage({ params }: EditPageProps) {
  const router = useRouter();
  const { setTitle } = useBreadcrumb();
  const { id } = params;

  const videoRef = useRef<HTMLVideoElement>(null);
  const subtitleRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  const [meeting, setMeeting] = useState<MeetingType | null>(null);
  const [originalSubtitles, setOriginalSubtitles] = useState<SubtitleType[]>([]);
  const [editedSubtitles, setEditedSubtitles] = useState<SubtitleType[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  const [isSaving, setIsSaving] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const [historySubtitleId, setHistorySubtitleId] = useState<string | null>(null);

  // Collaborative editing
  const [editSessions, setEditSessions] = useState<EditSession[]>([]);
  const [currentSession, setCurrentSession] = useState<EditSession | null>(null);
  const [showJoinModal, setShowJoinModal] = useState(false);
  const [commentsBySubtitle, setCommentsBySubtitle] = useState<Map<string, SubtitleComment[]>>(new Map());
  const [commentPanelSubtitleId, setCommentPanelSubtitleId] = useState<string | null>(null);

  // 뷰 모드: card(기존) / prose(속기)
  const [viewMode, setViewMode] = useState<'card' | 'prose'>('card');
  const [councilorsData, setCouncilorsData] = useState<CouncilorType[]>([]);
  const [agendasData, setAgendasData] = useState<AgendaType[]>([]);
  const [showSpeakerSuggest, setShowSpeakerSuggest] = useState(false);

  // Vrew 스타일 편집 상태
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [showFindReplace, setShowFindReplace] = useState(false);
  const [editingTimeId, setEditingTimeId] = useState<string | null>(null); // "subtitleId:start" or "subtitleId:end"
  const [editingTimeValue, setEditingTimeValue] = useState('');
  const [isMerging, setIsMerging] = useState(false);
  const [highlightedIds, setHighlightedIds] = useState<Set<string>>(new Set());
  const [currentHighlightId, setCurrentHighlightId] = useState<string | null>(null);

  // 변경사항 추적
  const changesMap = useRef<Map<string, { text?: string; speaker?: string; start_time?: number; end_time?: number }>>(
    new Map()
  );

  // 화자 옵션 (자막에서 실제 화자 이름 추출)
  const speakerOptions = React.useMemo(
    () => buildSpeakerOptions(editedSubtitles),
    [editedSubtitles]
  );

  // 초기 데이터 로드
  useEffect(() => {
    async function fetchData() {
      try {
        setIsLoading(true);
        setError(null);

        const [meetingData, subtitlesResponse] = await Promise.all([
          apiClient<MeetingType>(`/api/meetings/${id}`),
          apiClient<{ items: SubtitleType[] }>(
            `/api/meetings/${id}/subtitles?limit=1000`
          ),
        ]);

        setMeeting(meetingData);
        setTitle(meetingData.title);
        const items = subtitlesResponse.items ?? [];
        setOriginalSubtitles(items);
        setEditedSubtitles(items);

        if (meetingData.duration_seconds) {
          setDuration(meetingData.duration_seconds);
        }
      } catch (err) {
        setError(err instanceof Error ? err : new Error('Unknown error'));
      } finally {
        setIsLoading(false);
      }
    }

    fetchData();
  }, [id, setTitle]);

  // 의원 목록 + 안건 로드
  useEffect(() => {
    let cancelled = false;
    async function loadCouncilorsAndAgendas() {
      try {
        const [councilors, agendas] = await Promise.all([
          getCouncilors(),
          getAgendas(id).catch(() => [] as AgendaType[]),
        ]);
        if (!cancelled) {
          setCouncilorsData(councilors);
          setAgendasData(agendas);
        }
      } catch {
        // 실패 시 빈 배열 유지
      }
    }
    loadCouncilorsAndAgendas();
    return () => { cancelled = true; };
  }, [id]);

  // 속기 모드 키보드 단축키
  useAudioKeyboardShortcuts({
    videoRef,
    onSave: () => {
      const items: SubtitleBatchItem[] = Array.from(changesMap.current.entries()).map(
        ([subtitleId, changes]) => ({ id: subtitleId, ...changes })
      );
      if (items.length > 0) {
        updateSubtitlesBatch(id, items).then((response) => {
          setOriginalSubtitles([...editedSubtitles]);
          changesMap.current.clear();
          alert(`저장 완료: ${response.updated}개 항목이 수정되었습니다.`);
        }).catch((err) => {
          alert(`저장 실패: ${err instanceof Error ? err.message : '알 수 없는 오류'}`);
        });
      }
    },
    enabled: viewMode === 'prose',
  });

  // 편집 세션 로드
  useEffect(() => {
    const loadSessions = async () => {
      try {
        const sessions = await getEditSessions(id);
        setEditSessions(sessions.filter((s) => s.status === 'active'));
      } catch {
        // ignore
      }
    };
    loadSessions();
    const interval = setInterval(loadSessions, 10000); // 10초마다 갱신
    return () => clearInterval(interval);
  }, [id]);

  // 현재 세션 heartbeat (30초마다)
  useEffect(() => {
    if (!currentSession) return;
    const interval = setInterval(async () => {
      try {
        await updateEditSession(id, currentSession.id);
      } catch {
        // 세션 종료됨
        setCurrentSession(null);
      }
    }, 30000);
    return () => clearInterval(interval);
  }, [id, currentSession]);

  // 페이지 떠날 때 세션 종료
  useEffect(() => {
    const handleBeforeUnload = () => {
      if (currentSession) {
        deleteEditSession(id, currentSession.id).catch(() => {});
      }
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
      if (currentSession) {
        deleteEditSession(id, currentSession.id).catch(() => {});
      }
    };
  }, [id, currentSession]);

  // 코멘트 로드
  useEffect(() => {
    const loadComments = async () => {
      try {
        const allComments = await getSubtitleComments(id);
        const grouped = new Map<string, SubtitleComment[]>();
        for (const comment of allComments) {
          const list = grouped.get(comment.subtitle_id) || [];
          list.push(comment);
          grouped.set(comment.subtitle_id, list);
        }
        setCommentsBySubtitle(grouped);
      } catch {
        // ignore
      }
    };
    loadComments();
  }, [id]);

  // 현재 재생 위치에 해당하는 자막 인덱스
  const currentSubtitleIndex = editedSubtitles.findIndex(
    (sub) => currentTime >= sub.start_time && currentTime < sub.end_time
  );

  // 자동 스크롤
  useEffect(() => {
    if (autoScroll && currentSubtitleIndex >= 0) {
      const currentSubtitle = editedSubtitles[currentSubtitleIndex];
      if (currentSubtitle) {
        const element = subtitleRefs.current.get(currentSubtitle.id);
        if (element) {
          element.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }
    }
  }, [currentSubtitleIndex, autoScroll, editedSubtitles]);

  // 비디오 시간 업데이트
  const handleTimeUpdate = (time: number) => {
    setCurrentTime(time);
    if (videoRef.current) {
      setDuration(videoRef.current.duration || 0);
    }
  };

  // 자막 시간 클릭 → 해당 시점으로 비디오 이동
  const handleSubtitleTimeClick = (startTime: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime = startTime;
      videoRef.current.play();
    }
  };

  // 텍스트 수정
  const handleTextChange = (subtitleId: string, newText: string) => {
    setEditedSubtitles((prev) =>
      prev.map((sub) => (sub.id === subtitleId ? { ...sub, text: newText } : sub))
    );

    // 변경사항 추적
    const original = originalSubtitles.find((s) => s.id === subtitleId);
    if (original && original.text !== newText) {
      const current = changesMap.current.get(subtitleId) || {};
      changesMap.current.set(subtitleId, { ...current, text: newText });
    } else {
      const current = changesMap.current.get(subtitleId);
      if (current) {
        delete current.text;
        if (Object.keys(current).length === 0) {
          changesMap.current.delete(subtitleId);
        }
      }
    }
  };

  // 화자 수정
  const handleSpeakerChange = (subtitleId: string, newSpeaker: string) => {
    const speakerValue = newSpeaker === '' ? null : newSpeaker;

    setEditedSubtitles((prev) =>
      prev.map((sub) =>
        sub.id === subtitleId ? { ...sub, speaker: speakerValue } : sub
      )
    );

    // 변경사항 추적
    const original = originalSubtitles.find((s) => s.id === subtitleId);
    if (original && (original.speaker ?? '') !== newSpeaker) {
      const current = changesMap.current.get(subtitleId) || {};
      changesMap.current.set(subtitleId, { ...current, speaker: newSpeaker });
    } else {
      const current = changesMap.current.get(subtitleId);
      if (current) {
        delete current.speaker;
        if (Object.keys(current).length === 0) {
          changesMap.current.delete(subtitleId);
        }
      }
    }
  };

  // 시간 편집 시작 (더블클릭)
  const handleTimeEditStart = (subtitleId: string, field: 'start' | 'end', currentValue: number) => {
    setEditingTimeId(`${subtitleId}:${field}`);
    setEditingTimeValue(formatTimeEditable(currentValue));
  };

  // 시간 편집 완료
  const handleTimeEditEnd = (subtitleId: string, field: 'start' | 'end') => {
    const parsed = parseTimeInput(editingTimeValue);
    if (parsed !== null) {
      const sub = editedSubtitles.find((s) => s.id === subtitleId);
      if (sub) {
        // 검증: start < end
        const newStart = field === 'start' ? parsed : sub.start_time;
        const newEnd = field === 'end' ? parsed : sub.end_time;
        if (newStart >= newEnd) {
          alert('시작 시간이 종료 시간보다 크거나 같을 수 없습니다.');
          setEditingTimeId(null);
          return;
        }

        // 자막 상태 업데이트
        setEditedSubtitles((prev) =>
          prev.map((s) =>
            s.id === subtitleId
              ? { ...s, [field === 'start' ? 'start_time' : 'end_time']: parsed }
              : s
          )
        );

        // changesMap 업데이트
        const original = originalSubtitles.find((s) => s.id === subtitleId);
        const timeField = field === 'start' ? 'start_time' : 'end_time';
        const originalValue = original ? original[timeField] : undefined;
        if (originalValue !== parsed) {
          const current = changesMap.current.get(subtitleId) || {};
          changesMap.current.set(subtitleId, { ...current, [timeField]: parsed });
        } else {
          const current = changesMap.current.get(subtitleId);
          if (current) {
            delete current[timeField as keyof typeof current];
            if (Object.keys(current).length === 0) {
              changesMap.current.delete(subtitleId);
            }
          }
        }
      }
    }
    setEditingTimeId(null);
  };

  // 자막 분할
  const handleSplit = async (subtitleId: string, cursorPosition: number) => {
    try {
      const result = await splitSubtitle(id, subtitleId, cursorPosition);
      // editedSubtitles 업데이트: 원본을 2개로 교체
      setEditedSubtitles((prev) => {
        const idx = prev.findIndex((s) => s.id === subtitleId);
        if (idx === -1) return prev;
        const newList = [...prev];
        newList.splice(idx, 1, result.original, result.new);
        return newList;
      });
      setOriginalSubtitles((prev) => {
        const idx = prev.findIndex((s) => s.id === subtitleId);
        if (idx === -1) return [...prev, result.original, result.new];
        const newList = [...prev];
        newList.splice(idx, 1, result.original, result.new);
        return newList;
      });
      // changesMap에서 원본 제거 (서버가 이미 처리)
      changesMap.current.delete(subtitleId);
    } catch (err) {
      alert(err instanceof Error ? err.message : '분할 실패');
    }
  };

  // 자막 병합
  const handleMerge = async () => {
    if (selectedIds.size < 2) return;
    const ids = Array.from(selectedIds);

    // 시간순 정렬
    const sorted = ids
      .map((sid) => editedSubtitles.find((s) => s.id === sid))
      .filter(Boolean)
      .sort((a, b) => a!.start_time - b!.start_time)
      .map((s) => s!.id);

    if (!window.confirm(`${sorted.length}개 자막을 병합하시겠습니까?`)) return;

    try {
      setIsMerging(true);
      const result = await mergeSelectedSubtitles(id, sorted);

      // 병합된 자막 반영
      setEditedSubtitles((prev) => {
        const deletedIds = new Set(sorted.slice(1));
        return prev
          .map((s) => (s.id === sorted[0] ? result.merged : s))
          .filter((s) => !deletedIds.has(s.id));
      });
      setOriginalSubtitles((prev) => {
        const deletedIds = new Set(sorted.slice(1));
        return prev
          .map((s) => (s.id === sorted[0] ? result.merged : s))
          .filter((s) => !deletedIds.has(s.id));
      });

      // 정리
      for (const sid of sorted) changesMap.current.delete(sid);
      setSelectedIds(new Set());
    } catch (err) {
      alert(err instanceof Error ? err.message : '병합 실패');
    } finally {
      setIsMerging(false);
    }
  };

  // 화자 일괄 변경
  const handleBulkSpeakerChange = (newSpeaker: string) => {
    selectedIds.forEach((sid) => {
      handleSpeakerChange(sid, newSpeaker);
    });
    setSelectedIds(new Set());
  };

  // 체크박스 토글
  const handleToggleSelect = (subtitleId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(subtitleId)) {
        next.delete(subtitleId);
      } else {
        next.add(subtitleId);
      }
      return next;
    });
  };

  // FindReplace 하이라이트 콜백
  const handleFindReplaceHighlight = useCallback(
    (matchedIds: Set<string>, currentId: string | null) => {
      setHighlightedIds(matchedIds);
      setCurrentHighlightId(currentId);
      // 현재 매칭 자막으로 스크롤
      if (currentId) {
        const element = subtitleRefs.current.get(currentId);
        if (element) {
          element.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }
    },
    []
  );

  // FindReplace에서 텍스트 교체
  const handleFindReplaceReplace = useCallback(
    (subtitleId: string, newText: string) => {
      handleTextChange(subtitleId, newText);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [originalSubtitles]
  );

  // Ctrl+H 키보드 단축키
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'h') {
        e.preventDefault();
        setShowFindReplace((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  // 변경사항 개수
  const changesCount = changesMap.current.size;
  const hasChanges = changesCount > 0;

  // 저장
  const handleSave = async () => {
    if (!hasChanges) return;

    const items: SubtitleBatchItem[] = Array.from(changesMap.current.entries()).map(
      ([subtitleId, changes]) => ({
        id: subtitleId,
        ...changes,
      })
    );

    try {
      setIsSaving(true);
      const response = await updateSubtitlesBatch(id, items);

      // 성공 시 원본 업데이트 및 변경사항 초기화
      setOriginalSubtitles([...editedSubtitles]);
      changesMap.current.clear();

      alert(`저장 완료: ${response.updated}개 항목이 수정되었습니다.`);
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : '저장에 실패했습니다.';
      alert(`저장 실패: ${errorMessage}`);
    } finally {
      setIsSaving(false);
    }
  };

  // 뒤로 가기
  const handleBack = () => {
    if (hasChanges) {
      const confirmed = window.confirm(
        '저장하지 않은 변경사항이 있습니다. 페이지를 나가시겠습니까?'
      );
      if (!confirmed) return;
    }
    router.back();
  };

  // 편집 세션 시작 (실패 시에도 편집 진행 허용)
  const handleJoinEdit = async (name: string) => {
    try {
      const session = await createEditSession(id, name);
      setCurrentSession(session);
      setEditSessions((prev) => [...prev, session]);
    } catch (err) {
      console.warn('편집 세션 생성 실패 (편집은 계속 가능):', err instanceof Error ? err.message : err);
    }
    setShowJoinModal(false);
  };

  // 편집 세션 새로고침
  const handleRefreshSessions = async () => {
    try {
      const sessions = await getEditSessions(id);
      setEditSessions(sessions.filter((s) => s.status === 'active'));
    } catch {
      // ignore
    }
  };

  // 코멘트 새로고침
  const handleRefreshComments = async () => {
    try {
      const allComments = await getSubtitleComments(id);
      const grouped = new Map<string, SubtitleComment[]>();
      for (const comment of allComments) {
        const list = grouped.get(comment.subtitle_id) || [];
        list.push(comment);
        grouped.set(comment.subtitle_id, list);
      }
      setCommentsBySubtitle(grouped);
    } catch {
      // ignore
    }
  };

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
    <div
      data-testid="subtitle-edit-page"
      className="flex flex-col h-full"
    >
      {/* 활성 편집자 바 */}
      <ActiveEditorsBar
        meetingId={id}
        sessions={editSessions}
        onJoin={() => setShowJoinModal(true)}
        onRefresh={handleRefreshSessions}
      />

      {/* 상단 툴바 */}
      <div className="bg-white border-b border-gray-200 px-4 py-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <button
            data-testid="back-button"
            onClick={handleBack}
            className="flex items-center gap-1.5 text-sm text-gray-600 hover:text-gray-900 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
            돌아가기
          </button>
          <TranscriptStatusBadge
            meetingId={id}
            status={meeting.transcript_status || 'draft'}
            editable
            onStatusChange={(newStatus) =>
              setMeeting((prev) => prev ? { ...prev, transcript_status: newStatus } : prev)
            }
          />
        </div>
        <div className="flex items-center gap-2">
          {/* 뷰 모드 토글 */}
          <div className="flex items-center border border-gray-300 rounded-md overflow-hidden">
            <button
              data-testid="view-mode-card"
              onClick={() => setViewMode('card')}
              className={`px-2 py-1.5 text-xs font-medium transition-colors ${
                viewMode === 'card'
                  ? 'bg-primary text-white'
                  : 'bg-white text-gray-600 hover:bg-gray-50'
              }`}
              title="카드 편집"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 10h16M4 14h16M4 18h16" />
              </svg>
            </button>
            <button
              data-testid="view-mode-prose"
              onClick={() => setViewMode('prose')}
              className={`px-2 py-1.5 text-xs font-medium transition-colors ${
                viewMode === 'prose'
                  ? 'bg-primary text-white'
                  : 'bg-white text-gray-600 hover:bg-gray-50'
              }`}
              title="속기 편집"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </button>
          </div>
          <button
            data-testid="find-replace-toggle"
            onClick={() => setShowFindReplace((prev) => !prev)}
            className={`p-2 rounded-md transition-colors ${
              showFindReplace
                ? 'bg-primary text-white'
                : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
            }`}
            title="찾아 바꾸기 (Ctrl+H)"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </button>
        <Button
          data-testid="save-button"
          onClick={handleSave}
          disabled={!hasChanges}
          loading={isSaving}
        >
          {isSaving ? '저장 중...' : `저장${hasChanges ? ` (${changesCount})` : ''}`}
        </Button>
        </div>
      </div>

      {/* 메인 영역 */}
      {viewMode === 'prose' ? (
        /* ─── 속기 모드: 3-Panel (좌측 nav 240px + 중앙 편집기 + 우측 플레이어 320px) ─── */
        <div className="flex-1 min-h-0 grid grid-cols-1 md:grid-cols-[1fr_320px] lg:grid-cols-[240px_1fr_320px]">
          {/* 좌측: 네비게이션 패널 (태블릿에서 숨김) */}
          <div className="hidden lg:block overflow-y-auto">
            <TranscriptNavPanel
              subtitles={editedSubtitles}
              agendas={agendasData}
              meeting={meeting}
              currentTime={currentTime}
              onChapterClick={(time) => {
                if (videoRef.current) {
                  videoRef.current.currentTime = time;
                  videoRef.current.play();
                }
              }}
            />
          </div>

          {/* 중앙: 편집기 */}
          <div className="flex flex-col min-h-0 p-4 overflow-hidden">
            {/* 교정 도구 */}
            <div className="mb-2 space-y-2">
              <PiiMaskButton
                meetingId={id}
                onMaskApplied={async () => {
                  try {
                    const resp = await apiClient<{ items: SubtitleType[] }>(
                      `/api/meetings/${id}/subtitles?limit=1000`
                    );
                    const items = resp.items ?? [];
                    setOriginalSubtitles(items);
                    setEditedSubtitles(items);
                    changesMap.current.clear();
                  } catch { /* ignore */ }
                }}
              />
              <ProofreadingToolbar
                meetingId={id}
                onCorrectionsApplied={async () => {
                  try {
                    const resp = await apiClient<{ items: SubtitleType[] }>(
                      `/api/meetings/${id}/subtitles?limit=1000`
                    );
                    const items = resp.items ?? [];
                    setOriginalSubtitles(items);
                    setEditedSubtitles(items);
                    changesMap.current.clear();
                  } catch { /* ignore */ }
                }}
              />
            </div>

            {/* 찾아 바꾸기 */}
            {showFindReplace && (
              <FindReplaceBar
                subtitles={editedSubtitles}
                onReplace={handleFindReplaceReplace}
                onHighlight={handleFindReplaceHighlight}
                onClose={() => {
                  setShowFindReplace(false);
                  setHighlightedIds(new Set());
                  setCurrentHighlightId(null);
                }}
              />
            )}

            {/* 문단형 편집기 */}
            <ProseTranscriptEditor
              subtitles={editedSubtitles}
              currentTime={currentTime}
              councilors={councilorsData}
              onTextChange={handleTextChange}
              onSpeakerChange={handleSpeakerChange}
              committeeFilter={meeting.committee || undefined}
              onSeek={(time) => {
                if (videoRef.current) {
                  videoRef.current.currentTime = time;
                  videoRef.current.play();
                }
              }}
            />
          </div>

          {/* 우측: 플레이어 + 화자 추천 */}
          <div className="border-l border-gray-200 p-3 overflow-y-auto">
            <AudioPlayerPanel
              vodUrl={meeting.vod_url || ''}
              videoRef={videoRef}
              currentTime={currentTime}
              duration={duration}
              onTimeUpdate={handleTimeUpdate}
              onError={(err) => console.error('Video Error:', err)}
              currentSpeaker={
                editedSubtitles.find(
                  (s) => currentTime >= s.start_time && currentTime < s.end_time
                )?.speaker
              }
              currentCouncilor={
                (() => {
                  const speaker = editedSubtitles.find(
                    (s) => currentTime >= s.start_time && currentTime < s.end_time
                  )?.speaker;
                  return speaker
                    ? councilorsData.find((c) => c.name === speaker) ?? null
                    : null;
                })()
              }
            />
            {/* AI 화자 추천 버튼 */}
            <button
              data-testid="speaker-suggest-btn"
              onClick={() => setShowSpeakerSuggest(true)}
              className="w-full mt-3 px-3 py-2 text-sm bg-primary-5 text-primary-dark border border-primary-20 rounded-lg hover:bg-primary-10 transition-colors flex items-center justify-center gap-2"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
              </svg>
              AI 화자 추천
            </button>
          </div>
        </div>
      ) : (
        /* ─── 카드 모드 (기존): 비디오 60% + 자막 카드 40% ─── */
      <div className="flex-1 flex flex-col lg:flex-row gap-4 p-4 min-h-0">
        {/* 좌측: 비디오 플레이어 (60%) */}
        <div className="w-full lg:w-[60%]">
          <Mp4Player
            vodUrl={meeting.vod_url || ''}
            videoRef={videoRef}
            onTimeUpdate={handleTimeUpdate}
            onError={(err) => console.error('Video Error:', err)}
          />
          <VideoControls
            videoRef={videoRef}
            currentTime={currentTime}
            duration={duration}
          />
        </div>

        {/* 우측: 편집 가능한 자막 목록 (40%) */}
        <div className="w-full lg:w-[40%] flex flex-col">
          {/* 자동 스크롤 토글 */}
          <div className="mb-2 flex items-center justify-between bg-white px-4 py-2 border border-gray-200 rounded-md">
            <span className="text-sm text-gray-700">자동 스크롤</span>
            <button
              data-testid="auto-scroll-toggle"
              onClick={() => setAutoScroll((prev) => !prev)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                autoScroll ? 'bg-primary' : 'bg-gray-300'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  autoScroll ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
          </div>

          {/* 교정 도구 */}
          <div className="mb-2 space-y-2">
            <PiiMaskButton
              meetingId={id}
              onMaskApplied={async () => {
                // 마스킹 적용 후 자막 리로드
                try {
                  const resp = await apiClient<{ items: SubtitleType[] }>(
                    `/api/meetings/${id}/subtitles?limit=1000`
                  );
                  const items = resp.items ?? [];
                  setOriginalSubtitles(items);
                  setEditedSubtitles(items);
                  changesMap.current.clear();
                } catch { /* ignore */ }
              }}
            />
            <ProofreadingToolbar
              meetingId={id}
              onCorrectionsApplied={async () => {
                // 교정 적용 후 자막 리로드
                try {
                  const resp = await apiClient<{ items: SubtitleType[] }>(
                    `/api/meetings/${id}/subtitles?limit=1000`
                  );
                  const items = resp.items ?? [];
                  setOriginalSubtitles(items);
                  setEditedSubtitles(items);
                  changesMap.current.clear();
                } catch { /* ignore */ }
              }}
            />
          </div>

          {/* 찾아 바꾸기 */}
          {showFindReplace && (
            <FindReplaceBar
              subtitles={editedSubtitles}
              onReplace={handleFindReplaceReplace}
              onHighlight={handleFindReplaceHighlight}
              onClose={() => {
                setShowFindReplace(false);
                setHighlightedIds(new Set());
                setCurrentHighlightId(null);
              }}
            />
          )}

          {/* 자막 목록 */}
          <div
            data-testid="subtitle-list"
            className="flex-1 overflow-y-auto bg-white border border-gray-200 rounded-md"
          >
            {/* 선택 툴바 */}
            <SelectionToolbar
              selectedCount={selectedIds.size}
              speakerOptions={speakerOptions}
              onMerge={handleMerge}
              onBulkSpeakerChange={handleBulkSpeakerChange}
              onClearSelection={() => setSelectedIds(new Set())}
              isMerging={isMerging}
            />
            {editedSubtitles.length === 0 ? (
              <div className="p-8 text-center text-gray-500">
                자막이 없습니다.
              </div>
            ) : (
              <div className="divide-y divide-gray-200">
                {editedSubtitles.map((subtitle, index) => {
                  const isActive = index === currentSubtitleIndex;

                  return (
                    <div
                      key={subtitle.id}
                      ref={(el) => {
                        if (el) {
                          subtitleRefs.current.set(subtitle.id, el);
                        } else {
                          subtitleRefs.current.delete(subtitle.id);
                        }
                      }}
                      data-testid={`subtitle-item-${index}`}
                      className={`p-4 transition-colors ${
                        isActive
                          ? 'bg-primary-5 border-l-4 border-primary'
                          : currentHighlightId === subtitle.id
                          ? 'bg-highlight border-l-4 border-warning'
                          : highlightedIds.has(subtitle.id)
                          ? 'bg-highlight/40 border-l-4 border-warning/50'
                          : selectedIds.has(subtitle.id)
                          ? 'bg-primary-5 border-l-4 border-primary-30'
                          : 'border-l-4 border-transparent'
                      }`}
                    >
                      {/* 체크박스 + 시간 표시 + 이력/코멘트 아이콘 */}
                      <div className="flex items-center gap-2 mb-2">
                        <input
                          type="checkbox"
                          data-testid={`subtitle-checkbox-${index}`}
                          checked={selectedIds.has(subtitle.id)}
                          onChange={() => handleToggleSelect(subtitle.id)}
                          className="rounded border-gray-300 text-primary focus:ring-primary"
                        />
                        {/* 시간 인라인 편집 */}
                        {editingTimeId === `${subtitle.id}:start` ? (
                          <input
                            data-testid={`time-edit-start-${index}`}
                            type="text"
                            value={editingTimeValue}
                            onChange={(e) => setEditingTimeValue(e.target.value)}
                            onBlur={() => handleTimeEditEnd(subtitle.id, 'start')}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') handleTimeEditEnd(subtitle.id, 'start');
                              if (e.key === 'Escape') setEditingTimeId(null);
                            }}
                            className="w-20 px-1.5 py-0.5 text-xs border border-primary rounded focus:outline-none focus:ring-1 focus:ring-primary"
                            autoFocus
                          />
                        ) : (
                          <button
                            data-testid={`subtitle-time-start-${index}`}
                            onClick={() => handleSubtitleTimeClick(subtitle.start_time)}
                            onDoubleClick={(e) => {
                              e.stopPropagation();
                              handleTimeEditStart(subtitle.id, 'start', subtitle.start_time);
                            }}
                            className="text-xs text-gray-500 hover:text-primary transition-colors"
                            title="클릭: 이동 / 더블클릭: 시간 편집"
                          >
                            {formatTime(subtitle.start_time)}
                          </button>
                        )}
                        <span className="text-xs text-gray-400">~</span>
                        {editingTimeId === `${subtitle.id}:end` ? (
                          <input
                            data-testid={`time-edit-end-${index}`}
                            type="text"
                            value={editingTimeValue}
                            onChange={(e) => setEditingTimeValue(e.target.value)}
                            onBlur={() => handleTimeEditEnd(subtitle.id, 'end')}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') handleTimeEditEnd(subtitle.id, 'end');
                              if (e.key === 'Escape') setEditingTimeId(null);
                            }}
                            className="w-20 px-1.5 py-0.5 text-xs border border-primary rounded focus:outline-none focus:ring-1 focus:ring-primary"
                            autoFocus
                          />
                        ) : (
                          <button
                            data-testid={`subtitle-time-end-${index}`}
                            onClick={() => handleSubtitleTimeClick(subtitle.start_time)}
                            onDoubleClick={(e) => {
                              e.stopPropagation();
                              handleTimeEditStart(subtitle.id, 'end', subtitle.end_time);
                            }}
                            className="text-xs text-gray-500 hover:text-primary transition-colors"
                            title="클릭: 이동 / 더블클릭: 시간 편집"
                          >
                            {formatTime(subtitle.end_time)}
                          </button>
                        )}
                        <button
                          data-testid={`subtitle-history-${index}`}
                          onClick={() => setHistorySubtitleId(subtitle.id)}
                          className="text-gray-400 hover:text-primary transition-colors"
                          title="변경 이력"
                        >
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                          </svg>
                        </button>
                        <button
                          data-testid={`comment-icon-${subtitle.id}`}
                          onClick={() => setCommentPanelSubtitleId(subtitle.id)}
                          className="relative text-gray-400 hover:text-primary transition-colors"
                          title="코멘트"
                        >
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                          </svg>
                          {(commentsBySubtitle.get(subtitle.id)?.length || 0) > 0 && (
                            <span className="absolute -top-1 -right-1 bg-error text-white text-xs rounded-full w-3.5 h-3.5 flex items-center justify-center">
                              {commentsBySubtitle.get(subtitle.id)?.length}
                            </span>
                          )}
                        </button>
                        {/* 분할 버튼 */}
                        <button
                          data-testid={`subtitle-split-${index}`}
                          onClick={() => {
                            const textarea = document.querySelector<HTMLTextAreaElement>(
                              `[data-testid="subtitle-text-${index}"]`
                            );
                            const pos = textarea?.selectionStart ?? Math.floor(subtitle.text.length / 2);
                            if (pos > 0 && pos < subtitle.text.length) {
                              handleSplit(subtitle.id, pos);
                            } else {
                              alert('분할할 위치에 커서를 놓고 시도해주세요.');
                            }
                          }}
                          className="text-gray-400 hover:text-warning transition-colors"
                          title="자막 분할 (Ctrl+Enter)"
                        >
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l-2 2m0 0l-2-2m2 2V3m-6 8H4m16 0h-2M7 17l2-2m0 0l2 2m-2-2v4" />
                          </svg>
                        </button>
                      </div>

                      {/* 화자 선택 */}
                      <select
                        data-testid={`subtitle-speaker-${index}`}
                        value={subtitle.speaker ?? ''}
                        onChange={(e) =>
                          handleSpeakerChange(subtitle.id, e.target.value)
                        }
                        className="w-full mb-2 px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                      >
                        {speakerOptions.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>

                      {/* 텍스트 편집 */}
                      <textarea
                        data-testid={`subtitle-text-${index}`}
                        value={subtitle.text}
                        onChange={(e) => {
                          handleTextChange(subtitle.id, e.target.value);
                          // Auto-resize
                          e.target.style.height = 'auto';
                          e.target.style.height = e.target.scrollHeight + 'px';
                        }}
                        onFocus={(e) => {
                          e.target.style.height = 'auto';
                          e.target.style.height = e.target.scrollHeight + 'px';
                        }}
                        onKeyDown={(e) => {
                          // Ctrl+Enter → 자막 분할
                          if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                            e.preventDefault();
                            const pos = e.currentTarget.selectionStart;
                            if (pos > 0 && pos < subtitle.text.length) {
                              handleSplit(subtitle.id, pos);
                            }
                          }
                        }}
                        rows={2}
                        className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md resize-vertical focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent whitespace-pre-line"
                      />

                      {/* 단어 수준 변경사항 표시 */}
                      {(() => {
                        const original = originalSubtitles.find(s => s.id === subtitle.id);
                        if (!original || original.text === subtitle.text) return null;
                        const diff = getWordDiff(original.text, subtitle.text);
                        const hasChanges = diff.some(d => d.type !== 'same');
                        if (!hasChanges) return null;
                        return (
                          <div className="mt-1 px-2 py-1.5 bg-gray-50 border border-gray-200 rounded text-xs leading-relaxed whitespace-pre-line">
                            {diff.map((d, di) => (
                              <span
                                key={di}
                                className={
                                  d.type === 'removed'
                                    ? 'bg-error/10 text-error line-through'
                                    : d.type === 'added'
                                    ? 'bg-success/10 text-success font-medium'
                                    : 'text-gray-500'
                                }
                              >
                                {d.text}
                              </span>
                            ))}
                          </div>
                        );
                      })()}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
      )}

      {/* 변경 이력 모달 */}
      {historySubtitleId && (
        <SubtitleHistoryModal
          meetingId={id}
          subtitleId={historySubtitleId}
          onClose={() => setHistorySubtitleId(null)}
        />
      )}

      {/* 편집 시작 모달 */}
      {showJoinModal && (
        <EditorJoinModal
          onJoin={handleJoinEdit}
          onClose={() => setShowJoinModal(false)}
        />
      )}

      {/* 코멘트 패널 */}
      {commentPanelSubtitleId && (
        <CommentPanel
          meetingId={id}
          subtitleId={commentPanelSubtitleId}
          comments={commentsBySubtitle.get(commentPanelSubtitleId) || []}
          onCommentAdded={handleRefreshComments}
          onClose={() => setCommentPanelSubtitleId(null)}
        />
      )}

      {/* AI 화자 추천 모달 */}
      {showSpeakerSuggest && (
        <SpeakerSuggestModal
          meetingId={id}
          onApply={(speakerLabel, newName) => {
            // 해당 화자 라벨의 모든 자막에 의원 이름 일괄 반영
            for (const sub of editedSubtitles) {
              if (sub.speaker === speakerLabel) {
                handleSpeakerChange(sub.id, newName);
              }
            }
          }}
          onClose={() => setShowSpeakerSuggest(false)}
        />
      )}
    </div>
  );
}
