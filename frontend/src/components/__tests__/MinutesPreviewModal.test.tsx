/**
 * MinutesPreviewModal 테스트
 *
 * - 열릴 때 마크다운 로드(로딩 → 렌더)
 * - 간단 마크다운 렌더 (헤딩/굵게/○ 발언 단락)
 * - 편집 토글과 편집 내용의 미리보기 반영
 * - kordoc_available=false 시 수정본 다운로드 비활성 + 사유 툴팁
 * - 다운로드 호출 인자 (편집된 마크다운 / 기본 서식)
 * - 로드·다운로드 에러 표시
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import MinutesPreviewModal from '../MinutesPreviewModal';

const mockGetMinutesMarkdown = jest.fn();
const mockDownloadHwpxFromMarkdown = jest.fn();
const mockDownloadHwpx = jest.fn();

jest.mock('@/lib/api', () => ({
  __esModule: true,
  getMinutesMarkdown: (...args: unknown[]) => mockGetMinutesMarkdown(...args),
  downloadHwpxFromMarkdown: (...args: unknown[]) =>
    mockDownloadHwpxFromMarkdown(...args),
  downloadHwpx: (...args: unknown[]) => mockDownloadHwpx(...args),
}));

const SAMPLE_MARKDOWN = [
  '# 제391회 경기도의회 회의록',
  '',
  '## 의사일정',
  '1. 조례안 심사',
  '',
  '○김철수 위원  **동의합니다**. 이상입니다.',
].join('\n');

function openModal(overrides?: { onClose?: () => void }) {
  return render(
    <MinutesPreviewModal
      meetingId="M1"
      isOpen={true}
      onClose={overrides?.onClose ?? jest.fn()}
    />
  );
}

describe('MinutesPreviewModal', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetMinutesMarkdown.mockResolvedValue({
      markdown: SAMPLE_MARKDOWN,
      kordoc_available: true,
    });
    mockDownloadHwpxFromMarkdown.mockResolvedValue(undefined);
    mockDownloadHwpx.mockResolvedValue(undefined);
  });

  it('isOpen=false 이면 아무것도 렌더하지 않고 API 도 호출하지 않는다', () => {
    render(<MinutesPreviewModal meetingId="M1" isOpen={false} onClose={jest.fn()} />);

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(mockGetMinutesMarkdown).not.toHaveBeenCalled();
  });

  it('열리면 로딩 표시 후 마크다운을 렌더한다 (헤딩/굵게/발언 단락)', async () => {
    openModal();

    // 로딩 상태
    expect(screen.getByRole('status')).toBeInTheDocument();
    expect(mockGetMinutesMarkdown).toHaveBeenCalledWith('M1');

    // 헤딩 렌더
    await waitFor(() => {
      expect(
        screen.getByRole('heading', { name: '제391회 경기도의회 회의록' })
      ).toBeInTheDocument();
    });
    expect(screen.getByRole('heading', { name: '의사일정' })).toBeInTheDocument();

    // '**굵게**' → <strong>
    const strong = screen.getByText('동의합니다');
    expect(strong.tagName).toBe('STRONG');

    // '○' 발언 단락 (인라인 요소로 쪼개지므로 textContent 로 매칭)
    const speech = screen.getByText((_, element) => {
      return (
        element?.tagName === 'P' &&
        element.textContent === '○김철수 위원  동의합니다. 이상입니다.'
      );
    });
    expect(speech).toBeInTheDocument();
  });

  it('편집 토글 시 전체 마크다운 textarea 가 보이고, 수정이 미리보기에 반영된다', async () => {
    const user = userEvent.setup();
    openModal();

    await waitFor(() => {
      expect(screen.getByTestId('markdown-preview')).toBeInTheDocument();
    });

    // 편집 모드 → textarea 에 전체 마크다운
    await user.click(screen.getByTestId('mode-edit-button'));
    const editor = screen.getByTestId('markdown-editor') as HTMLTextAreaElement;
    expect(editor.value).toBe(SAMPLE_MARKDOWN);

    // 수정 후 미리보기로 돌아오면 반영
    fireEvent.change(editor, { target: { value: '# 수정된 회의록' } });
    await user.click(screen.getByTestId('mode-preview-button'));
    expect(
      screen.getByRole('heading', { name: '수정된 회의록' })
    ).toBeInTheDocument();
  });

  it('kordoc_available=false 이면 수정본 다운로드가 비활성화되고 사유 툴팁을 보여준다', async () => {
    mockGetMinutesMarkdown.mockResolvedValue({
      markdown: SAMPLE_MARKDOWN,
      kordoc_available: false,
    });
    openModal();

    await waitFor(() => {
      expect(screen.getByTestId('markdown-preview')).toBeInTheDocument();
    });

    const editedButton = screen.getByTestId('download-edited-hwpx-button');
    expect(editedButton).toBeDisabled();
    expect(editedButton).toHaveAttribute(
      'title',
      expect.stringContaining('kordoc 엔진을 사용할 수 없습니다')
    );
  });

  it('수정본 HWPX 다운로드는 편집된 마크다운으로 호출된다', async () => {
    const user = userEvent.setup();
    openModal();

    await waitFor(() => {
      expect(screen.getByTestId('markdown-preview')).toBeInTheDocument();
    });

    await user.click(screen.getByTestId('mode-edit-button'));
    fireEvent.change(screen.getByTestId('markdown-editor'), {
      target: { value: '# 수정된 회의록' },
    });

    await user.click(screen.getByTestId('download-edited-hwpx-button'));

    await waitFor(() => {
      expect(mockDownloadHwpxFromMarkdown).toHaveBeenCalledWith(
        'M1',
        '# 수정된 회의록'
      );
    });
  });

  it('기본 서식 HWPX 버튼은 downloadHwpx 를 호출한다', async () => {
    const user = userEvent.setup();
    openModal();

    await waitFor(() => {
      expect(screen.getByTestId('markdown-preview')).toBeInTheDocument();
    });

    await user.click(screen.getByTestId('download-native-hwpx-button'));

    await waitFor(() => {
      expect(mockDownloadHwpx).toHaveBeenCalledWith('M1');
    });
  });

  it('마크다운 로드 실패(401/409) 시 에러 문구를 보여준다', async () => {
    mockGetMinutesMarkdown.mockRejectedValue(
      new Error('자막이 없어 회의록 마크다운을 만들 수 없습니다. 먼저 AI 자막을 생성하세요.')
    );
    openModal();

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(
        '자막이 없어 회의록 마크다운을 만들 수 없습니다'
      );
    });
  });

  it('수정본 다운로드 실패 시 에러 문구를 보여준다', async () => {
    mockDownloadHwpxFromMarkdown.mockRejectedValue(
      new Error('kordoc hwpx 생성에 실패했습니다')
    );
    const user = userEvent.setup();
    openModal();

    await waitFor(() => {
      expect(screen.getByTestId('markdown-preview')).toBeInTheDocument();
    });

    await user.click(screen.getByTestId('download-edited-hwpx-button'));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(
        'kordoc hwpx 생성에 실패했습니다'
      );
    });
  });
});
