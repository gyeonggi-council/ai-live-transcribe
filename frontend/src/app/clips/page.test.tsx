import { render, screen, waitFor } from '@testing-library/react';

import ClipsPage from './page';

const mockReplace = jest.fn();
let mockSearchParams = new URLSearchParams();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ replace: mockReplace, push: jest.fn() }),
  useSearchParams: () => mockSearchParams,
  usePathname: () => '/clips',
}));

let mockUser: { role: string; username: string; display_name: string } | null;
jest.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ user: mockUser, loading: false, error: null, login: jest.fn(), pinLogin: jest.fn(), logout: jest.fn() }),
}));

const mockResolve = jest.fn();
jest.mock('@/lib/api', () => ({
  __esModule: true,
  API_BASE_URL: 'http://localhost:8000',
  apiClient: jest.fn(),
  resolveMeetingByMidx: (...args: unknown[]) => mockResolve(...args),
}));
jest.mock('@/hooks/useClipIndex', () => ({
  useClipIndex: () => ({ index: null, isLoading: false, error: null, offset: 0, setOffset: jest.fn(), shift: 0, refresh: jest.fn() }),
}));
jest.mock('@/hooks/useVodList', () => ({
  useVodList: () => ({ vods: [], isLoading: false, error: null, total: 0, page: 1, perPage: 100, hasNext: false, totalPages: 1, mutate: jest.fn() }),
}));

describe('/clips 워크벤치 페이지', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockSearchParams = new URLSearchParams();
    mockUser = { role: 'staff', username: 'staff1', display_name: '정책지원관' };
  });

  it('회의를 고르기 전에는 안내 문구와 회의 목록', () => {
    render(<ClipsPage />);
    expect(screen.getByTestId('clip-workbench')).toBeInTheDocument();
    expect(screen.getByTestId('clip-meeting-list')).toBeInTheDocument();
    expect(screen.getByText(/왼쪽 회의 목록을 클릭하면/)).toBeInTheDocument();
  });

  it('?midx= 는 회의 ID 로 바꿔 replace 한다 (옛 추출기 링크 회수)', async () => {
    mockSearchParams = new URLSearchParams('midx=138155');
    mockResolve.mockResolvedValue({ meeting_id: 'm-1', title: 'x' });
    render(<ClipsPage />);
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/clips?meeting=m-1'));
    expect(mockResolve).toHaveBeenCalledWith('138155');
  });

  it('midx 를 못 찾으면 안내를 띄우고 목록에서 고르게 한다', async () => {
    mockSearchParams = new URLSearchParams('midx=1');
    mockResolve.mockRejectedValue(new Error('이 영상 번호로 등록된 회의가 아직 없습니다.'));
    render(<ClipsPage />);
    expect(await screen.findByTestId('resolve-error')).toHaveTextContent('등록된 회의가 아직 없습니다');
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it('권한이 없으면 로그인 안내', () => {
    mockUser = null;
    render(<ClipsPage />);
    expect(screen.getByText(/로그인이 필요합니다/)).toBeInTheDocument();
  });
});
