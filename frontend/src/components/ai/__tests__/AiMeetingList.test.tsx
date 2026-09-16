import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import AiMeetingList, { canAskAbout } from '../AiMeetingList';

const M = (over: Record<string, unknown>) => ({
  id: 'x', title: 'T', meeting_date: '2026-09-01', stream_url: null, vod_url: null, status: 'ended',
  duration_seconds: null, created_at: '', updated_at: '', ...over,
});

jest.mock('@/hooks/useVodList', () => ({
  useVodList: () => ({
    vods: [M({ id: 'a', title: '제393회 제1차 안전행정위원회', subtitle_stage: 'ai' }), M({ id: 'b', title: '자막 없음', subtitle_stage: 'none' }), M({ id: 'c', title: '생중계', status: 'live' })],
    isLoading: false,
    error: null,
    hasNext: false,
  }),
}));
jest.mock('@/lib/api', () => ({ findClipMeetingsByMember: jest.fn().mockResolvedValue({ name: '', meeting_ids: [] }) }));

describe('AiMeetingList', () => {
  it('canAskAbout — 자막이 있거나 생중계면 고를 수 있다', () => {
    expect(canAskAbout({ status: 'ended', subtitle_stage: 'ai' })).toBe(true);
    expect(canAskAbout({ status: 'ended', subtitle_stage: 'none' })).toBe(false);
    expect(canAskAbout({ status: 'ended' })).toBe(false);
    expect(canAskAbout({ status: 'live' })).toBe(true);
  });

  it('disables meetings without subtitles and selects askable ones', async () => {
    const onSelect = jest.fn();
    render(<AiMeetingList selectedId={null} onSelect={onSelect} />);
    const rows = screen.getAllByTestId('ai-meeting-row');
    expect(rows[1]).toBeDisabled();
    await userEvent.click(rows[0]);
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 'a' }));
  });

  it('filters by title', async () => {
    render(<AiMeetingList selectedId={null} onSelect={jest.fn()} />);
    await userEvent.type(screen.getByTestId('ai-meeting-search'), '안전행정');
    expect(screen.getAllByTestId('ai-meeting-row')).toHaveLength(1);
  });
});
