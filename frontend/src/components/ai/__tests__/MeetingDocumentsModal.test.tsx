import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ApiError } from '@/lib/api';

import MeetingDocumentsModal from '../MeetingDocumentsModal';

const mockOptions = jest.fn();
const mockDownload = jest.fn();
jest.mock('@/lib/api', () => {
  const actual = jest.requireActual('@/lib/api');
  return {
    ...actual,
    getMeetingDocumentOptions: (...a: unknown[]) => mockOptions(...a),
    downloadMeetingDocument: (...a: unknown[]) => mockDownload(...a),
  };
});

const OPTIONS = {
  committee_short: '운영위',
  departments: ['의회사무처', '인사과'],
  material_requests: [
    { id: 'r1', councilor: '문승호', summary: '렌탈 계약 현황', department: '의회사무처' },
    { id: 'r2', councilor: '신미숙', summary: '소통협치관 자료', department: '소통협치관' },
  ],
  has_summary: false,
  has_subtitles: true,
};

describe('MeetingDocumentsModal', () => {
  beforeEach(() => {
    mockOptions.mockReset().mockResolvedValue(OPTIONS);
    mockDownload.mockReset().mockResolvedValue('260914 운영위 모니터링(회의)_인사과.hwpx');
  });

  it('downloads the chosen kind for the chosen department', async () => {
    render(<MeetingDocumentsModal meetingId="m1" open onClose={jest.fn()} />);
    await screen.findByText('업무보고 모니터링');
    await userEvent.selectOptions(screen.getByLabelText('부서'), '인사과');
    await userEvent.click(screen.getByTestId('meeting-documents-make'));
    await waitFor(() => expect(mockDownload).toHaveBeenCalledWith('m1', 'monitoring', { department: '인사과', requestId: undefined }));
    expect(await screen.findByRole('status')).toHaveTextContent('내려받았습니다');
  });

  it('cover picks one request or the department bundle, and warns when no summary for press', async () => {
    render(<MeetingDocumentsModal meetingId="m1" open onClose={jest.fn()} />);
    await screen.findByText('의원 요구자료 표지');
    await userEvent.click(screen.getByText('의원 요구자료 표지'));
    await userEvent.selectOptions(screen.getByLabelText('부서'), '의회사무처');
    const req = screen.getByLabelText('요구자료') as HTMLSelectElement;
    expect(Array.from(req.options).map((o) => o.textContent)).toEqual(['의회사무처 전체 묶음(ZIP)', '문승호 — 렌탈 계약 현황']);
    await userEvent.selectOptions(req, 'r1');
    await userEvent.click(screen.getByTestId('meeting-documents-make'));
    await waitFor(() => expect(mockDownload).toHaveBeenCalledWith('m1', 'datareq-cover', { department: '의회사무처', requestId: 'r1' }));
    await userEvent.click(screen.getByText('보도자료(초안)'));
    expect(screen.getByText(/회의 요약이 아직 없습니다/)).toBeInTheDocument();
  });

  it('shows server errors and permission errors', async () => {
    mockDownload.mockRejectedValueOnce(new ApiError(409, '자료요구가 없습니다.'));
    render(<MeetingDocumentsModal meetingId="m1" open onClose={jest.fn()} />);
    await screen.findByText('자료요구 목록');
    await userEvent.click(screen.getByText('자료요구 목록'));
    await userEvent.click(screen.getByTestId('meeting-documents-make'));
    expect(await screen.findByRole('alert')).toHaveTextContent('자료요구가 없습니다.');
  });

  it('explains when the viewer may not make documents', async () => {
    mockOptions.mockRejectedValueOnce(new ApiError(401, 'unauthorized'));
    render(<MeetingDocumentsModal meetingId="m1" open onClose={jest.fn()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('로그인하거나 의회망에서');
  });

  it('renders nothing when closed', () => {
    const { container } = render(<MeetingDocumentsModal meetingId="m1" open={false} onClose={jest.fn()} />);
    expect(container).toBeEmptyDOMElement();
    expect(mockOptions).not.toHaveBeenCalled();
  });
});
