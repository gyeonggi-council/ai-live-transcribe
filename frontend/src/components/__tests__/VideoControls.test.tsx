import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import VideoControls from '../VideoControls';

describe('VideoControls', () => {
  let mockVideoElement: HTMLVideoElement;
  let videoRef: React.MutableRefObject<HTMLVideoElement | null>;

  function getDefaultProps(overrides?: Partial<React.ComponentProps<typeof VideoControls>>) {
    return {
      videoRef,
      currentTime: 0,
      duration: 300,
      ...overrides,
    };
  }

  beforeEach(() => {
    jest.clearAllMocks();
    mockVideoElement = document.createElement('video');
    Object.defineProperty(mockVideoElement, 'paused', { value: true, writable: true, configurable: true });
    Object.defineProperty(mockVideoElement, 'playbackRate', { value: 1, writable: true, configurable: true });
    mockVideoElement.play = jest.fn().mockResolvedValue(undefined);
    mockVideoElement.pause = jest.fn();

    videoRef = { current: mockVideoElement };
  });

  describe('rendering', () => {
    it('renders control container', () => {
      render(<VideoControls {...getDefaultProps()} />);

      expect(screen.getByTestId('video-controls')).toBeInTheDocument();
    });

    it('renders play/pause button', () => {
      render(<VideoControls {...getDefaultProps()} />);

      expect(screen.getByTestId('play-pause-button')).toBeInTheDocument();
    });

    it('renders timeline seekbar', () => {
      render(<VideoControls {...getDefaultProps()} />);

      expect(screen.getByTestId('timeline-seekbar')).toBeInTheDocument();
    });

    it('renders playback speed selector', () => {
      render(<VideoControls {...getDefaultProps()} />);

      expect(screen.getByTestId('speed-selector')).toBeInTheDocument();
    });

    it('renders time display', () => {
      render(<VideoControls {...getDefaultProps()} />);

      expect(screen.getByTestId('time-display')).toBeInTheDocument();
    });
  });

  describe('play/pause button', () => {
    it('shows play icon when video is paused', () => {
      render(<VideoControls {...getDefaultProps()} />);

      const button = screen.getByTestId('play-pause-button');
      expect(button).toHaveAttribute('aria-label', '재생');
    });

    it('calls video.play when play button is clicked', async () => {
      const user = userEvent.setup();
      render(<VideoControls {...getDefaultProps()} />);

      await user.click(screen.getByTestId('play-pause-button'));

      expect(mockVideoElement.play).toHaveBeenCalled();
    });

    it('calls video.pause when pause button is clicked', async () => {
      Object.defineProperty(mockVideoElement, 'paused', { value: false, writable: true, configurable: true });
      const user = userEvent.setup();
      render(<VideoControls {...getDefaultProps()} />);

      await user.click(screen.getByTestId('play-pause-button'));

      expect(mockVideoElement.pause).toHaveBeenCalled();
    });

    it('shows pause icon when video is playing', () => {
      Object.defineProperty(mockVideoElement, 'paused', { value: false, writable: true, configurable: true });
      render(<VideoControls {...getDefaultProps()} />);

      const button = screen.getByTestId('play-pause-button');
      expect(button).toHaveAttribute('aria-label', '일시정지');
    });
  });

  describe('timeline seekbar', () => {
    it('has correct min, max, and value attributes', () => {
      render(<VideoControls {...getDefaultProps({ currentTime: 60, duration: 300 })} />);

      const seekbar = screen.getByTestId('timeline-seekbar') as HTMLInputElement;
      expect(seekbar).toHaveAttribute('min', '0');
      expect(seekbar).toHaveAttribute('max', '300');
      expect(seekbar).toHaveValue('60');
    });

    it('seeks video when seekbar value changes', () => {
      render(<VideoControls {...getDefaultProps()} />);

      const seekbar = screen.getByTestId('timeline-seekbar');
      fireEvent.change(seekbar, { target: { value: '120' } });

      expect(mockVideoElement.currentTime).toBe(120);
    });
  });

  // 배속은 버튼 4개 → 셀렉트 1개로 접었다(모바일 컨트롤 높이/폭 축소, 2026-08-21).
  describe('playback speed', () => {
    it('shows all speed options: 0.5x, 1x, 1.5x, 2x', () => {
      render(<VideoControls {...getDefaultProps()} />);

      const select = screen.getByTestId('speed-selector');
      expect(
        Array.from(select.querySelectorAll('option')).map((o) => o.textContent)
      ).toEqual(['0.5x', '1x', '1.5x', '2x']);
    });

    it('defaults to 1x speed', () => {
      render(<VideoControls {...getDefaultProps()} />);

      expect(screen.getByTestId('speed-selector')).toHaveValue('1');
    });

    it('changes playback rate when a speed is selected', async () => {
      const user = userEvent.setup();
      render(<VideoControls {...getDefaultProps()} />);

      await user.selectOptions(screen.getByTestId('speed-selector'), '2');

      expect(mockVideoElement.playbackRate).toBe(2);
    });

    it('reflects the active speed in the selector', async () => {
      const user = userEvent.setup();
      render(<VideoControls {...getDefaultProps()} />);

      await user.selectOptions(screen.getByTestId('speed-selector'), '1.5');

      expect(screen.getByTestId('speed-selector')).toHaveValue('1.5');
    });
  });

  describe('time display', () => {
    it('displays current time and duration in mm:ss format', () => {
      render(<VideoControls {...getDefaultProps({ currentTime: 65, duration: 300 })} />);

      const timeDisplay = screen.getByTestId('time-display');
      expect(timeDisplay).toHaveTextContent('01:05');
      expect(timeDisplay).toHaveTextContent('05:00');
    });

    it('displays 00:00 when time is 0', () => {
      render(<VideoControls {...getDefaultProps({ currentTime: 0, duration: 0 })} />);

      const timeDisplay = screen.getByTestId('time-display');
      expect(timeDisplay).toHaveTextContent('00:00');
    });

    it('displays hh:mm:ss for durations over 1 hour', () => {
      render(<VideoControls {...getDefaultProps({ currentTime: 3661, duration: 7200 })} />);

      const timeDisplay = screen.getByTestId('time-display');
      expect(timeDisplay).toHaveTextContent('1:01:01');
      expect(timeDisplay).toHaveTextContent('2:00:00');
    });
  });

  describe('when videoRef is null', () => {
    it('renders without crashing', () => {
      const nullRef = { current: null };
      render(<VideoControls videoRef={nullRef} currentTime={0} duration={0} />);

      expect(screen.getByTestId('video-controls')).toBeInTheDocument();
    });

    it('play button does nothing when videoRef is null', async () => {
      const nullRef = { current: null };
      const user = userEvent.setup();
      render(<VideoControls videoRef={nullRef} currentTime={0} duration={0} />);

      // Should not throw
      await user.click(screen.getByTestId('play-pause-button'));
    });
  });
});
