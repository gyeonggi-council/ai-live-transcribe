import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { ExtractorVersionType } from '@/types';

import AdminToolsPage from './page';


// ─── AuthContext 모킹 (RoleGuard가 사용) ─────────────────────────────────
let mockUser: { role: string; username: string; display_name: string } | null;

jest.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: mockUser,
    loading: false,
    error: null,
    login: jest.fn(),
    pinLogin: jest.fn(),
    logout: jest.fn(),
  }),
}));

// ─── API 모킹 ────────────────────────────────────────────────────────────
const mockGetExtractorVersion = jest.fn();
const mockUploadExtractorRelease = jest.fn();

jest.mock('@/lib/api', () => ({
  __esModule: true,
  API_BASE_URL: 'http://localhost:8000',
  getExtractorVersion: (...args: unknown[]) => mockGetExtractorVersion(...args),
  uploadExtractorRelease: (...args: unknown[]) =>
    mockUploadExtractorRelease(...args),
}));

const mockManifest: ExtractorVersionType = {
  name: '경기도의회 영상추출기',
  version: '1.2.0',
  notes: '버그 수정 및 안정화',
  published_at: '2026-07-01T00:00:00+00:00',
  url: 'http://localhost:8000/api/tools/extractor/download',
  sha256: 'abcdef0123456789deadbeefcafebabe',
  size: 52428800,
  min_supported_version: null,
};

describe('AdminToolsPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUser = { role: 'admin', username: 'admin', display_name: '관리자' };
  });

  it('현재 배포 버전 정보를 렌더링한다 (버전/sha256 앞 12자/다운로드 링크)', async () => {
    mockGetExtractorVersion.mockResolvedValue(mockManifest);

    render(<AdminToolsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('current-version')).toHaveTextContent('1.2.0');
    });
    // sha256 앞 12자만 표시
    expect(screen.getByText(/abcdef012345/)).toBeInTheDocument();
    // 다운로드 링크
    expect(
      screen.getByRole('link', { name: /설치파일 다운로드/ })
    ).toHaveAttribute(
      'href',
      expect.stringContaining('/api/tools/extractor/download')
    );
  });

  it('배포된 버전이 없으면(404→null) 안내를 보여준다', async () => {
    mockGetExtractorVersion.mockResolvedValue(null);

    render(<AdminToolsPage />);

    await waitFor(() => {
      expect(screen.getByText(/배포된 버전이 없습니다/)).toBeInTheDocument();
    });
  });

  it('외부 URL 모드로 업로드 제출 시 uploadExtractorRelease를 호출하고 카드1을 갱신한다', async () => {
    mockGetExtractorVersion.mockResolvedValue(null);
    mockUploadExtractorRelease.mockResolvedValue({
      ...mockManifest,
      version: '1.3',
      external_url: 'https://github.com/example/releases/v1.3/setup.exe',
    });

    const user = userEvent.setup();
    render(<AdminToolsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('upload-form')).toBeInTheDocument();
    });

    await user.type(screen.getByTestId('upload-version'), '1.3');
    await user.type(screen.getByTestId('upload-notes'), '새 기능 추가');
    await user.click(screen.getByTestId('mode-url'));
    await user.type(
      screen.getByTestId('upload-url'),
      'https://github.com/example/releases/v1.3/setup.exe'
    );
    await user.click(screen.getByTestId('upload-submit'));

    await waitFor(() => {
      expect(mockUploadExtractorRelease).toHaveBeenCalledWith({
        version: '1.3',
        notes: '새 기능 추가',
        externalUrl: 'https://github.com/example/releases/v1.3/setup.exe',
      });
    });
    // 성공 시 카드1 갱신 (초기 1회 + 성공 후 1회)
    await waitFor(() => {
      expect(mockGetExtractorVersion).toHaveBeenCalledTimes(2);
    });
  });

  it('파일 업로드 성공 후 파일 input 표시 파일명이 초기화된다', async () => {
    mockGetExtractorVersion.mockResolvedValue(null);
    mockUploadExtractorRelease.mockResolvedValue({
      ...mockManifest,
      version: '1.4',
    });

    const user = userEvent.setup();
    render(<AdminToolsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('upload-form')).toBeInTheDocument();
    });

    await user.type(screen.getByTestId('upload-version'), '1.4');
    const exe = new File([new Uint8Array([0x4d, 0x5a])], 'setup.exe', {
      type: 'application/octet-stream',
    });
    await user.upload(screen.getByTestId('upload-file'), exe);
    expect(
      (screen.getByTestId('upload-file') as HTMLInputElement).files
    ).toHaveLength(1);

    await user.click(screen.getByTestId('upload-submit'));

    await waitFor(() => {
      expect(mockUploadExtractorRelease).toHaveBeenCalledWith({
        version: '1.4',
        notes: '',
        file: exe,
      });
    });
    // 성공 후 파일 input 이 리마운트되어 선택 파일명이 남지 않는다
    await waitFor(() => {
      expect(
        (screen.getByTestId('upload-file') as HTMLInputElement).files
      ).toHaveLength(0);
    });
    expect((screen.getByTestId('upload-file') as HTMLInputElement).value).toBe('');
  });

  it('admin이 아니면 접근 권한 안내를 보여준다', async () => {
    mockUser = { role: 'staff', username: 'staff1', display_name: '직원' };

    render(<AdminToolsPage />);

    expect(screen.getByText(/접근 권한이 없습니다/)).toBeInTheDocument();
    expect(mockGetExtractorVersion).not.toHaveBeenCalled();
  });
});
