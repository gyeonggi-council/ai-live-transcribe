import { act, render, screen, waitFor } from '@testing-library/react';

import HlsPlayer from '../HlsPlayer';

// Mock HLS.js
const mockAttachMedia = jest.fn();
const mockLoadSource = jest.fn();
const mockDestroy = jest.fn();
const mockOn = jest.fn();
const mockStartLoad = jest.fn();
const mockRecoverMediaError = jest.fn();
// 생성자에 넘어간 hls.js 설정과 인스턴스 — 영상 지연 목표(liveSyncDuration)·스냅 착지 검증용
const mockConfigs: Array<Record<string, unknown>> = [];
const mockInstances: Array<{ liveSyncPosition: number }> = [];

jest.mock('hls.js', () => {
  const Events = {
    MANIFEST_PARSED: 'hlsManifestParsed',
    FRAG_BUFFERED: 'hlsFragBuffered',
    FRAG_CHANGED: 'hlsFragChanged',
    ERROR: 'hlsError',
  } as const;

  const ErrorTypes = {
    NETWORK_ERROR: 'networkError',
    MEDIA_ERROR: 'mediaError',
  } as const;

  return {
    __esModule: true,
    default: class MockHls {
      static isSupported() {
        return true;
      }
      static Events = Events;
      static ErrorTypes = ErrorTypes;
      attachMedia = mockAttachMedia;
      loadSource = mockLoadSource;
      destroy = mockDestroy;
      on = mockOn;
      startLoad = mockStartLoad;
      recoverMediaError = mockRecoverMediaError;
      liveSyncPosition = 0;
      latency = 0;
      targetLatency = 0;
      constructor(config: Record<string, unknown>) {
        mockConfigs.push(config);
        mockInstances.push(this);
      }
    },
  };
});

describe('HlsPlayer', () => {
  const defaultProps = {
    streamUrl: 'https://example.com/stream.m3u8',
  };

  beforeEach(() => {
    jest.clearAllMocks();
    // JSDOM의 HTMLMediaElement.play()는 Promise를 반환하지 않으므로 모킹 필요
    HTMLMediaElement.prototype.play = jest.fn().mockResolvedValue(undefined);
  });

  describe('rendering', () => {
    it('renders video element', () => {
      render(<HlsPlayer {...defaultProps} />);

      const video = screen.getByTestId('hls-video');
      expect(video).toBeInTheDocument();
      expect(video.tagName).toBe('VIDEO');
    });

    it('has video controls', () => {
      render(<HlsPlayer {...defaultProps} />);

      const video = screen.getByTestId('hls-video');
      expect(video).toHaveAttribute('controls');
    });

    it('renders in 16:9 aspect ratio container', () => {
      render(<HlsPlayer {...defaultProps} />);

      const container = screen.getByTestId('hls-player-container');
      expect(container).toHaveClass('aspect-video');
    });
  });

  describe('HLS initialization', () => {
    it('initializes HLS with stream URL', async () => {
      render(<HlsPlayer {...defaultProps} />);

      await waitFor(() => {
        expect(mockLoadSource).toHaveBeenCalledWith(defaultProps.streamUrl);
      });
    });

    it('attaches media to video element', async () => {
      render(<HlsPlayer {...defaultProps} />);

      await waitFor(() => {
        expect(mockAttachMedia).toHaveBeenCalled();
      });
    });

    it('destroys HLS instance on unmount', async () => {
      const { unmount } = render(<HlsPlayer {...defaultProps} />);

      // hls.js는 동적 import로 비동기 초기화됨 — 인스턴스 생성을 기다린 뒤 unmount
      await waitFor(() => {
        expect(mockLoadSource).toHaveBeenCalled();
      });

      unmount();

      await waitFor(() => {
        expect(mockDestroy).toHaveBeenCalled();
      });
    });

    it('reloads when stream URL changes', async () => {
      const { rerender } = render(<HlsPlayer streamUrl="https://example.com/stream1.m3u8" />);

      // 동적 import 초기화 완료를 기다린다 (동기 단언은 항상 0회로 실패)
      await waitFor(() => {
        expect(mockLoadSource).toHaveBeenCalledWith('https://example.com/stream1.m3u8');
      });

      rerender(<HlsPlayer streamUrl="https://example.com/stream2.m3u8" />);

      await waitFor(() => {
        expect(mockLoadSource).toHaveBeenCalledWith('https://example.com/stream2.m3u8');
      });
    });
  });

  describe('loading state', () => {
    it('shows loading spinner initially', () => {
      render(<HlsPlayer {...defaultProps} />);

      expect(screen.getByTestId('loading-spinner')).toBeInTheDocument();
    });

    it('hides loading spinner after video loads', async () => {
      render(<HlsPlayer {...defaultProps} />);

      // Simulate video loading
      const video = screen.getByTestId('hls-video') as HTMLVideoElement;

      act(() => {
        video.dispatchEvent(new Event('loadeddata'));
      });

      await waitFor(() => {
        expect(screen.queryByTestId('loading-spinner')).not.toBeInTheDocument();
      });
    });
  });

  describe('error state', () => {
    it('shows error message when stream fails', async () => {
      render(<HlsPlayer {...defaultProps} />);

      // Simulate error
      const video = screen.getByTestId('hls-video') as HTMLVideoElement;

      act(() => {
        video.dispatchEvent(new Event('error'));
      });

      await waitFor(() => {
        expect(screen.getByText(/영상을 불러올 수 없습니다/)).toBeInTheDocument();
      });
    });

    it('calls onError callback when error occurs', async () => {
      const handleError = jest.fn();
      render(<HlsPlayer {...defaultProps} onError={handleError} />);

      const video = screen.getByTestId('hls-video') as HTMLVideoElement;

      act(() => {
        video.dispatchEvent(new Event('error'));
      });

      await waitFor(() => {
        expect(handleError).toHaveBeenCalled();
      });
    });
  });

  describe('fullscreen', () => {
    it('supports fullscreen via controls', () => {
      render(<HlsPlayer {...defaultProps} />);

      const video = screen.getByTestId('hls-video') as HTMLVideoElement;
      expect(video).toHaveAttribute('controls');
    });
  });

  describe('volume control', () => {
    it('video element has controls for volume', () => {
      render(<HlsPlayer {...defaultProps} />);

      const video = screen.getByTestId('hls-video') as HTMLVideoElement;
      expect(video).toHaveAttribute('controls');
    });
  });

  describe('styling', () => {
    it('has black background', () => {
      render(<HlsPlayer {...defaultProps} />);

      const container = screen.getByTestId('hls-player-container');
      expect(container).toHaveClass('bg-black');
    });

    it('has rounded corners', () => {
      render(<HlsPlayer {...defaultProps} />);

      const container = screen.getByTestId('hls-player-container');
      expect(container).toHaveClass('rounded-lg');
    });
  });

  describe('ref forwarding', () => {
    it('forwards ref to video element', () => {
      const videoRef = { current: null };
      render(<HlsPlayer {...defaultProps} videoRef={videoRef} />);

      expect(videoRef.current).toBeInstanceOf(HTMLVideoElement);
    });
  });

  describe('HLS events', () => {
    it('calls onReady when manifest is parsed', async () => {
      const handleReady = jest.fn();

      // Capture the event handler passed to hls.on
      mockOn.mockImplementation((event, handler) => {
        if (event === 'hlsManifestParsed') {
          // Simulate manifest parsed immediately
          act(() => {
            handler();
          });
        }
      });

      render(<HlsPlayer {...defaultProps} onReady={handleReady} />);

      await waitFor(() => {
        expect(handleReady).toHaveBeenCalled();
      });
    });

    it('handles HLS fatal error', async () => {
      const handleError = jest.fn();

      mockOn.mockImplementation((event, handler) => {
        if (event === 'hlsError') {
          // 네트워크/미디어 외의 에러 타입 → default case에서 즉시 onError 호출
          act(() => {
            handler(null, { fatal: true, type: 'otherError' });
          });
        }
      });

      render(<HlsPlayer {...defaultProps} onError={handleError} />);

      await waitFor(() => {
        expect(handleError).toHaveBeenCalled();
      });
    });

    it('ignores non-fatal HLS errors', async () => {
      const handleError = jest.fn();

      mockOn.mockImplementation((event, handler) => {
        if (event === 'hlsError') {
          act(() => {
            handler(null, { fatal: false, type: 'networkError' });
          });
        }
      });

      render(<HlsPlayer {...defaultProps} onError={handleError} />);

      // Wait a bit and ensure error wasn't called
      await act(async () => {
        await new Promise((resolve) => {
          setTimeout(resolve, 100);
        });
      });
      expect(handleError).not.toHaveBeenCalled();
    });
  });

  describe('영상 지연 목표 (2026-09-14)', () => {
    const lastConfig = () => mockConfigs[mockConfigs.length - 1];

    it('syncTargetSec prop 이 liveSyncDuration 이 되고, 최대 지연은 +10, 스톨 증가는 0', async () => {
      render(<HlsPlayer {...defaultProps} syncTargetSec={14} />);
      await waitFor(() => expect(mockLoadSource).toHaveBeenCalled());
      expect(lastConfig().liveSyncDuration).toBe(14);
      expect(lastConfig().liveMaxLatencyDuration).toBe(24);
      expect(lastConfig().liveSyncOnStallIncrease).toBe(0);
    });

    it('prop 이 없으면 빌드 기본(20)', async () => {
      render(<HlsPlayer {...defaultProps} />);
      await waitFor(() => expect(mockLoadSource).toHaveBeenCalled());
      expect(lastConfig().liveSyncDuration).toBe(20);
    });

    it('prop 이 바뀌어도 hls 를 다시 만들지 않는다 (마운트 시 1회 해석)', async () => {
      const { rerender } = render(<HlsPlayer {...defaultProps} syncTargetSec={18} />);
      await waitFor(() => expect(mockLoadSource).toHaveBeenCalledTimes(1));
      rerender(<HlsPlayer {...defaultProps} syncTargetSec={14} />);
      await act(async () => {
        await new Promise((r) => setTimeout(r, 30));
      });
      expect(mockDestroy).not.toHaveBeenCalled();
      expect(mockLoadSource).toHaveBeenCalledTimes(1);
      expect(lastConfig().liveSyncDuration).toBe(18);
    });

    it('드리프트 스냅은 liveSyncPosition 에 착지한다 (−1 없음)', async () => {
      render(<HlsPlayer {...defaultProps} syncTargetSec={14} />);
      await waitFor(() => {
        expect(mockOn).toHaveBeenCalledWith('hlsFragBuffered', expect.any(Function));
      });
      const hls = mockInstances[mockInstances.length - 1];
      hls.liveSyncPosition = 100;
      const video = screen.getByTestId('hls-video') as HTMLVideoElement;
      let current = 80;
      Object.defineProperty(video, 'paused', { value: false, configurable: true });
      Object.defineProperty(video, 'currentTime', {
        get: () => current,
        set: (v: number) => {
          current = v;
        },
        configurable: true,
      });
      const call = mockOn.mock.calls.find((c) => c[0] === 'hlsFragBuffered');
      act(() => {
        (call as [string, () => void])[1]();
      });
      expect(current).toBe(100);
    });
  });
});
