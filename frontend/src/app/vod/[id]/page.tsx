'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';

import { Button } from '@/components/ui';
import {
  parseClockAnchors,
  wallMsFromClock,
  type ClockAnchor,
  type ClockAnchorSource,
} from '@/utils/meetingClock';

import MeetingDocumentsModal from '../../../components/ai/MeetingDocumentsModal';
import AiChatPanel from '../../../components/AiChatPanel';
import AiSummaryModal from '../../../components/AiSummaryModal';
import MaterialRequestPanel from '../../../components/MaterialRequestPanel';
import MeetingStageBadge from '../../../components/MeetingStageBadge';
import MeetingStageProgress from '../../../components/MeetingStageProgress';
import Mp4Player from '../../../components/Mp4Player';
import SearchInput from '../../../components/SearchInput';
import SubtitlePanel from '../../../components/SubtitlePanel';
import TranscriptExportButton from '../../../components/TranscriptExportButton';
import VideoClockBadge from '../../../components/VideoClockBadge';
import VideoControls from '../../../components/VideoControls';
import ViewerTabs from '../../../components/ViewerTabs';
import { useAuth } from '../../../contexts/AuthContext';
import { useBreadcrumb } from '../../../contexts/BreadcrumbContext';
import { logAccess, usePageAccessLog, useWatchAccessLog } from '../../../hooks/useAccessLog';
import { useMaterialRequests } from '../../../hooks/useMaterialRequests';
import { useRecordingSegmentPlayer } from '../../../hooks/useRecordingSegmentPlayer';
import { useSubtitleSearch } from '../../../hooks/useSubtitleSearch';
import { canUseAi } from '../../../lib/aiAccess';
import {
  API_BASE_URL,
  apiClient,
  ApiError,
  startSttProcessing,
  getSttStatus,
} from '../../../lib/api';
import { getMeetingStage } from '../../../utils/meetingStage';

import type { SttStatusResponse } from '../../../lib/api';
import type { MeetingType, SubtitleType } from '../../../types';

interface VodViewerPageProps {
  params: { id: string };
}

/**
 * 자막 종류 — 'auto' 는 서버 판단(AI 자막이 있으면 AI, 없으면 실시간).
 * 실시간 자막(초안)은 AI 자막이 만들어져도 kind='live' 로 보존된다.
 */
type SubtitleKind = 'auto' | 'live' | 'ai';

function VodViewerPageContent({ params }: VodViewerPageProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { effectiveRole } = useAuth();
  const { setTitle } = useBreadcrumb();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [meeting, setMeeting] = useState<MeetingType | null>(null);
  // 접속 통계의 시청 시간은 '재생 중' 일 때만 센다 — 틀어 놓고 잊은 탭까지 세면 부풀려진다
  const [videoPlaying, setVideoPlaying] = useState(false);
  const [docsOpen, setDocsOpen] = useState(false);
  const [subtitles, setSubtitles] = useState<SubtitleType[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  // 자막은 영상과 따로 로드한다 — 이 값이 true 여도 영상은 이미 재생 가능하다
  const [subtitlesLoading, setSubtitlesLoading] = useState(true);
  // 실시간 초안 ↔ AI 완성본 전환. ref 는 폴링 콜백에서 현재 선택을 읽기 위한 것
  // (reloadSubtitles 를 매번 새로 만들면 폴링 이펙트가 재실행된다).
  const [subtitleKind, setSubtitleKind] = useState<SubtitleKind>('auto');
  const subtitleKindRef = useRef<SubtitleKind>('auto');
  const [kindCounts, setKindCounts] = useState<{ live: number; ai: number }>({ live: 0, ai: 0 });
  const [effectiveKind, setEffectiveKind] = useState<SubtitleKind>('auto');
  const [error, setError] = useState<Error | null>(null);
  const [currentTime, setCurrentTime] = useState(0);

  // ─── 실제 시각(벽시계) ────────────────────────────────────────────────
  // 재생 위치가 "실제로 몇 시였나". 자막 시계는 정회 구간을 건너뛰므로 회의 시작 시각에
  // 더할 수 없고, 서버가 구간별 기준점을 준다(utils/meetingClock · GET .../clock-anchors).
  const [clockSource, setClockSource] = useState<ClockAnchorSource>('none');
  // 배지는 0.5초마다 스스로 읽는다 — 값이 아니라 ref 로 들어 렌더 횟수와 무관하게 흐른다
  const clockAnchorsRef = useRef<ClockAnchor[]>([]);
  const vodTimeOffsetRef = useRef(0);
  const [duration, setDuration] = useState(0);

  /**
   * `?t=초` — 통합검색·AI 답변에서 "이 회의로 이동" 했을 때 그 발언 시점부터 연다.
   * 2026-08-25 이전에는 이 값이 링크에 실려 오는데도 **읽는 곳이 없어** 항상 0초에서
   * 시작했다(검색 결과에서 00:12:41 을 눌러도 처음부터 재생).
   * 영상 준비와 자막 로드는 시점이 다르므로 각각 한 번씩만 적용한다.
   */
  const startAtRaw = searchParams.get('t');
  const parsedStartAt = startAtRaw === null ? NaN : Number(startAtRaw);
  const startAt = Number.isFinite(parsedStartAt) && parsedStartAt > 0 ? parsedStartAt : null;
  const startAtSeekedRef = useRef(false);
  const startAtScrolledRef = useRef(false);

  // 요구자료 감지 목록 (의원 자료 제출 요구 — 사무처 KMS 등록 보조)
  const materialRequests = useMaterialRequests(params.id);
  // STT 완료 폴링에서 재앵커된 요구자료를 리로드하기 위한 안정 참조
  // (refresh는 렌더마다 새 함수라 useCallback 의존성에 직접 넣으면 폴링 이펙트가 재실행됨)
  const materialRefreshRef = useRef(materialRequests.refresh);
  materialRefreshRef.current = materialRequests.refresh;
  // 미확인(detected) 건수 — 탭 배지와 하단 알림 줄이 함께 쓴다
  const pendingMaterialCount = materialRequests.requests.filter(
    (r) => r.status === 'detected'
  ).length;

  // 자막 패널 스크롤 요청 채널 — 검색 네비게이션과 요구자료 점프가 공유.
  // nonce 덕분에 같은 자막을 다시 요청해도 재스크롤된다.
  const [scrollRequest, setScrollRequest] = useState<{ id: string; nonce: number } | null>(null);
  const requestSubtitleScroll = useCallback((subtitleId: string) => {
    setScrollRequest((prev) => ({ id: subtitleId, nonce: (prev?.nonce ?? 0) + 1 }));
  }, []);

  // STT 처리 상태
  const [sttStatus, setSttStatus] = useState<SttStatusResponse | null>(null);
  const [sttError, setSttError] = useState<string | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // VOD 영상이 아직 없을 때(등록 대기) — 생중계 때 저장된 녹음이 있으면 자막 ▶ 로 그 구간
  // 음성을 들려준다(2026-09-15 담당자 요청). 생중계 화면과 같은 훅·같은 녹음 API 다.
  // 녹음이 없는 회의(라이브 STT 를 안 거쳤거나 보존 14일이 지남)는 ▶ 를 재생 버튼으로 만들지 않는다.
  const [hasRecording, setHasRecording] = useState(false);
  const [audioNotice, setAudioNotice] = useState<string | null>(null);
  const audioNoticeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const showAudioNotice = useCallback((message: string) => {
    setAudioNotice(message);
    if (audioNoticeTimerRef.current) clearTimeout(audioNoticeTimerRef.current);
    audioNoticeTimerRef.current = setTimeout(() => setAudioNotice(null), 4000);
  }, []);
  useEffect(() => () => {
    if (audioNoticeTimerRef.current) clearTimeout(audioNoticeTimerRef.current);
  }, []);
  const audioMeetingId = meeting?.id;
  const meetingVodUrl = meeting?.vod_url;
  useEffect(() => {
    setHasRecording(false);
    if (!audioMeetingId || meetingVodUrl) return;
    let cancelled = false;
    fetch(`${API_BASE_URL}/api/meetings/${audioMeetingId}/recording/meta`)
      .then((res) => {
        if (!cancelled) setHasRecording(res.ok);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [audioMeetingId, meetingVodUrl]);
  const { playSegment, playingSegmentId } = useRecordingSegmentPlayer({
    meetingId: audioMeetingId,
    onNotice: showAudioNotice,
  });


  // 자막 확대 + 검색
  const [subtitleExpanded, setSubtitleExpanded] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  // 보조 패널 탭 — 자막이 기본. 검색결과·요구자료를 세로로 이어 붙이지 않고
  // 동급의 탭으로 두어 "영상 바로 아래는 항상 자막"을 보장한다.
  const [activeTab, setActiveTab] = useState<'subtitles' | 'search' | 'materials'>('subtitles');

  // AI 요약 모달
  const [showAiSummary, setShowAiSummary] = useState(false);

  const { id } = params;

  // 자막 페이지 순차 로드 (백엔드 limit=1000이므로 페이지네이션 필요).
  // 장시간 본회의는 1000건 초과(최대 1617건 관찰됨) → 안전 상한까지 순회하되,
  // ★한 페이지가 올 때마다 화면에 붙인다 — 전부 모아 한 번에 넣으면 모바일에서
  //   자막이 수 초간 빈 채로 있다(1000건 ≈ 160KB, 회의당 2~3페이지).
  const loadSubtitles = useCallback(
    async (
      meetingId: string,
      state: { cancelled: boolean },
      kind?: SubtitleKind,
    ): Promise<void> => {
      const PAGE_SIZE = 1000;
      const MAX_PAGES = 20; // 안전 상한 (20,000건)
      const all: SubtitleType[] = [];
      const kindParam = kind && kind !== 'auto' ? `&kind=${kind}` : '';
      setSubtitlesLoading(true);
      try {
        for (let page = 0; page < MAX_PAGES; page++) {
          const offset = page * PAGE_SIZE;
          const resp = await apiClient<{
            items: SubtitleType[];
            total: number;
            kind?: SubtitleKind;
            kind_counts?: { live: number; ai: number };
          }>(
            `/api/meetings/${meetingId}/subtitles?limit=${PAGE_SIZE}&offset=${offset}${kindParam}`,
          );
          if (state.cancelled) return;
          // 종류별 보유 건수 — 실시간 초안/AI 완성본 토글 노출 판단에 쓴다
          if (resp.kind_counts) setKindCounts(resp.kind_counts);
          if (resp.kind) setEffectiveKind(resp.kind);
          const items = resp.items ?? [];
          all.push(...items);
          setSubtitles([...all]);
          if (items.length < PAGE_SIZE) break; // 마지막 페이지
          if (resp.total && all.length >= resp.total) break;
        }
      } finally {
        if (!state.cancelled) setSubtitlesLoading(false);
      }
    },
    [],
  );

  // 자막 데이터 리로드 (STT 완료 후 등)
  const reloadSubtitles = useCallback(async () => {
    try {
      await loadSubtitles(id, { cancelled: false }, subtitleKindRef.current);
    } catch {
      // 자막 리로드 실패는 조용히 무시
    }
  }, [id, loadSubtitles]);

  /** 실시간 초안 ↔ AI 완성본 전환 — 서버에서 해당 종류만 다시 받는다 */
  const handleKindChange = useCallback(
    (kind: SubtitleKind) => {
      setSubtitleKind(kind);
      subtitleKindRef.current = kind;
      setSubtitles([]);
      void loadSubtitles(id, { cancelled: false }, kind);
    },
    [id, loadSubtitles],
  );

  // ★회의 메타데이터가 오면 즉시 화면을 연다 — 예전에는 자막을 전부 받을 때까지
  //   Promise.all 로 묶여 있어서, 영상 플레이어조차 그때까지 뜨지 않았다.
  //   모바일에서 "영상 실행이 느리다"고 느껴지던 구간이 바로 여기다.
  useEffect(() => {
    const state = { cancelled: false };

    (async () => {
      try {
        setIsLoading(true);
        setError(null);

        const meetingData = await apiClient<MeetingType>(`/api/meetings/${id}`);
        if (state.cancelled) return;

        setMeeting(meetingData);
        setTitle(meetingData.title);
        // 초안(실시간 자막) 인덱스 ↔ KMS VOD 시간축 보정 — 있으면 반영(migration 030)
        vodTimeOffsetRef.current =
          Number((meetingData as { clip_time_offset?: number | null }).clip_time_offset ?? 0) || 0;
        if (meetingData.duration_seconds) {
          setDuration(meetingData.duration_seconds);
        }
        setIsLoading(false); // 여기서 영상이 뜬다 (자막은 뒤이어 채워진다)

        await loadSubtitles(id, state);
      } catch (err) {
        if (state.cancelled) return;
        setError(err instanceof Error ? err : new Error('Unknown error'));
        setIsLoading(false);
        setSubtitlesLoading(false);
      }
    })();

    return () => {
      state.cancelled = true;
    };
  }, [id, setTitle, loadSubtitles]);

  // 시각 기준점 로드 — 없거나 실패하면 시각 배지를 띄우지 않는다(틀린 시각보다 없는 편이 낫다)
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await apiClient<{ source?: string; anchors?: unknown }>(
          `/api/meetings/${id}/clock-anchors`,
        );
        if (cancelled) return;
        const anchors = parseClockAnchors(resp.anchors);
        clockAnchorsRef.current = anchors;
        setClockSource(anchors.length ? ((resp.source as ClockAnchorSource) ?? 'none') : 'none');
      } catch {
        if (cancelled) return;
        clockAnchorsRef.current = [];
        setClockSource('none');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  // 지금 재생 중인 장면의 실제 시각. 영상 요소에서 직접 읽어 일시정지·시크에도 그대로 맞는다.
  const getVodWallMs = useCallback(() => {
    const v = videoRef.current;
    if (!v || clockAnchorsRef.current.length === 0) return null;
    // 자막 시계 = VOD 재생 위치 − 초안 인덱스 보정 (migration 030 의 정의를 되돌린 것)
    return wallMsFromClock(clockAnchorsRef.current, v.currentTime - vodTimeOffsetRef.current);
  }, []);

  // 폴링 정리
  useEffect(() => {
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
      }
    };
  }, []);

  // STT 진행률 폴링 시작
  const startPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
    }

    pollingRef.current = setInterval(async () => {
      try {
        const status = await getSttStatus(id);
        setSttStatus(status);

        if (status.status === 'completed') {
          if (pollingRef.current) clearInterval(pollingRef.current);
          pollingRef.current = null;
          // 완료 시 자막 리로드 + 재앵커된 요구자료 시각 반영
          await reloadSubtitles();
          materialRefreshRef.current();
        } else if (status.status === 'failed') {
          if (pollingRef.current) clearInterval(pollingRef.current);
          pollingRef.current = null;
          setSttError(status.error || '알 수 없는 오류가 발생했습니다.');
        }
      } catch {
        // 폴링 에러는 조용히 무시 (다음 폴링에서 재시도)
      }
    }, 2000);
  }, [id, reloadSubtitles]);

  // 페이지 로드 시 STT 상태 자동 확인 (자막이 없고 vod_url이 있을 때).
  // subtitlesLoading 도 함께 본다 — 자막을 아직 받는 중인데 "자막 없음"으로
  // 판단해 STT 상태를 캐물으면 헛요청이 된다(영상과 자막 로드를 분리한 뒤 생김).
  useEffect(() => {
    if (isLoading || subtitlesLoading || subtitles.length > 0 || !meeting?.vod_url) return;

    async function checkSttStatus() {
      try {
        const status = await getSttStatus(id);
        if (status.status === 'running' || status.status === 'pending') {
          setSttStatus(status);
          startPolling();
        }
      } catch {
        // 상태 확인 실패는 무시 (아직 시작 안 한 경우)
      }
    }

    checkSttStatus();
  }, [id, isLoading, subtitlesLoading, subtitles.length, meeting?.vod_url, startPolling]);

  // 자막 생성 시작
  const handleStartStt = async () => {
    try {
      setSttError(null);
      const result = await startSttProcessing(id);
      setSttStatus({
        meeting_id: id,
        status: 'running',
        progress: 0,
        message: result.message,
        error: null,
        task_id: result.task_id,
      });
      startPolling();
    } catch (err) {
      // 409 = 이미 처리 중 → 에러 대신 폴링 시작
      if (err instanceof ApiError && err.status === 409) {
        setSttError(null);
        setSttStatus({
          meeting_id: id,
          status: 'running',
          progress: 0,
          message: '진행 상태 확인 중...',
          error: null,
        });
        startPolling();
        return;
      }
      if (err instanceof Error) {
        setSttError(err.message);
      } else {
        setSttError('STT 처리 시작에 실패했습니다.');
      }
    }
  };

  const handleTimeUpdate = (time: number) => {
    setCurrentTime(time);
    if (videoRef.current) {
      setDuration(videoRef.current.duration || 0);
    }
  };

  const handleSubtitleClick = (startTime: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime = startTime;
      videoRef.current.play();
    }
  };

  // `?t=` 적용 ①영상 — 위치는 `Mp4Player startTime` 이 **처음부터** 잡는다
  // (0초로 열고 나중에 옮기면 조각 경계에서 되돌아가 시점 이동이 먹지 않았다).
  // 여기서는 화면 표시만 맞추고 재생을 시도한다 — 재생은 best-effort 다.
  const handleVideoReady = useCallback(() => {
    if (startAt === null || startAtSeekedRef.current) return;
    const video = videoRef.current;
    if (!video) return;
    startAtSeekedRef.current = true;
    setCurrentTime(video.currentTime || startAt);
    const played = video.play?.();
    if (played && typeof played.catch === 'function') played.catch(() => {});
  }, [startAt]);

  // `?t=` 적용 ②자막 — 자막이 채워진 뒤 그 시점 자막으로 스크롤한다.
  // 영상만 옮기고 자막을 두면 "지금 어디를 보고 있는지"가 화면에서 갈라진다.
  useEffect(() => {
    if (startAt === null || startAtScrolledRef.current) return;
    if (subtitlesLoading || subtitles.length === 0) return;
    startAtScrolledRef.current = true;
    let target = subtitles[0];
    for (const s of subtitles) {
      if (s.start_time <= startAt + 0.5) target = s;
      else break;
    }
    if (target) requestSubtitleScroll(target.id);
  }, [startAt, subtitles, subtitlesLoading, requestSubtitleScroll]);

  // 요구자료 시각 클릭: 영상 시크 + 자막 패널도 같은 시점으로 스크롤.
  // subtitle_id(재앵커 후 유효한 AI 자막 id) 우선, 없거나 목록에 없으면 시간으로 탐색.
  const handleMaterialJump = (startTime: number, subtitleId?: string | null) => {
    handleSubtitleClick(startTime);
    const byId = subtitleId ? subtitles.find((s) => s.id === subtitleId) : undefined;
    const target =
      byId ??
      subtitles.find((s) => s.start_time <= startTime && startTime < s.end_time) ??
      (subtitles.length > 0
        ? subtitles.reduce((best, s) =>
            Math.abs(s.start_time - startTime) < Math.abs(best.start_time - startTime) ? s : best
          )
        : undefined);
    if (target) requestSubtitleScroll(target.id);
  };

  const handleHomeClick = () => {
    router.push('/');
  };

  // 자막 검색
  const {
    matchCount,
    currentMatchIndex,
    currentMatch,
    goToNextMatch,
    goToPrevMatch,
    isMatch,
  } = useSubtitleSearch({
    subtitles,
    query: searchQuery,
    filterMode: 'all',
  });

  // '검색결과' 탭은 일치한 자막만 — 전체 목록에서 눈으로 찾지 않게 한다.
  const matchedSubtitles = React.useMemo(
    () => subtitles.filter((s) => isMatch(s.id)),
    [subtitles, isMatch]
  );

  // 검색 네비게이션 이동도 통합 스크롤 채널로 (기존 동작 유지)
  useEffect(() => {
    if (currentMatch?.id) requestSubtitleScroll(currentMatch.id);
  }, [currentMatch?.id, requestSubtitleScroll]);

  // 영상 재생 여부 — 접속 통계의 시청 시간이 이 값만 본다
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return undefined;
    const on = () => setVideoPlaying(true);
    const off = () => setVideoPlaying(false);
    video.addEventListener('play', on);
    video.addEventListener('pause', off);
    video.addEventListener('ended', off);
    return () => {
      video.removeEventListener('play', on);
      video.removeEventListener('pause', off);
      video.removeEventListener('ended', off);
    };
  }, [meeting?.id]);

  // 검색어를 넣으면 검색결과 탭으로, 지우면 자막 탭으로 되돌린다
  // (탭이 있는데도 결과가 다른 탭에 숨어 있으면 검색이 먹통처럼 보인다)
  const handleSearch = (query: string) => {
    setSearchQuery(query);
    setActiveTab(query.trim() ? 'search' : 'subtitles');
    if (query.trim()) logAccess('search', { meetingId: meeting?.id ?? null });
  };

  // 접속 통계(2026-09-16) — 화면 열람 1회 + **영상이 실제로 재생 중일 때만** 5분마다 시청 신호.
  // IP 는 서버가 저장하지 않는다(접속처 이름으로만 바꾼다).
  usePageAccessLog('/vod/[id]', meeting?.id ?? null);
  useWatchAccessLog({ kind: 'watch_vod', meetingId: meeting?.id ?? null, active: videoPlaying });

  // 요구자료 시각 클릭 → 자막 탭으로 돌아가 해당 자막까지 스크롤
  const handleMaterialJumpFromTab = (startTime: number, subtitleId?: string | null) => {
    setActiveTab('subtitles');
    handleMaterialJump(startTime, subtitleId);
  };

  const isSttRunning =
    sttStatus?.status === 'pending' || sttStatus?.status === 'running';
  // AI 자막 생성 가능: VOD 등록됨 + 아직 AI 자막 전(자막 없음 또는 라이브 자막만).
  // 라이브 자막은 생성 시 더 정확한 AI 자막으로 교체된다. (관리자/회의담당 전용 API)
  const aiStageDone = ['ai', 'reviewing', 'final'].includes(meeting?.subtitle_stage ?? '');
  const showSttButton =
    !isLoading && !isSttRunning && !!meeting?.vod_url && !aiStageDone;

  // Loading state
  if (isLoading) {
    return (
      <div data-testid="page-loading" className="min-h-screen flex items-center justify-center">
        <div className="w-12 h-12 border-4 border-border border-t-primary rounded-full animate-spin" />
      </div>
    );
  }

  // Error state
  if (error || !meeting) {
    return (
      <div data-testid="page-error" className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <p className="text-error mb-4">오류가 발생했습니다.</p>
          <Button onClick={handleHomeClick}>홈으로 이동</Button>
        </div>
      </div>
    );
  }

  // AI 패널·요약 — 로그인 AI 역할(staff = QR 의원 포함) + 의회망 손님(2026-09-14, 정본 lib/aiAccess). 예전엔 meeting_manager·staff 가 빠져 있었다.
  const canEdit = canUseAi(effectiveRole);
  const stageInfo = getMeetingStage(meeting);
  // 두 종류가 다 있을 때만 초안/완성본 토글을 띄운다 — 한 종류뿐이면 고를 게 없다
  const showKindToggle = kindCounts.live > 0 && kindCounts.ai > 0;
  const selectedKind: 'live' | 'ai' =
    subtitleKind === 'auto'
      ? effectiveKind === 'live'
        ? 'live'
        : 'ai'
      : subtitleKind;
  // 녹음 시계는 라이브 자막 시각과만 맞는다 — AI 자막(영상 시각)에는 걸지 않는다
  const canPlayRecording = !meeting.vod_url && hasRecording && selectedKind === 'live';

  return (
    /* ★모바일은 '페이지가 스크롤되는 문서'가 아니라 '화면에 딱 맞는 앱'이다.
       예전엔 자막 패널이 h-[55vh] 고정이고 페이지 전체가 스크롤돼서, 위아래 띠를
       다 쌓고 나면 정작 자막이 150px 밖에 안 남았다(2026-08-22 신고).
       루트에서 overflow-hidden 으로 잠그고 자막 목록만 안에서 스크롤시킨다. */
    <div data-testid="vod-viewer-page" className="flex h-full min-h-0 flex-col overflow-hidden">
      {/* 상단 툴바 — 반드시 한 줄. 줄바꿈(flex-wrap)을 허용했더니 모바일에서
          [자막확대·단계바] / [회의록] / [검색] 3줄로 흩어져 영상이 그만큼 밀렸다.
          · 좁은 화면에서는 버튼 라벨을 숨겨 아이콘만 남기고, 검색창이 남은 폭을 먹는다.
          · 우측 pr 은 떠 있는 전역 컨트롤(햄버거·알림) 자리 예약 — 안 하면 그 밑에 깔린다. */}
      <div
        data-testid="vod-toolbar"
        className="flex shrink-0 flex-nowrap items-center gap-2 border-b border-border bg-surface py-2 pl-4 pr-24 lg:pr-16"
      >
        <button
          onClick={() => setSubtitleExpanded(prev => !prev)}
          className="px-2 py-1 rounded text-xs font-medium border border-border text-text-secondary hover:bg-surface-raised transition-colors flex items-center gap-1 whitespace-nowrap shrink-0"
          title={subtitleExpanded ? '기본 보기로 전환' : '자막 패널 확대'}
          aria-label={subtitleExpanded ? '기본 보기로 전환' : '자막 패널 확대'}
          data-testid="subtitle-expand-toggle"
        >
          {subtitleExpanded ? (
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 9V4.5M9 9H4.5M9 9L3.75 3.75M9 15v4.5M9 15H4.5M9 15l-5.25 5.25M15 9h4.5M15 9V4.5M15 9l5.25-5.25M15 15h4.5M15 15v4.5m0-4.5l5.25 5.25" />
            </svg>
          ) : (
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15" />
            </svg>
          )}
          <span className="hidden sm:inline">{subtitleExpanded ? '기본 보기' : '자막 확대'}</span>
        </button>
        {/* 단계 표시는 아래 단계 헤더(vod-stage-header)로 옮겼다 —
            툴바에 4단계를 넣으면 한 줄 규칙이 깨진다. */}
        {/* 회의록 작성/조회 링크 — 로그인 여부 무관, AI 요약만 관리자 제한 */}
        <Link
          href={`/vod/${meeting.id}/minutes`}
          title="회의록"
          className="px-2 sm:px-3 py-1 rounded text-xs font-medium border border-primary-20 text-primary hover:bg-primary-5 transition-colors inline-flex items-center gap-1 whitespace-nowrap shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          data-testid="go-to-minutes"
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          <span className="hidden sm:inline">회의록</span>
        </Link>
        {/* 부서별 문서(모니터링·자료요구 목록·표지·보도자료) — 버튼으로만, 권한은 서버가 판정(요약과 같다) */}
        {canEdit && (
        <button
          type="button"
          onClick={() => setDocsOpen(true)}
          title="문서 만들기"
          data-testid="open-meeting-documents"
          className="px-2 sm:px-3 py-1 rounded text-xs font-medium border border-primary-20 text-primary hover:bg-primary-5 transition-colors inline-flex items-center gap-1 whitespace-nowrap shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 10v6m0 0l-3-3m3 3l3-3M6 20h12a2 2 0 002-2V8.414a1 1 0 00-.293-.707l-4.414-4.414A1 1 0 0014.586 3H6a2 2 0 00-2 2v13a2 2 0 002 2z" />
          </svg>
          <span className="hidden sm:inline">문서</span>
        </button>
        )}
        <MeetingDocumentsModal meetingId={meeting.id} open={docsOpen} onClose={() => setDocsOpen(false)} />
        {/* 검색창이 남은 폭을 전부 먹는다 — min-w-0 이 없으면 입력이 줄바꿈을 유발한다 */}
        <div className="min-w-0 flex-1">
          <SearchInput onSearch={handleSearch} placeholder="자막 검색..." />
        </div>
      </div>

      {/* 단계 헤더 — 이 회의가 자막 처리 4단계 중 어디에 있는지, 다음에 무엇이 필요한지.
          안내 배너는 '아직 할 일이 남은' 회의에만 띄운다. AI 자막이 끝난 회의(대부분의
          지난 회의)에까지 배너를 깔면 영상이 그만큼 아래로 밀린다. */}
      <div
        data-testid="vod-stage-header"
        className="shrink-0 border-b border-border bg-surface px-4 py-1.5 lg:py-2.5"
      >
        <div className="flex items-center gap-4">
          {/* 모바일은 배지 한 줄만 — 4단계 진행바는 시청 중에 필요한 정보가 아니고
              한 줄(약 44px)이 자막 두 줄과 맞먹는다. 목록·PC 에서는 그대로 보인다. */}
          <div className="hidden min-w-0 max-w-md flex-1 lg:block">
            <MeetingStageProgress meeting={meeting} />
          </div>
          <MeetingStageBadge meeting={meeting} />
        </div>
        {stageInfo.currentIndex < 2 && (
          <p
            className="mt-2 hidden items-start gap-1.5 rounded-md bg-primary-5 px-3 py-2 text-xs leading-relaxed text-brand lg:flex"
            data-testid="stage-guidance"
          >
            <svg className="mt-px h-3.5 w-3.5 shrink-0" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z" />
            </svg>
            <span>{stageInfo.guidance}</span>
          </p>
        )}
      </div>

      <main
        data-testid="vod-layout"
        /* 모바일은 overflow-y-auto — 평소엔 딱 맞아서 스크롤이 안 생기지만,
           아주 작은 화면에서 자막이 0px 로 찌부러지는 것만은 막는다(아래 min-h). */
        className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-2 sm:gap-3 sm:p-3 lg:flex-row lg:gap-4 lg:overflow-hidden lg:p-4"
      >
        {/* Video Player (55% on desktop, hidden when subtitle expanded)
            lg:overflow-y-auto — 영상 아래 요구자료 패널까지 컬럼 안에서 스크롤 가능 */}
        <div
          data-testid="main-content"
          className={`w-full shrink-0 ${subtitleExpanded ? 'hidden' : 'lg:w-[55%] lg:flex-shrink-0 lg:min-h-0 lg:overflow-y-auto lg:pr-1'}`}
        >
          {meeting.vod_url ? (
            <>
              <Mp4Player
                vodUrl={meeting.vod_url}
                videoRef={videoRef}
                startTime={startAt ?? undefined}
                onReady={handleVideoReady}
                onTimeUpdate={handleTimeUpdate}
                onError={(err) => console.error('Video Error:', err)}
                overlay={
                  clockSource === 'none' ? null : (
                    <VideoClockBadge
                      getWallMs={getVodWallMs}
                      withDate
                      approximate={clockSource === 'estimated'}
                    />
                  )
                }
              />
              <VideoControls
                videoRef={videoRef}
                currentTime={currentTime}
                duration={duration}
              />
            </>
          ) : (
            // VOD URL 미등록 상태 — 30분 자동 등록 루프(kms_bulk_matcher)가 채우기
            // 전까지는 영상 없이 자막 타임라인만 열람 가능하도록 안내.
            // 관리자 VOD URL 등록 폼은 2026-09-08 사용자 결정으로 없앴다(PC·모바일 공통).
            <div
              data-testid="vod-pending"
              className="bg-gray-900 rounded-lg aspect-video flex flex-col items-center justify-center gap-3 p-6 text-center"
            >
              <svg className="w-16 h-16 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 10.5l4.72-4.72a.75.75 0 011.28.53v11.38a.75.75 0 01-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 002.25-2.25v-9a2.25 2.25 0 00-2.25-2.25h-9A2.25 2.25 0 002.25 7.5v9a2.25 2.25 0 002.25 2.25z" />
              </svg>
              <p className="text-white text-lg font-semibold">VOD 영상 등록 대기</p>
              <p className="text-white/60 text-sm max-w-sm leading-relaxed">
                생중계 종료 후 자막은 저장되었습니다. VOD 영상은 의회 홈페이지에 올라오면 30분 안에
                자동으로 등록되고, 이어서 AI 자막도 자동으로 만들어집니다.
                우측 패널에서 쌓인 자막({subtitles.length}건)을 먼저 확인하실 수 있습니다.
              </p>
              {canPlayRecording && (
                <p className="text-white/80 text-sm max-w-sm leading-relaxed" data-testid="vod-pending-audio-hint">
                  자막의 ▶ 시각을 누르면 생중계 때 녹음된 그 구간 음성을 들을 수 있습니다.
                </p>
              )}
            </div>
          )}

          {/* 요구자료 목록은 우측(모바일은 영상 아래) 탭으로 옮겼다 —
              영상과 자막 사이에 끼면 모바일에서 자막이 화면 밖으로 밀린다. */}
        </div>

        {/* Subtitle Panel (45% on desktop, full width when expanded)
            ★모바일 높이는 '남은 전부'(flex-1)다. 55vh 로 고정했더니 위아래 띠를
            쌓고 나면 실제 자막이 150px 밖에 안 남았다. 요구자료·검색결과는
            아래에 잇지 않고 같은 자리에서 탭으로 바꿔 넣는다. */}
        <div
          data-testid="sidebar"
          className={`flex w-full min-h-[9rem] flex-1 flex-col lg:h-full lg:min-h-0 lg:flex-none ${
            subtitleExpanded ? 'lg:w-full' : 'lg:w-[45%]'
          }`}
        >
          {/* STT 자막 생성 영역 */}
          {(showSttButton || isSttRunning || sttError) && (
            <div className="p-3 bg-surface border border-border rounded-lg mb-2">
              {showSttButton && !sttError && (
                <Button
                  data-testid="stt-start-button"
                  onClick={handleStartStt}
                  className="w-full"
                  title="관리자/회의담당 전용 — 회의당 약 10분, OpenAI 비용 발생 (영상 1시간당 약 $0.4)"
                >
                  {subtitles.length > 0 ? 'AI 자막 생성 (라이브 자막 교체)' : 'AI 자막 생성'}
                </Button>
              )}
              {isSttRunning && sttStatus && (
                <div data-testid="stt-progress">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium text-text-secondary">자막 생성 중...</span>
                    <span className="text-sm text-text-muted">{Math.round(sttStatus.progress * 100)}%</span>
                  </div>
                  <div className="w-full bg-surface-raised rounded-full h-2">
                    <div
                      className="bg-primary h-2 rounded-full transition-all duration-300"
                      style={{ width: `${Math.round(sttStatus.progress * 100)}%` }}
                    />
                  </div>
                  <p className="text-xs text-text-muted mt-1">{sttStatus.message}</p>
                </div>
              )}
              {sttStatus?.status === 'completed' && subtitles.length > 0 && (
                <p className="text-sm text-success font-medium">자막 생성 완료 ({subtitles.length}개)</p>
              )}
              {sttError && (
                <div data-testid="stt-error">
                  <p className="text-sm text-error mb-2">{sttError}</p>
                  <button
                    onClick={handleStartStt}
                    className="w-full py-2 px-4 bg-error/5 text-error text-sm font-medium rounded-md border border-error/30 hover:bg-error/10 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                  >
                    다시 시도
                  </button>
                </div>
              )}
            </div>
          )}

          {/* 자막 · 검색결과 · 요구자료 — 세로로 잇지 않고 같은 자리를 탭으로 바꿔 쓴다 */}
          <ViewerTabs
            className="mb-2"
            active={activeTab}
            onChange={(key) => setActiveTab(key as typeof activeTab)}
            tabs={[
              { key: 'subtitles', label: '자막', count: subtitles.length },
              {
                key: 'search',
                label: '검색결과',
                count: searchQuery ? matchCount : undefined,
              },
              {
                key: 'materials',
                label: '요구자료',
                count: materialRequests.requests.length,
                alert: pendingMaterialCount > 0,
              },
            ]}
          />

          {/* 검색 결과 네비게이션 */}
          {activeTab === 'search' && searchQuery && matchCount > 0 && (
            <div
              data-testid="search-navigation"
              className="flex items-center justify-between px-4 py-2 bg-highlight/20 border border-border rounded-t-lg"
            >
              <span className="text-sm text-text-secondary">
                검색 결과: {currentMatchIndex + 1} / {matchCount}
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={goToPrevMatch}
                  className="p-1 text-text-secondary hover:text-primary transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded"
                  aria-label="이전 결과"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                  </svg>
                </button>
                <button
                  onClick={goToNextMatch}
                  className="p-1 text-text-secondary hover:text-primary transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded"
                  aria-label="다음 결과"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                  </svg>
                </button>
              </div>
            </div>
          )}
          {activeTab === 'search' && searchQuery && matchCount === 0 && (
            <div className="px-4 py-2 bg-surface-raised border border-border rounded-t-lg text-sm text-text-muted">
              &quot;{searchQuery}&quot;에 대한 검색 결과가 없습니다.
            </div>
          )}
          {activeTab === 'search' && !searchQuery && (
            <div className="px-4 py-2 bg-surface-raised border border-border rounded-t-lg text-sm text-text-muted">
              상단 검색창에 발언 내용을 입력하면 결과가 여기에 표시됩니다.
            </div>
          )}

          {/* 탭 본문 — 요구자료는 목록 패널, 나머지는 자막 패널(검색결과는 일치분만) */}
          {activeTab === 'materials' ? (
            <div className="flex-1 min-h-0 overflow-y-auto" data-testid="materials-tab-panel">
              <MaterialRequestPanel
                requests={materialRequests.requests}
                isLoading={materialRequests.isLoading}
                onUpdate={materialRequests.update}
                onScan={subtitles.length > 0 ? materialRequests.scan : undefined}
                onJumpTo={meeting.vod_url ? handleMaterialJumpFromTab : undefined}
                onAddManual={materialRequests.addManual}
                fullViewHref={`/vod/${meeting.id}/materials`}
                fullHeight
              />
            </div>
          ) : (
            <div className="-mt-px flex min-h-0 flex-1 flex-col">
              <SubtitlePanel
                subtitles={activeTab === 'search' ? matchedSubtitles : subtitles}
                searchQuery={searchQuery}
                currentTime={currentTime}
                autoScroll={false}
                onSubtitleClick={handleSubtitleClick}
                onPlaySegment={canPlayRecording ? playSegment : undefined}
                playingSubtitleId={canPlayRecording ? playingSegmentId : null}
                isLoading={subtitlesLoading}
                scrollToSubtitleId={scrollRequest?.id}
                scrollNonce={scrollRequest?.nonce}
                /* 실시간 초안 ↔ AI 완성본 — 별도 줄을 두지 않고 자막 패널 헤더의
                   '자막' 제목 자리를 대신한다. 둘 다 있는 회의에서만 뜬다. */
                headerLeft={
                  showKindToggle && activeTab === 'subtitles' ? (
                    <div
                      className="flex min-w-0 items-center gap-1"
                      role="tablist"
                      aria-label="자막 종류 선택"
                      data-testid="subtitle-kind-toggle"
                    >
                      {([
                        { key: 'live' as const, short: '초안', long: '실시간 자막(초안)', count: kindCounts.live },
                        { key: 'ai' as const, short: '완성본', long: 'AI 자막(완성본)', count: kindCounts.ai },
                      ]).map((opt) => {
                        const active = selectedKind === opt.key;
                        return (
                          <button
                            key={opt.key}
                            type="button"
                            role="tab"
                            aria-selected={active}
                            aria-label={`${opt.long} ${opt.count}건`}
                            onClick={() => handleKindChange(opt.key)}
                            className={`rounded px-2 py-1 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary sm:px-2.5 ${
                              active
                                ? 'bg-primary-5 font-semibold text-brand'
                                : 'text-text-muted hover:bg-surface'
                            }`}
                            data-testid={`subtitle-kind-${opt.key}`}
                          >
                            <span className="sm:hidden">{opt.short}</span>
                            <span className="hidden sm:inline">{opt.long}</span>
                            <span className="ml-1 tabular-nums text-[10px] opacity-70">{opt.count}</span>
                          </button>
                        );
                      })}
                    </div>
                  ) : undefined
                }
              />
            </div>
          )}

          {audioNotice && (
            <div
              role="status"
              data-testid="audio-notice"
              className="shrink-0 border-t border-warning-bg/30 bg-warning-bg/10 px-4 py-2 text-center text-sm text-warning animate-fade-in"
            >
              {audioNotice}
            </div>
          )}

          {/* 하단: Export (모든 사용자) + AI 요약 (권한 있는 사용자만).
              ★모바일에서는 감춘다 — 시청 중에 쓰는 기능이 아닌데 자막을 두 줄 밀어낸다.
              내보내기는 상단 [회의록] 버튼으로 들어가는 회의록 화면에 그대로 있다.
              요구자료 알림 줄도 같은 이유로 없앴다 — 탭에 건수·미확인 표시가 이미 있다. */}
          {subtitles.length > 0 && (
            <div className="hidden border-t border-border bg-surface px-4 py-2 lg:block">
              <div className="flex gap-2">
                <TranscriptExportButton meetingId={id} meetingTitle={meeting.title} />
                {canEdit && (
                  <Button onClick={() => setShowAiSummary(true)}>
                    AI 요약
                  </Button>
                )}
              </div>
            </div>
          )}
        </div>
      </main>

      {/* AI 어시스턴트 (권한 있는 사용자만, 비로그인 시 완전 숨김) */}
      {canEdit && (
        <>
          <AiChatPanel meetingContextId={id} />
          <AiSummaryModal
            meetingId={id}
            isOpen={showAiSummary}
            onClose={() => setShowAiSummary(false)}
          />
        </>
      )}
    </div>
  );
}

/**
 * Suspense 래퍼 — `useSearchParams()`(`?t=`) 를 쓰는 페이지의 Next 14 요구사항이다.
 * 빠뜨리면 `next build` 가 프리렌더 단계에서 실패한다. `/search`·`/live` 와 같은 형태.
 */
export default function VodViewerPage({ params }: VodViewerPageProps) {
  return (
    <React.Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-surface-raised">
          <div className="text-text-muted">로딩 중...</div>
        </div>
      }
    >
      <VodViewerPageContent params={params} />
    </React.Suspense>
  );
}
