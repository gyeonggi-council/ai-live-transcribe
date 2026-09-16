import { render, screen, waitFor, fireEvent } from '@testing-library/react';

import { clearPreviewMeetingCache } from '@/components/search/SearchResultPreview';
import type { MeetingType } from '@/types';

import SearchPage from './page';

/**
 * 통합검색 — 결과를 누르면 그 자리에서 영상을 본다 (2026-08-25)
 *
 * 회귀 방지의 핵심은 첫 번째 테스트다. 예전에는 결과 줄을 누르면 곧바로
 * `router.push('/vod/…')` 로 페이지가 바뀌었고, 그래서 한 건 확인할 때마다
 * 뒤로가기로 돌아와야 했다. 이동은 이제 [이 회의로 이동] 버튼만 한다.
 */

const mockPush = jest.fn();
const mockReplace = jest.fn();

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
  useSearchParams: () => new URLSearchParams(),
}));

const mockGlobalSearch = jest.fn();
const mockApiClient = jest.fn();

jest.mock('@/lib/api', () => ({
  globalSearch: (...args: unknown[]) => mockGlobalSearch(...args),
  apiClient: (...args: unknown[]) => mockApiClient(...args),
}));

const HIT_A = {
  subtitle_id: 'sub-a',
  meeting_id: 'meeting-1',
  meeting_title: '제2차 정례회 문화체육관광위원회',
  meeting_date: '2026-08-14',
  text: '정보화 사업 예산이 늘었습니다',
  start_time: 761,
  end_time: 765,
  speaker: '김의원',
  confidence: 0.9,
};

const HIT_B = {
  ...HIT_A,
  subtitle_id: 'sub-b',
  text: '정보화담당관께 묻겠습니다',
  start_time: 1862,
  speaker: '이의원',
};

const MEETING: MeetingType = {
  id: 'meeting-1',
  title: '제2차 정례회 문화체육관광위원회',
  meeting_date: '2026-08-14',
  stream_url: null,
  vod_url: 'https://example.com/video/some.mp4',
  status: 'ended',
  duration_seconds: 9667,
  created_at: '2026-08-14T00:00:00Z',
} as MeetingType;

function respondWith(items: typeof HIT_A[]) {
  mockGlobalSearch.mockResolvedValue({
    items,
    total: items.length,
    limit: 20,
    offset: 0,
    query: '정보화',
  });
}

async function searchFor(text = '정보화') {
  render(<SearchPage />);
  fireEvent.change(screen.getByPlaceholderText('검색어를 입력하세요'), {
    target: { value: text },
  });
  fireEvent.click(screen.getByRole('button', { name: '검색' }));
  await waitFor(() => expect(screen.getAllByTestId('search-hit').length).toBeGreaterThan(0));
}

beforeAll(() => {
  // jsdom 은 실제 재생을 하지 않는다 — play() 를 스텁하지 않으면 "Not implemented" 를 뱉는다
  Object.defineProperty(window.HTMLMediaElement.prototype, 'play', {
    configurable: true,
    value: jest.fn().mockResolvedValue(undefined),
  });
});

beforeEach(() => {
  jest.clearAllMocks();
  clearPreviewMeetingCache();
  mockApiClient.mockResolvedValue(MEETING);
  respondWith([HIT_A, HIT_B]);
});

describe('검색 결과 클릭', () => {
  it('페이지를 옮기지 않는다 — router.push 를 부르지 않는다', async () => {
    await searchFor();
    fireEvent.click(screen.getAllByTestId('search-hit')[0]);

    await screen.findByTestId('search-preview');
    expect(mockPush).not.toHaveBeenCalled();
  });

  it('누른 줄 바로 아래에 미리보기가 붙는다', async () => {
    await searchFor();
    const rows = screen.getAllByTestId('search-hit');
    fireEvent.click(rows[0]);

    const preview = await screen.findByTestId('search-preview');
    expect(rows[0].nextElementSibling).toBe(preview);
    expect(rows[0]).toHaveAttribute('aria-expanded', 'true');
  });

  it('다른 줄을 눌러도 영상은 페이지에 하나뿐이다', async () => {
    await searchFor();
    fireEvent.click(screen.getAllByTestId('search-hit')[0]);
    await screen.findByTestId('search-preview');

    fireEvent.click(screen.getAllByTestId('search-hit')[1]);
    await waitFor(() => {
      expect(screen.getAllByTestId('search-preview')).toHaveLength(1);
    });
    expect(screen.getAllByTestId('search-hit')[1].nextElementSibling).toBe(
      screen.getByTestId('search-preview'),
    );
  });

  it('같은 줄을 다시 누르면 닫힌다', async () => {
    await searchFor();
    const row = screen.getAllByTestId('search-hit')[0];
    fireEvent.click(row);
    await screen.findByTestId('search-preview');

    fireEvent.click(row);
    await waitFor(() => {
      expect(screen.queryByTestId('search-preview')).not.toBeInTheDocument();
    });
  });

  it('회의 메타는 회의당 한 번만 조회한다', async () => {
    await searchFor();
    fireEvent.click(screen.getAllByTestId('search-hit')[0]);
    await screen.findByTestId('search-preview');
    fireEvent.click(screen.getAllByTestId('search-hit')[1]);
    await waitFor(() => expect(screen.getByTestId('search-preview')).toBeInTheDocument());

    expect(mockApiClient).toHaveBeenCalledTimes(1);
    expect(mockApiClient).toHaveBeenCalledWith('/api/meetings/meeting-1');
  });
});

describe('[이 회의로 이동]', () => {
  it('발언 시점을 t 로 실어 회의 상세로 간다', async () => {
    await searchFor();
    fireEvent.click(screen.getAllByTestId('search-hit')[0]);
    fireEvent.click(await screen.findByTestId('search-preview-open'));

    expect(mockPush).toHaveBeenCalledWith('/vod/meeting-1?t=761');
  });
});

describe('영상이 없는 회의', () => {
  it('안내만 내고 video 태그를 만들지 않는다', async () => {
    mockApiClient.mockResolvedValue({ ...MEETING, vod_url: null });
    await searchFor();
    fireEvent.click(screen.getAllByTestId('search-hit')[0]);

    await screen.findByTestId('search-preview-pending');
    expect(screen.queryByTestId('mp4-video')).not.toBeInTheDocument();
    // 영상이 없어도 자막 전문을 보러 갈 길은 남아 있어야 한다
    expect(screen.getByTestId('search-preview-open')).toBeInTheDocument();
  });
});
