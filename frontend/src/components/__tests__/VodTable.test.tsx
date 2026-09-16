import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { MeetingType } from '@/types';

import VodTable from '../VodTable';

// Mock next/navigation
const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
  }),
}));

/**
 * 2026-08-22: PC 표 + 모바일 카드 두 벌에서 '카드 하나'로 통일했다.
 * 표 헤더를 검사하던 테스트는 카드 구조 검사로 대체한다.
 */
describe('VodTable (회의 카드 목록)', () => {
  const mockVodList: MeetingType[] = [
    {
      id: 'vod-1',
      title: '제122회 본회의',
      meeting_date: '2026-02-04',
      stream_url: null,
      vod_url: 'https://vod.example.com/122',
      status: 'ended',
      duration_seconds: 5400,
      created_at: '2026-02-04T09:00:00Z',
      updated_at: '2026-02-04T11:30:00Z',
    },
    {
      id: 'vod-2',
      title: '제121회 상임위원회',
      meeting_date: '2026-02-03',
      stream_url: null,
      vod_url: 'https://vod.example.com/121',
      status: 'processing',
      duration_seconds: 7200,
      created_at: '2026-02-03T09:00:00Z',
      updated_at: '2026-02-03T11:00:00Z',
    },
    {
      id: 'vod-3',
      title: '제120회 예산결산위원회',
      meeting_date: '2026-02-02',
      stream_url: null,
      vod_url: 'https://vod.example.com/120',
      status: 'ended',
      duration_seconds: 9000,
      subtitle_stage: 'ai',
      created_at: '2026-02-02T09:00:00Z',
      updated_at: '2026-02-02T11:30:00Z',
    },
  ];

  beforeEach(() => {
    mockPush.mockClear();
  });

  describe('카드 렌더링', () => {
    it('회의마다 카드를 하나씩 그린다', () => {
      render(<VodTable vods={mockVodList} />);

      expect(screen.getAllByTestId('meeting-card')).toHaveLength(3);
      expect(screen.getByText('제122회 본회의')).toBeInTheDocument();
      expect(screen.getByText('제121회 상임위원회')).toBeInTheDocument();
      expect(screen.getByText('제120회 예산결산위원회')).toBeInTheDocument();
    });

    it('날짜와 재생시간을 함께 보여준다', () => {
      render(<VodTable vods={mockVodList} />);

      expect(screen.getByText('2026-02-04')).toBeInTheDocument();
      expect(screen.getByText('1:30:00')).toBeInTheDocument(); // 5400초
      expect(screen.getByText('2:00:00')).toBeInTheDocument(); // 7200초
      expect(screen.getByText('2:30:00')).toBeInTheDocument(); // 9000초
    });

    it('재생시간이 없으면 "-"로 표시한다', () => {
      render(<VodTable vods={[{ ...mockVodList[0]!, duration_seconds: null }]} />);

      expect(screen.getByText('-')).toBeInTheDocument();
    });

    it('카드마다 4단계 진행바가 붙는다', () => {
      render(<VodTable vods={mockVodList} />);

      expect(screen.getAllByTestId('meeting-stage-progress')).toHaveLength(3);
    });
  });

  describe('단계 배지 (4단계 모델)', () => {
    /** 배지 텍스트만 모은다 — 단계바 라벨("AI 자막 완료" 등)과 글자가 겹치기 때문 */
    const badgeTexts = () =>
      screen.getAllByTestId('meeting-stage-badge').map((b) => b.textContent);

    it('세 회의의 단계가 각각 다르게 표시된다', () => {
      render(<VodTable vods={mockVodList} />);

      expect(badgeTexts()).toEqual([
        'VOD 등록됨', // vod-1: ended + vod_url, 자막 단계 미지정
        'AI 자막 생성 중', // vod-2: processing
        'AI 자막 완료', // vod-3: subtitle_stage=ai
      ]);
    });
  });

  describe('빈 상태', () => {
    it('회의가 없으면 안내 문구만 보여준다', () => {
      render(<VodTable vods={[]} />);

      expect(screen.getByText('등록된 VOD가 없습니다')).toBeInTheDocument();
      expect(screen.queryByTestId('meeting-card')).not.toBeInTheDocument();
    });
  });

  describe('카드 클릭 이동', () => {
    it('카드를 누르면 해당 회의로 이동한다', async () => {
      const user = userEvent.setup();
      render(<VodTable vods={mockVodList} />);

      await user.click(screen.getAllByTestId('meeting-card')[0]!);

      expect(mockPush).toHaveBeenCalledWith('/vod/vod-1');
    });

    it('다른 카드를 누르면 그 회의로 이동한다', async () => {
      const user = userEvent.setup();
      render(<VodTable vods={mockVodList} />);

      await user.click(screen.getAllByTestId('meeting-card')[1]!);

      expect(mockPush).toHaveBeenCalledWith('/vod/vod-2');
    });

    it('키보드(Enter)로도 열 수 있다', async () => {
      const user = userEvent.setup();
      render(<VodTable vods={mockVodList} />);

      const card = screen.getAllByTestId('meeting-card')[0]!;
      card.focus();
      await user.keyboard('{Enter}');

      expect(mockPush).toHaveBeenCalledWith('/vod/vod-1');
    });
  });

  describe('선택 모드 (관리자)', () => {
    it('AI 자막 생성 가능한 회의에만 체크박스가 붙는다', () => {
      render(<VodTable vods={mockVodList} selectable selectedIds={new Set()} />);

      // vod-1 만 후보 (vod-2 는 processing, vod-3 는 이미 AI 자막 완료)
      expect(screen.getByTestId('select-checkbox-vod-1')).toBeInTheDocument();
      expect(screen.queryByTestId('select-checkbox-vod-2')).not.toBeInTheDocument();
      expect(screen.queryByTestId('select-checkbox-vod-3')).not.toBeInTheDocument();
    });

    it('선택 모드가 아니면 체크박스가 없다', () => {
      render(<VodTable vods={mockVodList} />);

      expect(screen.queryByTestId('select-checkbox-vod-1')).not.toBeInTheDocument();
    });
  });

  describe('접근성', () => {
    it('카드는 키보드로 접근 가능한 버튼이다', () => {
      render(<VodTable vods={mockVodList} />);

      screen.getAllByTestId('meeting-card').forEach((card) => {
        expect(card).toHaveAttribute('role', 'button');
        expect(card).toHaveAttribute('tabindex', '0');
      });
    });

    it('카드에 회의 내용이 실제로 들어 있다 (빈 상자가 아니다)', () => {
      render(<VodTable vods={mockVodList} />);

      screen.getAllByTestId('meeting-card').forEach((card) => {
        expect((card.textContent ?? '').trim().length).toBeGreaterThan(0);
      });
      const first = screen.getAllByTestId('meeting-card')[0]!;
      expect(within(first).getByText('제122회 본회의')).toBeInTheDocument();
    });

    it('className 을 그대로 받는다', () => {
      const { container } = render(<VodTable vods={mockVodList} className="custom-class" />);

      expect(container.firstChild).toHaveClass('custom-class');
    });
  });
});
