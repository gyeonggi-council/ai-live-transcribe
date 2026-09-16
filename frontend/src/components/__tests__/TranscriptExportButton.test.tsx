import { fireEvent, render, screen } from '@testing-library/react';

import TranscriptExportButton from '../TranscriptExportButton';

jest.mock('@/lib/api', () => ({
  downloadTranscript: jest.fn().mockResolvedValue(undefined),
  downloadVideoMinutes: jest.fn().mockResolvedValue(undefined),
}));

// 백엔드 배포 전이라 KMS_EXPORT_ENABLED 기본값은 false지만,
// 이 테스트는 '기능이 켜졌을 때' 옵션이 정상 동작하는지를 검증한다.
jest.mock('@/config/features', () => ({
  KMS_EXPORT_ENABLED: true,
}));

describe('TranscriptExportButton', () => {
  it('전자회의록(hwpx) 옵션을 노출한다', () => {
    render(<TranscriptExportButton meetingId="M1" meetingTitle="테스트 회의" />);

    // 드롭다운 토글 버튼 클릭
    fireEvent.click(screen.getByRole('button', { name: /회의록 내보내기/i }));

    // 전자회의록 hwpx 옵션이 보여야 한다 (label 텍스트 정확히 일치)
    expect(screen.getByText('전자회의록 (HWPX)')).toBeInTheDocument();
  });

  it('KMS 영상회의록(html) 옵션을 노출한다', () => {
    render(<TranscriptExportButton meetingId="M1" meetingTitle="테스트 회의" />);

    fireEvent.click(screen.getByRole('button', { name: /회의록 내보내기/i }));

    expect(screen.getByText('영상회의록 (HTML)')).toBeInTheDocument();
  });

  it('영상회의록 옵션 클릭 시 downloadVideoMinutes를 호출한다', () => {
    const { downloadVideoMinutes } = jest.requireMock('@/lib/api');
    render(<TranscriptExportButton meetingId="M1" meetingTitle="테스트 회의" />);

    fireEvent.click(screen.getByRole('button', { name: /회의록 내보내기/i }));
    fireEvent.click(screen.getByText('영상회의록 (HTML)'));

    expect(downloadVideoMinutes).toHaveBeenCalledWith('M1');
  });

  it('포맷 목록에 markdown, official, html, hwpx, srt, json이 모두 포함된다', () => {
    render(<TranscriptExportButton meetingId="M1" meetingTitle="테스트 회의" />);

    fireEvent.click(screen.getByRole('button', { name: /회의록 내보내기/i }));

    expect(screen.getByText('회의록 (MD)')).toBeInTheDocument();
    expect(screen.getByText('공식 회의록')).toBeInTheDocument();
    expect(screen.getByText('회의록 (HTML)')).toBeInTheDocument();
    expect(screen.getByText('전자회의록 (HWPX)')).toBeInTheDocument();
    expect(screen.getByText('자막 (SRT)')).toBeInTheDocument();
    expect(screen.getByText('데이터 (JSON)')).toBeInTheDocument();
  });
});
