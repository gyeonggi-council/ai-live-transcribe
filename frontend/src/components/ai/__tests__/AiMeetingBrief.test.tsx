import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import AiMeetingBrief from '../AiMeetingBrief';

const mockGetSummary = jest.fn();
const mockGenerateSummary = jest.fn();
jest.mock('@/lib/api', () => ({
  ApiError: class ApiError extends Error {},
  getSummary: (...a: unknown[]) => mockGetSummary(...a),
  generateSummary: (...a: unknown[]) => mockGenerateSummary(...a),
}));

const MEETING = {
  id: 'm1', title: '제393회 제3차 도시환경위원회', meeting_date: '2026-09-02', stream_url: null, vod_url: null,
  status: 'ended' as const, duration_seconds: 7200, created_at: '', updated_at: '',
};
const ROW = { id: 's', meeting_id: 'm1', summary_text: '요약', agenda_summaries: [], key_decisions: ['a'], action_items: [], model_used: '', created_at: '' };

describe('AiMeetingBrief', () => {
  beforeEach(() => {
    mockGetSummary.mockReset();
    mockGenerateSummary.mockReset();
  });

  it('shows the partial badge with refresh for old summaries', async () => {
    mockGetSummary.mockResolvedValue({ ...ROW, complete: false });
    mockGenerateSummary.mockResolvedValue({ ...ROW, complete: true, summary_text: '새 요약' });
    render(<AiMeetingBrief meeting={MEETING} canGenerate onAsk={jest.fn()} />);
    expect(await screen.findByTestId('ai-brief-partial')).toBeInTheDocument();
    await userEvent.click(screen.getByTestId('ai-brief-refresh'));
    expect(mockGenerateSummary).toHaveBeenCalledWith('m1', true);
    await waitFor(() => expect(screen.queryByTestId('ai-brief-partial')).not.toBeInTheDocument());
    expect(screen.getByText('새 요약')).toBeInTheDocument();
  });

  it('offers generation when none exists and hides it for anonymous', async () => {
    mockGetSummary.mockRejectedValue(new Error('404'));
    const { rerender } = render(<AiMeetingBrief meeting={MEETING} canGenerate onAsk={jest.fn()} />);
    expect(await screen.findByTestId('ai-brief-generate')).toBeInTheDocument();
    rerender(<AiMeetingBrief meeting={MEETING} canGenerate={false} onAsk={jest.fn()} />);
    expect(screen.queryByTestId('ai-brief-generate')).not.toBeInTheDocument();
  });
});
