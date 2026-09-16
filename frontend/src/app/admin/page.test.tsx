import React from 'react';

import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { getStatsMeetings, getStatsOverview, getStatsSpeakers } from '@/lib/api';

import AdminPage from './page';

// Mock next/link
jest.mock('next/link', () => {
  const MockLink = ({ children, href }: { children: React.ReactNode; href: string }) => {
    return <a href={href}>{children}</a>;
  };
  MockLink.displayName = 'MockLink';
  return MockLink;
});

// Mock API functions
jest.mock('@/lib/api', () => ({
  API_BASE_URL: 'http://localhost:8000',
  getStatsOverview: jest.fn(),
  getStatsSpeakers: jest.fn(),
  getStatsMeetings: jest.fn(),
  getStatsReport: jest.fn(),
}));

describe('AdminPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    global.fetch = jest.fn();
  });

  it('renders admin page', () => {
    (getStatsOverview as jest.Mock).mockResolvedValue({
      total_meetings: 0,
      total_subtitles: 0,
      total_duration: 0,
      average_confidence: 0,
    });
    (getStatsSpeakers as jest.Mock).mockResolvedValue([]);
    (getStatsMeetings as jest.Mock).mockResolvedValue([]);

    render(<AdminPage />);
    expect(screen.getByText('시스템관리')).toBeInTheDocument();
  });

  it('renders stats overview cards', async () => {
    (getStatsOverview as jest.Mock).mockResolvedValue({
      total_meetings: 10,
      total_subtitles: 500,
      total_duration: 3600,
      average_confidence: 0.95,
    });
    (getStatsSpeakers as jest.Mock).mockResolvedValue([]);
    (getStatsMeetings as jest.Mock).mockResolvedValue([]);

    render(<AdminPage />);
    // 2026-08-25 개선안 2i: 통계·리포트는 별도 탭으로 옮겼다
    fireEvent.click(screen.getByTestId('admin-tab-stats'));

    await waitFor(() => {
      expect(screen.getByTestId('stats-overview')).toBeInTheDocument();
    });

    expect(screen.getByText('10')).toBeInTheDocument(); // total meetings
    expect(screen.getByText('500')).toBeInTheDocument(); // total subtitles
  });

  it('renders monthly meeting chart', async () => {
    (getStatsOverview as jest.Mock).mockResolvedValue({
      total_meetings: 0,
      total_subtitles: 0,
      total_duration: 0,
      average_confidence: 0,
    });
    (getStatsSpeakers as jest.Mock).mockResolvedValue([]);
    (getStatsMeetings as jest.Mock).mockResolvedValue([
      { month: '2026-01', count: 5 },
      { month: '2026-02', count: 3 },
    ]);

    render(<AdminPage />);
    // 2026-08-25 개선안 2i: 통계·리포트는 별도 탭으로 옮겼다
    fireEvent.click(screen.getByTestId('admin-tab-stats'));

    await waitFor(() => {
      expect(screen.getByTestId('stats-chart')).toBeInTheDocument();
    });

    expect(screen.getByText('2026-01')).toBeInTheDocument();
    expect(screen.getByText('2026-02')).toBeInTheDocument();
  });

  it('renders speaker ranking table', async () => {
    (getStatsOverview as jest.Mock).mockResolvedValue({
      total_meetings: 0,
      total_subtitles: 0,
      total_duration: 0,
      average_confidence: 0,
    });
    (getStatsSpeakers as jest.Mock).mockResolvedValue([
      { speaker: '화자 1', total_count: 10, total_duration: 600 },
      { speaker: '화자 2', total_count: 5, total_duration: 300 },
    ]);
    (getStatsMeetings as jest.Mock).mockResolvedValue([]);

    render(<AdminPage />);
    // 2026-08-25 개선안 2i: 통계·리포트는 별도 탭으로 옮겼다
    fireEvent.click(screen.getByTestId('admin-tab-stats'));

    await waitFor(() => {
      expect(screen.getByTestId('stats-speakers')).toBeInTheDocument();
    });

    expect(screen.getByText('1. 화자 1')).toBeInTheDocument();
    expect(screen.getByText('2. 화자 2')).toBeInTheDocument();
  });

  it('renders report export section', async () => {
    (getStatsOverview as jest.Mock).mockResolvedValue({
      total_meetings: 0,
      total_subtitles: 0,
      total_duration: 0,
      average_confidence: 0,
    });
    (getStatsSpeakers as jest.Mock).mockResolvedValue([]);
    (getStatsMeetings as jest.Mock).mockResolvedValue([]);

    render(<AdminPage />);
    // 2026-08-25 개선안 2i: 통계·리포트는 별도 탭으로 옮겼다
    fireEvent.click(screen.getByTestId('admin-tab-stats'));

    await waitFor(() => {
      expect(screen.getByText('리포트 내보내기')).toBeInTheDocument();
    });

    expect(screen.getByText('Markdown 내보내기')).toBeInTheDocument();
  });
});
