import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { ChannelType } from '@/types';

import AdminPage from '../page';

jest.mock('@/lib/api', () => ({
  API_BASE_URL: 'http://localhost:8000',
  getStatsOverview: jest.fn().mockResolvedValue({
    total_meetings: 0,
    total_subtitles: 0,
    total_duration: 0,
    average_confidence: 0,
  }),
  getStatsSpeakers: jest.fn().mockResolvedValue([]),
  getStatsMeetings: jest.fn().mockResolvedValue([]),
  getStatsReport: jest.fn().mockResolvedValue(undefined),
}));

const mockFetch = jest.fn();

function createResponse(
  data: unknown,
  options: { ok?: boolean; status?: number; text?: string } = {}
) {
  return {
    ok: options.ok ?? true,
    status: options.status ?? 200,
    json: async () => data,
    text: async () => options.text ?? '',
  };
}

describe('AdminPage', () => {
  const channels: ChannelType[] = [
    {
      id: 'ch1',
      name: '본회의',
      code: 'A001',
      stream_url: 'https://example.com/ch1.m3u8',
      livestatus: 1,
      stt_running: true,
      has_schedule: true,
      session_no: 388,
      session_order: 1,
    },
    {
      id: 'ch2',
      name: '예산심사위',
      code: 'B002',
      stream_url: 'https://example.com/ch2.m3u8',
      livestatus: 1,
      stt_running: false,
      has_schedule: false,
    },
    {
      id: 'ch3',
      name: '상임위',
      code: 'C003',
      stream_url: 'https://example.com/ch3.m3u8',
      livestatus: 2,
      stt_running: true,
    },
  ];

  beforeEach(() => {
    jest.clearAllMocks();
    (global as typeof globalThis).fetch = mockFetch as typeof fetch;
  });

  it('renders diagnostics and summary stats', async () => {
    mockFetch
      .mockResolvedValueOnce(createResponse({ status: 'healthy' }))
      .mockResolvedValueOnce(createResponse(channels));

    render(<AdminPage />);

    await waitFor(() => {
      expect(screen.getByTestId('admin-kpi-api')).toHaveTextContent('healthy');
    });

    expect(screen.getByTestId('admin-kpi-channels')).toHaveTextContent('3개');
    expect(screen.getByTestId('admin-kpi-onair')).toHaveTextContent('2개');
    expect(screen.getByTestId('admin-kpi-stt')).toHaveTextContent('2개');
    // 개선안 2i: 개수만 알리던 경고에 채널 이름과 '채널 열기' 를 붙였다
    expect(screen.getByText(/방송중이지만 STT가 비활성인 채널이/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '채널 열기' })).toBeInTheDocument();
    const actionLinks = screen.getAllByRole('link');
    expect(actionLinks.find((link) => link.getAttribute('href') === '/live')).not.toBeNull();
    expect(actionLinks.find((link) => link.getAttribute('href') === '/bills')).not.toBeNull();
  });

  it('shows unhealthy state when channel status API fails', async () => {
    mockFetch
      .mockResolvedValueOnce(createResponse({ status: 'healthy' }))
      .mockResolvedValueOnce(createResponse([], { ok: false, status: 500 }));

    render(<AdminPage />);

    await waitFor(() => {
      expect(screen.getByTestId('admin-kpi-api')).toHaveTextContent('HTTP 오류: 200/500');
    });

    expect(screen.getByTestId('admin-kpi-channels')).toHaveTextContent('0개');
    expect(screen.getByTestId('admin-kpi-onair')).toHaveTextContent('0개');
  });

  it('handles network errors with message', async () => {
    mockFetch.mockRejectedValueOnce(new Error('network down'));

    render(<AdminPage />);

    await waitFor(() => {
      expect(screen.getByText('오류: network down')).toBeInTheDocument();
    });

    expect(screen.getByTestId('admin-kpi-api')).toHaveTextContent('API 요청 실패');
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it('re-runs diagnostics when clicking the button', async () => {
    const user = userEvent.setup();

    mockFetch
      .mockResolvedValue(createResponse({ status: 'healthy' }))
      .mockResolvedValue(createResponse(channels));

    render(<AdminPage />);

    const refreshButton = await screen.findByRole('button', { name: '시스템 점검' });
    await user.click(refreshButton);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(4);
    });
  });
});
