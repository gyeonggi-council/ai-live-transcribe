import { render, screen } from '@testing-library/react';

import type { MeetingType } from '@/types';

import ClipMeetingList from '../ClipMeetingList';

const mockUseVodList = jest.fn();
jest.mock('@/hooks/useVodList', () => ({
  useVodList: (...args: unknown[]) => mockUseVodList(...args),
}));

function meeting(over: Partial<MeetingType>): MeetingType {
  return {
    id: 'm',
    title: '제393회 제1차 안전행정위원회',
    meeting_date: '2026-09-07',
    status: 'ended',
    subtitle_stage: 'ai',
    vod_url: 'https://kms.ggc.go.kr/mp4/x.mp4',
    duration_seconds: 12000,
    ...over,
  } as unknown as MeetingType;
}

describe('ClipMeetingList — 회의 목록의 「의원 구분」 배지', () => {
  it('AI 자막 완료 = 완료 · 그 전 = 아직 · VOD 없음 = 영상 등록 전', () => {
    mockUseVodList.mockReturnValue({
      vods: [
        meeting({ id: 'ai', subtitle_stage: 'ai' }),
        meeting({ id: 'vod', title: '제393회 제2차 문화체육관광위원회', subtitle_stage: 'draft' }),
        meeting({ id: 'novod', title: '제393회 제2차 미래과학협력위원회', subtitle_stage: 'draft', vod_url: null }),
      ],
      isLoading: false,
      error: null,
    });
    render(<ClipMeetingList selectedId={null} onSelect={jest.fn()} />);
    const rows = screen.getAllByTestId('clip-meeting-row');
    expect(rows).toHaveLength(3);
    // 설치형 프로그램(webui/app.html 의 indexBadge)과 같은 문구여야 한다 — 한쪽만 고치지 말 것
    expect(screen.getAllByTestId('clip-index-status')).toHaveLength(3);
    expect(rows[0]).toHaveTextContent('의원 구분 완료');
    expect(rows[1]).toHaveTextContent('의원 구분 아직');
    expect(rows[1]).toBeEnabled();
    expect(rows[1]).toHaveAttribute('title', expect.stringContaining('AI 자막이 만들어지면'));
    expect(rows[2]).toHaveTextContent('영상 등록 전');
    expect(rows[2]).toBeDisabled();
  });
});
