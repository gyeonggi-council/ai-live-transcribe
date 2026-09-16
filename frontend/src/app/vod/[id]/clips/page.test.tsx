import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

import type { ClipIndexType, MeetingType } from '@/types';

import ClipsPage from './page';

const mockSetTitle = jest.fn();
jest.mock('@/contexts/BreadcrumbContext', () => ({
  useBreadcrumb: () => ({ dynamicTitle: null, setTitle: mockSetTitle }),
}));

let mockUser: { role: string; username: string; display_name: string } | null;
jest.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ user: mockUser, loading: false, error: null, login: jest.fn(), pinLogin: jest.fn(), logout: jest.fn() }),
}));

const mockApiClient = jest.fn();
const mockCreateClipJobV2 = jest.fn();
jest.mock('@/lib/api', () => ({
  __esModule: true,
  API_BASE_URL: 'http://localhost:8000',
  apiClient: (...args: unknown[]) => mockApiClient(...args),
  createClipJobV2: (...args: unknown[]) => mockCreateClipJobV2(...args),
  downloadClipJobFile: jest.fn(),
  deleteClipJob: jest.fn(),
}));

const mockIndex: ClipIndexType = {
  meeting_id: 'meeting-1',
  kms_midx: '138155',
  duration: 3600,
  source: 'official',
  time_offset: 0,
  warnings: [],
  speakers: [
    {
      key: '12057',
      code: '12057',
      name: '김지호',
      role: '위원',
      party: '더불어민주당',
      district: '부천시',
      photo_url: null,
      councilor_id: 'c1',
      total_seconds: 40,
      segments: [
        { idx: 0, start: 10, end: 30, seconds: 20, time: '00:00:10', title: '자료요구(김지호 위원)', named: true },
        { idx: 1, start: 100, end: 120, seconds: 20, time: '00:01:40', title: '1. 안건 상정', named: false },
      ],
    },
  ],
};
const mockUseClipIndex = jest.fn();
jest.mock('@/hooks/useClipIndex', () => ({
  useClipIndex: (...args: unknown[]) => mockUseClipIndex(...args),
}));
jest.mock('@/hooks/useClipJobs', () => ({
  useClipJobs: () => ({ jobs: [], store: null, isLoading: false, error: null, refresh: jest.fn() }),
}));
jest.mock('@/hooks/useVodList', () => ({
  useVodList: () => ({ vods: [], isLoading: false, error: null, total: 0, page: 1, perPage: 100, hasNext: false, totalPages: 1, mutate: jest.fn() }),
}));
jest.mock('@/components/Mp4Player', () => ({
  __esModule: true,
  default: ({ videoRef }: { videoRef?: React.MutableRefObject<HTMLVideoElement | null> }) => (
    <video
      data-testid="mp4-video"
      ref={(el) => {
        if (videoRef) videoRef.current = el;
      }}
    />
  ),
}));

const mockMeeting: MeetingType = {
  id: 'meeting-1',
  title: '제1회 테스트 회의',
  meeting_date: '2026-01-01',
  stream_url: null,
  vod_url: 'https://kms.ggc.go.kr/mp4/x.mp4',
  status: 'ended',
  duration_seconds: 3600,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

describe('ClipsPage (/vod/[id]/clips) — 웹 워크벤치', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUser = { role: 'staff', username: 'staff1', display_name: '정책지원관' };
    mockApiClient.mockResolvedValue(mockMeeting);
    mockUseClipIndex.mockReturnValue({
      index: mockIndex, isLoading: false, error: null, offset: 0, setOffset: jest.fn(), shift: 0, refresh: jest.fn(),
    });
    mockCreateClipJobV2.mockResolvedValue({ job_id: 'j1', status: 'queued', queue_position: 0 });
  });

  it('로그인 안 했으면 안내만', () => {
    mockUser = null;
    render(<ClipsPage params={{ id: 'meeting-1' }} />);
    expect(screen.getByText(/로그인이 필요합니다/)).toBeInTheDocument();
    expect(screen.queryByTestId('clip-workbench')).not.toBeInTheDocument();
  });

  it('데스크톱 핸드오프 없이 워크벤치가 뜨고, 회의 제목을 브레드크럼에 넣는다', async () => {
    render(<ClipsPage params={{ id: 'meeting-1' }} />);
    expect(screen.getByTestId('clip-workbench')).toBeInTheDocument();
    await waitFor(() => expect(mockSetTitle).toHaveBeenCalledWith('제1회 테스트 회의'));
    expect(screen.queryByTestId('open-extractor')).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain('ggcextractor://');
    // 회의가 정해진 화면이라 목록은 접혀 있다
    expect(screen.getByTestId('clip-meeting-list-collapsed')).toBeInTheDocument();
  });

  it('의원을 고르면 이름 있는 발언만 기본 선택되고, 컨트롤 레일에 단축키가 있다', async () => {
    render(<ClipsPage params={{ id: 'meeting-1' }} />);
    await screen.findByTestId('clip-editor');
    expect(screen.getAllByTestId('source-badge')[0]).toHaveTextContent('공식 인덱스');
    fireEvent.click(screen.getByTestId('speaker-card'));
    const rows = await screen.findAllByTestId('segment-row');
    expect(rows).toHaveLength(2);
    // 구간 줄 안의 체크박스만 센다 — 자막 패널의 「재생 위치 따라가기」(2026-09-11)도 체크박스다
    const boxes = rows.map((r) => within(r).getByRole('checkbox'));
    expect((boxes[0] as HTMLInputElement).checked).toBe(true);
    expect((boxes[1] as HTMLInputElement).checked).toBe(false);
    expect(rows[1]).toHaveTextContent('의사진행');
    expect(screen.getByTestId('clip-control-rail')).toHaveTextContent('Space');
    expect(screen.queryByText(/재생\/정지 ·/)).not.toBeInTheDocument();
  });

  it('선택 구간 추출 → createClipJobV2 에 공식 출처·라벨·구간이 실린다', async () => {
    render(<ClipsPage params={{ id: 'meeting-1' }} />);
    await screen.findByTestId('clip-editor');
    fireEvent.click(screen.getByTestId('speaker-card'));
    await screen.findAllByTestId('segment-row');
    fireEvent.click(screen.getByTestId('btn-extract'));
    await waitFor(() => expect(mockCreateClipJobV2).toHaveBeenCalled());
    const [meetingId, body] = mockCreateClipJobV2.mock.calls[0];
    expect(meetingId).toBe('meeting-1');
    // no = 그 의원 구간 목록 순번 → 파일 이름 `이름_회의명_번호` 의 번호(2026-09-10, 설치형 v1.13 과 같은 값)
    expect(body.segments).toEqual([{ start: 10, end: 30, no: 1 }]);
    expect(body.source_kind).toBe('official');
    expect(body.label).toBe('김지호');   // 라벨 기본값은 이름만 — 회의명·날짜·시각은 서버가 파일명에 붙인다(2026-09-08)
    expect(body.with_srt).toBe(true);
    expect(await screen.findByTestId('clip-notice')).toHaveTextContent('추출을 시작했습니다');
  });

  it('수동 자르기: 시작·종료를 직접 지정해 "이 구간 추출"', async () => {
    render(<ClipsPage params={{ id: 'meeting-1' }} />);
    await screen.findByTestId('clip-editor');
    const s = screen.getByTestId('sel-start');
    fireEvent.change(s, { target: { value: '00:10:00' } });
    fireEvent.blur(s);
    const e = screen.getByTestId('sel-end');
    fireEvent.change(e, { target: { value: '00:12:30' } });
    fireEvent.blur(e);
    expect(screen.getByTestId('sel-length')).toHaveTextContent('2분 30초');
    fireEvent.click(screen.getByTestId('btn-extract-selection'));
    await waitFor(() => expect(mockCreateClipJobV2).toHaveBeenCalled());
    const body = mockCreateClipJobV2.mock.calls[0][1];
    expect(body.segments).toEqual([{ start: 600, end: 750 }]);
    expect(body.source_kind).toBe('manual');
  });
});
