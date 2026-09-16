import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import ViewerTabs from '../ViewerTabs';

describe('ViewerTabs', () => {
  const tabs = [
    { key: 'subtitles', label: '실시간 자막' },
    { key: 'search', label: '검색결과', count: 12 },
    { key: 'materials', label: '요구자료', count: 25, alert: true },
  ];

  it('renders every tab with its count badge', () => {
    render(<ViewerTabs tabs={tabs} active="subtitles" onChange={jest.fn()} />);

    expect(screen.getByText('실시간 자막')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(screen.getByText('25')).toBeInTheDocument();
  });

  it('marks only the active tab as selected', () => {
    render(<ViewerTabs tabs={tabs} active="materials" onChange={jest.fn()} />);

    expect(screen.getByTestId('viewer-tab-materials')).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByTestId('viewer-tab-subtitles')).toHaveAttribute('aria-selected', 'false');
  });

  it('reports the clicked tab key', async () => {
    const user = userEvent.setup();
    const onChange = jest.fn();
    render(<ViewerTabs tabs={tabs} active="subtitles" onChange={onChange} />);

    await user.click(screen.getByTestId('viewer-tab-materials'));

    expect(onChange).toHaveBeenCalledWith('materials');
  });

  it('hides the badge when the count is zero', () => {
    render(
      <ViewerTabs
        tabs={[{ key: 'materials', label: '요구자료', count: 0 }]}
        active="materials"
        onChange={jest.fn()}
      />
    );

    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });

  /**
   * 2026-08-22: 자막 아래 '요구자료 N건 감지' 한 줄 알림을 없앴다
   * (모바일에서 자막 영역을 그만큼 잡아먹었다). 감지 사실은 이 탭 배지가 알린다.
   */
  it('flags unconfirmed items on the tab badge (하단 알림 줄의 대체물)', () => {
    render(<ViewerTabs tabs={tabs} active="subtitles" onChange={jest.fn()} />);

    const badge = screen.getByText('25');
    expect(badge).toHaveClass('text-error');
  });
});
