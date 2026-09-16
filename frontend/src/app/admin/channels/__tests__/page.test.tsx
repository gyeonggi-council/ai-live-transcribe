/**
 * 채널 관리 화면 (2026-09-16)
 *
 * 확인하는 것은 셋이다: 목록이 보이는가 · 자동 찾기 결과에서 저장이 되는가 ·
 * **못 찾았을 때 다음 할 일이 보이는가**(그냥 '실패' 로 끝나면 담당자가 막힌다).
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import AdminChannelsPage from '../page';

jest.mock('@/components/RoleGuard', () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

jest.mock('@/lib/api', () => ({
  listAdminChannels: jest.fn(),
  listCouncilPresets: jest.fn(),
  discoverChannels: jest.fn(),
  createAdminChannel: jest.fn(),
  createAdminChannelsBulk: jest.fn(),
  updateAdminChannel: jest.fn(),
  deleteAdminChannel: jest.fn(),
  probeAdminChannel: jest.fn(),
}));

const api = jest.requireMock('@/lib/api');

const CHANNEL = {
  id: 'ch14', name: '본회의', code: 'A011',
  stream_url: 'https://cdn.example/live/ch14/playlist.m3u8',
  committee: null, page_url: null, status_provider: 'ggc',
  manual_status: null, manual_until: null, sort_order: 10,
  is_active: true, is_test: false,
};

beforeEach(() => {
  jest.clearAllMocks();
  api.listAdminChannels.mockResolvedValue({ items: [CHANNEL], snapshot: {} });
  api.listCouncilPresets.mockResolvedValue({
    councils: [
      { name: '경기도의회', region: '광역', homepage: 'https://www.ggc.go.kr/',
        live_page: 'https://live.ggc.go.kr/onair/onair.do', vendor: 'webpot', note: '' },
    ],
    generated_at: '2026-09-16',
  });
});

it('등록된 채널을 보여준다', async () => {
  render(<AdminChannelsPage />);
  expect(await screen.findByText('본회의')).toBeInTheDocument();
  expect(screen.getByText('ch14')).toBeInTheDocument();
});

it('의회를 고르면 생중계 페이지 주소가 채워진다', async () => {
  const user = userEvent.setup();
  render(<AdminChannelsPage />);
  await screen.findByText('본회의');

  await user.selectOptions(screen.getByLabelText('의회 고르기'), '경기도의회');

  expect(screen.getByDisplayValue('https://live.ggc.go.kr/onair/onair.do')).toBeInTheDocument();
});

it('자동 찾기 결과에서 확인된 후보만 기본 선택되고 저장된다', async () => {
  const user = userEvent.setup();
  api.discoverChannels.mockResolvedValue({
    page_url: 'https://live.example/onair', vendor: 'webpot', warnings: [],
    fetched: [{ url: 'https://live.example/onair', status: 200 }],
    candidates: [
      { suggested_id: 'ch7', name: '안전행정위원회', m3u8_url: 'https://cdn.example/live/ch7/playlist.m3u8',
        code: '', confidence: 0.9, evidence: '', verified: true, http_status: 200 },
      { suggested_id: 'ch9', name: 'ch9', m3u8_url: 'https://cdn.example/live/ch9/playlist.m3u8',
        code: '', confidence: 0.7, evidence: '', verified: null, http_status: null },
    ],
  });
  api.createAdminChannelsBulk.mockResolvedValue({ created: ['ch7'], skipped: [], errors: [] });

  render(<AdminChannelsPage />);
  await screen.findByText('본회의');

  await user.type(screen.getByPlaceholderText(/onair/), 'https://live.example/onair');
  await user.click(screen.getByRole('button', { name: '채널 자동 찾기' }));

  await screen.findByTestId('discover-result');
  expect((screen.getByLabelText('안전행정위원회 선택') as HTMLInputElement).checked).toBe(true);
  expect((screen.getByLabelText('ch9 선택') as HTMLInputElement).checked).toBe(false);

  await user.click(screen.getByRole('button', { name: '선택한 채널 등록' }));

  await waitFor(() => expect(api.createAdminChannelsBulk).toHaveBeenCalled());
  const [items] = api.createAdminChannelsBulk.mock.calls[0];
  expect(items).toEqual([
    expect.objectContaining({ id: 'ch7', stream_url: 'https://cdn.example/live/ch7/playlist.m3u8' }),
  ]);
});

it('못 찾으면 무엇을 읽었는지와 직접 입력 길을 보여준다', async () => {
  const user = userEvent.setup();
  api.discoverChannels.mockResolvedValue({
    page_url: 'https://live.example/x', vendor: 'cast-do', candidates: [],
    warnings: ['이 페이지에서 영상 주소를 찾지 못했습니다. 대부분의 의회 생중계는 **방송 중일 때만** 드러납니다.'],
    fetched: [{ url: 'https://live.example/x', status: 200 }],
  });

  render(<AdminChannelsPage />);
  await screen.findByText('본회의');
  await user.type(screen.getByPlaceholderText(/onair/), 'https://live.example/x');
  await user.click(screen.getByRole('button', { name: '채널 자동 찾기' }));

  await screen.findByTestId('discover-result');
  expect(screen.getByText(/방송 중일 때만/)).toBeInTheDocument();
  expect(screen.getByText(/무엇을 읽었는지 보기/)).toBeInTheDocument();
  expect(screen.getByTestId('manual-card')).toBeInTheDocument();
});
