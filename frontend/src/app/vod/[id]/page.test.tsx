import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import VodViewerPage from './page';

import type { MeetingType, SubtitleType } from '../../../types';

// Mock next/navigation
const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
  }),
  // `?t=` 시점 이동을 읽는 훅 (2026-08-25) — 없으면 페이지가 렌더되지 않는다
  useSearchParams: () => new URLSearchParams(),
}));

// Mock BreadcrumbContext (stable reference to prevent infinite re-renders)
const mockSetTitle = jest.fn();
jest.mock('../../../contexts/BreadcrumbContext', () => ({
  useBreadcrumb: () => ({
    dynamicTitle: null,
    setTitle: mockSetTitle,
  }),
}));

// Mock AuthContext
jest.mock('../../../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: null,
    loading: false,
    error: null,
    login: jest.fn(),
    logout: jest.fn(),
  }),
}));

// Mock the apiClient
const mockApiClient = jest.fn();
jest.mock('../../../lib/api', () => ({
  __esModule: true,
  default: (...args: unknown[]) => mockApiClient(...args),
  apiClient: (...args: unknown[]) => mockApiClient(...args),
  startSttProcessing: jest.fn().mockRejectedValue(new Error('not available')),
  getSttStatus: jest.fn().mockRejectedValue(new Error('not available')),
  getVerificationStats: jest.fn().mockRejectedValue(new Error('not available')),
  getAgendas: jest.fn().mockResolvedValue([]),
  ApiError: class ApiError extends Error { status: number; constructor(m: string, s: number) { super(m); this.status = s; } },
  API_BASE_URL: 'http://localhost:8000',
}));

describe('VodViewerPage', () => {
  const mockMeeting: MeetingType = {
    id: 'vod-1',
    title: '제352회 본회의',
    meeting_date: '2024-01-15T10:00:00Z',
    stream_url: null,
    vod_url: 'https://example.com/video.mp4',
    status: 'ended',
    duration_seconds: 5400,
    created_at: '2024-01-15T00:00:00Z',
    updated_at: '2024-01-15T00:00:00Z',
  };

  const mockSubtitles: SubtitleType[] = [
    {
      id: 'sub-1',
      meeting_id: 'vod-1',
      start_time: 0,
      end_time: 5,
      text: '안녕하세요, 회의를 시작하겠습니다.',
      speaker: '의장',
      confidence: 0.95,
      created_at: '2024-01-15T10:00:00Z',
    },
    {
      id: 'sub-2',
      meeting_id: 'vod-1',
      start_time: 5,
      end_time: 10,
      text: '첫 번째 안건을 상정합니다.',
      speaker: '의장',
      confidence: 0.92,
      created_at: '2024-01-15T10:00:05Z',
    },
  ];

  const defaultParams = { id: 'vod-1' };

  beforeEach(() => {
    jest.clearAllMocks();
    mockApiClient.mockImplementation((endpoint: string) => {
      if (endpoint === '/api/meetings/vod-1') {
        return Promise.resolve(mockMeeting);
      }
      if (endpoint.startsWith('/api/meetings/vod-1/subtitles')) {
        return Promise.resolve({ items: mockSubtitles });
      }
      return Promise.reject(new Error('Unknown endpoint'));
    });
  });

  describe('page structure', () => {
    it('renders the VOD viewer page', async () => {
      render(<VodViewerPage params={defaultParams} />);

      await waitFor(() => {
        expect(screen.getByTestId('vod-viewer-page')).toBeInTheDocument();
      });
    });

    it('sets breadcrumb title after loading', async () => {
      render(<VodViewerPage params={defaultParams} />);

      await waitFor(() => {
        expect(mockSetTitle).toHaveBeenCalledWith('제352회 본회의');
      });
    });

    it('shows meeting title after loading', async () => {
      render(<VodViewerPage params={defaultParams} />);

      await waitFor(() => {
        expect(screen.getByTestId('vod-viewer-page')).toBeInTheDocument();
      });
    });
  });

  describe('layout', () => {
    it('has 55/45 layout on desktop (matches live page)', async () => {
      render(<VodViewerPage params={defaultParams} />);

      await waitFor(() => {
        const mainContent = screen.getByTestId('main-content');
        const sidebar = screen.getByTestId('sidebar');

        expect(mainContent).toHaveClass('lg:w-[55%]');
        expect(sidebar).toHaveClass('lg:w-[45%]');
      });
    });

    // 툴바가 줄바꿈되면 모바일에서 [자막확대]/[회의록]/[검색] 3줄로 흩어져
    // 영상이 그만큼 아래로 밀린다 (2026-08-21 사용자 지적). 한 줄을 강제한다.
    it('keeps the top toolbar on a single row and reserves space for the floating controls', async () => {
      render(<VodViewerPage params={defaultParams} />);

      await waitFor(() => {
        const toolbar = screen.getByTestId('vod-toolbar');
        expect(toolbar).toHaveClass('flex-nowrap');
        expect(toolbar).not.toHaveClass('flex-wrap');
        expect(toolbar).toHaveClass('pr-24');
      });
    });

    it('stacks content on mobile', async () => {
      render(<VodViewerPage params={defaultParams} />);

      await waitFor(() => {
        const layout = screen.getByTestId('vod-layout');
        expect(layout).toHaveClass('flex-col');
        expect(layout).toHaveClass('lg:flex-row');
      });
    });
  });

  describe('video player', () => {
    it('renders Mp4Player', async () => {
      render(<VodViewerPage params={defaultParams} />);

      await waitFor(() => {
        expect(screen.getByTestId('mp4-player-container')).toBeInTheDocument();
      });
    });

    it('renders VideoControls', async () => {
      render(<VodViewerPage params={defaultParams} />);

      await waitFor(() => {
        expect(screen.getByTestId('video-controls')).toBeInTheDocument();
      });
    });
  });

  describe('subtitle panel', () => {
    it('renders SubtitlePanel', async () => {
      render(<VodViewerPage params={defaultParams} />);

      await waitFor(() => {
        expect(screen.getByTestId('subtitle-panel')).toBeInTheDocument();
      });
    });

    it('displays subtitles after loading', async () => {
      render(<VodViewerPage params={defaultParams} />);

      await waitFor(() => {
        expect(screen.getByText('안녕하세요, 회의를 시작하겠습니다.')).toBeInTheDocument();
        expect(screen.getByText('첫 번째 안건을 상정합니다.')).toBeInTheDocument();
      });
    });
  });

  describe('action buttons', () => {
    it('shows disabled export button when not logged in', async () => {
      render(<VodViewerPage params={defaultParams} />);

      await waitFor(() => {
        expect(screen.getByText('회의록 내보내기')).toBeInTheDocument();
      });
    });
  });

  describe('API calls', () => {
    it('fetches meeting data with correct id', async () => {
      render(<VodViewerPage params={defaultParams} />);

      await waitFor(() => {
        expect(mockApiClient).toHaveBeenCalledWith('/api/meetings/vod-1');
      });
    });

    it('fetches subtitles with correct meeting id', async () => {
      render(<VodViewerPage params={defaultParams} />);

      await waitFor(() => {
        expect(mockApiClient).toHaveBeenCalledWith(
          expect.stringContaining('/api/meetings/vod-1/subtitles')
        );
      });
    });
  });

  describe('loading state', () => {
    it('shows loading indicator while fetching data', () => {
      mockApiClient.mockImplementation(() => new Promise(() => {})); // Never resolves

      render(<VodViewerPage params={defaultParams} />);

      expect(screen.getByTestId('page-loading')).toBeInTheDocument();
    });
  });

  describe('error state', () => {
    it('shows error message when API call fails', async () => {
      mockApiClient.mockRejectedValue(new Error('Network error'));

      render(<VodViewerPage params={defaultParams} />);

      await waitFor(() => {
        expect(screen.getByTestId('page-error')).toBeInTheDocument();
      });
    });

    it('shows home navigation button on error', async () => {
      mockApiClient.mockRejectedValue(new Error('Network error'));

      render(<VodViewerPage params={defaultParams} />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /홈으로 이동/ })).toBeInTheDocument();
      });
    });

    it('navigates to home when home button is clicked on error', async () => {
      mockApiClient.mockRejectedValue(new Error('Network error'));
      const user = userEvent.setup();

      render(<VodViewerPage params={defaultParams} />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /홈으로 이동/ })).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: /홈으로 이동/ }));

      expect(mockPush).toHaveBeenCalledWith('/');
    });
  });

  // 2026-09-15 담당자 요청 — VOD 영상 등록 대기 화면에서 자막 ▶ 를 누르면 생중계 녹음 음성이 나온다
  describe('VOD 등록 전 — 자막 ▶ 로 녹음 음성 재생', () => {
    const uuid = '70ebdfbb-b7eb-48a0-82c5-6c9993d68c5e';
    const pendingMeeting: MeetingType = { ...mockMeeting, id: uuid, vod_url: null };
    const liveSubtitles = mockSubtitles.map((s) => ({ ...s, meeting_id: uuid }));
    const fetchMock = jest.fn();
    const playMock = jest.fn().mockResolvedValue(undefined);
    const originalFetch = global.fetch;
    const originalAudio = window.Audio;
    const originalCreate = URL.createObjectURL;
    const originalRevoke = URL.revokeObjectURL;

    beforeEach(() => {
      mockApiClient.mockImplementation((endpoint: string) => {
        if (endpoint === `/api/meetings/${uuid}`) return Promise.resolve(pendingMeeting);
        if (endpoint.startsWith(`/api/meetings/${uuid}/subtitles`)) {
          return Promise.resolve({
            items: liveSubtitles,
            total: liveSubtitles.length,
            kind: 'live',
            kind_counts: { live: liveSubtitles.length, ai: 0 },
          });
        }
        return Promise.reject(new Error('Unknown endpoint'));
      });
      fetchMock.mockReset();
      global.fetch = fetchMock as unknown as typeof fetch;
      window.Audio = jest.fn(() => ({
        play: playMock,
        pause: jest.fn(),
        addEventListener: jest.fn(),
      })) as unknown as typeof Audio;
      URL.createObjectURL = jest.fn(() => 'blob:seg');
      URL.revokeObjectURL = jest.fn();
    });

    afterEach(() => {
      cleanup(); // 언마운트(재생 정리 → revokeObjectURL)가 목을 되돌리기 전에 돌게
      global.fetch = originalFetch;
      window.Audio = originalAudio;
      URL.createObjectURL = originalCreate;
      URL.revokeObjectURL = originalRevoke;
    });

    it('녹음이 있으면 ▶ 가 재생 버튼이 되고, 누르면 그 구간만 Range 로 받아 재생한다', async () => {
      const meta = { exists: true, size_bytes: 600_000, bytes_per_sec: 6000, start_offset_sec: 0, sessions: [] };
      fetchMock.mockImplementation((url: string) => {
        if (url.includes('/recording/meta')) {
          return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(meta) });
        }
        return Promise.resolve({ ok: true, status: 206, blob: () => Promise.resolve(new Blob(['x'])) });
      });
      const user = userEvent.setup();

      render(<VodViewerPage params={{ id: uuid }} />);

      await waitFor(() => {
        expect(screen.getByTestId('vod-pending-audio-hint')).toBeInTheDocument();
      });
      const chips = screen.getAllByTestId('time-chip');
      expect(chips[1]).toHaveAttribute('role', 'button');

      await user.click(chips[1]!);

      await waitFor(() => expect(playMock).toHaveBeenCalled());
      const rangeCall = fetchMock.mock.calls.find(
        ([url]) => String(url).endsWith(`/api/meetings/${uuid}/recording`),
      );
      // 두 번째 자막 5~10초 → 30000-2048 ~ 60000+4096
      expect(rangeCall?.[1]).toEqual({ headers: { Range: 'bytes=27952-64096' } });
      expect(chips[1]).toHaveAttribute('data-playing', 'true');
    });

    it('녹음이 없으면(404) ▶ 는 재생 버튼이 아니고 안내도 없다', async () => {
      fetchMock.mockResolvedValue({ ok: false, status: 404 });

      render(<VodViewerPage params={{ id: uuid }} />);

      await waitFor(() => {
        expect(screen.getByTestId('vod-pending')).toBeInTheDocument();
      });
      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalledWith(`http://localhost:8000/api/meetings/${uuid}/recording/meta`);
      });
      expect(screen.queryByTestId('vod-pending-audio-hint')).not.toBeInTheDocument();
      for (const chip of screen.getAllByTestId('time-chip')) {
        expect(chip).not.toHaveAttribute('role', 'button');
      }
    });

    it('VOD 영상이 있으면 녹음을 조회하지 않는다 (▶ 는 영상 시점 이동 그대로)', async () => {
      mockApiClient.mockImplementation((endpoint: string) => {
        if (endpoint === `/api/meetings/${uuid}`) {
          return Promise.resolve({ ...pendingMeeting, vod_url: 'https://example.com/v.mp4' });
        }
        if (endpoint.startsWith(`/api/meetings/${uuid}/subtitles`)) {
          return Promise.resolve({ items: liveSubtitles, kind: 'live' });
        }
        return Promise.reject(new Error('Unknown endpoint'));
      });

      render(<VodViewerPage params={{ id: uuid }} />);

      await waitFor(() => {
        expect(screen.getAllByTestId('time-chip').length).toBeGreaterThan(0);
      });
      expect(fetchMock).not.toHaveBeenCalled();
    });
  });
});
