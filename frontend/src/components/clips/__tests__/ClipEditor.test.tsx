import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import type { ClipIndexType, ClipJobType, ClipSpeakerType, MeetingType } from '@/types';

import ClipEditor from '../ClipEditor';

/**
 * 2026-09-08 사고: 같은 윤충식 위원 1구간 잡이 6개(연타). 추출 뒤 갱신되는 것이 의원 인덱스뿐이라
 * 기록 패널이 그대로였고, 담당자는 변화가 없으니 다시 눌렀다.
 * → 잡을 만들면 기록 목록을 즉시 갱신하고, 이 회의에 진행 중 잡이 있으면 추출 버튼을 잠근다.
 */
const mockUseClipJobs = jest.fn();
jest.mock('@/hooks/useClipJobs', () => ({
  ...jest.requireActual('@/hooks/useClipJobs'),
  useClipJobs: (...args: unknown[]) => mockUseClipJobs(...args),
}));

// 자동 클립 목록(2026-09-10)은 AutoClipsPanel 테스트가 맡는다 — 여기서는 비어 있는 회의
jest.mock('@/hooks/useAutoClips', () => ({
  useAutoClips: () => ({ jobs: [], notice: null, ttlDays: null, isLoading: false, error: null, refresh: jest.fn() }),
}));

const mockCreate = jest.fn();
jest.mock('@/lib/api', () => ({
  __esModule: true,
  createClipJobV2: (...args: unknown[]) => mockCreate(...args),
  downloadClipJobFile: jest.fn(),
  deleteClipJob: jest.fn(),
}));

const meeting = {
  id: 'm1',
  title: '제393회 제1차 안전행정위원회',
  meeting_date: '2026-09-07',
  status: 'ended',
  subtitle_stage: 'ai',
  vod_url: 'https://kms.ggc.go.kr/mp4/x.mp4',
  duration_seconds: 12000,
} as unknown as MeetingType;

const speaker: ClipSpeakerType = {
  key: 'k1',
  name: '윤충식',
  role: '위원',
  party: '국민의힘',
  district: '포천시',
  photo_url: null,
  councilor_id: 'c1',
  total_seconds: 280,
  segments: [{ idx: 0, start: 780, end: 1060, seconds: 280, time: '00:13:00', title: '발언 8회·답변 포함', named: true }],
};

const index: ClipIndexType = {
  meeting_id: 'm1',
  kms_midx: '138318',
  duration: 12000,
  source: 'ai',
  time_offset: 0,
  warnings: [],
  speakers: [speaker],
};

function activeJob(): ClipJobType {
  return {
    job_id: 'j1',
    meeting_id: 'm1',
    label: '윤충식',
    speaker_name: '윤충식',
    source_kind: 'ai',
    status: 'running',
    progress: 0,
    current_segment: 1,
    segment_count: 1,
    total_seconds: 282,
    merge: false,
    with_srt: true,
    error: null,
    files: [],
    bytes_total: 0,
    created_at: '2026-09-08T09:22:00+00:00',
    finished_at: null,
    expires_at: null,
    evicted_reason: null,
    download_urls: {},
  };
}

function renderEditor() {
  return render(<ClipEditor meeting={meeting} index={index} speaker={speaker} shift={0} offset={0} />);
}

describe('ClipEditor — 추출 버튼과 기록 갱신', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockCreate.mockResolvedValue({ job_id: 'j-new', status: 'queued', queue_position: 0 });
  });

  it('이 회의에 진행 중인 추출이 있으면 구간 추출·선택 구간 추출 버튼이 잠기고 라벨이 바뀐다', () => {
    mockUseClipJobs.mockReturnValue({ jobs: [activeJob()], store: null, isLoading: false, error: null, refresh: jest.fn() });
    renderEditor();
    const btn = screen.getByTestId('btn-extract');
    expect(btn).toBeDisabled();
    expect(btn).toHaveTextContent('추출 중…');
    expect(screen.getByTestId('btn-extract-selection')).toBeDisabled();
    fireEvent.submit(screen.getByTestId('clip-extract-form'));
    expect(mockCreate).not.toHaveBeenCalled();
  });

  it('추출을 누르면 잡 생성 뒤 기록 목록을 즉시 갱신하고, 라벨은 이름만·여유 1초', async () => {
    const refresh = jest.fn();
    mockUseClipJobs.mockReturnValue({ jobs: [], store: null, isLoading: false, error: null, refresh });
    renderEditor();
    const btn = screen.getByTestId('btn-extract');
    expect(btn).toBeEnabled();
    expect(btn).toHaveTextContent('영상 1개 추출하기');
    fireEvent.click(btn);
    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
    expect(mockCreate).toHaveBeenCalledWith(
      'm1',
      // no = 목록 순번 → 파일 이름 `이름_회의명_번호` 의 번호 (2026-09-10, 설치형과 같은 값)
      expect.objectContaining({ label: '윤충식', pad_before: 1, pad_after: 1, source_kind: 'ai', segments: [{ start: 780, end: 1060, no: 1 }] })
    );
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(screen.getByTestId('clip-notice')).toHaveTextContent('방금 추가된 항목');
  });
});
