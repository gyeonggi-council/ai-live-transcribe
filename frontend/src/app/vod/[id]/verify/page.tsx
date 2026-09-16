'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';

import { useRouter } from 'next/navigation';

import Mp4Player from '../../../../components/Mp4Player';
import Button from '../../../../components/ui/Button';
import VideoControls from '../../../../components/VideoControls';
import { useBreadcrumb } from '../../../../contexts/BreadcrumbContext';
import {
  apiClient,
  batchVerifySubtitles,
  getReviewQueue,
  getVerificationStats,
  updateSubtitle,
  verifySubtitle,
} from '../../../../lib/api';

import type { MeetingType, SubtitleType, VerificationStatsType } from '../../../../types';

interface VerifyPageProps {
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
 * 신뢰도 기반 색상 클래스
 */
function getConfidenceClass(confidence: number | null): string {
  if (confidence === null) return 'text-gray-600 bg-gray-50';
  if (confidence < 0.5) return 'text-error bg-error/10';
  if (confidence < 0.7) return 'text-warning bg-warning-bg/20';
  return 'text-success bg-success/10';
}

export default function VerifyPage({ params }: VerifyPageProps) {
  const router = useRouter();
  const { setTitle } = useBreadcrumb();
  const { id } = params;
  const videoRef = useRef<HTMLVideoElement>(null);

  // State
  const [meeting, setMeeting] = useState<MeetingType | null>(null);
  const [stats, setStats] = useState<VerificationStatsType | null>(null);
  const [queue, setQueue] = useState<SubtitleType[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  // 편집 상태
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingText, setEditingText] = useState('');

  // 처리 중 상태
  const [isProcessing, setIsProcessing] = useState(false);

  // 초기 데이터 로드
  useEffect(() => {
    async function fetchData() {
      try {
        setIsLoading(true);
        setError(null);

        const [meetingData, statsData, queueData] = await Promise.all([
          apiClient<MeetingType>(`/api/meetings/${id}`),
          getVerificationStats(id),
          getReviewQueue(id, { limit: 1000 }),
        ]);

        setMeeting(meetingData);
        setTitle(meetingData.title);
        setStats(statsData);
        setQueue(queueData.items ?? []);

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

  // 통계 새로고침
  const refreshStats = useCallback(async () => {
    try {
      const statsData = await getVerificationStats(id);
      setStats(statsData);
    } catch {
      // 통계 새로고침 실패는 무시
    }
  }, [id]);

  // 비디오 시간 업데이트
  const handleTimeUpdate = (time: number) => {
    setCurrentTime(time);
    if (videoRef.current) {
      setDuration(videoRef.current.duration || 0);
    }
  };

  // 자막 시간 클릭 → 해당 시점으로 비디오 이동
  const seekTo = (time: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime = time;
      videoRef.current.play();
    }
  };

  // 검증 처리
  const handleVerify = async (subtitleId: string) => {
    try {
      setIsProcessing(true);
      await verifySubtitle(id, subtitleId, 'verified');

      // 대기열에서 제거
      setQueue((prev) => prev.filter((s) => s.id !== subtitleId));

      // 통계 새로고침
      await refreshStats();

      // 다음 항목으로 이동
      if (currentIndex >= queue.length - 1) {
        setCurrentIndex(Math.max(0, queue.length - 2));
      }
    } catch (err) {
      alert(
        `검증 실패: ${err instanceof Error ? err.message : '알 수 없는 오류'}`
      );
    } finally {
      setIsProcessing(false);
    }
  };

  // 플래그 처리
  const handleFlag = async (subtitleId: string) => {
    try {
      setIsProcessing(true);
      await verifySubtitle(id, subtitleId, 'flagged');

      // 대기열에서 제거
      setQueue((prev) => prev.filter((s) => s.id !== subtitleId));

      // 통계 새로고침
      await refreshStats();

      // 다음 항목으로 이동
      if (currentIndex >= queue.length - 1) {
        setCurrentIndex(Math.max(0, queue.length - 2));
      }
    } catch (err) {
      alert(
        `플래그 실패: ${err instanceof Error ? err.message : '알 수 없는 오류'}`
      );
    } finally {
      setIsProcessing(false);
    }
  };

  // 편집 후 검증
  const handleEditAndVerify = async (subtitleId: string, newText: string) => {
    try {
      setIsProcessing(true);

      // 텍스트 업데이트
      await updateSubtitle(id, subtitleId, { text: newText });

      // 검증 상태 변경
      await verifySubtitle(id, subtitleId, 'verified');

      // 대기열에서 제거
      setQueue((prev) => prev.filter((s) => s.id !== subtitleId));

      // 통계 새로고침
      await refreshStats();

      // 편집 모드 종료
      setEditingId(null);
      setEditingText('');

      // 다음 항목으로 이동
      if (currentIndex >= queue.length - 1) {
        setCurrentIndex(Math.max(0, queue.length - 2));
      }
    } catch (err) {
      alert(
        `편집 및 검증 실패: ${err instanceof Error ? err.message : '알 수 없는 오류'}`
      );
    } finally {
      setIsProcessing(false);
    }
  };

  // 배치 검증
  const handleBatchVerify = async () => {
    if (queue.length === 0) return;

    const confirmed = window.confirm(
      `남은 ${queue.length}개의 자막을 모두 검증하시겠습니까?`
    );

    if (!confirmed) return;

    try {
      setIsProcessing(true);
      const subtitleIds = queue.map((s) => s.id);
      await batchVerifySubtitles(id, subtitleIds, 'verified');

      // 대기열 초기화
      setQueue([]);
      setCurrentIndex(0);

      // 통계 새로고침
      await refreshStats();

      alert('모든 자막이 검증되었습니다.');
    } catch (err) {
      alert(
        `배치 검증 실패: ${err instanceof Error ? err.message : '알 수 없는 오류'}`
      );
    } finally {
      setIsProcessing(false);
    }
  };

  // 편집 시작
  const startEdit = (subtitle: SubtitleType) => {
    setEditingId(subtitle.id);
    setEditingText(subtitle.text);
  };

  // 편집 취소
  const cancelEdit = () => {
    setEditingId(null);
    setEditingText('');
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
          <Button variant="primary" size="md" onClick={() => router.push('/')}>
            홈으로 이동
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div
      data-testid="verify-page"
      className="flex flex-col h-full"
    >

      {/* 진행률 바 */}
      {stats && (
        <div
          data-testid="progress-bar"
          className="px-6 py-3 bg-white border-b border-gray-200"
        >
          <div className="flex justify-between text-sm mb-1">
            <span className="font-medium text-gray-700">검증 진행률</span>
            <span className="text-gray-600">
              {Math.round(stats.progress * 100)}% ({stats.verified}/
              {stats.total})
            </span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2.5 mb-2">
            <div
              className="bg-success h-2.5 rounded-full transition-all duration-300"
              style={{ width: `${Math.round(stats.progress * 100)}%` }}
            />
          </div>
          <div className="flex gap-4 text-xs text-gray-500">
            <span className="flex items-center gap-1">
              <span className="inline-block w-2 h-2 bg-success rounded-full" />✓ 검증: {stats.verified}
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block w-2 h-2 bg-warning-bg rounded-full" />⚑ 플래그: {stats.flagged}
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block w-2 h-2 bg-gray-400 rounded-full" />미검증: {stats.unverified}
            </span>
          </div>
        </div>
      )}

      {/* 메인 콘텐츠 */}
      <div className="flex-1 flex flex-col lg:flex-row gap-0">
        {/* 좌측: 비디오 플레이어 (60%) */}
        <div className="lg:w-3/5 bg-black flex items-center justify-center">
          <div className="w-full">
            <Mp4Player
              vodUrl={meeting.vod_url || ''}
              videoRef={videoRef}
              onTimeUpdate={handleTimeUpdate}
              onError={(err) => console.error('Video Error:', err)}
            />
            <div className="bg-black">
              <VideoControls
                videoRef={videoRef}
                currentTime={currentTime}
                duration={duration}
              />
            </div>
          </div>
        </div>

        {/* 우측: 검증 대기열 (40%) */}
        <div className="lg:w-2/5 overflow-y-auto bg-white border-l border-gray-200">
          {queue.length === 0 ? (
            <div
              data-testid="empty-queue"
              className="h-full flex flex-col items-center justify-center p-8 text-center"
            >
              <svg
                className="w-16 h-16 text-success mb-4"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
              <h2 className="text-xl font-bold text-gray-900 mb-2">
                검증 완료!
              </h2>
              <p className="text-gray-600 mb-4">
                모든 자막이 검증되었습니다.
              </p>
              <Button
                variant="primary"
                size="md"
                onClick={() => router.push(`/vod/${id}`)}
              >
                VOD 페이지로 이동
              </Button>
            </div>
          ) : (
            <div className="p-4 space-y-3">
              {/* 배치 검증 버튼 */}
              <button
                data-testid="batch-verify-button"
                onClick={handleBatchVerify}
                disabled={isProcessing}
                className="w-full py-2.5 px-4 bg-success text-white text-sm font-medium rounded-md hover:bg-success/90 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:bg-gray-300 disabled:cursor-not-allowed"
              >
                {isProcessing ? '처리 중...' : `전체 검증 (${queue.length}개)`}
              </button>

              {/* 대기열 아이템 */}
              <div className="space-y-2">
                {queue.map((subtitle, index) => {
                  const isEditing = editingId === subtitle.id;
                  const isCurrent = index === currentIndex;
                  const confidenceClass = getConfidenceClass(subtitle.confidence);

                  return (
                    <div
                      key={subtitle.id}
                      data-testid={`queue-item-${index}`}
                      className={`p-3 border rounded-lg transition-all ${
                        isCurrent
                          ? 'ring-2 ring-primary border-primary bg-primary-5'
                          : 'border-gray-200 bg-white hover:border-gray-300'
                      }`}
                    >
                      {/* 시간 + 신뢰도 */}
                      <div className="flex items-center justify-between mb-2">
                        <button
                          data-testid={`seek-button-${index}`}
                          onClick={() => {
                            seekTo(subtitle.start_time);
                            setCurrentIndex(index);
                          }}
                          className="text-xs text-primary hover:underline"
                        >
                          ▶ {formatTime(subtitle.start_time)} ~{' '}
                          {formatTime(subtitle.end_time)}
                        </button>
                        {subtitle.confidence !== null && (
                          <span
                            className={`text-xs px-2 py-0.5 rounded ${confidenceClass}`}
                          >
                            신뢰도: {Math.round(subtitle.confidence * 100)}%
                          </span>
                        )}
                      </div>

                      {/* 화자 */}
                      {subtitle.speaker && (
                        <div className="text-xs text-gray-600 mb-1">
                          {subtitle.speaker}
                        </div>
                      )}

                      {/* 텍스트 (편집 모드 / 일반 모드) */}
                      {isEditing ? (
                        <div className="space-y-2">
                          <textarea
                            data-testid={`edit-textarea-${index}`}
                            value={editingText}
                            onChange={(e) => setEditingText(e.target.value)}
                            rows={3}
                            className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md resize-none focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                          />
                          <div className="flex gap-2">
                            <button
                              data-testid={`save-edit-button-${index}`}
                              onClick={() =>
                                handleEditAndVerify(subtitle.id, editingText)
                              }
                              disabled={isProcessing}
                              className="flex-1 py-1.5 px-3 bg-primary text-white text-xs font-medium rounded hover:bg-primary-light transition-colors disabled:bg-gray-300"
                            >
                              저장 및 검증
                            </button>
                            <button
                              data-testid={`cancel-edit-button-${index}`}
                              onClick={cancelEdit}
                              disabled={isProcessing}
                              className="flex-1 py-1.5 px-3 bg-gray-200 text-gray-700 text-xs font-medium rounded hover:bg-gray-300 transition-colors disabled:bg-gray-100"
                            >
                              취소
                            </button>
                          </div>
                        </div>
                      ) : (
                        <>
                          <p className="text-sm text-gray-900 mb-3">
                            {subtitle.text}
                          </p>

                          {/* 액션 버튼 */}
                          <div className="flex gap-2">
                            <button
                              data-testid={`verify-button-${index}`}
                              onClick={() => handleVerify(subtitle.id)}
                              disabled={isProcessing}
                              className="flex-1 py-1.5 px-3 bg-success/10 text-success text-xs font-medium rounded border border-success/30 hover:bg-success/20 transition-colors disabled:bg-gray-100 disabled:text-gray-400"
                            >
                              ✓ 검증
                            </button>
                            <button
                              data-testid={`edit-button-${index}`}
                              onClick={() => startEdit(subtitle)}
                              disabled={isProcessing}
                              className="flex-1 py-1.5 px-3 bg-primary-5 text-primary-dark text-xs font-medium rounded border border-primary-20 hover:bg-primary-10 transition-colors disabled:bg-gray-100 disabled:text-gray-400"
                            >
                              ✎ 편집
                            </button>
                            <button
                              data-testid={`flag-button-${index}`}
                              onClick={() => handleFlag(subtitle.id)}
                              disabled={isProcessing}
                              className="flex-1 py-1.5 px-3 bg-warning-bg/10 text-warning text-xs font-medium rounded border border-warning-bg/40 hover:bg-warning-bg/20 transition-colors disabled:bg-gray-100 disabled:text-gray-400"
                            >
                              ⚑ 플래그
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
