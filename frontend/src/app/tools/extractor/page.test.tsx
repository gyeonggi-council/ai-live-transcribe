import { render, screen, waitFor } from '@testing-library/react';

import ExtractorDownloadPage from './page';

const mockGetExtractorVersion = jest.fn();
let mockSearchParams = new URLSearchParams();

jest.mock('next/navigation', () => ({
  useSearchParams: () => mockSearchParams,
}));

jest.mock('@/lib/api', () => ({
  __esModule: true,
  API_BASE_URL: 'http://localhost:8000',
  getExtractorVersion: (...args: unknown[]) => mockGetExtractorVersion(...args),
}));

describe('ExtractorDownloadPage (공개)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockSearchParams = new URLSearchParams();
    mockGetExtractorVersion.mockResolvedValue({
      name: '경기도의회 영상추출기',
      version: '1.2.0',
      notes: '버그 수정 및 안정화',
      published_at: '2026-07-01T00:00:00+00:00',
      url: 'http://localhost:8000/api/tools/extractor/download',
      sha256: 'abcdef0123456789',
      size: 52428800,
      min_supported_version: null,
    });
  });

  it('프로그램 소개·현재 버전·다운로드 버튼·자동업데이트 안내를 렌더링한다', async () => {
    render(<ExtractorDownloadPage />);

    expect(screen.getByText('경기도의회 영상추출기')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText(/1\.2\.0/)).toBeInTheDocument();
    });
    expect(screen.getByText(/버그 수정 및 안정화/)).toBeInTheDocument();
    // 기본 다운로드는 의회 서버(basePath 가 붙은 API 주소), 대안으로 GitHub Releases
    expect(screen.getByTestId('download-server')).toHaveAttribute(
      'href',
      'http://localhost:8000/api/tools/extractor/download'
    );
    expect(screen.getByTestId('download-github')).toHaveAttribute(
      'href',
      expect.stringContaining('github.com/gyeonggi-council/ggc-extractor-releases')
    );
    // 웹 워크벤치 안내(병행)
    expect(screen.getByTestId('web-alternative')).toBeInTheDocument();
    // 응용프로그램 제어 정책으로 exe 가 막히는 PC 의 유일한 길 — 지우지 말 것
    expect(screen.getByTestId('webapp-install')).toBeInTheDocument();
    expect(screen.getByText(/설치가 차단되면/)).toBeInTheDocument();
    expect(screen.getByText(/자동으로 업데이트/)).toBeInTheDocument();
    // midx 파라미터 없이는 재시도 안내 미노출
    expect(screen.queryByTestId('midx-notice')).not.toBeInTheDocument();
  });

  it('?midx= 파라미터가 있으면 재시도 안내와 프로토콜 링크를 보여준다', async () => {
    mockSearchParams = new URLSearchParams('midx=138155');
    render(<ExtractorDownloadPage />);

    await waitFor(() => {
      expect(screen.getByTestId('midx-notice')).toBeInTheDocument();
    });
    expect(screen.getByTestId('retry-open')).toHaveAttribute(
      'href',
      'ggcextractor://open?midx=138155'
    );
    expect(screen.getByText(/138155/)).toBeInTheDocument();
  });

  it('midx 가 숫자가 아니면 재시도 안내를 보여주지 않는다', async () => {
    mockSearchParams = new URLSearchParams('midx=<script>');
    render(<ExtractorDownloadPage />);

    await waitFor(() => {
      expect(screen.getByText('경기도의회 영상추출기')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('midx-notice')).not.toBeInTheDocument();
  });
});
