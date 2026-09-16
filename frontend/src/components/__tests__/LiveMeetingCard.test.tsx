import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { MeetingType } from '@/types';

import LiveMeetingCard from '../LiveMeetingCard';

// Mock next/navigation
const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
  }),
}));

describe('LiveMeetingCard', () => {
  const mockLiveMeeting: MeetingType = {
    id: 'meeting-1',
    title: '제123회 본회의',
    meeting_date: '2026-02-05',
    stream_url: 'https://stream.example.com/live',
    vod_url: null,
    status: 'live',
    duration_seconds: null,
    created_at: '2026-02-05T09:00:00Z',
    updated_at: '2026-02-05T09:00:00Z',
  };

  beforeEach(() => {
    mockPush.mockClear();
  });

  describe('when broadcasting (live meeting exists)', () => {
    it('renders the live badge', () => {
      render(<LiveMeetingCard meeting={mockLiveMeeting} />);

      const liveBadge = screen.getByText('Live');
      expect(liveBadge).toBeInTheDocument();
    });

    it('displays the meeting title', () => {
      render(<LiveMeetingCard meeting={mockLiveMeeting} />);

      expect(screen.getByText('제123회 본회의')).toBeInTheDocument();
    });

    it('shows the "실시간 자막 보기" button', () => {
      render(<LiveMeetingCard meeting={mockLiveMeeting} />);

      const watchButton = screen.getByRole('button', { name: /실시간 자막 보기/i });
      expect(watchButton).toBeInTheDocument();
    });

    it('navigates to /live when button is clicked', async () => {
      const user = userEvent.setup();
      render(<LiveMeetingCard meeting={mockLiveMeeting} />);

      const watchButton = screen.getByRole('button', { name: /실시간 자막 보기/i });
      await user.click(watchButton);

      expect(mockPush).toHaveBeenCalledWith('/live');
    });

    it('displays the meeting date', () => {
      render(<LiveMeetingCard meeting={mockLiveMeeting} />);

      // Should show formatted date
      expect(screen.getByText(/2026년 2월 5일/)).toBeInTheDocument();
    });
  });

  describe('when no broadcast (no live meeting)', () => {
    it('displays "현재 진행 중인 회의가 없습니다" message', () => {
      render(<LiveMeetingCard meeting={null} />);

      expect(screen.getByText('현재 진행 중인 회의가 없습니다')).toBeInTheDocument();
    });

    it('does not show the live badge', () => {
      render(<LiveMeetingCard meeting={null} />);

      expect(screen.queryByText('Live')).not.toBeInTheDocument();
    });

    it('does not show the watch button', () => {
      render(<LiveMeetingCard meeting={null} />);

      expect(screen.queryByRole('button', { name: /실시간 자막 보기/i })).not.toBeInTheDocument();
    });
  });

  describe('styling and accessibility', () => {
    it('has a proper card structure with heading', () => {
      render(<LiveMeetingCard meeting={mockLiveMeeting} />);

      // Should have a heading for the section
      const heading = screen.getByRole('heading', { name: /실시간 회의/i });
      expect(heading).toBeInTheDocument();
    });

    it('accepts additional className prop', () => {
      const { container } = render(
        <LiveMeetingCard meeting={mockLiveMeeting} className="custom-class" />
      );

      const card = container.firstChild;
      expect(card).toHaveClass('custom-class');
    });
  });
});
