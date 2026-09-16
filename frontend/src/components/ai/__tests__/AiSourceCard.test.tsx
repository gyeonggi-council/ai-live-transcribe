import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import AiSourceCard, { formatSourceAt } from '../AiSourceCard';

jest.mock('next/link', () => {
  return function MockLink({ children, href }: { children: React.ReactNode; href: string }) {
    return <a href={href}>{children}</a>;
  };
});

const SRC = { meeting_id: 'm-1', meeting_title: '제393회 본회의', start_time: 5025, text_snippet: '발언', source_type: 'subtitle' as const };

describe('AiSourceCard', () => {
  it('formats HH:MM:SS', () => {
    expect(formatSourceAt(5025)).toBe('01:23:45');
  });

  it('links to the meeting at the source time', () => {
    render(<AiSourceCard source={SRC} />);
    expect(screen.getByRole('link')).toHaveAttribute('href', '/vod/m-1?t=5025');
    expect(screen.getByText('제393회 본회의')).toBeInTheDocument();
  });

  it('plays in place when onPlayAt is given', async () => {
    const onPlayAt = jest.fn();
    render(<AiSourceCard source={SRC} onPlayAt={onPlayAt} />);
    await userEvent.click(screen.getByTestId('ai-source-card'));
    expect(onPlayAt).toHaveBeenCalledWith(5025);
  });
});
