import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import type { ClipJobType } from '@/types';

import AutoClipsPanel from '../AutoClipsPanel';

/**
 * 자동으로 잘라 둔 영상(2026-09-10) — AI 자막이 끝난 회의의 의원 전원 영상을 서버가 미리 잘라 둔다.
 * 확인 없이 받기만 하되, 정확도가 99% 가 아니라 "공유 전 한 번 재생" 안내를 늘 붙인다(사용자 선택).
 */
let mockJobs: ClipJobType[] = [];
const mockUseAutoClips = jest.fn();
jest.mock('@/hooks/useAutoClips', () => ({
  useAutoClips: (...args: unknown[]) => {
    mockUseAutoClips(...args);
    return { jobs: mockJobs, notice: '공유하기 전에 한 번 재생해 확인해 주세요.', ttlDays: 3, isLoading: false, error: null, refresh: jest.fn() };
  },
}));

const mockDownload = jest.fn();
const mockFetchFile = jest.fn();
const mockSaveBlob = jest.fn();
jest.mock('@/lib/api', () => ({
  __esModule: true,
  downloadClipJobFile: (...args: unknown[]) => mockDownload(...args),
  fetchClipJobFile: (...args: unknown[]) => mockFetchFile(...args),
  saveBlob: (...args: unknown[]) => mockSaveBlob(...args),
  // 썸네일은 화면에 들어올 때만 받는다 — jsdom 에는 IntersectionObserver 가 없어 바로 부른다
  fetchClipThumb: jest.fn().mockResolvedValue(null),
}));

function job(over: Partial<ClipJobType> = {}): ClipJobType {
  return {
    job_id: 'j1',
    meeting_id: 'm1',
    meeting_title: '제393회 제3차 도시환경위원회',
    meeting_date: '2026-09-08',
    owner_username: '자동',
    label: '김태희',
    speaker_name: '김태희',
    source_kind: 'ai',
    status: 'done',
    progress: 1,
    current_segment: null,
    segment_count: 2,
    total_seconds: 1374,
    merge: false,
    with_srt: true,
    error: null,
    files: [
      { name: '김태희_제393회 제3차 도시환경위원회_2.mp4', kind: 'mp4', bytes: 42_000_000 },
      { name: '김태희_제393회 제3차 도시환경위원회_2.srt', kind: 'srt', bytes: 9_000 },
      { name: '김태희_제393회 제3차 도시환경위원회_3.mp4', kind: 'mp4', bytes: 25_000_000 },
    ],
    bytes_total: 67_009_000,
    created_at: '2026-09-10T12:00:00Z',
    finished_at: '2026-09-10T12:40:00Z',
    expires_at: '2026-09-13T12:40:00Z',
    evicted_reason: null,
    download_urls: {},
    origin: 'auto',
    compress: true,
    segments: [
      { start: 6660, end: 7521, no: 2 },
      { start: 11490, end: 12007, no: 3 },
    ],
    ...over,
  };
}

beforeEach(() => {
  mockJobs = [];
  mockDownload.mockReset().mockResolvedValue(undefined);
  mockFetchFile.mockReset().mockResolvedValue({ blob: new Blob(['x']), filename: 'x.mp4' });
  mockSaveBlob.mockReset();
  mockUseAutoClips.mockReset();
});

describe('AutoClipsPanel', () => {
  it('자동 클립이 없는 회의는 자리를 차지하지 않는다', () => {
    const { container } = render(<AutoClipsPanel meetingId="m1" speakerName="김태희" />);
    expect(container).toBeEmptyDOMElement();
    expect(mockUseAutoClips).toHaveBeenCalledWith({ meetingId: 'm1', days: 3 });
  });

  it('공유 전 확인 안내 + 구간 번호·시각 + 받기·보기', async () => {
    mockJobs = [job(), job({ job_id: 'j2', label: '이혜원', speaker_name: '이혜원' })];
    const onPreview = jest.fn();
    render(<AutoClipsPanel meetingId="m1" speakerName="김태희" onPreview={onPreview} />);
    expect(screen.getByTestId('auto-clips-notice')).toHaveTextContent('공유하기 전에 한 번 재생');
    expect(screen.getAllByTestId('auto-clip-job')).toHaveLength(1);          // 고른 의원 것만
    expect(screen.getByText('#2')).toBeInTheDocument();                      // 파일 이름 끝 번호와 같은 값
    // 워크벤치 안에서만 나오는 "원본에서 보기" — 영상을 그 구간으로 옮긴다
    fireEvent.click(screen.getAllByTestId('auto-clip-preview')[1]);
    expect(onPreview).toHaveBeenCalledWith(11490);
    fireEvent.click(screen.getAllByTestId('clip-file-download')[0]);
    await waitFor(() =>
      expect(mockDownload).toHaveBeenCalledWith('m1', 'j1', '김태희_제393회 제3차 도시환경위원회_2.mp4')
    );
  });

  it('추출을 요청한 시각을 보여준다 (2026-09-16 사용자 요청)', () => {
    mockJobs = [job()];
    render(<AutoClipsPanel meetingId="m1" speakerName="김태희" />);
    const times = screen.getByTestId('clip-requested-at');
    expect(times).toHaveTextContent('요청');
    expect(times).toHaveTextContent('완료');
  });

  it('클립마다 썸네일 자리와 「재생 확인」 버튼이 있다', () => {
    mockJobs = [job()];
    render(<AutoClipsPanel meetingId="m1" speakerName="김태희" />);
    expect(screen.getAllByTestId('clip-thumb')).toHaveLength(2);             // mp4 2개
    expect(screen.getAllByTestId('clip-file-check')).toHaveLength(2);
  });

  it('「재생 확인」 → 그 파일을 받아 모달에서 재생하고, 「이 파일 받기」는 다시 받지 않는다', async () => {
    mockJobs = [job()];
    render(<AutoClipsPanel meetingId="m1" speakerName="김태희" />);
    fireEvent.click(screen.getAllByTestId('clip-file-check')[0]);
    await waitFor(() => expect(screen.getByTestId('clip-preview-video')).toBeInTheDocument());
    expect(mockFetchFile).toHaveBeenCalledWith(
      'm1', 'j1', '김태희_제393회 제3차 도시환경위원회_2.mp4', expect.any(Function), expect.any(AbortSignal)
    );
    fireEvent.click(screen.getByTestId('clip-preview-save'));
    expect(mockSaveBlob).toHaveBeenCalledTimes(1);
    expect(mockFetchFile).toHaveBeenCalledTimes(1);                          // 두 번 받지 않는다
    expect(mockDownload).not.toHaveBeenCalled();
  });

  it('전부 받기는 mp4 를 하나씩 차례로 받는다', async () => {
    mockJobs = [job()];
    render(<AutoClipsPanel meetingId="m1" speakerName="김태희" />);
    fireEvent.click(screen.getByTestId('auto-clip-download-all'));
    await waitFor(() => expect(mockDownload).toHaveBeenCalledTimes(2));
    expect(mockDownload.mock.calls.map((c) => c[2])).toEqual([
      '김태희_제393회 제3차 도시환경위원회_2.mp4',
      '김태희_제393회 제3차 도시환경위원회_3.mp4',
    ]);
  });

  it('다른 의원만 있으면 직접 자르라고 안내한다', () => {
    mockJobs = [job({ speaker_name: '이혜원', label: '이혜원' })];
    render(<AutoClipsPanel meetingId="m1" speakerName="김태희" />);
    expect(screen.getByTestId('auto-clips-none-for-speaker')).toHaveTextContent('직접 자를 수 있습니다');
  });

  it('자르는 중이면 받기 버튼 대신 진행 상태', () => {
    mockJobs = [job({ status: 'running', progress: 0.5, current_segment: 1, files: [] })];
    render(<AutoClipsPanel meetingId="m1" speakerName="김태희" />);
    expect(screen.getByTestId('auto-clip-status')).toHaveTextContent('자르는 중 1/2');
    expect(screen.queryByTestId('clip-file-download')).toBeNull();
  });

  it('최근 목록은 회의별로 묶는다', () => {
    mockJobs = [job(), job({ job_id: 'j9', meeting_id: 'm2', meeting_title: '제393회 제2차 경제노동위원회', meeting_date: '2026-09-09' })];
    render(<AutoClipsPanel days={3} />);
    const groups = screen.getAllByTestId('auto-clips-meeting');
    expect(groups).toHaveLength(2);
    expect(groups[0]).toHaveTextContent('경제노동위원회');                     // 최근 회의 먼저
  });
});
