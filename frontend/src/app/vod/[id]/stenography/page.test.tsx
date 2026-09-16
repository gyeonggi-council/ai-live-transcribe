import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import StenographyPage from './page';

import type {
  MeetingType,
  StenographyComparison,
  StenographyRecord,
} from '../../../../types';

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

const mockApiClient = jest.fn();
const mockGetStenographyRecords = jest.fn();
const mockCreateStenographyRecord = jest.fn();
const mockUpdateStenographyRecord = jest.fn();
const mockDeleteStenographyRecord = jest.fn();
const mockCompareStenography = jest.fn();

jest.mock('../../../../lib/api', () => ({
  __esModule: true,
  apiClient: (...args: unknown[]) => mockApiClient(...args),
  getStenographyRecords: (...args: unknown[]) => mockGetStenographyRecords(...args),
  createStenographyRecord: (...args: unknown[]) => mockCreateStenographyRecord(...args),
  updateStenographyRecord: (...args: unknown[]) => mockUpdateStenographyRecord(...args),
  deleteStenographyRecord: (...args: unknown[]) => mockDeleteStenographyRecord(...args),
  compareStenography: (...args: unknown[]) => mockCompareStenography(...args),
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

const mockRecords: StenographyRecord[] = [
  {
    id: 'record-1',
    meeting_id: 'meeting-1',
    content: '속기록 내용 1',
    stenographer_name: '홍길동',
    status: 'draft',
    file_path: null,
    filename: null,
    file_size: null,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
  {
    id: 'record-2',
    meeting_id: 'meeting-1',
    content: '속기록 내용 2',
    stenographer_name: '김철수',
    status: 'submitted',
    file_path: '/files/record2.txt',
    filename: 'record2.txt',
    file_size: 1024,
    created_at: '2024-01-02T00:00:00Z',
    updated_at: '2024-01-02T00:00:00Z',
  },
];

const mockComparison: StenographyComparison = {
  stenography_lines: ['속기록 1번째 줄', '속기록 2번째 줄'],
  subtitle_texts: ['STT 자막 1', 'STT 자막 2'],
  total_steno_lines: 2,
  total_subtitle_count: 2,
};

function setupMocks(options?: { noRecords?: boolean }) {
  mockApiClient.mockImplementation((url: string) => {
    if (url.includes('/meetings/')) {
      return Promise.resolve(mockMeeting);
    }
    return Promise.reject(new Error('Not found'));
  });
  mockGetStenographyRecords.mockResolvedValue(options?.noRecords ? [] : mockRecords);
  mockCreateStenographyRecord.mockResolvedValue(mockRecords[0]);
  mockUpdateStenographyRecord.mockResolvedValue({ ...mockRecords[0], status: 'submitted' });
  mockDeleteStenographyRecord.mockResolvedValue(undefined);
  mockCompareStenography.mockResolvedValue(mockComparison);
}

describe('StenographyPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders loading state initially', () => {
    mockApiClient.mockReturnValue(new Promise(() => {}));
    mockGetStenographyRecords.mockReturnValue(new Promise(() => {}));
    render(<StenographyPage params={defaultParams} />);
    expect(screen.getByTestId('page-loading')).toBeInTheDocument();
  });

  it('renders stenography page with records', async () => {
    setupMocks();
    render(<StenographyPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('stenography-page')).toBeInTheDocument();
    });

    expect(screen.getByText('제1회 테스트 회의')).toBeInTheDocument();
    expect(screen.getByText('홍길동')).toBeInTheDocument();
    expect(screen.getByText('김철수')).toBeInTheDocument();
  });

  it('shows empty state when no records', async () => {
    setupMocks({ noRecords: true });
    render(<StenographyPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByText('등록된 속기록이 없습니다.')).toBeInTheDocument();
    });
  });

  it('opens form modal when add button is clicked', async () => {
    setupMocks();
    const user = userEvent.setup();
    render(<StenographyPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('stenography-page')).toBeInTheDocument();
    });

    await user.click(screen.getByTestId('add-record-button'));
    expect(screen.getAllByText('속기록 등록').length).toBeGreaterThan(0);
    expect(screen.getByTestId('stenographer-name-input')).toBeInTheDocument();
  });

  it('shows comparison modal when compare button is clicked', async () => {
    setupMocks();
    const user = userEvent.setup();
    render(<StenographyPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('stenography-page')).toBeInTheDocument();
    });

    await user.click(screen.getByTestId('compare-button-record-1'));

    await waitFor(() => {
      expect(screen.getByText('속기록-STT 자막 비교')).toBeInTheDocument();
    });

    expect(screen.getByText('속기록 1번째 줄')).toBeInTheDocument();
    expect(screen.getByText('STT 자막 1')).toBeInTheDocument();
  });

  it('changes status when dropdown is changed', async () => {
    setupMocks();
    const user = userEvent.setup();
    render(<StenographyPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('stenography-page')).toBeInTheDocument();
    });

    const statusSelect = screen.getByTestId('status-select-record-1') as HTMLSelectElement;
    await user.selectOptions(statusSelect, 'submitted');

    await waitFor(() => {
      expect(mockUpdateStenographyRecord).toHaveBeenCalledWith('meeting-1', 'record-1', { status: 'submitted' });
    });
  });

  it('shows error state on API failure', async () => {
    mockApiClient.mockRejectedValue(new Error('Network error'));
    mockGetStenographyRecords.mockRejectedValue(new Error('Network error'));
    render(<StenographyPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('page-error')).toBeInTheDocument();
    });
  });

  it('displays stenography list with records', async () => {
    setupMocks();
    render(<StenographyPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('stenography-list')).toBeInTheDocument();
    });

    expect(screen.getByText('속기록 내용 1')).toBeInTheDocument();
    expect(screen.getByText('속기록 내용 2')).toBeInTheDocument();
  });

  it('shows form with submit button', async () => {
    setupMocks();
    const user = userEvent.setup();
    render(<StenographyPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('stenography-page')).toBeInTheDocument();
    });

    await user.click(screen.getByTestId('add-record-button'));

    expect(screen.getByTestId('submit-button')).toBeInTheDocument();
    expect(screen.getByTestId('content-input')).toBeInTheDocument();
    expect(screen.getByTestId('file-input')).toBeInTheDocument();
  });
});
