'use client';

import React, { Suspense, useCallback, useEffect, useRef, useState } from 'react';

import { useRouter, useSearchParams } from 'next/navigation';

import {
  liveClockAnchor,
  stabilizeAnchor,
  wallMsFromClock,
  type ClockAnchor,
} from '@/utils/meetingClock';

import Badge from '../../components/Badge';
import ChannelSelector from '../../components/ChannelSelector';
import CommitteeMembersModal from '../../components/CommitteeMembersModal';
import HlsPlayer, { LIVE_SYNC_TARGET_SEC } from '../../components/HlsPlayer';
import CurrentUtteranceCard from '../../components/live/CurrentUtteranceCard';
import LiveAgendaPanel from '../../components/live/LiveAgendaPanel';
import LiveFaceOverlay from '../../components/live/LiveFaceOverlay';
import LiveViewer from '../../components/live/LiveViewer';
import MaterialRequestPanel from '../../components/MaterialRequestPanel';
import SearchInput from '../../components/SearchInput';
import SubtitlePanel from '../../components/SubtitlePanel';
import TranscriptExportButton from '../../components/TranscriptExportButton';
import VideoClockBadge from '../../components/VideoClockBadge';
import ViewerTabs from '../../components/ViewerTabs';
import { usePageAccessLog, useWatchAccessLog } from '../../hooks/useAccessLog';
import { useChannelStatus } from '../../hooks/useChannelStatus';
import useLiveMeeting from '../../hooks/useLiveMeeting';
import { useMaterialRequests } from '../../hooks/useMaterialRequests';
import { useIsDesktop } from '../../hooks/useMediaQuery';
import { useMicSttStream } from '../../hooks/useMicSttStream';
import { useRecordingSegmentPlayer } from '../../hooks/useRecordingSegmentPlayer';
import { useSubtitleSearch } from '../../hooks/useSubtitleSearch';
import { useSubtitleWebSocket } from '../../hooks/useSubtitleWebSocket';
import { API_BASE_URL } from '../../lib/api';
import { LateArrivalTracker, pickSyncTarget, resolveVideoClock } from '../../utils/liveSync';
import { coarsenLiveSpeaker } from '../../utils/speakerLabel';


import type { ConnectionStatus, SttStatusType } from '../../hooks/useSubtitleWebSocket';
import type { ChannelType, MaterialRequestType, SubtitleType } from '../../types';

/**
 * SubtitleGenerationStatus — 자막 패널 하단 상태 바 + 진행 게이지.
 * 시청자가 "지금 자막이 생성되고 있는지, 얼마나 됐는지"를 한눈에 본다.
 * - 생성 중(초록): 다음 자막을 처리 중 — 경과 시간 + 평균과 함께 게이지가 차오름
 *   (평균은 최근 도착 간격에서 실측, 기본 12초 / 게이지 최대 ~18초)
 * - 음성 대기(노랑): 25~90초 — 발언이 없는 상태
 * - 수신 없음(회색): 90초 초과 — 정회/방송 종료 가능성
 * - 연결 상태 이상 시 연결 안내 표시
 */
const DEFAULT_AVG_INTERVAL_SEC = 12; // 배치 전사 주기 실측 전 기본값 (서버가 window_seconds 를 주면 그 값)
const GAUGE_MAX_SEC = 18; // 윈도우 12초 + 전사 처리 ~3초 + 여유 (서버 창 길이 + 6 으로 파생, 이 값은 폴백)

// ─── 영상-자막 정밀 동기화 ──────────────────────────────────────────────
// 서버 stt_status의 audio_clock(자막 start_time과 같은 오디오-초 시계)과
// hls.js의 실측 라이브 지연(latency)으로 "영상이 지금 보여주는 오디오-초"를
// 역산해, 각 자막을 영상이 그 발언 지점에 도달하는 순간 표시한다(VOD처럼).
// 측정 불가 시(네이티브 HLS, 서버 구버전 등) 기존 고정 지연으로 폴백.
const FALLBACK_DISPLAY_DELAY_MS = Number(
  process.env.NEXT_PUBLIC_SUBTITLE_DISPLAY_DELAY_MS ?? 5000,
);
// 백엔드 디코더가 플레이리스트 엣지보다 뒤처지는 추정치(폴링+다운로드+디코딩)
const BACKEND_EDGE_LAG_SEC = Number(process.env.NEXT_PUBLIC_SYNC_EDGE_LAG_SEC ?? 3);
const ANCHOR_STALE_MS = 15000; // 상태 방송이 이보다 오래되면 앵커 무효
const MAX_CLOCK_LAG_SEC = 45; // 안전판: 영상시계가 서버시계보다 이 이상 뒤지지 않게 클램프

function SubtitleGenerationStatus({
  lastActivityTime,
  connectionStatus,
  sttStatus,
  subtitleCount,
}: {
  lastActivityTime: number | null;
  connectionStatus: ConnectionStatus;
  sttStatus: SttStatusType | null;
  /** 지금까지 쌓인 자막 수 — 패널 헤더가 사라지면서 이 줄로 옮겨왔다 */
  subtitleCount?: number;
}) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  // 역할 분담 (사용자 요구: '자막이 나오면 게이지가 초기화' — 항상 동시):
  //  - 게이지 0점(elapsed): 자막이 '이 화면에 실제로 추가된 순간'(lastActivityTime,
  //    표시 지연까지 반영된 시각)을 직접 사용 → 자막 등장 = 게이지 리셋이 보장된다.
  //  - 상태 분류(생성 중/음성 대기/정회)와 평균 간격: 서버 방송(stt_status)이
  //    단일 진실 — 방송 중간에 들어온 시청자도 동일한 상태를 본다.
  //  - 아직 이 화면에 자막이 안 온 신규 접속자는 서버 경과로 임시 표시.
  const STATUS_STALE_MS = 15000; // 상태 방송이 끊긴 지 오래면 무시(서버 중단 등)
  // != null: null뿐 아니라 undefined(미수신/테스트 목)도 안전하게 거른다
  const serverFresh =
    sttStatus != null && now - sttStatus.receivedAt < STATUS_STALE_MS;

  const serverState: 'generating' | 'listening' | 'idle' | null =
    serverFresh && sttStatus ? sttStatus.state : null;
  // 창 길이는 서버 env(LIVE_BATCH_WINDOW_SECONDS)로 바뀌므로 게이지 기준도 서버값에서 파생한다 (2026-09-14)
  const windowSec = serverFresh && sttStatus?.window_seconds ? sttStatus.window_seconds : null;
  const gaugeMaxSec = windowSec != null ? Math.round(windowSec + 6) : GAUGE_MAX_SEC;
  let avgSec = windowSec != null ? Math.round(windowSec) : DEFAULT_AVG_INTERVAL_SEC;
  if (serverFresh && sttStatus?.avg_interval) {
    avgSec = Math.round(sttStatus.avg_interval);
  }

  let elapsed: number | null;
  if (lastActivityTime) {
    // 자막 표시 이벤트와 같은 시계 — 새 자막이 패널에 붙는 순간 0으로 리셋.
    // (now 상태는 1초 틱이라 직후엔 음수가 될 수 있음 → 0으로 클램프)
    elapsed = Math.max(0, Math.floor((now - lastActivityTime) / 1000));
  } else if (serverFresh && sttStatus && sttStatus.seconds_since_subtitle !== null) {
    elapsed = Math.floor(
      sttStatus.seconds_since_subtitle + (now - sttStatus.receivedAt) / 1000,
    );
  } else {
    elapsed = null;
  }

  let dot: React.ReactNode;
  let label: React.ReactNode;
  let textCls = 'text-text-muted';
  /** 게이지는 상태 줄 **위**의 2px 헤어라인이다 — 채워지는 비율(0~100)만 넘긴다 */
  let gaugePct: number | null = null;
  let gaugeOverdue = false;

  // 화면 기준 최근 등장(elapsed)이 우선 — 정밀 동기화 모드에선 서버 상태가
  // 화면보다 ~영상지연만큼 앞서므로(발언 중단 직후 'listening'), 자막이 아직
  // 화면에 흘러나오는 동안에는 '생성 중'으로 유지한다.
  const showGenerating =
    (elapsed !== null && elapsed < 25) || serverState === 'generating';
  const showListening =
    serverState === 'listening' ||
    (serverState === null && elapsed !== null && elapsed < 90);

  if (connectionStatus !== 'connected') {
    dot = <span className="inline-flex h-[7px] w-[7px] shrink-0 rounded-full bg-gray-400" />;
    label =
      connectionStatus === 'connecting'
        ? '자막 서버에 연결하는 중...'
        : '자막 서버 연결이 끊겼습니다 — 자동으로 재연결합니다';
  } else if (showGenerating) {
    textCls = 'text-success font-medium';
    dot = (
      <span className="h-[7px] w-[7px] shrink-0 animate-live-pulse rounded-full bg-success" />
    );
    const e = elapsed ?? 0;
    gaugeOverdue = e > gaugeMaxSec;
    label = (
      <>
        <span className="shrink-0">자막 생성 중{gaugeOverdue ? ' — 길어지는 중' : ''}</span>
        <span className="truncate text-text-muted tabular-nums">
          {e}초 · 평균 {avgSec}초 · 최대 ~{gaugeMaxSec}초
        </span>
      </>
    );
    gaugePct = Math.min(100, Math.round((e / gaugeMaxSec) * 100));
  } else if (showListening) {
    textCls = 'text-warning';
    dot = <span className="inline-flex h-[7px] w-[7px] shrink-0 rounded-full bg-warning-bg" />;
    label = (
      <span className="truncate">
        음성 대기 중 — 발언이 시작되면 자막이 표시됩니다
        {elapsed !== null ? ` (마지막 ${elapsed}초 전)` : ''}
      </span>
    );
  } else {
    dot = <span className="inline-flex h-[7px] w-[7px] shrink-0 rounded-full bg-gray-300" />;
    label = <span className="truncate">자막 수신 없음 — 정회 중이거나 방송이 종료되었을 수 있습니다</span>;
  }

  /*
   * 2026-08-25 개선안 2a·2e: 44px 두 줄 → **2px 헤어라인 + 28px 한 줄**.
   * 게이지를 6px 알약으로 두면 그 자체가 한 줄을 차지하는데, 이 게이지가 전하는 정보는
   * "얼마나 기다렸나" 하나뿐이라 굵기가 필요 없다. 트랙은 항상 그려서 상태가 바뀌어도
   * 높이가 흔들리지 않게 한다 — 자막 목록이 1px 씩 튀면 읽던 줄을 놓친다.
   */
  return (
    <div data-testid="stt-activity" className="shrink-0 border-t border-border bg-surface">
      <div className="h-0.5 w-full bg-gray-100" aria-hidden="true">
        {gaugePct !== null && (
          <div
            className={`h-full transition-all duration-1000 ease-linear ${
              gaugeOverdue ? 'animate-pulse bg-warning-bg' : 'bg-success'
            }`}
            style={{ width: `${gaugePct}%` }}
          />
        )}
      </div>
      <div className="flex h-7 items-center gap-1.5 px-3 text-xs sm:px-4">
        {dot}
        <span className={`flex min-w-0 items-baseline gap-1.5 ${textCls}`}>{label}</span>
        {subtitleCount != null && (
          <span className="ml-auto shrink-0 tabular-nums text-text-muted">{subtitleCount}건</span>
        )}
      </div>
    </div>
  );
}

/**
 * 연결 상태에 따른 배지 설정
 */
function getConnectionStatusBadge(status: ConnectionStatus): {
  variant: 'live' | 'success' | 'warning' | 'secondary';
  text: string;
} {
  switch (status) {
    case 'connecting':
      return { variant: 'warning', text: '연결 중...' };
    case 'connected':
      return { variant: 'success', text: '연결됨' };
    case 'disconnected':
      return { variant: 'secondary', text: '연결 끊김' };
    case 'error':
      return { variant: 'warning', text: '연결 오류' };
    default:
      return { variant: 'secondary', text: '알 수 없음' };
  }
}

/** 글자 크기 3단 — 버튼 하나가 md → lg → xl 을 돌린다 */
const FONT_SCALE_LABEL: Record<'md' | 'lg' | 'xl', string> = {
  md: '보통',
  lg: '크게',
  xl: '아주 크게',
};

function LivePageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const channelParam = searchParams.get('channel');
  const replayMeetingParam = searchParams.get('replay_meeting');
  // 채널 선택은 URL(?channel=chX)이 단일 기준 — 별도 상태로 들고 있으면
  // 사이드바 '실시간 방송'(/live)으로 돌아와도 뷰어가 유지되는 버그가 생긴다.
  const videoRef = useRef<HTMLVideoElement>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [currentTime, _setCurrentTime] = useState<number | undefined>(undefined);
  const [subtitleExpanded, setSubtitleExpanded] = useState(false);
  // 뷰 모드: 'classic' = 기존 편집자용 레이아웃 (기본), 'viewer' = 새 GAC 시민용 디자인
  const [viewMode, setViewMode] = useState<'viewer' | 'classic'>('classic');
  // 위원회 위원 명단 모달 (뷰어/클래식 공용)
  const [showMembers, setShowMembers] = useState(false);

  // ── 한 줄 헤더가 접어 둔 것들 (2026-08-25 개선안 2a·2e) ────────────────
  // 모바일 검색은 줄을 새로 만들지 않고 헤더 줄을 덮는다. ⋮ 는 정렬·마이크·
  // 위원 명단처럼 자주 안 쓰는 것을 담는다.
  const [mobileSearchOpen, setMobileSearchOpen] = useState(false);
  const [overflowOpen, setOverflowOpen] = useState(false);

  // 자막 패널 헤더가 사라지면서 그 컨트롤의 상태가 여기로 올라왔다 —
  // 탭 줄 오른쪽(ViewerTabs.rightSlot)에서 그리고, SubtitlePanel 에는 값으로 내린다.
  const [autoFollow, setAutoFollow] = useState(true);
  const [sortOrder, setSortOrder] = useState<'newest' | 'oldest'>('oldest');
  const [fontScale, setFontScale] = useState<'md' | 'lg' | 'xl'>('md');

  // 의사일정에서 특정 안건의 첫 자막으로 점프 (같은 안건을 다시 눌러도 재스크롤되게 nonce)
  const [agendaJumpId, setAgendaJumpId] = useState<string | null>(null);
  const [agendaJumpNonce, setAgendaJumpNonce] = useState(0);

  // PC/모바일 분기 — '지금 발언'을 카드로 뺄지 목록에 남길지가 이 값 하나로 갈린다
  const isDesktop = useIsDesktop();

  // 보조 패널 탭 — 실시간 자막이 기본. 검색결과·요구자료를 자막 아래에 잇지 않고
  // 같은 자리를 바꿔 쓰게 해서, 영상 바로 밑이 항상 "지금 발언"이 되게 한다.
  const [activeTab, setActiveTab] = useState<'subtitles' | 'search' | 'materials'>('subtitles');

  // Replay 모드: meeting의 vod_url을 가져와서 MP4로 재생
  const [replayVodUrl, setReplayVodUrl] = useState<string | null>(null);

  // 실시간 자막 클릭 안내 토스트
  const [liveNotice, setLiveNotice] = useState<string | null>(null);
  const noticeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // STT 시작 시각 추정 (시계 시간 표시용)
  const sttStartedAtRef = useRef<number | null>(null);

  // 영상-자막 정밀 동기화: HlsPlayer가 실측 라이브 지연(초)을 1초 주기로 기록
  const hlsLatencyRef = useRef<number | null>(null);
  // 재생 위치의 자막 시계를 읽는 함수 (HlsPlayer 가 hls.js playingDate 로 채운다)
  const hlsClockRef = useRef<(() => number | null) | null>(null);
  // hls.js 의 유효 목표 지연 — 스톨 뒤에도 syncTargetSec 그대로인지 보는 진단값
  const hlsTargetLatencyRef = useRef<number | null>(null);
  // 동기화 가능 여부 (직전 렌더 기준) — 훅의 고정 지연을 켜고 끄는 데 사용
  const [syncActive, setSyncActive] = useState(false);
  // "영상보다 늦게 도착한 자막" 카운터 — 영상 지연을 줄일 때의 안전 게이지 (0 유지가 목표)
  const lateTrackerRef = useRef(new LateArrivalTracker());

  // 채널 목록 (방송 상태 포함)
  const {
    channels,
    isLoading: isChannelsLoading,
    requestNotificationPermission,
  } = useChannelStatus();

  // 활성 채널 ID — URL 파라미터가 유일한 기준
  const activeChannelId = channelParam || undefined;

  // 실시간 회의 데이터
  const { meeting } = useLiveMeeting(activeChannelId || undefined);

  // 활성 채널 전체 정보
  const activeChannel = channels.find(c => c.id === channelParam) || null;

  // 영상 지연 목표 — `?sync=N`(현장 실험) > 서버값(채널 상태 응답 sync_target_sec = api env
  // LIVE_SYNC_TARGET_SEC, 재빌드 없이 조정) > 빌드 기본. hls.js 는 시작 뒤 목표를 낮춰도 스스로 못
  // 따라오므로 채널 응답이 오기 전엔 플레이어를 띄우지 않는다(syncTargetReady — 2초 지나면 폴백으로 진행).
  const syncParam = searchParams.get('sync');
  const { value: syncTargetSec, source: syncTargetSource } = pickSyncTarget({
    search: syncParam,
    server: activeChannel?.sync_target_sec,
    fallback: LIVE_SYNC_TARGET_SEC,
  });
  const hasActiveChannel = activeChannel != null;
  const [syncGateTimedOut, setSyncGateTimedOut] = useState(false);
  useEffect(() => {
    if (hasActiveChannel) return undefined;
    const t = setTimeout(() => setSyncGateTimedOut(true), 2000);
    return () => clearTimeout(t);
  }, [hasActiveChannel]);
  const syncTargetReady = hasActiveChannel || !!syncParam || syncGateTimedOut;

  // 활성 채널의 stream URL (meeting이 없어도 채널에서 직접 가져옴)
  const originStreamUrl = meeting?.stream_url
    || activeChannel?.stream_url
    || '';
  // 영상은 원본 CDN 이 아니라 서버의 '깊은 재생목록'(api/channels hls 라우트)으로 연다.
  // 원본 재생목록은 6초뿐이라 20초 지연을 못 잡고 접속 직후 ≈14초를 일시정지로 벌었는데,
  // 서버가 전사용으로 이미 받은 세그먼트 40초를 재생목록으로 내주면 접속 즉시 20초 전에서
  // 시작한다. STT 가 안 붙은 채널이면 서버가 원본으로 302 → 예전 톱업 폴백 그대로.
  const activeStreamUrl = originStreamUrl && channelParam
    ? `${API_BASE_URL}/api/channels/${channelParam}/hls/playlist.m3u8`
    : originStreamUrl;

  // 활성 채널 이름
  const activeChannelName = activeChannel?.name || '';

  // 방송 상태: 채널 데이터 로드 전에는 null, 로드 후 true/false
  const isOnAir = activeChannel == null ? null : activeChannel.livestatus === 1;

  // 자막이 비어 있을 때 보여줄 안내 문구 (방송 상태별).
  // 라이브는 "불러오는" 개념이 없으므로 항상 빈 상태 문구로 표시한다.
  const subtitleEmptyMessage = (() => {
    switch (activeChannel?.livestatus) {
      case 1: // 방송중
        return '방송 중입니다. 음성 인식이 시작되면 자막이 표시됩니다.';
      case 2: // 정회중
        return '정회 중입니다. 회의가 재개되면 자막이 표시됩니다.';
      case 0: // 방송전
      case 4: // 생중계 없음
        return '방송 시작 시 자막이 표시됩니다.';
      default:
        return '표시할 자막이 없습니다.';
    }
  })();

  // 요구자료 감지 목록 — 등록된 회의(UUID)일 때 REST 로드, WS 이벤트로 증분
  const meetingUuid =
    meeting?.id && /^[0-9a-f-]{36}$/i.test(meeting.id) ? meeting.id : null;
  const materialRequests = useMaterialRequests(meetingUuid);

  // 접속 통계(2026-09-16) — 화면 열람 1회 + 방송 중일 때 5분마다 시청 신호. IP 는 서버가 저장하지 않는다
  usePageAccessLog('/live');
  useWatchAccessLog({
    kind: 'watch_live',
    meetingId: meetingUuid ?? activeChannel?.id ?? null,
    active: isOnAir === true,
  });
  const { appendRequest } = materialRequests;
  // 감지되면 목록에만 넣는다 — 보고 있던 자막을 요구자료로 밀어내지 않고,
  // 하단 한 줄 알림(MaterialRequestAlertBar)의 건수만 올라간다.
  const handleMaterialRequest = useCallback(
    (request: MaterialRequestType) => {
      appendRequest(request);
    },
    [appendRequest]
  );
  const pendingMaterialCount = materialRequests.requests.filter(
    (r) => r.status === 'detected'
  ).length;

  // WebSocket을 통한 실시간 자막 수신
  // 생중계는 항상 채널 ID로 연결 (백엔드가 채널 ID 룸으로 브로드캐스트)
  const wsRoomId = activeChannelId || '';
  const {
    subtitles: liveSubtitles,
    interimText,
    lastActivityTime,
    sttStatus,
    connectionStatus,
    connect,
  } = useSubtitleWebSocket({
    meetingId: wsRoomId,
    autoConnect: !!activeChannelId,
    onMaterialRequest: handleMaterialRequest,
    // 정밀 동기화 모드에선 지연 0 — 자막을 즉시 배열에 넣고, 표시 타이밍은
    // 아래 videoClock 게이팅(영상이 발언 지점에 도달하는 순간)이 전담한다.
    // 동기화 불가 시(네이티브 HLS 등) 기존 고정 지연 폴백.
    displayDelay: syncActive ? 0 : FALLBACK_DISPLAY_DELAY_MS,
  });

  // 종료된 방송의 누적 자막 — 방송이 live가 아니거나 WS 메모리가 비었을 때
  // /api/meetings/{uuid}/subtitles 로 DB에서 직접 로드.
  const [endedSubtitles, setEndedSubtitles] = useState<SubtitleType[]>([]);
  useEffect(() => {
    // ★회의/채널이 바뀌면 무조건 먼저 비운다 — 새 회의 자막이 0건일 때
    //   이전 채널의 자막이 화면에 그대로 남던 버그(2026-06-12, 경제노동위
    //   914건이 교육기획위 방송전 화면에 잔류) 방지.
    setEndedSubtitles([]);
    if (!meeting?.id) return;
    // meeting.id가 실제 UUID일 때만 (채널 스텁은 "ch6" 같은 ID)
    const isUuid = /^[0-9a-f-]{36}$/i.test(meeting.id);
    if (!isUuid) return;
    // 실시간 중이어도 초기 로드 1회로 기존 자막 채워둠 (새 자막은 WS로 추가)
    // ★API limit 상한이 1000이라 그 이상 요청하면 422로 거부됨(과거 limit=2000 버그
    //   — 종료된 회의 자막이 조용히 안 보이던 원인). 1000개 단위로 페이지네이션.
    let cancelled = false;
    (async () => {
      try {
        const pageSize = 1000;
        const maxPages = 8; // 안전 상한 (~8000개)
        const all: SubtitleType[] = [];
        for (let page = 0; page < maxPages; page++) {
          const res = await fetch(
            `${API_BASE_URL}/api/meetings/${meeting.id}/subtitles?limit=${pageSize}&offset=${page * pageSize}`,
          );
          if (!res.ok) break;
          const data = await res.json();
          // 응답 키는 items (과거 subtitles 가정도 이중 버그였음)
          const items: SubtitleType[] = Array.isArray(data)
            ? data
            : data.items || data.subtitles || [];
          all.push(...items);
          if (items.length < pageSize) break;
        }
        if (!cancelled && all.length > 0) setEndedSubtitles(all);
      } catch {
        // ignore
      }
    })();
    return () => { cancelled = true; };
  }, [meeting?.id]);

  // 라이브 + DB 병합 (id 기준 중복 제거, 시작시간 오름차순)
  const subtitles = React.useMemo(() => {
    const byId = new Map<string, SubtitleType>();
    for (const s of endedSubtitles) byId.set(s.id, s);
    for (const s of liveSubtitles) byId.set(s.id, s); // 라이브가 우선 (교정 반영)
    return Array.from(byId.values()).sort(
      (a, b) => a.start_time - b.start_time,
    );
  }, [liveSubtitles, endedSubtitles]);

  // ─── 영상-자막 정밀 동기화 ──────────────────────────────────────────────
  // 동기화 하트비트: 앵커가 살아 있는 동안 0.5초 주기로 게이팅을 재평가
  const hasAnchor = sttStatus?.audio_clock != null;
  const [, setClockTick] = useState(0);
  useEffect(() => {
    if (!hasAnchor) return;
    const t = setInterval(() => setClockTick((n) => n + 1), 500);
    return () => clearInterval(t);
  }, [hasAnchor]);

  // 영상이 지금 보여주는 지점의 오디오-초(자막 타임라인과 같은 시계):
  // 보관분 재생목록의 PDT 로 직접 읽고, 없을 때만 지연 추정으로 역산한다 (resolveVideoClock).
  const hlsLatency = hlsLatencyRef.current;
  const pdtClock = hlsClockRef.current?.() ?? null;
  const videoClockPrevRef = useRef<number | null>(null);
  let videoClock: number | null = null;
  let clockSource: 'pdt' | 'latency' | null = null;
  // 진단 — 디코더 대비 영상 여유(자막이 안 늦으려면 ≥ ready_lag)와, 그것으로 역산한 디코더의 엣지 지연
  // (서버 stt_status.edge_lag 와 1초 안에서 맞아야 한다)
  let decodeMarginSec: number | null = null;
  let edgeLagObserved: number | null = null;
  if (
    !replayMeetingParam &&
    sttStatus &&
    sttStatus.audio_clock != null &&
    Date.now() - sttStatus.receivedAt < ANCHOR_STALE_MS
  ) {
    const serverClockNow =
      sttStatus.audio_clock + (Date.now() - sttStatus.receivedAt) / 1000;
    ({ clock: videoClock, source: clockSource } = resolveVideoClock({
      serverClockNow,
      pdtClock,
      hlsLatency,
      // 지연 추정 폴백(PDT 없는 원본 재생목록)에도 서버 실측을 쓴다 — 없으면 옛 가정 3초
      edgeLagSec: sttStatus.edge_lag_p95 ?? BACKEND_EDGE_LAG_SEC,
      maxLagSec: MAX_CLOCK_LAG_SEC,
    }));
    if (pdtClock != null) {
      decodeMarginSec = Math.round((serverClockNow - pdtClock) * 10) / 10;
      if (hlsLatency != null) {
        edgeLagObserved = Math.round((hlsLatency - decodeMarginSec) * 10) / 10;
      }
    }
  }
  if (videoClock != null) {
    // 지연 측정의 작은 출렁임으로 시계가 뒤로 가서 이미 표시한 자막이
    // 사라지는 깜빡임 방지 — 8초 미만의 후퇴는 직전 값 유지, 그 이상의
    // 후퇴(스톨 후 큰 보정 등)는 진짜 교정으로 보고 수용한다.
    const prev = videoClockPrevRef.current;
    if (prev != null && videoClock < prev && prev - videoClock < 8) {
      videoClock = prev;
    }
  }
  videoClockPrevRef.current = videoClock;
  const isSynced = videoClock != null;

  // ─── 실제 시각(벽시계) ────────────────────────────────────────────────
  // "지금 화면의 이 장면이 실제로 몇 시였나". 자막 시계 0 의 실제 시각을 서버 상태 방송
  // (audio_clock = 지금까지 디코딩한 오디오 초)과 수집 지연(edge_lag)으로 잡는다.
  // 그 위에 영상 시계(videoClock)를 얹으면 **화면에 보이는 장면의 시각**이 된다 —
  // 영상이 엣지보다 20초 뒤라 PC 시계보다 그만큼 이전이고, 그래야 자막 목록의 시각과 맞다.
  const liveAnchorRef = useRef<ClockAnchor | null>(null);
  liveAnchorRef.current = stabilizeAnchor(
    liveAnchorRef.current,
    replayMeetingParam
      ? null
      : liveClockAnchor({
          audioClock: sttStatus?.audio_clock,
          receivedAt: sttStatus?.receivedAt ?? 0,
          edgeLagSec: sttStatus?.edge_lag_p95 ?? BACKEND_EDGE_LAG_SEC,
        }),
  );
  // 배지는 스스로 0.5초마다 읽는다 — 값이 아니라 ref 를 넘겨 렌더 간격과 무관하게 흐르게 한다
  const liveWallMsRef = useRef<number | null>(null);
  liveWallMsRef.current = liveAnchorRef.current
    ? wallMsFromClock([liveAnchorRef.current], videoClock)
    : null;
  const getLiveWallMs = useCallback(() => liveWallMsRef.current, []);
  // 자막 목록의 시각 표기도 같은 기준점을 쓴다 — 영상 위 시각과 목록 시각이 어긋나 보이지 않게.
  // (기준점이 없을 때만 예전 추정치 — 첫 자막 도착 시각 기준 — 로 물러난다)
  const subtitleClockEpoch = liveAnchorRef.current?.wallMs ?? sttStartedAtRef.current;
  useEffect(() => {
    setSyncActive(isSynced);
  }, [isSynced]);

  // 늦은 도착 판정 — 동기화 성립 뒤 새로 온 자막이 이미 영상 시계를 지났으면 카운트
  useEffect(() => {
    lateTrackerRef.current.observe(subtitles, videoClock);
  }, [subtitles, videoClock]);
  useEffect(() => {
    lateTrackerRef.current.reset();
  }, [channelParam]);

  // 운영 진단 훅 — 콘솔에서 window.__syncDebug로 동기화 입력값 확인
  // (syncTarget·readyLagP95·hlsWindowSec·lateCount 는 영상 지연 목표 조정의 근거)
  if (typeof window !== 'undefined') {
    (window as unknown as { __syncDebug?: object }).__syncDebug = {
      isSynced,
      videoClock,
      clockSource,
      pdtClock,
      hlsLatency,
      audioClock: sttStatus?.audio_clock ?? null,
      anchorAgeMs: sttStatus ? Date.now() - sttStatus.receivedAt : null,
      edgeLagSec: sttStatus?.edge_lag_p95 ?? BACKEND_EDGE_LAG_SEC,
      syncTarget: syncTargetSec,
      syncTargetSource,
      serverSyncTarget: sttStatus?.sync_target_sec ?? activeChannel?.sync_target_sec ?? null,
      hlsTargetLatency: hlsTargetLatencyRef.current,
      decodeMarginSec,
      edgeLagObserved,
      edgeLagP95: sttStatus?.edge_lag_p95 ?? null,
      syncNeedP95: sttStatus?.sync_need_p95 ?? null,
      syncNeedMax: sttStatus?.sync_need_max ?? null,
      windowSeconds: sttStatus?.window_seconds ?? null,
      readyLagLast: sttStatus?.ready_lag_last ?? null,
      readyLagP95: sttStatus?.ready_lag_p95 ?? null,
      apiSecLast: sttStatus?.api_sec_last ?? null,
      hlsWindowSec: sttStatus?.hls_window_sec ?? null,
      lateCount: lateTrackerRef.current.lateCount,
      maxLateSec: lateTrackerRef.current.maxLateSec,
    };
  }

  // 지난 날짜 회의의 자막 숨김 — 정회가 자정을 넘기는 등으로 어제 회의가
  // DB에 살아 있어도, 날짜가 바뀌고 아직 방송 전이면 어제 자막을 보여줄
  // 이유가 없다 (사용자 요청 2026-06-12: 날짜·회차가 바뀌면 기존 자막 숨김).
  // 방송중(1)/정회중(2)은 진행 중인 회의의 연속이므로 그대로 표시하고,
  // 리플레이 모드는 과거 회의를 명시적으로 여는 기능이라 제외한다.
  const isStaleArchive = React.useMemo(() => {
    if (replayMeetingParam) return false;
    const ls = activeChannel?.livestatus;
    if (ls === 1 || ls === 2) return false;
    const md = meeting?.meeting_date;
    if (!md) return false;
    const today = new Date().toLocaleDateString('en-CA'); // YYYY-MM-DD (로컬)
    return md.slice(0, 10) !== today;
  }, [replayMeetingParam, activeChannel?.livestatus, meeting?.meeting_date]);

  // 게이팅: 영상이 자막의 시작 지점에 도달했을 때만 표시 (동기화 불가 시 전체)
  // + 라이브 화면은 화자 실명 대신 기관 구분(도의원/집행부)만 표시
  //   — 라이브 화자식별은 오인식이 있어 잘못된 실명 노출이 더 해롭다.
  //   (저장 데이터·VOD AI 자막의 실명은 그대로 유지)
  const displaySubtitles = React.useMemo(() => {
    if (isStaleArchive) return [];
    const gated =
      videoClock == null ? subtitles : subtitles.filter((s) => s.start_time <= videoClock);
    return gated.map((s) => ({ ...s, speaker: coarsenLiveSpeaker(s.speaker) }));
  }, [subtitles, videoClock, isStaleArchive]);

  // 동기화 모드에선 interim(인식 중) 미리보기를 숨긴다 — 영상보다 수십 초
  // 앞선 발언이 미리 노출되어 동기화가 깨져 보이기 때문
  const displayInterim = isSynced ? '' : interimText;

  // 게이지 0점: 자막이 '화면에 실제로 등장한 순간' (동기화 모드의 단일 진실).
  // 접속 직후 백로그 일괄 표시는 등장으로 치지 않는다 (서버 경과로 표시).
  const [lastRevealTime, setLastRevealTime] = useState<number | null>(null);
  const prevRevealCountRef = useRef(0);
  const revealCount = displaySubtitles.length;
  useEffect(() => {
    if (revealCount > prevRevealCountRef.current && prevRevealCountRef.current > 0) {
      setLastRevealTime(Date.now());
    }
    prevRevealCountRef.current = revealCount;
  }, [revealCount]);
  useEffect(() => {
    setLastRevealTime(null);
    prevRevealCountRef.current = 0;
    videoClockPrevRef.current = null; // 채널 변경 시 시계 단조 가드 초기화
  }, [activeChannelId]);

  const {
    isStreaming: isMicStreaming,
    status: _micStatus,
    error: _micError,
    start: startMicStreaming,
    stop: stopMicStreaming,
  } = useMicSttStream({
    meetingId: wsRoomId,
  });

  // 자막 검색 기능
  const {
    filteredSubtitles,
    matchCount,
    currentMatchIndex,
    currentMatch,
    goToNextMatch,
    goToPrevMatch,
    isMatch,
  } = useSubtitleSearch({
    subtitles: displaySubtitles, // 동기화 게이팅 적용 후 목록 (영상 도달분만)
    query: searchQuery,
    filterMode: 'all',
  });

  // '검색결과' 탭은 일치한 자막만 — 전체 타임라인에서 눈으로 찾지 않게 한다.
  const matchedSubtitles = React.useMemo(
    () => displaySubtitles.filter((s) => isMatch(s.id)),
    [displaySubtitles, isMatch]
  );

  // Replay 모드: meeting의 vod_url을 가져와서 MP4로 재생
  useEffect(() => {
    if (!replayMeetingParam) {
      setReplayVodUrl(null);
      return;
    }
    let cancelled = false;
    async function fetchVodUrl() {
      try {
        const res = await fetch(`${API_BASE_URL}/api/meetings/${replayMeetingParam}`);
        if (res.ok) {
          const data = await res.json();
          if (!cancelled && data.vod_url) {
            setReplayVodUrl(data.vod_url);
          }
        }
      } catch (err) {
        console.error('[Replay] Failed to fetch meeting vod_url:', err);
      }
    }
    fetchVodUrl();
    return () => { cancelled = true; };
  }, [replayMeetingParam]);

  // STT 라이프사이클은 서버의 AutoSttManager(backend/app/services/auto_stt.py)가
  // 방송 상태 전환을 감지해 자동으로 관리합니다. 과거에는 여기서 비로그인 시청자가
  // POST /api/channels/{id}/stt/start 를 호출했으나,
  // (1) 보안 하드닝 후 해당 엔드포인트는 admin/meeting_manager 권한이 필요해 401 발생,
  // (2) AutoSttManager 도입으로 클라이언트 호출이 중복이 되었습니다.
  // 따라서 클라이언트는 더 이상 STT 시작을 트리거하지 않습니다.

  // 자막이 수신되면 STT 시작 시각을 추정
  useEffect(() => {
    if (subtitles.length > 0 && !sttStartedAtRef.current) {
      const latest = subtitles[subtitles.length - 1]!;
      sttStartedAtRef.current = Date.now() - latest.start_time * 1000;
    }
  }, [subtitles]);

  // 채널 변경 시 STT 시작 시각 리셋
  useEffect(() => {
    sttStartedAtRef.current = null;
    liveAnchorRef.current = null;
    stopMicStreaming();
  }, [activeChannelId, stopMicStreaming]);

  // 토스트 정리
  useEffect(() => {
    return () => {
      if (noticeTimerRef.current) clearTimeout(noticeTimerRef.current);
    };
  }, []);

  const handleLiveClickNotice = useCallback(() => {
    setLiveNotice('실시간 방송에서는 시점 이동이 지원되지 않습니다');
    if (noticeTimerRef.current) clearTimeout(noticeTimerRef.current);
    noticeTimerRef.current = setTimeout(() => setLiveNotice(null), 3000);
  }, []);

  const showNotice = useCallback((message: string) => {
    setLiveNotice(message);
    if (noticeTimerRef.current) clearTimeout(noticeTimerRef.current);
    noticeTimerRef.current = setTimeout(() => setLiveNotice(null), 4000);
  }, []);

  // 자막 ▶ 클릭 → 그 구간의 녹음 음성을 웹에서 바로 재생 (자막 검증용).
  // CBR mp3라 시간→바이트가 선형 — 필요한 구간 바이트만 Range로 받아 blob 재생.
  // (전체 파일 스트리밍·탐색이 필요 없어 진행 중 녹음에도 견고)
  // 재생 동안 라이브 영상은 음소거하고 끝나면 복원한다.
  // ★사용자 결정(2026-08-18): 상임위 최대 5개 동시 개최 — 놓친 위원회의 이전 발언을
  //   음성으로 되돌려 듣는 용도로 재활성 (2026-06-11 숨김 결정을 뒤집음).
  const ENABLE_SEGMENT_PLAYBACK = true;
  // 구현은 VOD 등록 전 화면과 같이 쓴다 (hooks/useRecordingSegmentPlayer — 2026-09-15 옮김).
  // 채널 변경/언마운트 시 재생 정리(+영상 음량 복원)도 훅이 한다.
  const { playSegment: handlePlaySegment, playingSegmentId } = useRecordingSegmentPlayer({
    meetingId: meeting?.id,
    onNotice: showNotice,
    duckRef: videoRef,
  });

  const handleHlsError = useCallback((err: Error) => {
    console.error('HLS Error:', err);
  }, []);

  // 검색어를 넣으면 검색결과 탭으로, 지우면 실시간 자막 탭으로 되돌린다
  const handleSearch = (query: string) => {
    setSearchQuery(query);
    setActiveTab(query.trim() ? 'search' : 'subtitles');
  };

  const handleSubtitleClick = useCallback((startTime: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime = startTime;
      videoRef.current.play();
    }
  }, []);

  const handleChannelSelect = (channel: ChannelType) => {
    router.push(`/live?channel=${channel.id}`);
    // 첫 채널 선택 시 알림 권한 요청
    requestNotificationPermission();
  };

  const handleBackToChannels = () => {
    router.push('/live');
  };

  // 채널 미선택 상태 → ChannelSelector 표시
  if (!activeChannelId) {
    return (
      <div data-testid="live-page" className="flex flex-col h-full">
        <ChannelSelector
          channels={channels}
          isLoading={isChannelsLoading}
          onSelect={handleChannelSelect}
        />
      </div>
    );
  }

  // 채널 선택됨 → 플레이어 표시
  const connectionBadge = getConnectionStatusBadge(connectionStatus);

  // ────────────────────────────────────────────────────
  // 뷰어 모드 (새 GAC 디자인)
  // ────────────────────────────────────────────────────
  if (viewMode === 'viewer') {
    // 최근 자막에서 현재 발언자 파생 (화면에 등장한 자막 기준)
    const latestSubtitle = displaySubtitles[displaySubtitles.length - 1];
    const currentSpeakerName = latestSubtitle?.speaker || undefined;

    // 간이 지연 계산 (초)
    const latency = lastActivityTime
      ? Math.max(0, (Date.now() - lastActivityTime) / 1000)
      : undefined;

    // 영상 슬롯 (HLS 또는 REPLAY)
    const videoSlot = replayVodUrl ? (
      <video
        ref={videoRef}
        src={replayVodUrl}
        controls
        autoPlay
        playsInline
        className="w-full h-full"
        data-testid="replay-video"
      />
    ) : isOnAir === false && !replayMeetingParam ? (
      <div className="w-full h-full flex flex-col items-center justify-center gap-3 bg-gray-950">
        <svg className="w-16 h-16 text-white/40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
        </svg>
        <p className="text-white/60 text-lg">현재 방송 중이 아닙니다</p>
        <p className="text-white/40 text-sm">{activeChannel?.status_text || '방송전'}</p>
      </div>
    ) : activeStreamUrl && !replayMeetingParam && syncTargetReady ? (
      <HlsPlayer
        streamUrl={activeStreamUrl}
        videoRef={videoRef}
        onError={handleHlsError}
        latencyRef={hlsLatencyRef}
        playingClockRef={hlsClockRef}
        syncTargetSec={syncTargetSec}
        targetLatencyRef={hlsTargetLatencyRef}
      />
    ) : (
      <div className="w-full h-full grid place-items-center bg-gray-950 text-white/50">
        스트림 URL을 불러오는 중...
      </div>
    );

    // 뷰어(시민용) 영상 슬롯 위에 얹는 것 둘 — 우상단 실제 시각 배지, 좌상단 [의원 찾기].
    // 자리가 겹치지 않으므로 한 relative 컨테이너에 함께 둔다.
    const videoSlotWithOverlays = (
      <div className="relative h-full w-full">
        {videoSlot}
        {!replayMeetingParam && <VideoClockBadge getWallMs={getLiveWallMs} />}
        <LiveFaceOverlay
          videoRef={videoRef}
          channelId={activeChannelId}
          speakerHint={currentSpeakerName}
          enabled={isOnAir === true || !!replayVodUrl}
        />
      </div>
    );

    return (
      <div data-testid="live-page" className="flex flex-col h-full">
        {/* 상단 미니 컨트롤 바 — 채널 목록 / 모드 전환 / 상태.
            우측 전역 컨트롤(통합검색/알림/접속자수)이 떠 있으므로 그 공간을 예약(pr)하고,
            좁은 화면에서는 줄바꿈(flex-wrap)으로 겹침을 방지한다. */}
        <div className="bg-surface border-b border-border py-2 pl-4 pr-24 md:pr-44 lg:pr-[300px] flex flex-wrap items-center gap-x-3 gap-y-2">
          <button
            onClick={handleBackToChannels}
            className="shrink-0 whitespace-nowrap text-sm text-primary hover:text-primary-light flex items-center gap-1"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
            채널 목록
          </button>
          <span className="hidden sm:inline text-sm text-text-muted">|</span>
          <span className="shrink-0 whitespace-nowrap truncate max-w-[45vw] text-sm font-medium text-text-secondary">{activeChannelName}</span>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {replayMeetingParam && <Badge variant="warning">REPLAY</Badge>}
            {/* 뷰어 모드 상태 뱃지 — 실제 status_text 우선 표시 */}
            {!replayMeetingParam && activeChannel?.livestatus === 1 && (
              <Badge variant="live">{activeChannel.status_text || 'LIVE'}</Badge>
            )}
            {!replayMeetingParam && activeChannel?.livestatus === 2 && (
              <Badge variant="warning">{activeChannel.status_text || '정회중'}</Badge>
            )}
            {!replayMeetingParam && (activeChannel?.livestatus === 0 || activeChannel?.livestatus === 4) && (
              <Badge variant="secondary">{activeChannel.status_text || '방송전'}</Badge>
            )}
            <div data-testid="connection-status" className="shrink-0 flex items-center gap-1.5">
              <Badge variant={connectionBadge.variant}>{connectionBadge.text}</Badge>
              {(connectionStatus === 'disconnected' || connectionStatus === 'error') && (
                <button
                  onClick={connect}
                  className="text-xs text-primary hover:text-primary-light transition-colors"
                  data-testid="reconnect-button"
                >
                  재연결
                </button>
              )}
            </div>
            {activeChannelName.endsWith('위원회') && (
              <button
                onClick={() => setShowMembers(true)}
                className="shrink-0 whitespace-nowrap px-3 py-1 rounded text-xs font-medium border border-border text-text-secondary hover:bg-surface-raised transition-colors"
                title="이 위원회의 위원 명단 보기"
                data-testid="committee-members-button"
              >
                👥 위원 명단
              </button>
            )}
            <button
              onClick={() => setViewMode('classic')}
              className="shrink-0 whitespace-nowrap px-3 py-1 rounded text-xs font-medium border border-border text-text-secondary hover:bg-surface-raised transition-colors"
              title="기존 편집자용 레이아웃"
            >
              클래식 뷰
            </button>
          </div>
        </div>

        {activeChannelName.endsWith('위원회') && (
          <CommitteeMembersModal
            committee={activeChannelName}
            committeeCode={activeChannel?.code}
            isOpen={showMembers}
            onClose={() => setShowMembers(false)}
          />
        )}
        {/* 새 GAC 뷰어 */}
        <div className="flex-1 min-h-0">
          <LiveViewer
            videoSlot={videoSlotWithOverlays}
            meetingTitle={meeting?.title || activeChannelName || '실시간 회의'}
            sessionLabel={activeChannel?.session_no ? `제${activeChannel.session_no}회` : undefined}
            subtitles={displaySubtitles}
            interimText={displayInterim}
            isLive={isOnAir === true}
            latencySeconds={latency}
            currentSpeaker={
              currentSpeakerName
                ? { name: currentSpeakerName, partyColor: 'var(--ggc-primary)' }
                : undefined
            }
            onExport={meeting?.id ? () => {
              // 내보내기는 TranscriptExportButton 재사용 대신 alert으로 일단
              window.alert('회의록 내보내기는 "클래식 뷰"에서 이용 가능합니다.');
            } : undefined}
          />
        </div>
      </div>
    );
  }

  // ────────────────────────────────────────────────────
  // 클래식 모드 (기존 편집자용 레이아웃)
  // ────────────────────────────────────────────────────
  // '지금 발언' 카드에 쓸 마지막 자막 — PC 에서만 목록 밖으로 나온다
  const latestSubtitle = displaySubtitles[displaySubtitles.length - 1];

  return (
    <div data-testid="live-page" className="flex h-full min-h-0 flex-col">
      {/*
        ── 한 줄 헤더 (모바일 44px · PC 52px) ────────────────────────────────
        2026-08-25 개선안 2a·2e. 예전에는 이 자리가 `flex-wrap` 이라 모바일에서
        3줄로 접혔고(뒤로가기 / 채널명·배지들 / 검색창), 그 아래 탭·패널헤더·상태·
        내보내기가 각각 한 줄을 더 먹어 **껍데기만 5줄**이었다. 390px 화면에서
        자막에 남는 높이가 150px 남짓이었다.

        지금은 한 줄이다. 자주 안 쓰는 것(위원 명단·마이크·내보내기·정렬·클래식뷰)은
        ⋮ 로 접고, 검색은 아이콘을 누르면 이 줄을 덮는다 — 줄을 새로 만들지 않는다.
        우측 pr-* 은 PlatformLayout 이 띄우는 전역 컨트롤 자리다.
      */}
      <div className="relative flex h-11 shrink-0 items-center gap-2 border-b border-border bg-surface pl-1 pr-24 sm:gap-3 md:pr-44 lg:h-[52px] lg:pr-[300px]">
        <button
          onClick={handleBackToChannels}
          className="grid h-9 w-9 shrink-0 place-items-center rounded-md text-primary transition-colors hover:bg-surface-raised lg:h-8 lg:w-auto lg:gap-1 lg:px-2 lg:flex lg:items-center"
          aria-label="채널 목록으로"
          title="채널 목록으로"
        >
          <svg className="h-[18px] w-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          <span className="hidden text-[13.5px] font-medium text-text-secondary lg:inline">채널</span>
        </button>

        <span className="min-w-0 truncate text-base font-bold tracking-heading text-text lg:text-[17px]">
          {activeChannelName}
        </span>

        {/* 상태 배지 — 방송 중이면 붉게, 정회·방송전은 그 문구 그대로 */}
        {replayMeetingParam ? (
          <span className="shrink-0 rounded bg-warning-bg/20 px-1.5 py-0.5 text-[10px] font-bold tracking-[0.06em] text-warning-dark">
            REPLAY
          </span>
        ) : isOnAir === true ? (
          <span className="inline-flex shrink-0 items-center gap-1.5 rounded bg-live px-1.5 py-0.5 text-[10px] font-bold tracking-[0.06em] text-white lg:px-2 lg:text-[10.5px]">
            <span className="h-[5px] w-[5px] animate-live-pulse rounded-full bg-white" />
            <span className="hidden lg:inline">{activeChannel?.status_text || 'LIVE'}</span>
            <span className="lg:hidden">LIVE</span>
          </span>
        ) : activeChannel?.livestatus === 2 ? (
          <span className="shrink-0 rounded bg-warning-bg/20 px-1.5 py-0.5 text-[10px] font-bold text-warning-dark">
            {activeChannel?.status_text || '정회중'}
          </span>
        ) : isOnAir === false ? (
          <span className="shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-bold text-text-muted">
            {activeChannel?.status_text || '방송전'}
          </span>
        ) : null}

        {/* 회차 · 시청자 — PC 는 한 문장, 모바일은 시청자 수만 */}
        <span className="hidden shrink-0 text-[13px] tabular-nums text-text-muted lg:inline">
          {activeChannel?.session_no ? `제${activeChannel.session_no}회 제${activeChannel.session_order ?? 1}차` : ''}
          {activeChannel?.session_no && sttStatus?.viewers ? ' · ' : ''}
          {sttStatus?.viewers ? `${sttStatus.viewers}명 시청` : ''}
        </span>
        {sttStatus?.viewers != null && sttStatus.viewers > 0 && (
          <span
            className="shrink-0 text-xs tabular-nums text-text-muted lg:hidden"
            data-testid="viewer-count"
            title="지금 이 방송을 보고 있는 사람 수"
          >
            {sttStatus.viewers}명
          </span>
        )}

        {/* 연결 상태 — PC 는 점 + 글자, 모바일은 점만 */}
        <span data-testid="connection-status" className="flex shrink-0 items-center gap-1.5">
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              connectionStatus === 'connected'
                ? 'bg-success'
                : connectionStatus === 'connecting'
                  ? 'bg-warning-bg'
                  : 'bg-gray-300'
            }`}
            aria-hidden="true"
          />
          <span
            className={`hidden text-[12.5px] font-medium lg:inline ${
              connectionStatus === 'connected' ? 'text-success' : 'text-text-muted'
            }`}
          >
            {connectionBadge.text}
          </span>
          {(connectionStatus === 'disconnected' || connectionStatus === 'error') && (
            <button
              onClick={connect}
              className="text-xs text-primary transition-colors hover:text-primary-light"
              data-testid="reconnect-button"
            >
              재연결
            </button>
          )}
        </span>

        <div className="flex-1" />

        {/* 자막 검색 — PC 는 고정폭 상시 노출, 모바일은 아이콘 → 줄 덮기 */}
        <div className="hidden w-[280px] shrink-0 lg:block">
          <SearchInput onSearch={handleSearch} placeholder="자막 검색" />
        </div>
        <button
          type="button"
          onClick={() => setMobileSearchOpen(true)}
          className="grid h-9 w-9 shrink-0 place-items-center rounded-md text-text-secondary transition-colors hover:bg-surface-raised lg:hidden"
          aria-label="자막 검색"
          data-testid="mobile-search-open"
        >
          <svg className="h-[19px] w-[19px]" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
        </button>

        {activeChannelName.endsWith('위원회') && (
          <button
            onClick={() => setShowMembers(true)}
            className="hidden h-8 shrink-0 items-center rounded-md border border-border-strong px-3 text-[13px] font-medium text-text-secondary transition-colors hover:bg-surface-raised lg:inline-flex"
            title="이 위원회의 위원 명단 보기"
            data-testid="committee-members-button-classic"
          >
            위원 명단
          </button>
        )}

        {/* ⋮ — 자주 안 쓰는 것들을 접어 둔 자리 */}
        <div className="relative shrink-0">
          <button
            type="button"
            onClick={() => setOverflowOpen((v) => !v)}
            aria-haspopup="menu"
            aria-expanded={overflowOpen}
            aria-label="더 보기"
            data-testid="live-overflow-toggle"
            className="grid h-9 w-9 place-items-center rounded-md text-text-secondary transition-colors hover:bg-surface-raised lg:h-8 lg:w-8 lg:border lg:border-border-strong"
          >
            <svg className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.75h.008v.008H12V6.75zm0 5.25h.008v.008H12V12zm0 5.25h.008v.008H12v-.008z" />
            </svg>
          </button>
          {overflowOpen && (
            <>
              <div className="fixed inset-0 z-30" onClick={() => setOverflowOpen(false)} aria-hidden="true" />
              <div
                role="menu"
                data-testid="live-overflow-menu"
                className="absolute right-0 top-full z-40 mt-1 w-52 overflow-hidden rounded-lg border border-border bg-surface py-1 shadow-card-elevated"
              >
                {activeChannelName.endsWith('위원회') && (
                  <button
                    role="menuitem"
                    onClick={() => {
                      setOverflowOpen(false);
                      setShowMembers(true);
                    }}
                    className="block w-full px-4 py-2 text-left text-sm text-text-secondary hover:bg-surface-raised lg:hidden"
                  >
                    위원 명단
                  </button>
                )}
                <button
                  role="menuitem"
                  onClick={() => {
                    setOverflowOpen(false);
                    setSortOrder(sortOrder === 'newest' ? 'oldest' : 'newest');
                  }}
                  data-testid="sort-toggle"
                  className="block w-full px-4 py-2 text-left text-sm text-text-secondary hover:bg-surface-raised"
                >
                  {sortOrder === 'newest' ? '시간순으로 보기' : '최신순으로 보기'}
                </button>
                <button
                  role="menuitem"
                  onClick={() => {
                    setOverflowOpen(false);
                    if (isMicStreaming) stopMicStreaming();
                    else startMicStreaming();
                  }}
                  disabled={!wsRoomId}
                  data-testid="mic-stream-toggle"
                  className="block w-full px-4 py-2 text-left text-sm text-text-secondary hover:bg-surface-raised disabled:opacity-40 lg:hidden"
                >
                  {isMicStreaming ? '마이크 중지' : '마이크로 받아쓰기'}
                </button>
                <button
                  role="menuitem"
                  onClick={() => {
                    setOverflowOpen(false);
                    setViewMode('viewer');
                  }}
                  className="block w-full px-4 py-2 text-left text-sm text-text-secondary hover:bg-surface-raised"
                  title="시민용 큰 화면 레이아웃"
                >
                  뷰어 화면으로
                </button>
              </div>
            </>
          )}
        </div>

        {/* 모바일 검색 — 헤더 줄을 덮는다. 줄을 새로 만들지 않는 것이 요점이다 */}
        {mobileSearchOpen && (
          <div className="absolute inset-0 z-20 flex items-center gap-2 bg-surface px-2 lg:hidden">
            <div className="min-w-0 flex-1">
              <SearchInput onSearch={handleSearch} placeholder="자막 검색" />
            </div>
            <button
              type="button"
              onClick={() => {
                setMobileSearchOpen(false);
                handleSearch('');
              }}
              className="shrink-0 px-2 text-sm font-medium text-text-secondary"
              data-testid="mobile-search-close"
            >
              닫기
            </button>
          </div>
        )}
      </div>

      {/*
        본문 — 모바일: [영상 풀블리드] + [탭] + [자막(남은 높이 전부)] + [상태 한 줄]
              PC: 좌 58%(영상 · 지금 발언 · 도구 · 의사일정) / 우(탭 + 자막 + 상태)
      */}
      <main
        data-testid="live-layout"
        className="flex min-h-0 flex-1 flex-col overflow-hidden lg:flex-row lg:gap-4 lg:p-4"
      >
        {/* ── 좌: 영상 ─────────────────────────────────────────────────── */}
        <div
          data-testid="main-content"
          className={`flex shrink-0 flex-col gap-3 ${
            subtitleExpanded ? 'hidden' : 'lg:min-h-0 lg:w-[58%]'
          }`}
        >
          {/* 모바일은 좌우 여백·라운드 없이 화면 폭을 꽉 쓴다 — 같은 높이에 더 큰 화면 */}
          <div className="group relative w-full shrink-0 lg:mx-0 lg:max-w-none">
            {replayVodUrl ? (
              <div className="relative aspect-video overflow-hidden bg-black lg:rounded-lg">
                <video
                  ref={videoRef}
                  src={replayVodUrl}
                  controls
                  autoPlay
                  playsInline
                  className="h-full w-full"
                  data-testid="replay-video"
                />
              </div>
            ) : isOnAir === false && !replayMeetingParam ? (
              <div className="flex aspect-video flex-col items-center justify-center gap-3 bg-gray-900 lg:rounded-lg">
                <svg className="h-16 w-16 text-text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
                <p className="text-lg text-text-muted">현재 방송 중이 아닙니다</p>
                <p className="text-sm text-text-muted">{activeChannel?.status_text || '방송전'}</p>
              </div>
            ) : activeStreamUrl && !replayMeetingParam && syncTargetReady ? (
              <HlsPlayer
                streamUrl={activeStreamUrl}
                videoRef={videoRef}
                onError={handleHlsError}
                latencyRef={hlsLatencyRef}
                playingClockRef={hlsClockRef}
                syncTargetSec={syncTargetSec}
                targetLatencyRef={hlsTargetLatencyRef}
              />
            ) : replayMeetingParam && !replayVodUrl ? (
              <div className="flex aspect-video flex-col items-center justify-center gap-3 bg-gray-900 lg:rounded-lg">
                <div className="h-8 w-8 animate-spin rounded-full border-2 border-text-muted border-t-white" />
                <p className="text-text-muted">VOD 영상 로딩 중...</p>
              </div>
            ) : (
              <div className="flex aspect-video items-center justify-center bg-black lg:rounded-lg">
                <p className="text-text-muted">스트림 URL을 불러오는 중...</p>
              </div>
            )}
            {/* 영상 위 자막 오버레이는 두지 않는다 (2026-09-08 사용자 결정) — 자막은 아래 패널 한 곳에서만.
                예외가 둘이다 (2026-09-16 담당자 요청):
                · 시각 배지 — 자막이 아니라 "이 장면이 몇 시였나"이고, 자막 목록에만 있던 시각을 영상에서도 보인다.
                · [의원 찾기] — 상시 오버레이가 아니라 **누를 때만** 뜨는 얼굴 인식이다. */}
            {!replayMeetingParam && <VideoClockBadge getWallMs={getLiveWallMs} />}
            <LiveFaceOverlay
              videoRef={videoRef}
              channelId={activeChannelId}
              speakerHint={latestSubtitle?.speaker}
              enabled={isOnAir === true || !!replayVodUrl}
            />
          </div>

          {/* PC 전용 — 지금 발언 · 도구 · 의사일정.
              모바일에서는 '지금 발언'이 목록 마지막 줄로 남는다(highlightLatestLive). */}
          {isDesktop && (
            <>
              <CurrentUtteranceCard
                subtitle={latestSubtitle}
                interimText={displayInterim}
                isLive={isOnAir === true}
                sttStartedAt={subtitleClockEpoch}
                className="shrink-0"
              />

              <div className="flex shrink-0 flex-wrap items-center gap-2">
                {meeting?.id && (
                  <TranscriptExportButton
                    meetingId={meeting.id}
                    meetingTitle={meeting.title || activeChannelName || '실시간 회의'}
                  />
                )}
                <button
                  onClick={isMicStreaming ? stopMicStreaming : startMicStreaming}
                  className={`inline-flex h-[34px] shrink-0 items-center rounded-md border px-3 text-[13.5px] font-medium transition-colors ${
                    isMicStreaming
                      ? 'border-error/30 bg-error/5 text-error hover:bg-error/10'
                      : 'border-border-strong bg-surface text-text-secondary hover:bg-surface-raised'
                  }`}
                  data-testid="mic-stream-toggle-desktop"
                  disabled={!wsRoomId}
                >
                  {isMicStreaming ? '마이크 중지' : '마이크'}
                </button>
              </div>

              <LiveAgendaPanel
                meetingId={meetingUuid}
                currentTime={videoClock ?? currentTime}
                refreshKey={displaySubtitles.length}
                onJump={(row) => {
                  if (row.firstSubtitleId) {
                    setAgendaJumpId(row.firstSubtitleId);
                    setAgendaJumpNonce((n) => n + 1);
                    setActiveTab('subtitles');
                  }
                }}
                className="min-h-[120px] flex-1"
              />
            </>
          )}
        </div>

        {/* ── 우: 탭 + 자막 + 상태 ────────────────────────────────────── */}
        <div
          data-testid="sidebar"
          className="flex min-h-0 w-full flex-1 flex-col overflow-hidden border-border lg:h-full lg:rounded-lg lg:border"
        >
          {/* 탭 줄이 곧 패널 헤더다 — 자막 패널의 헤더 한 줄을 여기로 흡수했다 */}
          <ViewerTabs
            className="border-b border-border"
            active={activeTab}
            onChange={(key) => setActiveTab(key as typeof activeTab)}
            tabs={[
              { key: 'subtitles', label: '자막', count: displaySubtitles.length || undefined },
              {
                key: 'search',
                label: '검색결과',
                count: searchQuery ? matchCount : undefined,
              },
              ...(meetingUuid
                ? [
                    {
                      key: 'materials',
                      label: '요구자료',
                      count: materialRequests.requests.length,
                      alert: pendingMaterialCount > 0,
                    },
                  ]
                : []),
            ]}
            rightSlot={
              activeTab === 'materials' ? undefined : (
                <>
                  <button
                    type="button"
                    onClick={() => setAutoFollow((v) => !v)}
                    aria-pressed={autoFollow}
                    data-testid="auto-follow-toggle"
                    title={autoFollow ? '자동 따라가기 끄기 (이전 자막 보기)' : '자동 따라가기 켜기 (새 자막 자동 스크롤)'}
                    className={`grid h-8 w-8 place-items-center rounded-md transition-colors ${
                      autoFollow ? 'bg-primary text-white' : 'text-text-secondary hover:bg-surface-raised'
                    }`}
                  >
                    {autoFollow ? (
                      <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
                        <path d="M12 2a10 10 0 100 20 10 10 0 000-20zm0 18a8 8 0 110-16 8 8 0 010 16zm-1-8.5L15.5 14 14 15.5 9 12V7h2v5z" />
                      </svg>
                    ) : (
                      <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M10 9v6M14 9v6M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                    )}
                  </button>
                  <button
                    type="button"
                    onClick={() => setFontScale(fontScale === 'md' ? 'lg' : fontScale === 'lg' ? 'xl' : 'md')}
                    data-testid="font-scale-toggle"
                    title={`자막 글자 크기 — 현재 ${FONT_SCALE_LABEL[fontScale]}. 누르면 다음 크기로 바뀝니다`}
                    aria-label={`자막 글자 크기 ${FONT_SCALE_LABEL[fontScale]}`}
                    className={`grid h-8 w-8 place-items-center rounded-md text-sm font-bold transition-colors ${
                      fontScale === 'md' ? 'text-text-secondary hover:bg-surface-raised' : 'bg-primary-5 text-primary-dark'
                    }`}
                  >
                    Aa
                  </button>
                  <button
                    type="button"
                    onClick={() => setSubtitleExpanded((v) => !v)}
                    aria-pressed={subtitleExpanded}
                    data-testid="subtitle-expand-toggle"
                    title={subtitleExpanded ? '기본 보기로 전환' : '자막 넓게 보기'}
                    className="hidden h-8 w-8 place-items-center rounded-md text-text-secondary transition-colors hover:bg-surface-raised lg:grid"
                  >
                    {subtitleExpanded ? (
                      <svg className="h-[15px] w-[15px]" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9 9V4.5M9 9H4.5M9 9L3.75 3.75M9 15v4.5M9 15H4.5M9 15l-5.25 5.25M15 9h4.5M15 9V4.5M15 9l5.25-5.25M15 15h4.5M15 15v4.5m0-4.5l5.25 5.25" />
                      </svg>
                    ) : (
                      <svg className="h-[15px] w-[15px]" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15" />
                      </svg>
                    )}
                  </button>
                </>
              )
            }
          />

          {/* Search Navigation */}
          {activeTab === 'search' && searchQuery && matchCount > 0 && (
            <div
              data-testid="search-navigation"
              className="flex shrink-0 items-center justify-between border-b border-border bg-highlight/30 px-4 py-1.5"
            >
              <span className="text-sm text-text-secondary">
                검색 결과: {currentMatchIndex + 1} / {matchCount}
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={goToPrevMatch}
                  className="p-1 text-text-secondary transition-colors hover:text-brand"
                  aria-label="이전 결과"
                  data-testid="prev-match-button"
                >
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                  </svg>
                </button>
                <button
                  onClick={goToNextMatch}
                  className="p-1 text-text-secondary transition-colors hover:text-brand"
                  aria-label="다음 결과"
                  data-testid="next-match-button"
                >
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                  </svg>
                </button>
              </div>
            </div>
          )}

          {activeTab === 'search' && searchQuery && matchCount === 0 && (
            <div
              data-testid="no-search-results"
              className="shrink-0 border-b border-border bg-surface-raised px-4 py-1.5 text-sm text-text-muted"
            >
              &quot;{searchQuery}&quot;에 대한 검색 결과가 없습니다.
            </div>
          )}
          {activeTab === 'search' && !searchQuery && (
            <div className="shrink-0 border-b border-border bg-surface-raised px-4 py-1.5 text-sm text-text-muted">
              위 검색창에 발언 내용을 입력하면 결과가 여기에 표시됩니다.
            </div>
          )}

          {/* 탭 본문 — 요구자료는 목록 패널, 나머지는 자막 패널(검색결과는 일치분만).
              채널을 바꿔 요구자료 탭이 사라지면(미등록 회의) 자막으로 되돌아간다. */}
          {activeTab === 'materials' && meetingUuid ? (
            <div className="min-h-0 flex-1 overflow-y-auto" data-testid="materials-tab-panel">
              <MaterialRequestPanel
                requests={materialRequests.requests}
                isLoading={materialRequests.isLoading}
                onUpdate={materialRequests.update}
                onAddManual={materialRequests.addManual}
                fullHeight
              />
            </div>
          ) : (
            <>
              <div className="min-h-0 flex-1">
                <SubtitlePanel
                  subtitles={activeTab === 'search' ? matchedSubtitles : filteredSubtitles}
                  searchQuery={searchQuery}
                  currentTime={videoClock ?? currentTime}
                  onSubtitleClick={handleSubtitleClick}
                  interimText={activeTab === 'search' ? '' : displayInterim}
                  isLive
                  /* PC 는 '지금 발언'을 영상 아래 카드로 뺐으므로 목록은 지나간 발언 전용이다 */
                  highlightLatestLive={activeTab === 'subtitles' && isOnAir === true && !isDesktop}
                  isLoading={false}
                  emptyMessage={subtitleEmptyMessage}
                  sttStartedAt={subtitleClockEpoch}
                  onLiveClickNotice={handleLiveClickNotice}
                  onPlaySegment={ENABLE_SEGMENT_PLAYBACK ? handlePlaySegment : undefined}
                  playingSubtitleId={playingSegmentId}
                  scrollToSubtitleId={agendaJumpId ?? currentMatch?.id}
                  scrollNonce={agendaJumpNonce}
                  hideHeader
                  borderless
                  autoFollow={autoFollow}
                  onAutoFollowChange={setAutoFollow}
                  sortOrder={sortOrder}
                  onSortOrderChange={setSortOrder}
                  fontScale={fontScale}
                />
              </div>

              {/* 자막 생성 상태 — 2px 헤어라인 + 28px 한 줄.
                  게이지 0점은 자막의 '화면 등장 순간': 동기화 모드에선 게이팅 통과
                  시각(lastRevealTime), 폴백 모드에선 지연 표시 시각(lastActivityTime) */}
              {activeTab === 'subtitles' && (
                <SubtitleGenerationStatus
                  lastActivityTime={isSynced ? lastRevealTime : lastActivityTime}
                  connectionStatus={connectionStatus}
                  sttStatus={sttStatus}
                  subtitleCount={displaySubtitles.length}
                />
              )}
            </>
          )}

          {/* 실시간 자막 클릭 안내 토스트 */}
          {liveNotice && (
            <div className="shrink-0 border-t border-warning-bg/30 bg-warning-bg/10 px-4 py-2 text-center text-sm text-warning animate-fade-in">
              {liveNotice}
            </div>
          )}
        </div>
      </main>
      {activeChannelName.endsWith('위원회') && (
        <CommitteeMembersModal
          committee={activeChannelName}
          committeeCode={activeChannel?.code}
          isOpen={showMembers}
          onClose={() => setShowMembers(false)}
        />
      )}
    </div>
  );
}

export default function LivePage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center bg-surface-raised">
        <p className="text-text-muted">로딩 중...</p>
      </div>
    }>
      <LivePageContent />
    </Suspense>
  );
}
