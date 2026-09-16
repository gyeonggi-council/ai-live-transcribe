import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { MeetingType } from '@/types';

import VodListPage from './page';

// Mock next/navigation
const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
  }),
}));

// Mock useVodList hook
const mockUseVodList = jest.fn();
jest.mock('@/hooks/useVodList', () => ({
  useVodList: (...args: unknown[]) => mockUseVodList(...args),
}));

// Mock AuthContext — 페이지가 관리자 여부(useAuth)를 사용
jest.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ user: null, login: jest.fn(), logout: jest.fn() }),
}));

// No Header mock needed - Header removed in favor of PlatformLayout

describe('VodListPage', () => {
  // ★날짜는 현재 회기(391회 정례회, 2026-06-09~24) 안이어야 page의
  //   CURRENT_SESSION 필터를 통과해 목록에 표시된다.
  const mockVods: MeetingType[] = [
    {
      id: 'vod-1',
      title: '제391회 제1차 본회의 [2026-06-09]',
      meeting_date: '2026-06-09',
      stream_url: null,
      vod_url: 'https://vod.example.com/4419',
      status: 'ended',
      duration_seconds: 5400,
      kms_no: 4419,
      created_at: '2026-06-09T09:00:00Z',
      updated_at: '2026-06-09T11:30:00Z',
    },
    {
      id: 'vod-2',
      title: '제391회 제1차 교육기획위원회 [2026-06-10]',
      meeting_date: '2026-06-10',
      stream_url: null,
      vod_url: 'https://vod.example.com/4425',
      status: 'processing',
      duration_seconds: 7200,
      kms_no: 4425,
      created_at: '2026-06-10T09:00:00Z',
      updated_at: '2026-06-10T11:00:00Z',
    },
  ];

  beforeEach(() => {
    jest.clearAllMocks();
    mockUseVodList.mockReturnValue({
      vods: mockVods,
      isLoading: false,
      error: null,
      totalPages: 2,
      total: 15,
      page: 1,
      perPage: 10,
      hasNext: true,
      mutate: jest.fn(),
    });
  });

  describe('Page Structure', () => {
    it('renders page title', () => {
      render(<VodListPage />);

      expect(screen.getByText('회의 목록')).toBeInTheDocument();
    });

    it('renders page container', () => {
      render(<VodListPage />);

      expect(screen.getByText('회의 목록')).toBeInTheDocument();
    });
  });

  describe('Loading State', () => {
    it('shows loading indicator when data is loading', () => {
      mockUseVodList.mockReturnValue({
        vods: [],
        isLoading: true,
        error: null,
        totalPages: 0,
        total: 0,
        page: 1,
        perPage: 10,
        hasNext: false,
        mutate: jest.fn(),
      });

      render(<VodListPage />);

      // 로딩은 TableSkeleton(role=status, aria-label='테이블 로딩 중')으로 표시
      expect(screen.getByRole('status', { name: '테이블 로딩 중' })).toBeInTheDocument();
    });
  });

  describe('Error State', () => {
    it('shows error message when API fails', () => {
      mockUseVodList.mockReturnValue({
        vods: [],
        isLoading: false,
        error: new Error('Network error'),
        totalPages: 0,
        total: 0,
        page: 1,
        perPage: 10,
        hasNext: false,
        mutate: jest.fn(),
      });

      render(<VodListPage />);

      expect(screen.getByText('데이터를 불러올 수 없습니다')).toBeInTheDocument();
    });
  });

  describe('VOD Table Display', () => {
    it('renders VodTable with meeting data', () => {
      render(<VodListPage />);

      // 2026-08-22: PC 표 → 카드로 통일 (표는 더 이상 없다)
      expect(screen.getByTestId('meeting-card-list')).toBeInTheDocument();
      expect(screen.getAllByText('제391회 제1차 본회의 [2026-06-09]').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('제391회 제1차 교육기획위원회 [2026-06-10]').length).toBeGreaterThanOrEqual(1);
    });
  });

  describe('Pagination', () => {
    it('renders pagination when totalPages > 1', () => {
      render(<VodListPage />);

      expect(screen.getByRole('navigation', { name: /페이지네이션/ })).toBeInTheDocument();
    });

    it('does not render pagination when totalPages is 1', () => {
      mockUseVodList.mockReturnValue({
        vods: mockVods,
        isLoading: false,
        error: null,
        totalPages: 1,
        total: 2,
        page: 1,
        perPage: 10,
        hasNext: false,
        mutate: jest.fn(),
      });

      render(<VodListPage />);

      expect(screen.queryByRole('navigation', { name: /페이지네이션/ })).not.toBeInTheDocument();
    });

    it('calls useVodList with updated page when page changes', async () => {
      const user = userEvent.setup();
      render(<VodListPage />);

      const nextButton = screen.getByRole('button', { name: /다음/ });
      await user.click(nextButton);

      await waitFor(() => {
        expect(mockUseVodList).toHaveBeenCalledWith(
          expect.objectContaining({ page: 2 })
        );
      });
    });
  });

  describe('Empty State', () => {
    it('shows empty message when no VODs', () => {
      mockUseVodList.mockReturnValue({
        vods: [],
        isLoading: false,
        error: null,
        totalPages: 0,
        total: 0,
        page: 1,
        perPage: 10,
        hasNext: false,
        mutate: jest.fn(),
      });

      render(<VodListPage />);

      expect(screen.getByText('표시할 회의가 없습니다')).toBeInTheDocument();
    });
  });

  describe('Session Tabs (회기 탭 — 391회 이후 관리)', () => {
    const multiSessionVods: MeetingType[] = [
      ...mockVods,
      {
        id: 'vod-392',
        title: '제392회 제1차 본회의 [2026-07-07]',
        meeting_date: '2026-07-07',
        stream_url: null,
        vod_url: 'https://vod.example.com/4452',
        status: 'ended',
        duration_seconds: 3600,
        kms_no: 4452,
        created_at: '2026-07-07T09:00:00Z',
        updated_at: '2026-07-07T11:00:00Z',
      },
      {
        // 관리 시작(391회) 이전 회기 — 어떤 탭에도 나오면 안 됨
        id: 'vod-389',
        title: '제389회 제2차 본회의 [2026-04-30]',
        meeting_date: '2026-04-30',
        stream_url: null,
        vod_url: 'https://vod.example.com/4416',
        status: 'ended',
        duration_seconds: 3600,
        kms_no: 4416,
        created_at: '2026-04-30T09:00:00Z',
        updated_at: '2026-04-30T11:00:00Z',
      },
    ];

    beforeEach(() => {
      mockUseVodList.mockReturnValue({
        vods: multiSessionVods,
        isLoading: false,
        error: null,
        totalPages: 1,
        total: 4,
        page: 1,
        perPage: 200,
        hasNext: false,
        mutate: jest.fn(),
      });
    });

    it('renders session options (newest first) and defaults to the latest session', () => {
      render(<VodListPage />);

      const select = screen.getByTestId('session-select') as HTMLSelectElement;
      expect(select).toHaveValue('392');
      // 기본 선택 = 최신 회기(392) — 392 회의만 표시
      expect(screen.getAllByText('제392회 제1차 본회의 [2026-07-07]').length).toBeGreaterThanOrEqual(1);
      expect(screen.queryByText('제391회 제1차 본회의 [2026-06-09]')).not.toBeInTheDocument();
    });

    it('switches sessions when another session is selected', async () => {
      const user = userEvent.setup();
      render(<VodListPage />);

      await user.selectOptions(screen.getByTestId('session-select'), '391');

      expect(screen.getAllByText('제391회 제1차 본회의 [2026-06-09]').length).toBeGreaterThanOrEqual(1);
      expect(screen.queryByText('제392회 제1차 본회의 [2026-07-07]')).not.toBeInTheDocument();
    });

    it('shows all managed sessions (≥391) in 전체, excluding older sessions', async () => {
      const user = userEvent.setup();
      render(<VodListPage />);

      await user.selectOptions(screen.getByTestId('session-select'), 'all');

      expect(screen.getAllByText('제392회 제1차 본회의 [2026-07-07]').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('제391회 제1차 본회의 [2026-06-09]').length).toBeGreaterThanOrEqual(1);
      // 391회 이전 회기는 전체에서도 제외
      expect(screen.queryByText('제389회 제2차 본회의 [2026-04-30]')).not.toBeInTheDocument();
    });

    it('does not offer a pre-391 session option', () => {
      render(<VodListPage />);

      const select = screen.getByTestId('session-select');
      expect(within(select).queryByText(/제389회/)).not.toBeInTheDocument();
    });

    // 상태 칩(전체·실시간·VOD·AI…)은 2026-08-25 개선안 2f 에서 삭제했다 —
    // 회기·위원회 필터와 행마다의 진행 막대가 이미 같은 일을 하고 있었다.
    it('상태 칩 줄이 없다 (회기·위원회 필터와 진행 막대로 대체)', () => {
      render(<VodListPage />);

      expect(screen.queryByTestId('stage-filter-ai_done')).not.toBeInTheDocument();
      expect(screen.getByTestId('session-select')).toBeInTheDocument();
      expect(screen.getByTestId('committee-select')).toBeInTheDocument();
    });

    it('단계 이름은 목록 머리 범례에 한 번만 나온다', () => {
      render(<VodListPage />);

      const legend = screen.getByTestId('meeting-stage-legend');
      expect(within(legend).getByText('실시간')).toBeInTheDocument();
      expect(within(legend).getByText('AI 완료')).toBeInTheDocument();
      expect(within(legend).getByText('현재 단계')).toBeInTheDocument();
    });
  });
});
