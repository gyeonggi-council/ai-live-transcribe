import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import MinutesPage from './page';

import type { MeetingSummaryType, MeetingType, SubtitleType } from '../../../../types';

const mockPush = jest.fn();
const mockSetTitle = jest.fn();

jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
    back: jest.fn(),
  }),
}));

jest.mock('next/link', () => {
  function MockLink({ children, href }: { children: React.ReactNode; href: string }) {
    return <a href={href}>{children}</a>;
  }
  MockLink.displayName = 'MockLink';
  return MockLink;
});

jest.mock('../../../../contexts/BreadcrumbContext', () => ({
  useBreadcrumb: () => ({
    dynamicTitle: null,
    setTitle: mockSetTitle,
  }),
}));

// 로그인 상태 제어 — 전자회의록 미리보기·편집 버튼 게이트 테스트용
let mockAuthUser: { id: string; username: string; role: string } | null = null;

jest.mock('../../../../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: mockAuthUser,
    loading: false,
    error: null,
    login: jest.fn(),
    pinLogin: jest.fn(),
    logout: jest.fn(),
  }),
}));

const mockApiClient = jest.fn();
const mockGetMinutesByAgenda = jest.fn();
const mockUpdateMeetingStatus = jest.fn();
const mockGetMinutesMarkdown = jest.fn();

jest.mock('../../../../lib/api', () => ({
  __esModule: true,
  apiClient: (...args: unknown[]) => mockApiClient(...args),
  getMinutesByAgenda: (...args: unknown[]) => mockGetMinutesByAgenda(...args),
  updateMeetingStatus: (...args: unknown[]) => mockUpdateMeetingStatus(...args),
  getAgendaFiles: jest.fn().mockResolvedValue([]),
  uploadAgendaFile: jest.fn().mockResolvedValue({}),
  deleteAgendaFile: jest.fn().mockResolvedValue(undefined),
  getMinutesMarkdown: (...args: unknown[]) => mockGetMinutesMarkdown(...args),
  downloadHwpxFromMarkdown: jest.fn().mockResolvedValue(undefined),
  downloadHwpx: jest.fn().mockResolvedValue(undefined),
  API_BASE_URL: 'http://localhost:8000',
}));

const defaultParams = { id: 'meeting-1' };

const mockMeeting: MeetingType = {
  id: 'meeting-1',
  title: '제1회 테스트 회의',
  meeting_date: '2024-01-01T00:00:00Z',
  stream_url: null,
  vod_url: 'https://example.com/vod.mp4',
  status: 'ended',
  duration_seconds: 3600,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
};

const mockSubtitles: SubtitleType[] = [
  {
    id: 'subtitle-1',
    meeting_id: 'meeting-1',
    start_time: 0,
    end_time: 3,
    text: '안녕하세요.',
    speaker: '화자 1',
    confidence: 0.95,
    created_at: '2024-01-01T00:00:00Z',
  },
  {
    id: 'subtitle-2',
    meeting_id: 'meeting-1',
    start_time: 3,
    end_time: 6,
    text: '오늘 회의를 시작하겠습니다.',
    speaker: '화자 1',
    confidence: 0.92,
    created_at: '2024-01-01T00:00:00Z',
  },
  {
    id: 'subtitle-3',
    meeting_id: 'meeting-1',
    start_time: 6,
    end_time: 10,
    text: '좋습니다.',
    speaker: '화자 2',
    confidence: 0.88,
    created_at: '2024-01-01T00:00:00Z',
  },
];

const mockSummary: MeetingSummaryType = {
  id: 'summary-1',
  meeting_id: 'meeting-1',
  summary_text: '테스트 회의 요약입니다.',
  agenda_summaries: [
    { order_num: 1, title: '안건 1', summary: '안건 1 요약' },
    { order_num: 2, title: '안건 2', summary: '안건 2 요약' },
  ],
  key_decisions: ['결정 1', '결정 2'],
  action_items: ['조치 1'],
  model_used: 'gpt-4o-mini',
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
};

const mockAgendaMinutes = {
  agendas: [
    {
      order_num: 1,
      title: '안건 1',
      description: null,
      subtitles: [mockSubtitles[0], mockSubtitles[1]],
      speaker_groups: [
        { speaker: '화자 1', texts: ['안녕하세요.', '오늘 회의를 시작하겠습니다.'], start_time: 0, end_time: 6 },
      ],
    },
    {
      order_num: 2,
      title: '안건 2',
      description: null,
      subtitles: [mockSubtitles[2]],
      speaker_groups: [
        { speaker: '화자 2', texts: ['좋습니다.'], start_time: 6, end_time: 10 },
      ],
    },
  ],
  unassigned_subtitles: [],
  total_subtitles: 3,
};

function setupMocks(options?: { noSummary?: boolean; noSubtitles?: boolean; aiKind?: boolean }) {
  mockApiClient.mockImplementation((url: string) => {
    if (url.includes('/subtitles')) {
      return Promise.resolve({
        items: options?.noSubtitles ? [] : mockSubtitles,
        ...(options?.aiKind
          ? { kind: 'ai', kind_counts: { live: 0, ai: mockSubtitles.length } }
          : {}),
      });
    }
    if (url.includes('/summary')) {
      if (options?.noSummary) {
        return Promise.reject(new Error('Not found'));
      }
      return Promise.resolve(mockSummary);
    }
    return Promise.resolve(mockMeeting);
  });
  mockGetMinutesByAgenda.mockResolvedValue(mockAgendaMinutes);
  mockUpdateMeetingStatus.mockResolvedValue(mockMeeting);
}

describe('MinutesPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockAuthUser = null;
    mockGetMinutesMarkdown.mockResolvedValue({
      markdown: '# 미리보기 회의록',
      kordoc_available: true,
    });
  });

  it('renders loading state initially', () => {
    mockApiClient.mockReturnValue(new Promise(() => {}));
    render(<MinutesPage params={defaultParams} />);
    expect(screen.getByTestId('page-loading')).toBeInTheDocument();
  });

  it('renders minutes page with subtitle data', async () => {
    setupMocks({ noSummary: true });
    render(<MinutesPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('minutes-page')).toBeInTheDocument();
    });

    expect(screen.getByText('제1회 테스트 회의')).toBeInTheDocument();
    expect(screen.getByText('화자 1')).toBeInTheDocument();
    expect(screen.getByText('화자 2')).toBeInTheDocument();
  });

  it('groups consecutive same-speaker subtitles', async () => {
    setupMocks({ noSummary: true });
    render(<MinutesPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('minutes-content')).toBeInTheDocument();
    });

    // 화자 1의 두 자막이 합쳐져야 함
    expect(screen.getByText('안녕하세요. 오늘 회의를 시작하겠습니다.')).toBeInTheDocument();
  });

  it('shows empty state when no subtitles', async () => {
    setupMocks({ noSummary: true, noSubtitles: true });
    render(<MinutesPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByText('자막 데이터가 없습니다. STT를 먼저 실행해주세요.')).toBeInTheDocument();
    });
  });

  it('switches to summary tab', async () => {
    setupMocks();
    const user = userEvent.setup();
    render(<MinutesPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('minutes-page')).toBeInTheDocument();
    });

    await user.click(screen.getByTestId('tab-summary'));
    expect(screen.getByTestId('summary-content')).toBeInTheDocument();
    expect(screen.getByText('테스트 회의 요약입니다.')).toBeInTheDocument();
  });

  it('switches to agenda tab and shows agenda items', async () => {
    setupMocks();
    const user = userEvent.setup();
    render(<MinutesPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('minutes-page')).toBeInTheDocument();
    });

    await user.click(screen.getByTestId('tab-agenda'));
    expect(screen.getByTestId('agenda-content')).toBeInTheDocument();

    // 안건별 API 로딩 후 아코디언 표시
    await waitFor(() => {
      expect(screen.getByText(/안건 1/)).toBeInTheDocument();
      expect(screen.getByText(/안건 2/)).toBeInTheDocument();
    });
  });

  it('renders AI summary generation button', async () => {
    setupMocks({ noSummary: true });
    render(<MinutesPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('generate-summary-button')).toBeInTheDocument();
    });
  });

  it('renders PDF export button', async () => {
    setupMocks({ noSummary: true });
    render(<MinutesPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('export-pdf-button')).toBeInTheDocument();
    });
  });

  it('shows error state on API failure', async () => {
    mockApiClient.mockRejectedValue(new Error('Network error'));
    render(<MinutesPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('page-error')).toBeInTheDocument();
    });
  });

  describe('전자회의록 미리보기·편집 버튼', () => {
    it('로그인 + AI 자막이 있으면 버튼이 노출되고 클릭 시 모달이 열린다', async () => {
      mockAuthUser = { id: 'u1', username: 'admin', role: 'admin' };
      setupMocks({ noSummary: true, aiKind: true });
      const user = userEvent.setup();
      render(<MinutesPage params={defaultParams} />);

      await waitFor(() => {
        expect(screen.getByTestId('minutes-page')).toBeInTheDocument();
      });

      const button = screen.getByTestId('minutes-preview-button');
      expect(button).toBeInTheDocument();

      await user.click(button);
      expect(
        screen.getByRole('dialog', { name: '전자회의록 미리보기·편집' })
      ).toBeInTheDocument();
      await waitFor(() => {
        expect(mockGetMinutesMarkdown).toHaveBeenCalledWith('meeting-1');
      });
    });

    it('비로그인 시 버튼이 노출되지 않는다', async () => {
      mockAuthUser = null;
      setupMocks({ noSummary: true, aiKind: true });
      render(<MinutesPage params={defaultParams} />);

      await waitFor(() => {
        expect(screen.getByTestId('minutes-page')).toBeInTheDocument();
      });

      expect(screen.queryByTestId('minutes-preview-button')).toBeNull();
    });

    it('AI 자막이 없으면(kind_counts.ai=0) 로그인해도 버튼이 노출되지 않는다', async () => {
      mockAuthUser = { id: 'u1', username: 'admin', role: 'admin' };
      setupMocks({ noSummary: true });
      render(<MinutesPage params={defaultParams} />);

      await waitFor(() => {
        expect(screen.getByTestId('minutes-page')).toBeInTheDocument();
      });

      expect(screen.queryByTestId('minutes-preview-button')).toBeNull();
    });
  });

  it('shows key decisions and action items in summary', async () => {
    setupMocks();
    const user = userEvent.setup();
    render(<MinutesPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('minutes-page')).toBeInTheDocument();
    });

    await user.click(screen.getByTestId('tab-summary'));
    expect(screen.getByText('결정 1')).toBeInTheDocument();
    expect(screen.getByText('조치 1')).toBeInTheDocument();
  });
});
