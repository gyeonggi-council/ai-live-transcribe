import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { MeetingType } from '@/types';

import RecentVodList from '../RecentVodList';

// Mock next/navigation
const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
  }),
}));

describe('RecentVodList', () => {
  const mockVodList: MeetingType[] = [
    {
      id: 'vod-1',
      title: '제122회 본회의',
      meeting_date: '2026-02-04',
      stream_url: null,
      vod_url: 'https://vod.example.com/122',
      status: 'ended',
      duration_seconds: 5400,
      created_at: '2026-02-04T09:00:00Z',
      updated_at: '2026-02-04T11:30:00Z',
    },
    {
      id: 'vod-2',
      title: '제121회 상임위원회',
      meeting_date: '2026-02-03',
      stream_url: null,
      vod_url: 'https://vod.example.com/121',
      status: 'processing',
      duration_seconds: 7200,
      created_at: '2026-02-03T09:00:00Z',
      updated_at: '2026-02-03T11:00:00Z',
    },
    {
      id: 'vod-3',
      title: '제120회 예산결산위원회',
      meeting_date: '2026-02-02',
      stream_url: null,
      vod_url: 'https://vod.example.com/120',
      status: 'ended',
      duration_seconds: 9000,
      created_at: '2026-02-02T09:00:00Z',
      updated_at: '2026-02-02T11:30:00Z',
    },
  ];

  beforeEach(() => {
    mockPush.mockClear();
  });

  describe('when VOD list has items', () => {
    it('renders all VOD items', () => {
      render(<RecentVodList vods={mockVodList} />);

      expect(screen.getAllByText('제122회 본회의').length).toBeGreaterThan(0);
      expect(screen.getAllByText('제121회 상임위원회').length).toBeGreaterThan(0);
      expect(screen.getAllByText('제120회 예산결산위원회').length).toBeGreaterThan(0);
    });

    it('displays the meeting date for each item', () => {
      render(<RecentVodList vods={mockVodList} />);

      expect(screen.getAllByText(/2026\.02\.04/).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/2026\.02\.03/).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/2026\.02\.02/).length).toBeGreaterThan(0);
    });

    it('displays the correct status badge for ended VOD', () => {
      render(<RecentVodList vods={mockVodList} />);

      const completedBadges = screen.getAllByText('자막완료');
      expect(completedBadges.length).toBeGreaterThanOrEqual(1);
    });

    it('displays the correct status badge for processing VOD', () => {
      render(<RecentVodList vods={mockVodList} />);

      expect(screen.getAllByText('자막생성중').length).toBeGreaterThan(0);
    });

    it('displays a localized status for scheduled/live items', () => {
      const mixedStatusList: MeetingType[] = [
        {
          ...mockVodList[0],
          id: 'vod-scheduled',
          title: '예정된 회의',
          status: 'scheduled',
        },
        {
          ...mockVodList[1],
          id: 'vod-live',
          title: '진행 중 회의',
          status: 'live',
        },
      ];

      render(<RecentVodList vods={mixedStatusList} />);

      expect(screen.getAllByText('대기중').length).toBeGreaterThan(0);
      expect(screen.getAllByText('진행중').length).toBeGreaterThan(0);
    });

    it('navigates to /vod/:id when item is clicked', async () => {
      const user = userEvent.setup();
      render(<RecentVodList vods={mockVodList} />);

      const firstItem = screen.getAllByText('제122회 본회의')[0]!;
      await user.click(firstItem);

      expect(mockPush).toHaveBeenCalledWith('/vod/vod-1');
    });

    it('displays duration in human-readable format', () => {
      render(<RecentVodList vods={mockVodList} />);

      // 5400 seconds = 01:30:00
      expect(screen.getByText('01:30:00')).toBeInTheDocument();
      // 7200 seconds = 02:00:00
      expect(screen.getByText('02:00:00')).toBeInTheDocument();
    });
  });

  describe('when VOD list is empty', () => {
    it('displays empty state message', () => {
      render(<RecentVodList vods={[]} />);

      expect(screen.getByText('등록된 회의가 없습니다')).toBeInTheDocument();
    });

    it('does not render any table rows', () => {
      render(<RecentVodList vods={[]} />);

      expect(screen.queryByRole('row')).not.toBeInTheDocument();
    });
  });

  describe('styling and accessibility', () => {
    it('has a proper section heading', () => {
      render(<RecentVodList vods={mockVodList} />);

      const heading = screen.getByRole('heading', { name: /최근 회의/i });
      expect(heading).toBeInTheDocument();
    });

    it('renders items as table rows', () => {
      render(<RecentVodList vods={mockVodList} />);

      const table = screen.getByRole('table');
      expect(table).toBeInTheDocument();

      // thead row + 3 data rows = 4 total
      const rows = screen.getAllByRole('row');
      expect(rows).toHaveLength(4);
    });

    it('accepts additional className prop', () => {
      const { container } = render(
        <RecentVodList vods={mockVodList} className="custom-class" />
      );

      const section = container.firstChild;
      expect(section).toHaveClass('custom-class');
    });

    it('renders table column headers', () => {
      render(<RecentVodList vods={mockVodList} />);

      expect(screen.getByText('날짜')).toBeInTheDocument();
      expect(screen.getByText('회의명')).toBeInTheDocument();
      expect(screen.getByText('시간')).toBeInTheDocument();
      expect(screen.getByText('상태')).toBeInTheDocument();
    });
  });
});
