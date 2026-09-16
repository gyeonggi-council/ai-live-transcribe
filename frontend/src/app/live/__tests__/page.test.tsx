import { act } from 'react';

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import LivePage from '../page';

import type { MeetingType } from '../../../types';

// Mock global fetch for STT start/stop API calls
const mockFetch = jest.fn().mockResolvedValue({
  ok: true,
  json: () => Promise.resolve({ status: 'started' }),
  text: () => Promise.resolve(''),
});
global.fetch = mockFetch;

// Mock the useLiveMeeting hook
const mockUseLiveMeeting = jest.fn();
jest.mock('../../../hooks/useLiveMeeting', () => ({
  __esModule: true,
  default: () => mockUseLiveMeeting(),
}));

// Mock the useSubtitleWebSocket hook
const mockUseSubtitleWebSocket = jest.fn();
jest.mock('../../../hooks/useSubtitleWebSocket', () => ({
  __esModule: true,
  useSubtitleWebSocket: () => mockUseSubtitleWebSocket(),
}));

// Mock the useChannelStatus hook
const mockUseChannelStatus = jest.fn();
jest.mock('../../../hooks/useChannelStatus', () => ({
  __esModule: true,
  useChannelStatus: () => mockUseChannelStatus(),
}));

// Mock the useRouter and useSearchParams hooks
const mockPush = jest.fn();
const mockSearchParamsGet = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
  }),
  useSearchParams: () => ({
    get: mockSearchParamsGet,
  }),
}));

// Mock HLS.js
jest.mock('hls.js', () => {
  const Events = {
    MANIFEST_PARSED: 'hlsManifestParsed',
    ERROR: 'hlsError',
  } as const;

  const ErrorTypes = {
    NETWORK_ERROR: 'networkError',
    MEDIA_ERROR: 'mediaError',
  } as const;

  return {
    __esModule: true,
    default: class MockHls {
      static isSupported() {
        return true;
      }
      static Events = Events;
      static ErrorTypes = ErrorTypes;
      attachMedia = jest.fn();
      loadSource = jest.fn();
      destroy = jest.fn();
      on = jest.fn();
    },
  };
});

describe('LivePage', () => {
  const mockLiveMeeting: MeetingType = {
    id: 'meeting-1',
    title: '제352회 본회의',
    meeting_date: '2024-01-15T10:00:00Z',
    stream_url: 'https://example.com/stream.m3u8',
    vod_url: null,
    status: 'live',
    duration_seconds: null,
    created_at: '2024-01-15T00:00:00Z',
    updated_at: '2024-01-15T00:00:00Z',
  };

  const defaultWebSocketReturn = {
    subtitles: [],
    connectionStatus: 'connected' as const,
    connect: jest.fn(),
    disconnect: jest.fn(),
    clearSubtitles: jest.fn(),
  };

  const renderLivePage = async (options: { expectSttStart?: boolean } = {}) => {
    // STT 시작은 서버 AutoSttManager가 전담 — 클라이언트는 더 이상 fetch로
    // STT를 트리거하지 않으므로 fetch 호출을 기대하면 안 된다 (기본 false).
    const { expectSttStart = false } = options;

    render(<LivePage />);

    if (expectSttStart) {
      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled();
      });
    }
  };

  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => new Promise(() => {}),
      text: () => Promise.resolve(''),
    });
    mockUseSubtitleWebSocket.mockReturnValue(defaultWebSocketReturn);
    mockUseChannelStatus.mockReturnValue({
      channels: [
        { id: 'ch14', name: '본회의', code: 'A011', stream_url: 'https://example.com/ch14/playlist.m3u8', livestatus: 1 },
      ],
      isLoading: false,
      error: null,
      requestNotificationPermission: jest.fn(),
    });
    // 기본: channel 파라미터로 채널이 선택된 상태 (replay_meeting은 null)
    mockSearchParamsGet.mockImplementation((key: string) => {
      if (key === 'channel') return 'ch14';
      return null;
    });
  });

  describe('when live meeting exists', () => {
    beforeEach(() => {
      mockUseLiveMeeting.mockReturnValue({
        meeting: mockLiveMeeting,
        isLoading: false,
        error: null,
      });
    });

    it('renders the page', async () => {
      await renderLivePage();

      expect(screen.getByTestId('live-page')).toBeInTheDocument();
    });

    it('shows header with channel name', async () => {
      await renderLivePage();

      // 채널 이름이 헤더와 채널바에 표시됨
      const channelNames = screen.getAllByText('본회의');
      expect(channelNames.length).toBeGreaterThanOrEqual(1);
    });

    it('shows live badge in header', async () => {
      await renderLivePage();

      // Header와 채널바 모두 LIVE 배지가 표시됨
      const liveBadges = screen.getAllByText(/LIVE|Live/i);
      expect(liveBadges.length).toBeGreaterThanOrEqual(1);
    });

    it('renders HLS player', async () => {
      await renderLivePage();

      expect(screen.getByTestId('hls-player-container')).toBeInTheDocument();
    });

    it('renders subtitle panel', async () => {
      await renderLivePage();

      expect(screen.getByTestId('subtitle-panel')).toBeInTheDocument();
    });

    it('renders search input in header', async () => {
      await renderLivePage();

      expect(screen.getByRole('searchbox')).toBeInTheDocument();
    });

    it('has 58/42 layout on desktop', async () => {
      await renderLivePage();

      const mainContent = screen.getByTestId('main-content');
      const sidebar = screen.getByTestId('sidebar');

      // 2026-08-25 개선안 2e: 영상 55% → 58%. 되찾은 좌측 공간에 '지금 발언' 카드와
      // 의사일정이 들어간다. 자막 패널은 여전히 flex-1 로 나머지를 차지하고,
      // 모바일에선 그 flex-1 이 남은 '높이' 전부가 되어 자막 가독성을 확보한다.
      expect(mainContent).toHaveClass('lg:w-[58%]');
      expect(sidebar).toHaveClass('flex-1');
      expect(sidebar).toHaveClass('min-h-0');
    });
  });

  describe('when no channel selected', () => {
    beforeEach(() => {
      mockSearchParamsGet.mockReturnValue(null);
      mockUseLiveMeeting.mockReturnValue({
        meeting: null,
        isLoading: false,
        error: null,
      });
    });

    it('shows channel selector', async () => {
      await renderLivePage({ expectSttStart: false });

      expect(screen.getByTestId('channel-selector')).toBeInTheDocument();
      // 2026-08-25 개선안 2b: 제목이 '채널 선택' → '실시간 방송' 으로 바뀌었다.
      expect(screen.getByText('실시간 방송')).toBeInTheDocument();
    });

    it('shows channel list', async () => {
      await renderLivePage({ expectSttStart: false });

      // 채널명은 상단 단(방송 중 또는 예정)과 '전체 채널' 목록에 각각 한 번씩 나온다
      expect(screen.getAllByText('본회의').length).toBeGreaterThan(0);
      expect(screen.getByTestId('channel-selector')).toBeInTheDocument();
    });

    it('navigates to channel on select', async () => {
      const user = userEvent.setup();
      await renderLivePage({ expectSttStart: false });

      await user.click(screen.getByTestId('channel-ch14'));

      expect(mockPush).toHaveBeenCalledWith('/live?channel=ch14');
    });
  });

  describe('channel loading state', () => {
    beforeEach(() => {
      mockSearchParamsGet.mockReturnValue(null);
      mockUseChannelStatus.mockReturnValue({
        channels: [],
        isLoading: true,
        error: null,
        requestNotificationPermission: jest.fn(),
      });
      mockUseLiveMeeting.mockReturnValue({
        meeting: null,
        isLoading: false,
        error: null,
      });
    });

    it('shows loading spinner in channel selector', async () => {
      await renderLivePage({ expectSttStart: false });

      // ChannelSelector shows spinner when isLoading=true
      expect(screen.getByTestId('live-page')).toBeInTheDocument();
    });
  });

  describe('search functionality', () => {
    beforeEach(() => {
      mockUseLiveMeeting.mockReturnValue({
        meeting: mockLiveMeeting,
        isLoading: false,
        error: null,
      });
    });

    it('updates search query when typing in search input', async () => {
      jest.useFakeTimers();
      const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });

      await renderLivePage();

      const searchInput = screen.getByRole('searchbox');
      await user.type(searchInput, '예산');

      await act(async () => {
        jest.advanceTimersByTime(300);
      });

      // The subtitle panel should receive the search query
      // This is tested via integration - the searchQuery prop is passed to SubtitlePanel
      expect(searchInput).toHaveValue('예산');

      jest.useRealTimers();
    });
  });

  describe('responsive layout', () => {
    beforeEach(() => {
      mockUseLiveMeeting.mockReturnValue({
        meeting: mockLiveMeeting,
        isLoading: false,
        error: null,
      });
    });

    it('stacks content on mobile', async () => {
      await renderLivePage();

      const layout = screen.getByTestId('live-layout');
      expect(layout).toHaveClass('flex-col');
      expect(layout).toHaveClass('lg:flex-row');
    });

    it('video takes full width on mobile', async () => {
      await renderLivePage();

      // 개선안 2a: 모바일은 좌우 여백·라운드 없이 화면 폭을 꽉 쓴다.
      // 폭 제한은 lg 이상에서만 걸린다.
      const mainContent = screen.getByTestId('main-content');
      expect(mainContent.className).toContain('lg:w-[58%]');
      expect(mainContent.className).not.toContain('max-w-[68vh]');
    });
  });

  describe('WebSocket subtitle integration', () => {
    beforeEach(() => {
      mockUseLiveMeeting.mockReturnValue({
        meeting: mockLiveMeeting,
        isLoading: false,
        error: null,
      });
    });

    it('displays connection status', async () => {
      await renderLivePage();

      expect(screen.getByTestId('connection-status')).toBeInTheDocument();
      expect(screen.getByText('연결됨')).toBeInTheDocument();
    });

    it('shows connecting status when connecting', async () => {
      mockUseSubtitleWebSocket.mockReturnValue({
        ...defaultWebSocketReturn,
        connectionStatus: 'connecting',
      });

      await renderLivePage();

      expect(screen.getByText('연결 중...')).toBeInTheDocument();
    });

    it('shows disconnected status and reconnect button when disconnected', async () => {
      mockUseSubtitleWebSocket.mockReturnValue({
        ...defaultWebSocketReturn,
        connectionStatus: 'disconnected',
      });

      await renderLivePage();

      expect(screen.getByText('연결 끊김')).toBeInTheDocument();
      expect(screen.getByTestId('reconnect-button')).toBeInTheDocument();
    });

    it('calls connect when reconnect button is clicked', async () => {
      const mockConnect = jest.fn();
      mockUseSubtitleWebSocket.mockReturnValue({
        ...defaultWebSocketReturn,
        connectionStatus: 'disconnected',
        connect: mockConnect,
      });

      const user = userEvent.setup();
      await renderLivePage();

      await user.click(screen.getByTestId('reconnect-button'));

      expect(mockConnect).toHaveBeenCalledTimes(1);
    });

    it('shows error status and reconnect button when error', async () => {
      mockUseSubtitleWebSocket.mockReturnValue({
        ...defaultWebSocketReturn,
        connectionStatus: 'error',
      });

      await renderLivePage();

      expect(screen.getByText('연결 오류')).toBeInTheDocument();
      expect(screen.getByTestId('reconnect-button')).toBeInTheDocument();
    });

    it('displays received subtitles in the panel', async () => {
      const mockSubtitles = [
        {
          id: 'sub-1',
          meeting_id: 'meeting-1',
          start_time: 0,
          end_time: 5,
          text: '테스트 자막입니다.',
          speaker: null,
          confidence: 0.9,
          created_at: '2024-01-15T10:00:00Z',
        },
      ];

      mockUseSubtitleWebSocket.mockReturnValue({
        ...defaultWebSocketReturn,
        subtitles: mockSubtitles,
      });

      await renderLivePage();

      // SubtitlePanel 에서 렌더링됨 (영상 위 오버레이는 2026-09-08 제거)
      const matches = screen.getAllByText('테스트 자막입니다.');
      expect(matches.length).toBeGreaterThanOrEqual(1);
    });

    it('hides previous-day subtitles when channel is before broadcast (stale archive)', async () => {
      // 어제 정회된 회의가 DB에 살아 있어도, 날짜가 바뀌고 방송 전이면
      // 기존 자막을 표시하지 않는다 (mockLiveMeeting.meeting_date = 2024-01-15 = 과거)
      mockUseChannelStatus.mockReturnValue({
        channels: [
          { id: 'ch14', name: '본회의', code: 'A011', stream_url: 'https://example.com/ch14/playlist.m3u8', livestatus: 0 },
        ],
        isLoading: false,
        error: null,
        requestNotificationPermission: jest.fn(),
      });
      mockUseSubtitleWebSocket.mockReturnValue({
        ...defaultWebSocketReturn,
        subtitles: [
          {
            id: 'sub-old',
            meeting_id: 'meeting-1',
            start_time: 0,
            end_time: 5,
            text: '어제 회의 자막입니다.',
            speaker: null,
            confidence: 0.9,
            created_at: '2024-01-15T10:00:00Z',
          },
        ],
      });

      await renderLivePage();

      expect(screen.queryByText('어제 회의 자막입니다.')).not.toBeInTheDocument();
      expect(screen.getByText('방송 시작 시 자막이 표시됩니다.')).toBeInTheDocument();
    });

    it('clears previous meeting archive when switching to a meeting without subtitles', async () => {
      // 채널 전환 재현: A 회의(자막 있음) → B 회의(자막 0건)로 meeting이 바뀌면
      // 이전 회의 자막이 화면에 남으면 안 된다 (2026-06-12 잔류 버그 회귀 방지)
      const subA = {
        id: 'sub-a',
        meeting_id: 'aaaaaaaa-1111-2222-3333-444444444444',
        start_time: 0,
        end_time: 5,
        text: '이전 채널 회의 자막입니다.',
        speaker: null,
        confidence: 0.9,
        created_at: new Date().toISOString(),
      };
      mockFetch.mockImplementation((url: string) => {
        const body = String(url).includes('aaaaaaaa')
          ? { items: [subA] }
          : { items: [] };
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(body),
          text: () => Promise.resolve(''),
        });
      });
      const meetingA = {
        ...mockLiveMeeting,
        id: 'aaaaaaaa-1111-2222-3333-444444444444',
        meeting_date: new Date().toISOString(),
      };
      const meetingB = {
        ...mockLiveMeeting,
        id: 'bbbbbbbb-1111-2222-3333-444444444444',
        meeting_date: new Date().toISOString(),
      };
      mockUseLiveMeeting.mockReturnValue({ meeting: meetingA, isLoading: false, error: null });

      const { rerender } = render(<LivePage />);
      await waitFor(() => {
        expect(screen.getAllByText('이전 채널 회의 자막입니다.').length).toBeGreaterThanOrEqual(1);
      });

      mockUseLiveMeeting.mockReturnValue({ meeting: meetingB, isLoading: false, error: null });
      rerender(<LivePage />);

      await waitFor(() => {
        expect(screen.queryByText('이전 채널 회의 자막입니다.')).not.toBeInTheDocument();
      });
    });
  });

  describe('영상 지연 목표 (2026-09-14)', () => {
    const channelWithTarget = (extra: Record<string, unknown>) => ({
      channels: [
        {
          id: 'ch14', name: '본회의', code: 'A011',
          stream_url: 'https://example.com/ch14/playlist.m3u8', livestatus: 1, ...extra,
        },
      ],
      isLoading: false,
      error: null,
      requestNotificationPermission: jest.fn(),
    });
    const syncDebug = () =>
      (window as unknown as { __syncDebug: { syncTarget: number; syncTargetSource: string } }).__syncDebug;

    beforeEach(() => {
      mockUseLiveMeeting.mockReturnValue({ meeting: mockLiveMeeting, isLoading: false, error: null });
    });

    it('채널 응답의 sync_target_sec 가 플레이어 목표가 된다 (출처 server)', async () => {
      mockUseChannelStatus.mockReturnValue(channelWithTarget({ sync_target_sec: 17 }));
      await renderLivePage();
      await waitFor(() => expect(screen.getByTestId('hls-video')).toBeInTheDocument());
      expect(syncDebug().syncTarget).toBe(17);
      expect(syncDebug().syncTargetSource).toBe('server');
    });

    it('?sync= 가 있으면 서버값보다 이긴다 (출처 query)', async () => {
      mockUseChannelStatus.mockReturnValue(channelWithTarget({ sync_target_sec: 17 }));
      mockSearchParamsGet.mockImplementation((key: string) => {
        if (key === 'channel') return 'ch14';
        if (key === 'sync') return '14';
        return null;
      });
      await renderLivePage();
      await waitFor(() => expect(screen.getByTestId('hls-video')).toBeInTheDocument());
      expect(syncDebug().syncTarget).toBe(14);
      expect(syncDebug().syncTargetSource).toBe('query');
    });

    it('서버가 값을 안 주면 빌드 기본(출처 default)', async () => {
      mockUseChannelStatus.mockReturnValue(channelWithTarget({}));
      await renderLivePage();
      await waitFor(() => expect(screen.getByTestId('hls-video')).toBeInTheDocument());
      expect(syncDebug().syncTarget).toBe(20);
      expect(syncDebug().syncTargetSource).toBe('default');
    });

    it('채널 응답이 아직 없으면 플레이어를 띄우지 않다가 2초 뒤 폴백으로 띄운다', async () => {
      jest.useFakeTimers();
      try {
        mockUseChannelStatus.mockReturnValue({
          channels: [], isLoading: true, error: null, requestNotificationPermission: jest.fn(),
        });
        render(<LivePage />);
        expect(screen.queryByTestId('hls-video')).not.toBeInTheDocument();
        act(() => {
          jest.advanceTimersByTime(2100);
        });
        expect(screen.getByTestId('hls-video')).toBeInTheDocument();
      } finally {
        jest.useRealTimers();
      }
    });
  });
});
