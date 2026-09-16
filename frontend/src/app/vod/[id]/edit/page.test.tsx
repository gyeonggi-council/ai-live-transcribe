import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import SubtitleEditPage from './page';

import type {
  EditSession,
  MeetingType,
  SubtitleComment,
  SubtitleType,
} from '../../../../types';

const mockPush = jest.fn();
const mockBack = jest.fn();
const mockSetTitle = jest.fn();

jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
    back: mockBack,
  }),
}));

jest.mock('../../../../contexts/BreadcrumbContext', () => ({
  useBreadcrumb: () => ({
    dynamicTitle: null,
    setTitle: mockSetTitle,
  }),
}));

const mockApiClient = jest.fn();
const mockUpdateSubtitlesBatch = jest.fn();
const mockGetEditSessions = jest.fn();
const mockCreateEditSession = jest.fn();
const mockUpdateEditSession = jest.fn();
const mockDeleteEditSession = jest.fn();
const mockGetSubtitleComments = jest.fn();
const mockCreateSubtitleComment = jest.fn();
const mockToggleCommentResolved = jest.fn();

jest.mock('../../../../lib/api', () => ({
  __esModule: true,
  apiClient: (...args: unknown[]) => mockApiClient(...args),
  updateSubtitlesBatch: (...args: unknown[]) => mockUpdateSubtitlesBatch(...args),
  getEditSessions: (...args: unknown[]) => mockGetEditSessions(...args),
  createEditSession: (...args: unknown[]) => mockCreateEditSession(...args),
  updateEditSession: (...args: unknown[]) => mockUpdateEditSession(...args),
  deleteEditSession: (...args: unknown[]) => mockDeleteEditSession(...args),
  getSubtitleComments: (...args: unknown[]) => mockGetSubtitleComments(...args),
  createSubtitleComment: (...args: unknown[]) => mockCreateSubtitleComment(...args),
  toggleCommentResolved: (...args: unknown[]) => mockToggleCommentResolved(...args),
}));

jest.mock('../../../../components/Mp4Player', () => {
  function MockMp4Player({ videoRef }: { videoRef: React.RefObject<HTMLVideoElement> }) {
    return <video ref={videoRef} data-testid="mock-video" />;
  }
  MockMp4Player.displayName = 'MockMp4Player';
  return MockMp4Player;
});

jest.mock('../../../../components/VideoControls', () => {
  function MockVideoControls() {
    return <div data-testid="mock-video-controls" />;
  }
  MockVideoControls.displayName = 'MockVideoControls';
  return MockVideoControls;
});

jest.mock('../../../../components/PiiMaskButton', () => {
  function MockPiiMaskButton() {
    return <button data-testid="mock-pii-mask-button">PII Mask</button>;
  }
  MockPiiMaskButton.displayName = 'MockPiiMaskButton';
  return MockPiiMaskButton;
});

jest.mock('../../../../components/ProofreadingToolbar', () => {
  function MockProofreadingToolbar() {
    return <div data-testid="mock-proofreading-toolbar">Proofreading</div>;
  }
  MockProofreadingToolbar.displayName = 'MockProofreadingToolbar';
  return MockProofreadingToolbar;
});

jest.mock('../../../../components/SubtitleHistoryModal', () => {
  function MockSubtitleHistoryModal({ onClose }: { onClose: () => void }) {
    return (
      <div data-testid="mock-subtitle-history-modal">
        <button onClick={onClose}>Close</button>
      </div>
    );
  }
  MockSubtitleHistoryModal.displayName = 'MockSubtitleHistoryModal';
  return MockSubtitleHistoryModal;
});

jest.mock('../../../../components/TranscriptStatusBadge', () => {
  function MockTranscriptStatusBadge() {
    return <div data-testid="mock-transcript-status-badge">Status Badge</div>;
  }
  MockTranscriptStatusBadge.displayName = 'MockTranscriptStatusBadge';
  return MockTranscriptStatusBadge;
});

const defaultParams = { id: 'meeting-1' };

const mockMeeting: MeetingType = {
  id: 'meeting-1',
  title: '제1회 테스트 회의',
  meeting_date: '2024-01-01T00:00:00Z',
  stream_url: null,
  vod_url: 'https://example.com/vod.mp4',
  status: 'ended',
  duration_seconds: 3600,
  transcript_status: 'draft',
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
];

const mockEditSessions: EditSession[] = [
  {
    id: 'session-1',
    meeting_id: 'meeting-1',
    editor_name: '홍길동',
    started_at: '2024-01-01T00:00:00Z',
    last_active_at: '2024-01-01T00:05:00Z',
    status: 'active',
  },
];

const mockComments: SubtitleComment[] = [
  {
    id: 'comment-1',
    subtitle_id: 'subtitle-1',
    meeting_id: 'meeting-1',
    author_name: '검토자1',
    content: '이 부분 수정 필요',
    resolved: false,
    created_at: '2024-01-01T00:00:00Z',
  },
];

function setupMocks(options?: { noSubtitles?: boolean; noSessions?: boolean }) {
  mockApiClient.mockImplementation((url: string) => {
    if (url.includes('/subtitles')) {
      return Promise.resolve({ items: options?.noSubtitles ? [] : mockSubtitles });
    }
    return Promise.resolve(mockMeeting);
  });
  mockUpdateSubtitlesBatch.mockResolvedValue({ updated: 1, items: mockSubtitles });
  mockGetEditSessions.mockResolvedValue(options?.noSessions ? [] : mockEditSessions);
  mockCreateEditSession.mockResolvedValue(mockEditSessions[0]);
  mockUpdateEditSession.mockResolvedValue(undefined);
  mockDeleteEditSession.mockResolvedValue(undefined);
  mockGetSubtitleComments.mockResolvedValue(mockComments);
  mockCreateSubtitleComment.mockResolvedValue(mockComments[0]);
  mockToggleCommentResolved.mockResolvedValue(undefined);
}

describe('SubtitleEditPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
    // Mock scrollIntoView for JSDOM
    Element.prototype.scrollIntoView = jest.fn();
  });

  afterEach(() => {
    jest.runOnlyPendingTimers();
    jest.useRealTimers();
  });

  it('renders loading state initially', () => {
    mockApiClient.mockReturnValue(new Promise(() => {}));
    render(<SubtitleEditPage params={defaultParams} />);
    expect(screen.getByTestId('page-loading')).toBeInTheDocument();
  });

  it('renders edit page with subtitles', async () => {
    setupMocks();
    render(<SubtitleEditPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('subtitle-edit-page')).toBeInTheDocument();
    });

    expect(screen.getByText('안녕하세요.')).toBeInTheDocument();
    expect(screen.getByText('오늘 회의를 시작하겠습니다.')).toBeInTheDocument();
  });

  it('shows active editors bar', async () => {
    setupMocks();
    render(<SubtitleEditPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('active-editors')).toBeInTheDocument();
    });

    expect(screen.getByText('홍길동')).toBeInTheDocument();
  });

  it('shows empty editors when no sessions', async () => {
    setupMocks({ noSessions: true });
    render(<SubtitleEditPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('active-editors')).toBeInTheDocument();
    });

    expect(screen.getByText('없음')).toBeInTheDocument();
  });

  it('opens join modal when editor join button is clicked', async () => {
    setupMocks();
    const user = userEvent.setup({ delay: null });
    render(<SubtitleEditPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('subtitle-edit-page')).toBeInTheDocument();
    });

    await user.click(screen.getByTestId('editor-join-btn'));
    expect(screen.getByRole('heading', { name: '편집 시작' })).toBeInTheDocument();
    expect(screen.getByTestId('editor-name-input')).toBeInTheDocument();
  });

  it('shows comment icon with count badge', async () => {
    setupMocks();
    render(<SubtitleEditPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('subtitle-edit-page')).toBeInTheDocument();
    });

    const commentIcon = screen.getByTestId('comment-icon-subtitle-1');
    expect(commentIcon).toBeInTheDocument();
    expect(commentIcon.querySelector('span')).toHaveTextContent('1');
  });

  it('opens comment panel when comment icon is clicked', async () => {
    setupMocks();
    const user = userEvent.setup({ delay: null });
    render(<SubtitleEditPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('subtitle-edit-page')).toBeInTheDocument();
    });

    await user.click(screen.getByTestId('comment-icon-subtitle-1'));
    expect(screen.getByTestId('comment-panel')).toBeInTheDocument();
    expect(screen.getByText('이 부분 수정 필요')).toBeInTheDocument();
  });

  it('allows creating new comment', async () => {
    setupMocks();
    const user = userEvent.setup({ delay: null });
    render(<SubtitleEditPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('subtitle-edit-page')).toBeInTheDocument();
    });

    await user.click(screen.getByTestId('comment-icon-subtitle-1'));

    const commentInput = screen.getByTestId('comment-input');
    await user.type(commentInput, '검토자2');

    const contentInput = screen.getByPlaceholderText('코멘트 내용...');
    await user.type(contentInput, '새 코멘트');

    const submitButton = screen.getByText('코멘트 추가');
    await user.click(submitButton);

    await waitFor(() => {
      expect(mockCreateSubtitleComment).toHaveBeenCalledWith(
        'meeting-1',
        'subtitle-1',
        '검토자2',
        '새 코멘트'
      );
    });
  });

  it('shows subtitle list', async () => {
    setupMocks();
    render(<SubtitleEditPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('subtitle-list')).toBeInTheDocument();
    });

    expect(screen.getAllByRole('textbox').length).toBeGreaterThan(0);
  });

  it('shows auto-scroll toggle', async () => {
    setupMocks();
    render(<SubtitleEditPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('auto-scroll-toggle')).toBeInTheDocument();
    });
  });

  it('shows save button', async () => {
    setupMocks();
    render(<SubtitleEditPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('save-button')).toBeInTheDocument();
    });
  });
});
