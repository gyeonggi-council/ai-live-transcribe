import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import AiSummaryModal from '../AiSummaryModal';

const mockGetSummary = jest.fn();
const mockGenerateSummary = jest.fn();
jest.mock('@/lib/api', () => ({
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
  getSummary: (...a: unknown[]) => mockGetSummary(...a),
  generateSummary: (...a: unknown[]) => mockGenerateSummary(...a),
}));

const FULL = {
  id: 's1', meeting_id: 'm1', summary_text: '전체 요약', agenda_summaries: [{ order_num: 1, title: '안건', summary: '내용' }],
  key_decisions: ['가결'], action_items: ['자료 제출'], model_used: 'x', created_at: '', complete: true,
};

describe('AiSummaryModal', () => {
  beforeEach(() => {
    mockGetSummary.mockReset();
    mockGenerateSummary.mockReset();
  });

  it('reads the stored summary on open and does not generate by itself', async () => {
    mockGetSummary.mockResolvedValue(FULL);
    render(<AiSummaryModal meetingId="m1" isOpen onClose={() => {}} />);
    expect(await screen.findByText('전체 요약')).toBeInTheDocument();
    expect(screen.getByText('자료 제출')).toBeInTheDocument();
    expect(mockGenerateSummary).not.toHaveBeenCalled();
    expect(screen.queryByTestId('ai-summary-refresh')).not.toBeInTheDocument();
  });

  it('offers generation when none exists and does not loop on failure', async () => {
    mockGetSummary.mockRejectedValue(new Error('404'));
    mockGenerateSummary.mockRejectedValue(new Error('실패'));
    render(<AiSummaryModal meetingId="m1" isOpen onClose={() => {}} />);
    const btn = await screen.findByTestId('ai-summary-generate');
    await userEvent.click(btn);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('실패'));
    await new Promise((r) => setTimeout(r, 30));
    expect(mockGenerateSummary).toHaveBeenCalledTimes(1);
  });

  it('shows the partial badge and refresh for old summaries', async () => {
    mockGetSummary.mockResolvedValue({ ...FULL, complete: false });
    mockGenerateSummary.mockResolvedValue(FULL);
    render(<AiSummaryModal meetingId="m1" isOpen onClose={() => {}} />);
    expect(await screen.findByTestId('ai-summary-partial')).toBeInTheDocument();
    await userEvent.click(screen.getByTestId('ai-summary-refresh'));
    expect(mockGenerateSummary).toHaveBeenCalledWith('m1', true);
    await waitFor(() => expect(screen.queryByTestId('ai-summary-partial')).not.toBeInTheDocument());
  });
});
