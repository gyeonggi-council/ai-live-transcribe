import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import SpeakerManagementPage from './page';

import type { MeetingType, SubtitleType } from '../../../../types';

const mockPush = jest.fn();
const mockSetTitle = jest.fn();

jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
  }),
}));

jest.mock('../../../../contexts/BreadcrumbContext', () => ({
  useBreadcrumb: () => ({
    dynamicTitle: null,
    setTitle: mockSetTitle,
  }),
}));

const mockApiClient = jest.fn();
const mockUpdateSubtitlesBatch = jest.fn();
const mockGetSpeakersTimeline = jest.fn();
const mockScrollIntoView = jest.fn();
const originalScrollIntoView = (window.HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView;

const mockMergeSpeakers = jest.fn();
const mockGetCouncilors = jest.fn();
const mockDownloadSpeechClip = jest.fn();
const mockCreateClipJob = jest.fn();
const mockGetClipJob = jest.fn();
const mockDownloadClipJobResult = jest.fn();

jest.mock('../../../../lib/api', () => ({
  __esModule: true,
  API_BASE_URL: 'http://localhost:8000',
  apiClient: (...args: unknown[]) => mockApiClient(...args),
  updateSubtitlesBatch: (...args: unknown[]) => mockUpdateSubtitlesBatch(...args),
  getSpeakersTimeline: (...args: unknown[]) => mockGetSpeakersTimeline(...args),
  mergeSpeakers: (...args: unknown[]) => mockMergeSpeakers(...args),
  getCouncilors: (...args: unknown[]) => mockGetCouncilors(...args),
  downloadSpeechClip: (...args: unknown[]) => mockDownloadSpeechClip(...args),
  createClipJob: (...args: unknown[]) => mockCreateClipJob(...args),
  getClipJob: (...args: unknown[]) => mockGetClipJob(...args),
  downloadClipJobResult: (...args: unknown[]) => mockDownloadClipJobResult(...args),
}));

const defaultParams = { id: 'meeting-1' };

const mockMeeting: MeetingType = {
  id: 'meeting-1',
  title: '제1회 테스트 회의',
  meeting_date: '2024-01-01T00:00:00Z',
  stream_url: null,
  vod_url: 'https://example.com/vod.mp4',
  status: 'ended',
  duration_seconds: 3600,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
};

const mockSubtitles: SubtitleType[] = [
  {
    id: 'subtitle-1',
    meeting_id: 'meeting-1',
    start_time: 0,
    end_time: 3,
    text: '첫 번째 발언',
    speaker: null,
    confidence: 0.91,
    created_at: '2024-01-01T00:00:00Z',
  },
  {
    id: 'subtitle-2',
    meeting_id: 'meeting-1',
    start_time: 3,
    end_time: 6,
    text: '두 번째 발언',
    speaker: '의장',
    confidence: 0.87,
    created_at: '2024-01-01T00:00:03Z',
  },
];

const mockTimeline = {
  speakers: [
    {
      speaker: '의장',
      total_time: 3,
      segment_count: 1,
      segments: [
        { id: 'subtitle-2', start_time: 3, end_time: 6, text: '두 번째 발언', confidence: 0.87 },
      ],
    },
    {
      speaker: '(미지정)',
      total_time: 3,
      segment_count: 1,
      segments: [
        { id: 'subtitle-1', start_time: 0, end_time: 3, text: '첫 번째 발언', confidence: 0.91 },
      ],
    },
  ],
  total_duration: 6,
};

describe('SpeakerManagementPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockScrollIntoView.mockClear();

    Object.defineProperty(window.HTMLElement.prototype as { scrollIntoView: () => void }, 'scrollIntoView', {
      configurable: true,
      writable: true,
      value: mockScrollIntoView,
    });

    mockApiClient.mockImplementation((endpoint: string) => {
      if (endpoint === '/api/meetings/meeting-1') {
        return Promise.resolve(mockMeeting);
      }

      if (endpoint === '/api/meetings/meeting-1/subtitles?limit=1000') {
        return Promise.resolve({ items: mockSubtitles });
      }

      return Promise.reject(new Error('Unknown endpoint'));
    });

    mockGetSpeakersTimeline.mockResolvedValue(mockTimeline);
    mockUpdateSubtitlesBatch.mockResolvedValue({ updated: 0, items: [] });
    mockMergeSpeakers.mockResolvedValue({ merged: '', into: '', updated: 0 });
    mockGetCouncilors.mockResolvedValue([]);
    mockDownloadSpeechClip.mockResolvedValue(undefined);
  });

  afterEach(() => {
    Object.defineProperty(window.HTMLElement.prototype as { scrollIntoView: unknown }, 'scrollIntoView', {
      configurable: true,
      writable: true,
      value: originalScrollIntoView,
    });
  });

  it('renders meeting title and timeline tab by default', async () => {
    render(<SpeakerManagementPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByText('제1회 테스트 회의')).toBeInTheDocument();
    });

    // Default tab should be "발언 타임라인"
    expect(screen.getByTestId('tab-timeline')).toBeInTheDocument();
    expect(screen.getByTestId('tab-assign')).toBeInTheDocument();

    // Timeline shows speaker cards
    await waitFor(() => {
      expect(screen.getByText('의장')).toBeInTheDocument();
      expect(screen.getByText('(미지정)')).toBeInTheDocument();
    });
  });

  it('switches to assign tab and shows subtitle list', async () => {
    const user = userEvent.setup();
    render(<SpeakerManagementPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByText('제1회 테스트 회의')).toBeInTheDocument();
    });

    // Click "화자 지정" tab
    await user.click(screen.getByTestId('tab-assign'));

    await waitFor(() => {
      expect(screen.getByText('첫 번째 발언')).toBeInTheDocument();
      expect(screen.getByText('두 번째 발언')).toBeInTheDocument();
    });
  });

  it('saves speaker changes as batch update payload', async () => {
    const alertMock = jest.spyOn(window, 'alert').mockImplementation(() => {});
    const user = userEvent.setup();

    render(<SpeakerManagementPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByText('제1회 테스트 회의')).toBeInTheDocument();
    });

    // Switch to assign tab
    await user.click(screen.getByTestId('tab-assign'));

    await waitFor(() => {
      expect(screen.getByText('첫 번째 발언')).toBeInTheDocument();
    });

    // Click the first subtitle's speaker button to open CouncilorPicker
    const speakerButtons = screen.getAllByRole('button', { name: /(미지정)|의장/ });
    const firstSpeakerBtn = speakerButtons.find((btn) => btn.textContent?.includes('(미지정)'));
    expect(firstSpeakerBtn).toBeTruthy();
    await user.click(firstSpeakerBtn!);

    // CouncilorPicker shows an input — type the speaker name and press Enter
    const pickerInput = screen.getByPlaceholderText('화자 선택 또는 입력');
    await user.clear(pickerInput);
    await user.type(pickerInput, '화자 1{Enter}');

    const saveButton = screen.getByRole('button', { name: /변경 저장/i });
    await user.click(saveButton);

    expect(mockUpdateSubtitlesBatch).toHaveBeenCalledWith('meeting-1', [
      {
        id: 'subtitle-1',
        speaker: '화자 1',
      },
    ]);

    expect(alertMock).toHaveBeenCalled();
    alertMock.mockRestore();
  });

  it('shows navigation links for correction and verification', async () => {
    render(<SpeakerManagementPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByRole('link', { name: '교정/편집으로 이동' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: '돌아가기' })).toBeInTheDocument();
    });
  });

  it('shows error message when loading fails', async () => {
    mockApiClient.mockRejectedValue(new Error('Network error'));

    render(<SpeakerManagementPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByText('회의 정보를 불러오지 못했습니다.')).toBeInTheDocument();
    });
  });

  it('expands speaker card to show segments on click', async () => {
    const user = userEvent.setup();
    render(<SpeakerManagementPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('speaker-card-0')).toBeInTheDocument();
    });

    // Click speaker card to expand
    await user.click(screen.getByTestId('speaker-card-0'));

    // Should show the segment text
    await waitFor(() => {
      expect(screen.getByText('두 번째 발언')).toBeInTheDocument();
    });
  });

  it('renders clip download button in expanded timeline', async () => {
    const user = userEvent.setup();
    render(<SpeakerManagementPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('speaker-card-0')).toBeInTheDocument();
    });

    // Expand speaker card
    await user.click(screen.getByTestId('speaker-card-0'));

    // Check for clip download button
    await waitFor(() => {
      const clipButtons = screen.getAllByTestId('clip-download-button');
      expect(clipButtons.length).toBeGreaterThan(0);
    });
  });

  it('클립 버튼 클릭 시 인증 fetch 기반 downloadSpeechClip 을 호출한다', async () => {
    // 구형 <a download> 직링크는 Authorization 헤더가 없어 401 — 회귀 가드
    const user = userEvent.setup();
    render(<SpeakerManagementPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('speaker-card-0')).toBeInTheDocument();
    });

    await user.click(screen.getByTestId('speaker-card-0'));

    const [clipButton] = await screen.findAllByTestId('clip-download-button');
    expect(clipButton).toBeTruthy();
    await user.click(clipButton!);

    await waitFor(() => {
      // 의장 화자의 구간 (start 3 ~ end 6), speaker 쿼리 파라미터 없이 시간만 전달
      expect(mockDownloadSpeechClip).toHaveBeenCalledWith('meeting-1', 3, 6);
    });
  });

  it('60초 초과 구간 클립은 clip-jobs 경로로 다운로드한다', async () => {
    // 동기 clip API 는 TTFB ≈ 구간 길이 → 프록시 타임아웃. 61초 이상 구간은
    // 단일 세그먼트 잡 생성 → 폴링 → 결과 다운로드 (clips 페이지와 동일 정책).
    mockGetSpeakersTimeline.mockResolvedValue({
      speakers: [
        {
          speaker: '의장',
          total_time: 90,
          segment_count: 1,
          segments: [
            { id: 's-long', start_time: 10, end_time: 100, text: '긴 발언', confidence: 0.9 },
          ],
        },
      ],
      total_duration: 100,
    });
    mockCreateClipJob.mockResolvedValue({ job_id: 'job-9' });
    mockGetClipJob.mockResolvedValue({
      status: 'done',
      progress: 1,
      current_segment: null,
      error: null,
      filename: 'clip.mp4',
    });
    mockDownloadClipJobResult.mockResolvedValue(undefined);

    const user = userEvent.setup();
    render(<SpeakerManagementPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('speaker-card-0')).toBeInTheDocument();
    });
    await user.click(screen.getByTestId('speaker-card-0'));

    const [clipButton] = await screen.findAllByTestId('clip-download-button');
    await user.click(clipButton!);

    await waitFor(() => {
      expect(mockCreateClipJob).toHaveBeenCalledWith('meeting-1', [{ start: 10, end: 100 }]);
    });
    await waitFor(() => {
      expect(mockDownloadClipJobResult).toHaveBeenCalledWith('meeting-1', 'job-9');
    });
    expect(mockDownloadSpeechClip).not.toHaveBeenCalled();
  });

  it('클립 다운로드 실패 시 에러를 알리고 버튼이 다시 활성화된다', async () => {
    const alertMock = jest.spyOn(window, 'alert').mockImplementation(() => {});
    mockDownloadSpeechClip.mockRejectedValue(new Error('로그인이 필요합니다'));

    const user = userEvent.setup();
    render(<SpeakerManagementPage params={defaultParams} />);

    await waitFor(() => {
      expect(screen.getByTestId('speaker-card-0')).toBeInTheDocument();
    });

    await user.click(screen.getByTestId('speaker-card-0'));

    const [clipButton] = await screen.findAllByTestId('clip-download-button');
    expect(clipButton).toBeTruthy();
    await user.click(clipButton!);

    await waitFor(() => {
      expect(alertMock).toHaveBeenCalledWith('로그인이 필요합니다');
    });
    expect(clipButton).toBeEnabled();
    alertMock.mockRestore();
  });
});
