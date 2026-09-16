import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import SubtitleItem from '../SubtitleItem';

describe('SubtitleItem', () => {
  const defaultProps = {
    startTime: 3661.5, // 1:01:01.5
    text: 'Test subtitle text',
  };

  describe('time formatting', () => {
    it('formats time as HH:MM:SS', () => {
      render(<SubtitleItem {...defaultProps} />);

      expect(screen.getByText('01:01:01')).toBeInTheDocument();
    });

    it('formats time correctly for hours < 10', () => {
      render(<SubtitleItem startTime={3600} text="Text" />);

      expect(screen.getByText('01:00:00')).toBeInTheDocument();
    });

    it('formats time correctly when no hours', () => {
      render(<SubtitleItem startTime={65} text="Text" />);

      expect(screen.getByText('00:01:05')).toBeInTheDocument();
    });

    it('uses monospace font for time', () => {
      render(<SubtitleItem {...defaultProps} />);

      const timeChip = screen.getByTestId('time-chip');
      expect(timeChip).toHaveClass('font-mono');
    });
  });

  describe('text display', () => {
    it('displays the subtitle text', () => {
      render(<SubtitleItem {...defaultProps} />);

      expect(screen.getByText('Test subtitle text')).toBeInTheDocument();
    });
  });

  describe('current highlight', () => {
    it('highlights when isCurrent is true', () => {
      render(<SubtitleItem {...defaultProps} isCurrent />);

      const item = screen.getByTestId('subtitle-item');
      expect(item).toHaveClass('border-l-4');
      expect(item).toHaveClass('border-brand');
    });

    it('does not highlight when isCurrent is false', () => {
      render(<SubtitleItem {...defaultProps} isCurrent={false} />);

      const item = screen.getByTestId('subtitle-item');
      expect(item).not.toHaveClass('border-l-4');
      expect(item).not.toHaveClass('border-brand');
    });
  });

  describe('keyword highlight', () => {
    it('highlights matching keywords', () => {
      render(<SubtitleItem {...defaultProps} highlightQuery="subtitle" />);

      const highlight = screen.getByText('subtitle');
      expect(highlight).toHaveClass('bg-highlight');
    });

    it('is case insensitive when highlighting', () => {
      render(<SubtitleItem {...defaultProps} highlightQuery="TEST" />);

      const highlight = screen.getByText('Test');
      expect(highlight).toHaveClass('bg-highlight');
    });

    it('highlights multiple occurrences', () => {
      render(<SubtitleItem startTime={0} text="test one test two" highlightQuery="test" />);

      const highlights = screen.getAllByText('test');
      expect(highlights).toHaveLength(2);
      highlights.forEach((el) => {
        expect(el).toHaveClass('bg-highlight');
      });
    });
  });

  describe('click interaction', () => {
    it('calls onClick with startTime when clicked', async () => {
      const user = userEvent.setup();
      const handleClick = jest.fn();

      render(<SubtitleItem {...defaultProps} onClick={handleClick} />);

      await user.click(screen.getByTestId('subtitle-item'));

      expect(handleClick).toHaveBeenCalledWith(3661.5);
    });

    it('has hover styles', () => {
      render(<SubtitleItem {...defaultProps} />);

      const item = screen.getByTestId('subtitle-item');
      expect(item).toHaveClass('hover:bg-surface-raised');
    });
  });

  describe('copy button', () => {
    const mockWriteText = jest.fn().mockResolvedValue(undefined);

    beforeEach(() => {
      Object.defineProperty(navigator, 'clipboard', {
        value: { writeText: mockWriteText },
        writable: true,
        configurable: true,
      });
      mockWriteText.mockClear();
    });

    it('shows copy button on hover', () => {
      render(<SubtitleItem {...defaultProps} />);
      const copyBtn = screen.getByTestId('copy-button');
      expect(copyBtn).toBeInTheDocument();
      expect(copyBtn).toHaveClass('opacity-0', 'group-hover:opacity-100');
    });

    it('copies text to clipboard when clicked', () => {
      const handleClick = jest.fn();
      render(<SubtitleItem {...defaultProps} onClick={handleClick} />);

      fireEvent.click(screen.getByTestId('copy-button'));

      expect(mockWriteText).toHaveBeenCalledWith('Test subtitle text');
      // Should NOT trigger the parent onClick (seek)
      expect(handleClick).not.toHaveBeenCalled();
    });
  });

  describe('correction state', () => {
    const getTextWrapper = () => {
      const el = document.querySelector('[data-correction-state]');
      return el;
    };

    it('shows spinner and "교정 중" label when pending', () => {
      render(<SubtitleItem {...defaultProps} correctionState="pending" />);

      const spinner = screen.getByTestId('correction-spinner');
      expect(spinner).toBeInTheDocument();

      const label = screen.getByTestId('correction-label');
      expect(label).toHaveTextContent('교정 중');

      const wrapper = getTextWrapper();
      expect(wrapper).toHaveAttribute('data-correction-state', 'pending');
      expect(wrapper).toHaveClass('text-text-muted');
    });

    it('shows checkmark and "교정됨" label when corrected', () => {
      render(<SubtitleItem {...defaultProps} correctionState="corrected" />);

      const check = screen.getByTestId('correction-check');
      expect(check).toBeInTheDocument();
      expect(check).toHaveTextContent('\u2713');

      const label = screen.getByTestId('correction-label');
      expect(label).toHaveTextContent('교정됨');
    });

    it('shows no animation when none', () => {
      render(<SubtitleItem {...defaultProps} correctionState="none" />);

      expect(screen.queryByTestId('correction-spinner')).not.toBeInTheDocument();

      const wrapper = getTextWrapper();
      expect(wrapper).not.toHaveClass('animate-shimmer');
      expect(wrapper).not.toHaveClass('animate-text-flash');
    });

    it('shows no animation when correctionState is undefined', () => {
      render(<SubtitleItem {...defaultProps} />);

      expect(screen.queryByTestId('correction-spinner')).not.toBeInTheDocument();

      const wrapper = getTextWrapper();
      expect(wrapper).toHaveAttribute('data-correction-state', 'none');
      expect(wrapper).not.toHaveClass('animate-shimmer');
      expect(wrapper).not.toHaveClass('animate-text-flash');
    });

    it('shows only corrected text when corrected with originalText', () => {
      render(
        <SubtitleItem
          startTime={0}
          text="교정된 텍스트입니다"
          correctionState="corrected"
          originalText="원본 텍스트입니다"
        />
      );

      // 보정 전 원본은 표시하지 않음
      expect(screen.queryByTestId('original-text')).not.toBeInTheDocument();
      // 보정 후 텍스트만 표시
      expect(screen.getByText('교정된 텍스트입니다')).toBeInTheDocument();
    });
  });

  describe('styling', () => {
    it('has correct base styles', () => {
      render(<SubtitleItem {...defaultProps} />);

      const item = screen.getByTestId('subtitle-item');
      expect(item).toHaveClass('px-4');
      expect(item).toHaveClass('py-3');
      expect(item).toHaveClass('border-b');
      expect(item).toHaveClass('cursor-pointer');
    });

    it('time chip has interactive styling', () => {
      render(<SubtitleItem {...defaultProps} />);

      const timeChip = screen.getByTestId('time-chip');
      expect(timeChip).toHaveClass('text-brand');
      expect(timeChip).toHaveClass('bg-brand/10');
      expect(timeChip).toHaveClass('rounded');
    });

    it('text has dark color', () => {
      render(<SubtitleItem {...defaultProps} />);

      const text = screen.getByText('Test subtitle text');
      expect(text.parentElement).toHaveClass('text-text');
    });
  });
  describe('구간 음성 재생 표시', () => {
    // 화면에 '지금 이 구간이 들리는 중'이 보여야 한다 — 재생은 소리만 나고
    // 목록은 그대로라, 표시가 없으면 어느 줄을 눌렀는지 알 수 없다(2026-09-01 요청).
    it('재생 중이 아니면 ▶ 를 보여준다', () => {
      render(<SubtitleItem {...defaultProps} onPlayAudio={jest.fn()} />);

      const chip = screen.getByTestId('time-chip');
      expect(chip).toHaveTextContent('▶');
      expect(chip).not.toHaveAttribute('data-playing');
      expect(chip).toHaveAttribute('aria-pressed', 'false');
      expect(chip).toHaveAttribute('title', '이 구간 음성 듣기');
    });

    it('재생 중이면 ■ 와 "재생 중"을 보여주고 강조한다', () => {
      render(<SubtitleItem {...defaultProps} onPlayAudio={jest.fn()} isPlayingAudio />);

      const chip = screen.getByTestId('time-chip');
      expect(chip).toHaveTextContent('■');
      expect(chip).toHaveTextContent('재생 중');
      expect(chip).toHaveAttribute('data-playing', 'true');
      expect(chip).toHaveAttribute('aria-pressed', 'true');
      expect(chip).toHaveAttribute('title', '재생 중 — 누르면 멈춥니다');
      expect(chip).toHaveClass('bg-brand');
    });

    it('시간 칩을 눌러도 자막 항목 클릭(시점 이동)은 일어나지 않는다', () => {
      const onPlayAudio = jest.fn();
      const onClick = jest.fn();
      render(
        <SubtitleItem {...defaultProps} onClick={onClick} onPlayAudio={onPlayAudio} />
      );

      fireEvent.click(screen.getByTestId('time-chip'));

      expect(onPlayAudio).toHaveBeenCalledTimes(1);
      expect(onClick).not.toHaveBeenCalled();
    });
  });
});
