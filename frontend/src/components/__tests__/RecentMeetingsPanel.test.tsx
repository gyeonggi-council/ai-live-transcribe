import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { MeetingType } from '@/types';

import NotificationOptInBanner from '../NotificationOptInBanner';
import RecentMeetingsPanel from '../RecentMeetingsPanel';

jest.mock('next/link', () => {
  const MockLink = ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>{children}</a>
  );
  MockLink.displayName = 'MockLink';
  return MockLink;
});

function meeting(overrides: Partial<MeetingType> & { id: string }): MeetingType {
  return {
    title: '제392회 제1차 의회운영위원회 [2026-07-22]',
    meeting_date: '2026-07-22',
    stream_url: null,
    vod_url: 'https://kms.ggc.go.kr/mp4//mp4media2/bon/bon_392_1.mp4',
    status: 'ended',
    duration_seconds: 14942,
    committee: '의회운영위원회',
    kms_no: 4479,
    created_at: '2026-07-22T00:00:00Z',
    updated_at: '2026-07-22T00:00:00Z',
    ...overrides,
  };
}

describe('RecentMeetingsPanel', () => {
  it('shows the newest meetings first, limited to the initial count', () => {
    render(
      <RecentMeetingsPanel
        meetings={[
          meeting({ id: 'a', meeting_date: '2026-07-20', title: '오래된 회의 [2026-07-20]' }),
          meeting({ id: 'b', meeting_date: '2026-07-23', title: '최신 회의 [2026-07-23]' }),
          meeting({ id: 'c', meeting_date: '2026-07-22', title: '중간 회의 [2026-07-22]' }),
          meeting({ id: 'd', meeting_date: '2026-07-19', title: '더 오래된 회의 [2026-07-19]' }),
        ]}
      />
    );

    const items = within(screen.getByTestId('recent-meeting-list')).getAllByRole('listitem');
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent('최신 회의');
    expect(items[2]).toHaveTextContent('오래된 회의');
    expect(screen.queryByText('더 오래된 회의')).not.toBeInTheDocument();
  });

  it('strips the bracketed date from the title and shows date + duration', () => {
    render(<RecentMeetingsPanel meetings={[meeting({ id: 'a' })]} />);

    expect(screen.getByText('제392회 제1차 의회운영위원회')).toBeInTheDocument();
    // 14942초 = 4시간 9분
    expect(screen.getByText(/2026\. 7\. 22 \(수\)/)).toHaveTextContent('4시간 9분');
  });

  it('expands and collapses with the 더 보기 button', async () => {
    const user = userEvent.setup();
    render(
      <RecentMeetingsPanel
        meetings={Array.from({ length: 5 }, (_, i) =>
          meeting({ id: `m${i}`, meeting_date: `2026-07-2${i}`, title: `회의 ${i}` })
        )}
      />
    );

    expect(within(screen.getByTestId('recent-meeting-list')).getAllByRole('listitem')).toHaveLength(3);

    await user.click(screen.getByTestId('recent-meetings-toggle'));
    expect(within(screen.getByTestId('recent-meeting-list')).getAllByRole('listitem')).toHaveLength(5);

    await user.click(screen.getByTestId('recent-meetings-toggle'));
    expect(within(screen.getByTestId('recent-meeting-list')).getAllByRole('listitem')).toHaveLength(3);
  });

  it('hides the toggle when everything already fits', () => {
    render(<RecentMeetingsPanel meetings={[meeting({ id: 'a' })]} />);

    expect(screen.queryByTestId('recent-meetings-toggle')).not.toBeInTheDocument();
  });

  it('falls back to a placeholder when the meeting has no video', () => {
    const { container } = render(
      <RecentMeetingsPanel meetings={[meeting({ id: 'a', vod_url: null })]} />
    );

    expect(container.querySelector('video')).toBeNull();
    // 자리표시에는 위원회명이 들어간다
    expect(screen.getAllByText('의회운영위원회').length).toBeGreaterThan(0);
  });

  it('shows loading, error and empty states', () => {
    const { rerender } = render(<RecentMeetingsPanel meetings={[]} isLoading />);
    expect(screen.getByText('로딩 중...')).toBeInTheDocument();

    rerender(<RecentMeetingsPanel meetings={[]} hasError />);
    expect(screen.getByText('데이터를 불러오지 못했습니다.')).toBeInTheDocument();

    rerender(<RecentMeetingsPanel meetings={[]} />);
    expect(screen.getByText('등록된 회의가 없습니다')).toBeInTheDocument();
  });
});

describe('NotificationOptInBanner', () => {
  const originalNotification = (window as unknown as { Notification?: unknown }).Notification;

  function stubPermission(permission: NotificationPermission, requestPermission = jest.fn()) {
    Object.defineProperty(window, 'Notification', {
      configurable: true,
      writable: true,
      value: { permission, requestPermission },
    });
  }

  afterEach(() => {
    Object.defineProperty(window, 'Notification', {
      configurable: true,
      writable: true,
      value: originalNotification,
    });
  });

  it('asks for permission only while it is undecided', () => {
    stubPermission('default');
    const { unmount } = render(<NotificationOptInBanner />);
    expect(screen.getByTestId('notification-optin-banner')).toBeInTheDocument();
    unmount();

    stubPermission('granted');
    render(<NotificationOptInBanner />);
    expect(screen.queryByTestId('notification-optin-banner')).not.toBeInTheDocument();
  });

  it('requests the browser permission and disappears once granted', async () => {
    const user = userEvent.setup();
    const requestPermission = jest.fn().mockResolvedValue('granted' as NotificationPermission);
    stubPermission('default', requestPermission);

    render(<NotificationOptInBanner />);
    await user.click(screen.getByRole('button', { name: '알림을 허용' }));

    expect(requestPermission).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('notification-optin-banner')).not.toBeInTheDocument();
  });
});
