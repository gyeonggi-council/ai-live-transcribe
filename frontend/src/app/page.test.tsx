import { render, screen } from '@testing-library/react';

import Home from './page';

jest.mock('next/link', () => {
  const MockLink = ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>{children}</a>
  );
  MockLink.displayName = 'MockLink';
  return MockLink;
});

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn() }),
}));

jest.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: null,
    loading: false,
    error: null,
    login: jest.fn(),
    logout: jest.fn(),
  }),
}));

const mockUseChannelStatus = jest.fn();
const mockUseRecentVods = jest.fn();

jest.mock('@/hooks', () => ({
  useChannelStatus: (...args: unknown[]) => mockUseChannelStatus(...args),
  useRecentVods: (...args: unknown[]) => mockUseRecentVods(...args),
}));

jest.mock('@/lib/api', () => ({
  ApiError: class extends Error { constructor(public status: number, message: string) { super(message); } },
  apiClient: jest.fn().mockResolvedValue([]),
}));

describe('Home page', () => {
  beforeEach(() => {
    jest.clearAllMocks();

    mockUseChannelStatus.mockReturnValue({
      channels: [
        { id: 'ch1', name: '본회의장', code: 'plenary', stream_url: '', livestatus: 1 },
        { id: 'ch2', name: '건설위', code: 'construction', stream_url: '', livestatus: 0 },
      ],
      isLoading: false,
      error: null,
    });

    mockUseRecentVods.mockReturnValue({
      vods: [],
      isLoading: false,
      error: null,
      mutate: jest.fn(),
    });
  });

  it('renders the dashboard heading', () => {
    render(<Home />);
    expect(screen.getByText('대시보드')).toBeInTheDocument();
  });

  it('renders channel grid with live channel', () => {
    render(<Home />);
    expect(screen.getAllByText('본회의장').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('LIVE').length).toBeGreaterThanOrEqual(1);
  });

  it('shows live broadcast section header', () => {
    render(<Home />);
    // 2026-08-25 개선안 2d: 바깥 카드를 벗기면서 제목도 '지금 방송 중'으로 바뀌었다.
    expect(screen.getByText('지금 방송 중')).toBeInTheDocument();
  });

  it('shows empty state when no channels are live', () => {
    mockUseChannelStatus.mockReturnValue({
      channels: [
        { id: 'ch1', name: '본회의장', code: 'plenary', stream_url: '', livestatus: 0 },
      ],
      isLoading: false,
      error: null,
    });
    render(<Home />);
    expect(screen.getByText('현재 진행 중인 방송이 없습니다')).toBeInTheDocument();
  });

  it('only shows live channels, not off-air', () => {
    render(<Home />);
    // 방송중인 본회의장은 표시
    expect(screen.getByText('본회의장')).toBeInTheDocument();
    // 방송 안하는 건설위는 대시보드에 표시되지 않음
    expect(screen.queryByText('건설위')).not.toBeInTheDocument();
  });

  it('shows full channel list link', () => {
    render(<Home />);
    expect(screen.getByText(/전체 채널/)).toBeInTheDocument();
  });

  it('shows loading state for VODs', () => {
    mockUseRecentVods.mockReturnValue({
      vods: [],
      isLoading: true,
      error: null,
      mutate: jest.fn(),
    });
    render(<Home />);
    expect(screen.getByText('로딩 중...')).toBeInTheDocument();
  });

  it('shows error state for VODs', () => {
    mockUseRecentVods.mockReturnValue({
      vods: [],
      isLoading: false,
      error: new Error('fail'),
      mutate: jest.fn(),
    });
    render(<Home />);
    expect(screen.getByText('데이터를 불러오지 못했습니다.')).toBeInTheDocument();
  });
});
