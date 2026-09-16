import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { MeetingType, StatsOverviewType } from '@/types';

import DashboardWorkQueue from '../DashboardWorkQueue';


jest.mock('next/link', () => {
  const MockLink = ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>{children}</a>
  );
  MockLink.displayName = 'MockNextLink';
  return MockLink;
});

const makeMeeting = (overrides: Partial<MeetingType> = {}): MeetingType => ({
  id: 'test-1',
  title: '제388회 본회의',
  meeting_date: '2026-03-01',
  stream_url: null,
  vod_url: null,
  status: 'processing',
  duration_seconds: 3600,
  created_at: '2026-03-01T00:00:00Z',
  updated_at: '2026-03-01T00:00:00Z',
  ...overrides,
});

const defaultStats: StatsOverviewType = {
  total_meetings: 42,
  total_subtitles: 1234,
  total_duration: 457200, // 127 hours
  average_confidence: 0.952,
};

const defaultProps = {
  processingVods: [] as MeetingType[],
  draftMeetings: [] as MeetingType[],
  statsOverview: defaultStats,
  kpiLoading: false,
  kpiError: '',
  onRetryKpi: jest.fn(),
};

describe('DashboardWorkQueue', () => {
  it('shows empty state when no processing VODs', () => {
    render(<DashboardWorkQueue {...defaultProps} />);
    expect(screen.getByText('대기 중인 VOD가 없습니다')).toBeInTheDocument();
  });

  it('renders processing VODs with links', () => {
    const vods = [
      makeMeeting({ id: 'v1', title: '건설위 1차', status: 'processing' }),
    ];
    render(<DashboardWorkQueue {...defaultProps} processingVods={vods} />);

    expect(screen.getByText('건설위 1차')).toBeInTheDocument();
    expect(screen.getByText('1건')).toBeInTheDocument();
    const link = screen.getByText('건설위 1차').closest('a');
    expect(link).toHaveAttribute('href', '/vod/v1');
  });

  it('renders draft meetings with verify links', () => {
    const drafts = [
      makeMeeting({ id: 'm1', title: '환경위 3차', status: 'ended', transcript_status: 'draft' }),
    ];
    render(<DashboardWorkQueue {...defaultProps} draftMeetings={drafts} />);

    expect(screen.getByText('환경위 3차')).toBeInTheDocument();
    const link = screen.getByText('환경위 3차').closest('a');
    expect(link).toHaveAttribute('href', '/vod/m1/verify');
  });

  it('shows KPI stats', () => {
    render(<DashboardWorkQueue {...defaultProps} />);

    expect(screen.getByText('42건')).toBeInTheDocument();
    expect(screen.getByText('1,234개')).toBeInTheDocument();
    expect(screen.getByText('127시간')).toBeInTheDocument();
    expect(screen.getByText('95.2%')).toBeInTheDocument();
  });

  it('shows loading placeholders for KPI', () => {
    render(<DashboardWorkQueue {...defaultProps} kpiLoading={true} />);

    const dashes = screen.getAllByText('-');
    expect(dashes.length).toBe(4);
  });

  it('shows KPI error and retry button', async () => {
    const user = userEvent.setup();
    const onRetry = jest.fn();

    render(
      <DashboardWorkQueue
        {...defaultProps}
        kpiError="운영 지표를 불러오지 못했습니다."
        onRetryKpi={onRetry}
      />
    );

    expect(screen.getByText('운영 지표를 불러오지 못했습니다.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('shows empty state for draft meetings', () => {
    render(<DashboardWorkQueue {...defaultProps} />);
    expect(screen.getByText('검증 대기 건이 없습니다')).toBeInTheDocument();
  });
});
