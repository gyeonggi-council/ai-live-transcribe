import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { getAccessStats } from '@/lib/api';
import type { AccessStatsType } from '@/types';

import VisitsPage from './page';

jest.mock('@/lib/api', () => ({
  __esModule: true,
  getAccessStats: jest.fn(),
  recordAccess: jest.fn().mockResolvedValue(undefined),
}));

const mockStats = getAccessStats as jest.Mock;

function stats(overrides: Partial<AccessStatsType> = {}): AccessStatsType {
  return {
    days: 30,
    from: '2026-08-18',
    to: '2026-09-16',
    site: null,
    today: { visitors: 656, page_views: 900, watch_seconds: 7200 },
    now_watching: 12,
    totals: {
      visitors: 1200,
      page_views: 3000,
      watch_seconds: 360000,
      avg_daily_visitors: 40,
      login_prompts: 7,
    },
    daily: [
      { date: '2026-09-15', visitors: 500, page_views: 900, watch_seconds: 3600, login_prompts: 0 },
      { date: '2026-09-16', visitors: 656, page_views: 1000, watch_seconds: 7200, login_prompts: 7 },
    ],
    sites: [
      { label: '외부', visitors: 900, page_views: 2000, watch_seconds: 300000, login_prompts: 0, share: 75 },
      { label: '무선인터넷', visitors: 300, page_views: 1000, watch_seconds: 60000, login_prompts: 0, share: 25 },
    ],
    hourly: Array.from({ length: 24 }, (_, hour) => ({ hour, visitors: hour === 10 ? 80 : 5 })),
    weekday_hour: Array.from({ length: 7 }, () => Array.from({ length: 24 }, () => 3)),
    features: [
      { kind: 'page', label: '화면 열람', events: 3000, visitors: 1200 },
      { kind: 'search', label: '자막 검색', events: 120, visitors: 60 },
    ],
    devices: [
      { device: 'pc', visitors: 800 },
      { device: 'mobile', visitors: 400 },
    ],
    meetings: [
      {
        meeting_id: '70ebdfbb-b7eb-48a0-82c5-6c9993d68c5e',
        title: '제393회 제4차 예산결산특별위원회',
        meeting_date: '2026-09-16',
        viewers: 120,
        watch_seconds: 180000,
      },
    ],
    insights: ['접속이 가장 몰리는 때는 10시 무렵입니다.'],
    detail_since: '2026-09-16',
    ...overrides,
  };
}

describe('/visits 접속 통계', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockStats.mockResolvedValue(stats());
  });

  it('오늘·지금 보는 중·앱 로그인 안내를 한눈 카드로 보여준다', async () => {
    render(<VisitsPage />);

    await screen.findByTestId('visits-page');
    await waitFor(() => expect(screen.getByTestId('stat-today')).toHaveTextContent('656명'));
    expect(screen.getByTestId('stat-now-watching')).toHaveTextContent('12명');
    expect(screen.getByTestId('stat-login-prompt')).toHaveTextContent('7회');
    expect(screen.getByTestId('stat-watch')).toHaveTextContent('2.0시간');
    expect(screen.getByTestId('insights')).toHaveTextContent('10시');
  });

  it('접속처·회의·기능 목록을 그린다', async () => {
    render(<VisitsPage />);

    await waitFor(() => expect(screen.getByTestId('site-외부')).toBeInTheDocument());
    expect(screen.getByTestId('site-외부')).toHaveTextContent('900명 · 75%');
    expect(screen.getAllByTestId('meeting-row')).toHaveLength(1);
    expect(screen.getAllByTestId('feature-row')).toHaveLength(2);
    expect(screen.getByText('제393회 제4차 예산결산특별위원회')).toHaveAttribute(
      'href',
      '/vod/70ebdfbb-b7eb-48a0-82c5-6c9993d68c5e'
    );
  });

  it('접속처를 누르면 그 접속처만 다시 불러 상세를 펼친다 (드릴다운)', async () => {
    render(<VisitsPage />);

    const row = await screen.findByTestId('site-무선인터넷');
    expect(screen.queryByTestId('site-detail')).not.toBeInTheDocument();

    mockStats.mockResolvedValueOnce(stats({ site: '무선인터넷' }));
    fireEvent.click(row);

    await waitFor(() => expect(screen.getByTestId('site-detail')).toBeInTheDocument());
    expect(mockStats).toHaveBeenLastCalledWith(30, '무선인터넷');
    expect(row).toHaveAttribute('aria-expanded', 'true');
  });

  it('기간을 바꾸면 그 기간으로 다시 부른다', async () => {
    render(<VisitsPage />);

    await screen.findByTestId('period-7');
    fireEvent.click(screen.getByTestId('period-7'));

    await waitFor(() => expect(mockStats).toHaveBeenLastCalledWith(7));
  });

  it('IP 를 저장하지 않는다는 안내를 항상 보여준다', async () => {
    render(<VisitsPage />);

    const note = await screen.findByTestId('privacy-note');
    expect(note).toHaveTextContent('IP 주소는 저장하지 않습니다');
    expect(note).toHaveTextContent('2026-09-16부터');
  });

  it('기록이 없으면 빈 안내를 보여준다', async () => {
    mockStats.mockResolvedValue(
      stats({ sites: [], meetings: [], features: [], devices: [], insights: [] })
    );
    render(<VisitsPage />);

    await waitFor(() => expect(screen.getAllByText('아직 쌓인 기록이 없습니다.').length).toBeGreaterThan(0));
  });

  it('불러오기에 실패하면 이유를 보여준다', async () => {
    mockStats.mockRejectedValue(new Error('서버 점검 중'));
    render(<VisitsPage />);

    await waitFor(() => expect(screen.getByText(/서버 점검 중/)).toBeInTheDocument());
  });
});
