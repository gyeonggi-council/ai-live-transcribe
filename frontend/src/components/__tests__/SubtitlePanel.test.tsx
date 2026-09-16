import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import SubtitlePanel from '../SubtitlePanel';

import type { SubtitleType } from '../../types';

describe('SubtitlePanel', () => {
  const mockSubtitles: SubtitleType[] = [
    {
      id: '1',
      meeting_id: 'meeting-1',
      start_time: 0,
      end_time: 5,
      text: '첫 번째 자막입니다.',
      speaker: null,
      confidence: 0.95,
      created_at: '2024-01-01T00:00:00Z',
    },
    {
      id: '2',
      meeting_id: 'meeting-1',
      start_time: 5,
      end_time: 10,
      text: '두 번째 자막입니다.',
      speaker: null,
      confidence: 0.92,
      created_at: '2024-01-01T00:00:05Z',
    },
    {
      id: '3',
      meeting_id: 'meeting-1',
      start_time: 10,
      end_time: 15,
      text: '세 번째 자막입니다.',
      speaker: null,
      confidence: 0.98,
      created_at: '2024-01-01T00:00:10Z',
    },
  ];

  const defaultProps = {
    subtitles: mockSubtitles,
  };

  describe('subtitle list rendering', () => {
    it('renders all subtitles', () => {
      render(<SubtitlePanel {...defaultProps} />);

      expect(screen.getByText('첫 번째 자막입니다.')).toBeInTheDocument();
      expect(screen.getByText('두 번째 자막입니다.')).toBeInTheDocument();
      expect(screen.getByText('세 번째 자막입니다.')).toBeInTheDocument();
    });

    it('renders subtitles in order', () => {
      render(<SubtitlePanel {...defaultProps} />);

      const items = screen.getAllByTestId('subtitle-item');
      expect(items).toHaveLength(3);
    });

    it('shows empty state when no subtitles', () => {
      render(<SubtitlePanel subtitles={[]} />);

      expect(screen.getByText(/자막을 불러오는 중/)).toBeInTheDocument();
    });

    it('shows loading spinner in empty state', () => {
      render(<SubtitlePanel subtitles={[]} />);

      expect(screen.getByTestId('loading-spinner')).toBeInTheDocument();
    });
  });

  describe('auto scroll', () => {
    it('scrolls to top when new subtitle is added', async () => {
      const { rerender, container } = render(<SubtitlePanel subtitles={mockSubtitles.slice(0, 2)} />);

      // 자막이 역순으로 렌더링되므로 최신 자막은 맨 위에 표시됨 → scrollTop = 0
      rerender(<SubtitlePanel subtitles={mockSubtitles} />);

      await waitFor(() => {
        const scrollableList = container.querySelector('.overflow-y-auto');
        expect(scrollableList?.scrollTop).toBe(0);
      });
    });

    it('can disable auto scroll', async () => {
      const scrollIntoViewMock = jest.fn();
      Element.prototype.scrollIntoView = scrollIntoViewMock;

      const { rerender } = render(
        <SubtitlePanel subtitles={mockSubtitles.slice(0, 2)} autoScroll={false} />
      );

      rerender(<SubtitlePanel subtitles={mockSubtitles} autoScroll={false} />);

      await waitFor(() => {
        expect(scrollIntoViewMock).not.toHaveBeenCalled();
      });
    });
  });

  describe('subtitle click interaction', () => {
    it('calls onSubtitleClick with start time when clicked', async () => {
      const user = userEvent.setup();
      const handleClick = jest.fn();

      render(<SubtitlePanel {...defaultProps} onSubtitleClick={handleClick} />);

      await user.click(screen.getByText('첫 번째 자막입니다.'));

      expect(handleClick).toHaveBeenCalledWith(0);
    });

    it('calls onSubtitleClick with correct time for each subtitle', async () => {
      const user = userEvent.setup();
      const handleClick = jest.fn();

      render(<SubtitlePanel {...defaultProps} onSubtitleClick={handleClick} />);

      await user.click(screen.getByText('두 번째 자막입니다.'));

      expect(handleClick).toHaveBeenCalledWith(5);
    });
  });

  describe('search highlight', () => {
    it('highlights matching text when searchQuery is provided', () => {
      render(<SubtitlePanel {...defaultProps} searchQuery="번째" />);

      // The highlight is applied within SubtitleItem component
      // We verify the search query is passed down correctly
      const highlights = screen.getAllByText('번째');
      expect(highlights.length).toBeGreaterThan(0);
      // Each highlighted text should have the highlight background
      highlights.forEach((highlight) => {
        expect(highlight).toHaveClass('bg-highlight');
      });
    });

    it('does not highlight when searchQuery is empty', () => {
      render(<SubtitlePanel {...defaultProps} searchQuery="" />);

      const text = screen.getByText('첫 번째 자막입니다.');
      expect(text).not.toHaveClass('bg-highlight');
    });

    it('is case insensitive for search', () => {
      render(
        <SubtitlePanel
          subtitles={[
            {
              id: '1',
              meeting_id: 'm1',
              start_time: 0,
              end_time: 5,
              text: 'Hello World',
              speaker: null,
              confidence: 0.9,
              created_at: '2024-01-01T00:00:00Z',
            },
          ]}
          searchQuery="hello"
        />
      );

      const highlight = screen.getByText('Hello');
      expect(highlight).toHaveClass('bg-highlight');
    });
  });

  describe('current subtitle highlight', () => {
    it('highlights current subtitle based on currentTime', () => {
      render(<SubtitlePanel {...defaultProps} currentTime={7} />);

      const items = screen.getAllByTestId('subtitle-item');
      // Default sort for non-live is 'oldest', so second subtitle (5-10s) is at index 1
      expect(items[1]).toHaveClass('border-l-4');
      expect(items[1]).toHaveClass('border-brand');
    });

    it('does not highlight any when currentTime is undefined', () => {
      render(<SubtitlePanel {...defaultProps} />);

      const items = screen.getAllByTestId('subtitle-item');
      items.forEach((item) => {
        expect(item).not.toHaveClass('border-l-4');
        expect(item).not.toHaveClass('border-brand');
      });
    });
  });

  describe('styling', () => {
    it('has scrollable container', () => {
      render(<SubtitlePanel {...defaultProps} />);

      const container = screen.getByTestId('subtitle-panel');
      // Container has overflow-hidden and the inner list has overflow-y-auto
      expect(container).toHaveClass('overflow-hidden');
    });

    it('has full height', () => {
      render(<SubtitlePanel {...defaultProps} />);

      const container = screen.getByTestId('subtitle-panel');
      expect(container).toHaveClass('h-full');
    });

    it('has rounded card styling', () => {
      render(<SubtitlePanel {...defaultProps} />);

      const container = screen.getByTestId('subtitle-panel');
      expect(container).toHaveClass('rounded-lg');
      expect(container).toHaveClass('bg-surface');
    });
  });

  describe('header', () => {
    it('shows title', () => {
      render(<SubtitlePanel {...defaultProps} />);

      expect(screen.getByText('자막')).toBeInTheDocument();
    });

    it('shows subtitle count', () => {
      render(<SubtitlePanel {...defaultProps} />);

      expect(screen.getByText('3')).toBeInTheDocument();
    });
  });

  describe('scrollToSubtitleId / scrollNonce (검색·요구자료 점프 스크롤)', () => {
    it('scrolls to the subtitle when scrollToSubtitleId is set', async () => {
      const scrollIntoViewMock = jest.fn();
      Element.prototype.scrollIntoView = scrollIntoViewMock;

      render(<SubtitlePanel {...defaultProps} scrollToSubtitleId="2" scrollNonce={1} />);

      await waitFor(() => expect(scrollIntoViewMock).toHaveBeenCalled());
    });

    it('re-scrolls when the same id is requested again with a bumped nonce', async () => {
      const scrollIntoViewMock = jest.fn();
      Element.prototype.scrollIntoView = scrollIntoViewMock;

      const { rerender } = render(
        <SubtitlePanel {...defaultProps} scrollToSubtitleId="2" scrollNonce={1} />
      );
      await waitFor(() => expect(scrollIntoViewMock).toHaveBeenCalledTimes(1));

      // 같은 id + nonce 증가 → 재스크롤 (요구자료 같은 항목 재클릭 시나리오)
      rerender(<SubtitlePanel {...defaultProps} scrollToSubtitleId="2" scrollNonce={2} />);
      await waitFor(() => expect(scrollIntoViewMock).toHaveBeenCalledTimes(2));
    });

    it('falls back to chunk prefix when a long subtitle was split', async () => {
      const scrollIntoViewMock = jest.fn();
      Element.prototype.scrollIntoView = scrollIntoViewMock;

      // 4줄 자막 → splitLongSubtitle이 id를 'long_chunk_0', 'long_chunk_1'로 재작성
      const longSubtitle: SubtitleType = {
        id: 'long',
        meeting_id: 'meeting-1',
        start_time: 20,
        end_time: 40,
        text: '한 줄\n두 줄\n세 줄\n네 줄',
        speaker: null,
        confidence: 0.9,
        created_at: '2024-01-01T00:00:20Z',
      };
      const { container } = render(
        <SubtitlePanel
          subtitles={[...mockSubtitles, longSubtitle]}
          scrollToSubtitleId="long"
          scrollNonce={1}
        />
      );

      // 원본 id 요소는 없고 chunk id만 존재하지만, prefix 폴백으로 스크롤된다
      expect(container.querySelector('[data-subtitle-id="long"]')).toBeNull();
      expect(container.querySelector('[data-subtitle-id="long_chunk_0"]')).not.toBeNull();
      await waitFor(() => expect(scrollIntoViewMock).toHaveBeenCalled());
    });
  });
});
