import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import type { ClipJobType } from '@/types';

import ClipJobsPanel from '../ClipJobsPanel';

const mockUseClipJobs = jest.fn();
jest.mock('@/hooks/useClipJobs', () => ({
  useClipJobs: (...args: unknown[]) => mockUseClipJobs(...args),
}));

const mockDownload = jest.fn();
const mockDelete = jest.fn();
jest.mock('@/lib/api', () => ({
  __esModule: true,
  downloadClipJobFile: (...args: unknown[]) => mockDownload(...args),
  deleteClipJob: (...args: unknown[]) => mockDelete(...args),
  fetchClipJobFile: jest.fn().mockResolvedValue({ blob: new Blob(['x']), filename: 'x.mp4' }),
  saveBlob: jest.fn(),
  fetchClipThumb: jest.fn().mockResolvedValue(null),
}));

function job(over: Partial<ClipJobType>): ClipJobType {
  return {
    job_id: 'j1',
    meeting_id: 'm1',
    meeting_title: '제393회 제2차 본회의',
    meeting_date: '2026-09-02',
    owner_username: 'staff1',
    label: '김지호 위원',
    speaker_name: '김지호',
    source_kind: 'official',
    status: 'done',
    progress: 1,
    current_segment: null,
    segment_count: 2,
    total_seconds: 95,
    merge: true,
    with_srt: true,
    error: null,
    files: [
      { name: '김지호 위원_회의_20260902_1분35초_합본2구간.mp4', kind: 'mp4', bytes: 20 * 1024 * 1024 },
      { name: '김지호 위원_회의_20260902_1분35초_합본2구간.srt', kind: 'srt', bytes: 2048 },
    ],
    bytes_total: 20 * 1024 * 1024 + 2048,
    created_at: '2026-09-03T01:00:00+00:00',
    finished_at: '2026-09-03T01:02:00+00:00',
    expires_at: '2026-09-10T01:02:00+00:00',
    evicted_reason: null,
    download_urls: {},
    ...over,
  };
}

describe('ClipJobsPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockDownload.mockResolvedValue(undefined);
    mockDelete.mockResolvedValue({ job_id: 'j1', status: 'expired' });
  });

  it('완료 잡은 파일별 내려받기 버튼, 진행 중 잡은 진행률', () => {
    mockUseClipJobs.mockReturnValue({
      jobs: [job({}), job({ job_id: 'j2', status: 'running', progress: 0.4, current_segment: 1, files: [] })],
      store: { used_bytes: 1024 ** 3, max_bytes: 8 * 1024 ** 3, ttl_days: 7 },
      isLoading: false,
      error: null,
      refresh: jest.fn(),
    });
    render(<ClipJobsPanel scope="mine" />);
    expect(screen.getAllByTestId('clip-job-row')).toHaveLength(2);
    // mp4 는 썸네일 카드, 짝지어진 srt 는 그 카드 안의 「자막」 버튼
    expect(screen.getAllByTestId('clip-file-card')).toHaveLength(1);
    expect(screen.getAllByTestId('clip-file-download')).toHaveLength(1);
    expect(screen.getAllByTestId('clip-file-srt')).toHaveLength(1);
    expect(screen.getAllByTestId('clip-requested-at').length).toBeGreaterThan(0);
    expect(screen.getByTestId('clip-job-progress')).toHaveStyle({ width: '40%' });
    expect(screen.getByTestId('clip-store-usage')).toHaveTextContent('1.00 GB / 8.00 GB');
    expect(screen.getAllByText(/제393회 제2차 본회의/).length).toBeGreaterThan(0);
  });

  it('추출 중인데 진행률이 0 이면(1구간 잡) 움직이는 막대와 "추출 중…" — 0% 로 멈춰 보이지 않게', () => {
    mockUseClipJobs.mockReturnValue({
      jobs: [job({ job_id: 'j3', status: 'running', progress: 0, current_segment: 1, segment_count: 1, files: [] })],
      store: null, isLoading: false, error: null, refresh: jest.fn(),
    });
    render(<ClipJobsPanel scope="mine" meetingId="m1" compact />);
    expect(screen.getByTestId('clip-job-progress-indeterminate')).toBeInTheDocument();
    expect(screen.queryByTestId('clip-job-progress')).not.toBeInTheDocument();
    expect(screen.getByTestId('clip-job-row')).toHaveTextContent('추출 중…');
    expect(screen.getByTestId('clip-job-row')).not.toHaveTextContent('0%');
  });

  it('내려받기 클릭 → downloadClipJobFile(meeting, job, 파일명)', async () => {
    mockUseClipJobs.mockReturnValue({ jobs: [job({})], store: null, isLoading: false, error: null, refresh: jest.fn() });
    render(<ClipJobsPanel scope="mine" meetingId="m1" compact />);
    fireEvent.click(screen.getAllByTestId('clip-file-download')[0]);
    await waitFor(() => expect(mockDownload).toHaveBeenCalledWith('m1', 'j1', expect.stringMatching(/\.mp4$/)));
  });

  it('용량으로 삭제된 잡은 이유를 보여준다', () => {
    mockUseClipJobs.mockReturnValue({
      jobs: [job({ status: 'expired', evicted_reason: 'capacity', files: [] })],
      store: null, isLoading: false, error: null, refresh: jest.fn(),
    });
    render(<ClipJobsPanel />);
    expect(screen.getByTestId('clip-job-evicted')).toHaveTextContent('저장 공간이 모자라');
    expect(screen.queryByTestId('clip-file-download')).not.toBeInTheDocument();
  });

  it('비어 있으면 안내', () => {
    mockUseClipJobs.mockReturnValue({ jobs: [], store: null, isLoading: false, error: null, refresh: jest.fn() });
    render(<ClipJobsPanel />);
    expect(screen.getByTestId('clip-jobs-empty')).toBeInTheDocument();
  });
});
