import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { ChannelType, UpcomingScheduleType } from '@/types';

import ChannelSelector from '../ChannelSelector';

// 의사일정은 서버가 의회 홈페이지에서 수집한다 — 화면 테스트에서는 값만 갈아 끼운다.
let mockSchedule: UpcomingScheduleType | null = null;
jest.mock('@/hooks/useUpcomingSchedule', () => ({
  useUpcomingSchedule: () => ({ schedule: mockSchedule, isLoading: false, error: null }),
}));

beforeEach(() => {
  mockSchedule = null;
});

const SCHEDULE: UpcomingScheduleType = {
  from: '2026-09-01',
  to: '2026-09-07',
  synced_at: new Date().toISOString(),
  days: [
    {
      date: '2026-09-01',
      items: [
        {
          committee_code: 'A011',
          committee_name: '본회의',
          start_time: '11:00',
          session_no: 393,
          session_order: 1,
          session_kind: '임시회',
          agenda_items: ['제393회 임시회 회기 결정', '회의록 서명의원 선출'],
          is_cancelled: false,
          changed_at: '2026-08-31T00:00:00+00:00',
        },
      ],
    },
  ],
};

const channels: ChannelType[] = [
  {
    id: 'ch2',
    name: '상임위',
    code: 'B002',
    stream_url: 'https://example.com/ch2.m3u8',
    livestatus: 0,
    has_schedule: true,
    stt_running: true,
    session_no: 388,
    session_order: 1,
  },
  {
    id: 'ch1',
    name: '본회의',
    code: 'A001',
    stream_url: 'https://example.com/ch1.m3u8',
    livestatus: 1,
    stt_running: false,
  },
  {
    id: 'ch3',
    name: '정회중위원회',
    code: 'C003',
    stream_url: 'https://example.com/ch3.m3u8',
    livestatus: 2,
    stt_running: true,
  },
];

describe('ChannelSelector', () => {
  it('renders loading state', () => {
    render(<ChannelSelector channels={[]} isLoading={true} onSelect={jest.fn()} />);

    expect(document.querySelector('.animate-spin')).toBeInTheDocument();
  });

  /**
   * 2026-08-25 개선안 2b: 균등 격자 → 방송 중 / 오늘 예정 / 전체 채널 3단.
   * 순서는 그대로 '방송 중이 맨 위'이고, 정회중은 '오늘 예정'의 첫 줄이다.
   */
  it('방송 중 · 오늘 예정 · 전체 채널 세 단으로 나눈다', () => {
    const onSelect = jest.fn();

    render(<ChannelSelector channels={channels} isLoading={false} onSelect={onSelect} />);

    expect(screen.getByText('지금 방송 중')).toBeInTheDocument();
    expect(screen.getByText('오늘 예정')).toBeInTheDocument();
    expect(screen.getByText('전체 채널')).toBeInTheDocument();

    // 방송 중(ch1) → 오늘 예정(정회중 ch3 → 방송전 ch2) 순
    const cards = screen
      .getAllByTestId(/^channel-ch/)
      .filter((el) => el.tagName === 'BUTTON');
    expect(cards[0]).toHaveTextContent('본회의');
    expect(cards[1]).toHaveTextContent('정회중위원회');
    expect(cards[2]).toHaveTextContent('상임위');

    // 방송 중 카드에만 STT 표시가 붙는다 (예정·전체 목록에는 벨만)
    expect(screen.getByText('STT OFF')).toBeInTheDocument();
    expect(screen.getByText('정회중')).toBeInTheDocument();
    expect(screen.getByText('제388회 제1차')).toBeInTheDocument();
  });

  it('전체 채널 목록에는 방송 예정이 없는 채널도 모두 나온다', () => {
    render(<ChannelSelector channels={channels} isLoading={false} onSelect={jest.fn()} />);

    channels.forEach((ch) => {
      expect(screen.getByTestId(`channel-all-${ch.id}`)).toBeInTheDocument();
    });
  });

  it('calls onSelect when channel card is clicked', async () => {
    const user = userEvent.setup();
    const onSelect = jest.fn();

    render(<ChannelSelector channels={channels} isLoading={false} onSelect={onSelect} />);

    await user.click(screen.getByTestId('channel-ch1'));

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(channels[1]);
  });
  describe('다가오는 일정', () => {
    it('일정이 없으면 섹션 자체를 그리지 않는다 (휴회 기간에 빈 상자 금지)', () => {
      render(<ChannelSelector channels={channels} isLoading={false} onSelect={jest.fn()} />);
      expect(screen.queryByTestId('upcoming-schedule')).not.toBeInTheDocument();
    });

    it('날짜·시간·회기·안건 개수를 보여준다', () => {
      mockSchedule = SCHEDULE;
      render(<ChannelSelector channels={channels} isLoading={false} onSelect={jest.fn()} />);

      expect(screen.getByTestId('upcoming-schedule')).toBeInTheDocument();
      expect(screen.getByText('9월 1일 (화)')).toBeInTheDocument();
      expect(screen.getByText('11:00')).toBeInTheDocument();
      expect(screen.getByText('제393회 임시회 제1차')).toBeInTheDocument();
      expect(screen.getByText(/안건 2/)).toBeInTheDocument();
    });

    it('안건 목록을 함께 낸다 (펼치면 보인다)', () => {
      mockSchedule = SCHEDULE;
      render(<ChannelSelector channels={channels} isLoading={false} onSelect={jest.fn()} />);

      expect(screen.getByText('제393회 임시회 회기 결정')).toBeInTheDocument();
      expect(screen.getByText('회의록 서명의원 선출')).toBeInTheDocument();
    });

    it('취소된 회의는 지우지 않고 취소로 표시한다', () => {
      mockSchedule = {
        ...SCHEDULE,
        days: [
          {
            date: '2026-09-01',
            items: [{ ...SCHEDULE.days[0]!.items[0]!, is_cancelled: true }],
          },
        ],
      };
      render(<ChannelSelector channels={channels} isLoading={false} onSelect={jest.fn()} />);

      // 채널 목록에도 '본회의' 가 있으므로 이 섹션 안에서만 찾는다
      const row = screen.getByTestId('upcoming-item-A011');
      expect(within(row).getByText('취소')).toBeInTheDocument();
      expect(within(row).getByText('본회의')).toHaveClass('line-through');
    });

    it('마지막으로 홈페이지를 확인한 시각을 적는다 (안건은 수시로 바뀐다)', () => {
      mockSchedule = SCHEDULE;
      render(<ChannelSelector channels={channels} isLoading={false} onSelect={jest.fn()} />);

      expect(screen.getByText(/의회 홈페이지 .*확인/)).toBeInTheDocument();
    });
  });

  it('오늘 진행 중인 회기를 제목 줄에 적는다', () => {
    mockSchedule = SCHEDULE;
    render(<ChannelSelector channels={channels} isLoading={false} onSelect={jest.fn()} />);

    // channels[0] 이 has_schedule + session_no 388
    expect(screen.getByText(/제388회 .*진행 중/)).toBeInTheDocument();
  });
});
