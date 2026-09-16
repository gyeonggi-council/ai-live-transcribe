import { render, screen } from '@testing-library/react';

import type { ChannelType } from '@/types';

import DashboardChannelStrip from '../DashboardChannelStrip';


jest.mock('next/link', () => {
  const MockLink = ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>{children}</a>
  );
  MockLink.displayName = 'MockNextLink';
  return MockLink;
});

const makeChannel = (overrides: Partial<ChannelType> = {}): ChannelType => ({
  id: 'ch1',
  name: '본회의장',
  code: 'plenary',
  stream_url: 'https://example.com/stream',
  livestatus: 0,
  has_schedule: false,
  ...overrides,
});

describe('DashboardChannelStrip', () => {
  it('shows loading skeleton when isLoading is true', () => {
    render(<DashboardChannelStrip channels={[]} isLoading={true} />);
    expect(screen.getByText('채널 현황')).toBeInTheDocument();
  });

  it('shows empty message when no channels are live', () => {
    const channels = [makeChannel({ livestatus: 0 })];
    render(<DashboardChannelStrip channels={channels} isLoading={false} />);
    expect(screen.getByText('현재 방송 중인 채널이 없습니다')).toBeInTheDocument();
  });

  it('renders ON AIR channel cards', () => {
    const channels = [
      makeChannel({ id: 'ch1', name: '본회의장', livestatus: 1 }),
      makeChannel({ id: 'ch2', name: '건설위', livestatus: 0 }),
    ];
    render(<DashboardChannelStrip channels={channels} isLoading={false} />);

    expect(screen.getByText('본회의장')).toBeInTheDocument();
    expect(screen.getByText('ON AIR')).toBeInTheDocument();
    expect(screen.getByText('1개 방송중')).toBeInTheDocument();
    // OFF channel should not render as card
    expect(screen.queryByText('건설위')).not.toBeInTheDocument();
  });

  it('renders recess (정회중) channels', () => {
    const channels = [
      makeChannel({ id: 'ch1', name: '교육위', livestatus: 2 }),
    ];
    render(<DashboardChannelStrip channels={channels} isLoading={false} />);

    expect(screen.getByText('교육위')).toBeInTheDocument();
    expect(screen.getByText('정회중')).toBeInTheDocument();
  });

  it('shows rest summary counts', () => {
    const channels = [
      makeChannel({ id: 'ch1', livestatus: 0 }),
      makeChannel({ id: 'ch2', livestatus: 0 }),
      makeChannel({ id: 'ch3', livestatus: 3 }),
    ];
    render(<DashboardChannelStrip channels={channels} isLoading={false} />);

    expect(screen.getByText('방송전 2개')).toBeInTheDocument();
    expect(screen.getByText('종료 1개')).toBeInTheDocument();
  });

  it('links ON AIR channel to /live?channel={id}', () => {
    const channels = [makeChannel({ id: 'ch5', name: '환경위', livestatus: 1 })];
    render(<DashboardChannelStrip channels={channels} isLoading={false} />);

    const link = screen.getByText('환경위').closest('a');
    expect(link).toHaveAttribute('href', '/live?channel=ch5');
  });

  it('shows schedule info for channels with session data', () => {
    const channels = [
      makeChannel({
        id: 'ch1',
        name: '본회의장',
        livestatus: 1,
        has_schedule: true,
        session_no: 388,
        session_order: 1,
      }),
    ];
    render(<DashboardChannelStrip channels={channels} isLoading={false} />);
    expect(screen.getByText('제388회 제1차')).toBeInTheDocument();
  });

  it('has link to full channel list', () => {
    render(<DashboardChannelStrip channels={[]} isLoading={false} />);
    const link = screen.getByText('전체 채널 보기');
    expect(link.closest('a')).toHaveAttribute('href', '/live');
  });
});
