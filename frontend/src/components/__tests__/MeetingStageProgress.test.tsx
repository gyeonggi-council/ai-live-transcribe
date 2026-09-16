import { render, screen } from '@testing-library/react';

import type { MeetingType } from '@/types';

import MeetingStageBadge from '../MeetingStageBadge';
import MeetingStageProgress from '../MeetingStageProgress';

const base: Pick<MeetingType, 'status'> &
  Partial<Pick<MeetingType, 'subtitle_stage' | 'vod_url'>> = {
  status: 'ended',
  subtitle_stage: 'none',
  vod_url: null,
};

describe('MeetingStageProgress', () => {
  it('세 단계를 시안 순서대로 그린다', () => {
    render(<MeetingStageProgress meeting={base} />);

    expect(screen.getByText('실시간 자막')).toBeInTheDocument();
    expect(screen.getByText('VOD 등록')).toBeInTheDocument();
    expect(screen.getByText('AI 자막 생성 완료')).toBeInTheDocument();
  });

  it('VOD 등록된 회의는 2단계 노드가 현재 단계다', () => {
    render(
      <MeetingStageProgress
        meeting={{ ...base, subtitle_stage: 'draft', vod_url: 'https://kms/a.mp4' }}
      />,
    );

    expect(screen.getByTestId('stage-node-live')).toHaveAttribute('data-state', 'done');
    expect(screen.getByTestId('stage-node-vod')).toHaveAttribute('data-state', 'current');
    expect(screen.getByTestId('stage-node-ai_done')).toHaveAttribute('data-state', 'pending');
  });

  it('AI 자막 완료 회의는 세 단계가 모두 완료다', () => {
    render(
      <MeetingStageProgress
        meeting={{ ...base, subtitle_stage: 'ai', vod_url: 'https://kms/a.mp4' }}
      />,
    );

    ['live', 'vod', 'ai_done'].forEach((key) => {
      expect(screen.getByTestId(`stage-node-${key}`)).toHaveAttribute('data-state', 'done');
    });
  });

  it('진행 단계를 접근성 라벨로도 알린다', () => {
    render(<MeetingStageProgress meeting={{ ...base, status: 'processing' }} />);

    expect(screen.getByTestId('meeting-stage-progress')).toHaveAttribute(
      'aria-label',
      '자막 처리 단계: AI 자막 생성 중',
    );
  });

  it('hideLabels 면 라벨 없이 노드만 그린다 (좁은 자리용)', () => {
    render(<MeetingStageProgress meeting={base} hideLabels />);

    expect(screen.queryByText('AI 자막 생성 완료')).not.toBeInTheDocument();
    expect(screen.getByTestId('stage-node-live')).toBeInTheDocument();
  });

  // 목록(/vod)은 2칸 막대만 쓴다 — 단계 이름은 목록 머리 범례에 한 번만 나온다.
  describe('variant="segments" (회의 목록 행)', () => {
    it('이름 없이 두 칸만 그린다', () => {
      render(<MeetingStageProgress meeting={base} variant="segments" />);

      expect(screen.getByTestId('stage-segment-live')).toBeInTheDocument();
      expect(screen.getByTestId('stage-segment-ai_done')).toBeInTheDocument();
      expect(screen.queryByText('실시간 자막')).not.toBeInTheDocument();
      expect(screen.queryByTestId('stage-node-live')).not.toBeInTheDocument();
    });

    it('생중계 중이면 첫 칸이 라이브, 둘째 칸이 빈 칸이다', () => {
      render(<MeetingStageProgress meeting={{ ...base, status: 'live' }} variant="segments" />);

      expect(screen.getByTestId('stage-segment-live')).toHaveAttribute('data-tone', 'live');
      expect(screen.getByTestId('stage-segment-ai_done')).toHaveAttribute('data-tone', 'empty');
    });

    it('완료 회의는 두 칸이 모두 채워진다', () => {
      render(
        <MeetingStageProgress
          meeting={{ ...base, subtitle_stage: 'ai', vod_url: 'https://kms/a.mp4' }}
          variant="segments"
        />,
      );

      expect(screen.getByTestId('stage-segment-live')).toHaveAttribute('data-tone', 'done');
      expect(screen.getByTestId('stage-segment-ai_done')).toHaveAttribute('data-tone', 'done');
    });
  });
});

describe('MeetingStageBadge', () => {
  it('단계 라벨을 그대로 보여준다', () => {
    render(
      <MeetingStageBadge
        meeting={{ ...base, subtitle_stage: 'draft', vod_url: 'https://kms/a.mp4' }}
      />,
    );

    expect(screen.getByTestId('meeting-stage-badge')).toHaveTextContent('VOD 등록됨');
  });

  it('생중계 중에는 진행 단계와 라이브 표시가 함께 나온다', () => {
    render(<MeetingStageBadge meeting={{ ...base, status: 'live' }} />);

    const badge = screen.getByTestId('meeting-stage-badge');
    expect(badge).toHaveTextContent('실시간 자막 생성 중');
    expect(badge).toHaveAttribute('data-stage', 'live');
  });
});
