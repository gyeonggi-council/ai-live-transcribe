import { render, screen, waitFor, fireEvent } from '@testing-library/react';

import Mp4Player, { toPlayableVodUrl, isHlsUrl } from '../Mp4Player';

// hls.js 동적 import 목킹 — KMS HLS 재생 분기 검증용
const mockLoadSource = jest.fn();
const mockAttachMedia = jest.fn();
const mockDestroy = jest.fn();
const mockHlsOn = jest.fn();
/** hls.js 에 넘긴 설정 — startPosition(시작 시점) 검증용 */
const mockHlsConfig = jest.fn();

jest.mock('hls.js', () => ({
  __esModule: true,
  default: class MockHls {
    static isSupported = () => true;
    static Events = { ERROR: 'hlsError' };
    constructor(config?: unknown) {
      mockHlsConfig(config);
    }
    loadSource = mockLoadSource;
    attachMedia = mockAttachMedia;
    destroy = mockDestroy;
    on = mockHlsOn;
  },
}));

describe('toPlayableVodUrl (KMS mp4 → HLS 변환, 2026-07-21 KMS 개편 대응)', () => {
  it('KMS 직접 mp4 주소를 Wowza HLS 주소로 변환한다', () => {
    expect(
      toPlayableVodUrl(
        'https://kms.ggc.go.kr/mp4//mp4media2/gyoyukhaengjeong/20260720_gyoyukhaengjeong.mp4'
      )
    ).toBe(
      'https://kms.ggc.go.kr/vod/_definst_//mp4media2/gyoyukhaengjeong/20260720_gyoyukhaengjeong.mp4/playlist.m3u8'
    );
  });

  it('KMS가 아닌 mp4 주소는 그대로 반환한다', () => {
    const url = 'https://example.com/video/some.mp4';
    expect(toPlayableVodUrl(url)).toBe(url);
  });

  it('이미 m3u8인 주소는 그대로 반환한다', () => {
    const url = 'https://kms.ggc.go.kr/vod/_definst_//a/b.mp4/playlist.m3u8';
    expect(toPlayableVodUrl(url)).toBe(url);
  });
});

describe('isHlsUrl', () => {
  it('m3u8 주소를 판별한다', () => {
    expect(isHlsUrl('https://x/y/playlist.m3u8')).toBe(true);
    expect(isHlsUrl('https://x/y/playlist.m3u8?token=1')).toBe(true);
    expect(isHlsUrl('https://x/y/video.mp4')).toBe(false);
  });
});

describe('Mp4Player HLS 분기 (KMS VOD)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('KMS mp4는 HLS로 변환해 hls.js로 재생한다 (video src 미지정)', async () => {
    render(
      <Mp4Player vodUrl="https://kms.ggc.go.kr/mp4//mp4media2/gihoek/20260720_gihoek.mp4" />
    );
    const video = screen.getByTestId('mp4-video');
    expect(video).not.toHaveAttribute('src');
    await waitFor(() => {
      expect(mockLoadSource).toHaveBeenCalledWith(
        'https://kms.ggc.go.kr/vod/_definst_//mp4media2/gihoek/20260720_gihoek.mp4/playlist.m3u8'
      );
    });
    expect(mockAttachMedia).toHaveBeenCalled();
  });

  it('startTime 을 주면 그 위치의 조각부터 받는다 (0초부터 받고 옮기지 않는다)', async () => {
    render(
      <Mp4Player
        vodUrl="https://kms.ggc.go.kr/mp4//mp4media2/gihoek/20260720_gihoek.mp4"
        startTime={517}
      />
    );
    await waitFor(() => expect(mockHlsConfig).toHaveBeenCalled());
    expect(mockHlsConfig).toHaveBeenCalledWith(
      expect.objectContaining({ startPosition: 517 })
    );
  });

  it('startTime 이 없으면 처음부터 재생한다', async () => {
    render(
      <Mp4Player vodUrl="https://kms.ggc.go.kr/mp4//mp4media2/gihoek/20260720_gihoek.mp4" />
    );
    await waitFor(() => expect(mockHlsConfig).toHaveBeenCalled());
    expect(mockHlsConfig).toHaveBeenCalledWith(
      expect.objectContaining({ startPosition: -1 })
    );
  });

  it('언마운트 시 hls 인스턴스를 정리한다', async () => {
    const { unmount } = render(
      <Mp4Player vodUrl="https://kms.ggc.go.kr/mp4//mp4media2/gihoek/20260720_gihoek.mp4" />
    );
    await waitFor(() => expect(mockAttachMedia).toHaveBeenCalled());
    unmount();
    expect(mockDestroy).toHaveBeenCalled();
  });
});

describe('Mp4Player', () => {
  const defaultProps = {
    vodUrl: 'https://example.com/video.mp4',
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('rendering', () => {
    it('renders video element', () => {
      render(<Mp4Player {...defaultProps} />);

      const video = screen.getByTestId('mp4-video');
      expect(video).toBeInTheDocument();
      expect(video.tagName).toBe('VIDEO');
    });

    it('renders container with correct test id', () => {
      render(<Mp4Player {...defaultProps} />);

      expect(screen.getByTestId('mp4-player-container')).toBeInTheDocument();
    });

    it('sets video src to vodUrl', () => {
      render(<Mp4Player {...defaultProps} />);

      const video = screen.getByTestId('mp4-video') as HTMLVideoElement;
      expect(video.src).toBe(defaultProps.vodUrl);
    });

    it('renders in 16:9 aspect ratio container', () => {
      render(<Mp4Player {...defaultProps} />);

      const container = screen.getByTestId('mp4-player-container');
      expect(container).toHaveClass('aspect-video');
    });
  });

  describe('loading state', () => {
    it('shows loading spinner initially', () => {
      render(<Mp4Player {...defaultProps} />);

      expect(screen.getByTestId('loading-spinner')).toBeInTheDocument();
    });

    it('hides loading spinner after video loads', async () => {
      render(<Mp4Player {...defaultProps} />);

      const video = screen.getByTestId('mp4-video') as HTMLVideoElement;
      fireEvent.loadedData(video);

      await waitFor(() => {
        expect(screen.queryByTestId('loading-spinner')).not.toBeInTheDocument();
      });
    });
  });

  describe('error state', () => {
    it('shows error message when video fails to load', async () => {
      render(<Mp4Player {...defaultProps} />);

      const video = screen.getByTestId('mp4-video') as HTMLVideoElement;
      fireEvent.error(video);

      await waitFor(() => {
        expect(screen.getByText(/영상을 불러올 수 없습니다/)).toBeInTheDocument();
      });
    });

    it('calls onError callback when error occurs', async () => {
      const handleError = jest.fn();
      render(<Mp4Player {...defaultProps} onError={handleError} />);

      const video = screen.getByTestId('mp4-video') as HTMLVideoElement;
      fireEvent.error(video);

      await waitFor(() => {
        expect(handleError).toHaveBeenCalled();
      });
    });
  });

  describe('callbacks', () => {
    it('calls onTimeUpdate with current time during playback', async () => {
      const handleTimeUpdate = jest.fn();
      render(<Mp4Player {...defaultProps} onTimeUpdate={handleTimeUpdate} />);

      const video = screen.getByTestId('mp4-video') as HTMLVideoElement;
      Object.defineProperty(video, 'currentTime', { value: 10.5, writable: true });
      fireEvent.timeUpdate(video);

      await waitFor(() => {
        expect(handleTimeUpdate).toHaveBeenCalledWith(10.5);
      });
    });

    it('calls onReady when video can play', async () => {
      const handleReady = jest.fn();
      render(<Mp4Player {...defaultProps} onReady={handleReady} />);

      const video = screen.getByTestId('mp4-video') as HTMLVideoElement;
      fireEvent.loadedData(video);

      await waitFor(() => {
        expect(handleReady).toHaveBeenCalled();
      });
    });
  });

  describe('ref forwarding', () => {
    it('forwards ref to video element', () => {
      const videoRef = { current: null };
      render(<Mp4Player {...defaultProps} videoRef={videoRef} />);

      expect(videoRef.current).toBeInstanceOf(HTMLVideoElement);
    });
  });

  describe('styling', () => {
    it('has black background', () => {
      render(<Mp4Player {...defaultProps} />);

      const container = screen.getByTestId('mp4-player-container');
      expect(container).toHaveClass('bg-black');
    });

    it('has rounded corners', () => {
      render(<Mp4Player {...defaultProps} />);

      const container = screen.getByTestId('mp4-player-container');
      expect(container).toHaveClass('rounded-lg');
    });
  });

  describe('URL changes', () => {
    it('updates video source when vodUrl changes', () => {
      const { rerender } = render(<Mp4Player vodUrl="https://example.com/video1.mp4" />);

      const video = screen.getByTestId('mp4-video') as HTMLVideoElement;
      expect(video.src).toBe('https://example.com/video1.mp4');

      rerender(<Mp4Player vodUrl="https://example.com/video2.mp4" />);

      expect(video.src).toBe('https://example.com/video2.mp4');
    });
  });
});
