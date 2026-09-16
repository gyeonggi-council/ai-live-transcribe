import type { MeetingType } from '@/types';
import { LIST_STAGE_LEGEND, MEETING_STAGES, getListSegments, getMeetingStage } from '@/utils/meetingStage';

type StageSource = Pick<MeetingType, 'status'> &
  Partial<Pick<MeetingType, 'subtitle_stage' | 'vod_url'>>;

const meeting = (over: Partial<StageSource> = {}): StageSource => ({
  status: 'ended',
  subtitle_stage: 'none',
  vod_url: null,
  ...over,
});

describe('getMeetingStage — 자막 처리 3단계', () => {
  it('3단계 정의는 시안 순서를 지킨다', () => {
    expect(MEETING_STAGES.map((s) => s.key)).toEqual(['live', 'vod', 'ai_done']);
  });

  it('생중계 중이면 1단계가 현재 단계이고 라이브로 표시된다', () => {
    const info = getMeetingStage(meeting({ status: 'live', subtitle_stage: 'draft' }));

    expect(info.currentIndex).toBe(0);
    expect(info.states).toEqual(['current', 'pending', 'pending']);
    expect(info.isLive).toBe(true);
    expect(info.tone).toBe('live');
    expect(info.filterKey).toBe('live');
  });

  it('실시간 자막만 있고 VOD가 없으면 1단계에 머문다', () => {
    const info = getMeetingStage(meeting({ subtitle_stage: 'draft' }));

    expect(info.currentIndex).toBe(0);
    expect(info.statusLabel).toBe('실시간 자막(초안)');
    // 안내는 '지금 어느 단계인가'가 아니라 '다음에 무엇이 필요한가'를 말한다
    expect(info.guidance).toContain('자동으로 등록');
    expect(info.filterKey).toBe('live');
  });

  it('VOD가 등록되면 2단계로 넘어간다', () => {
    const info = getMeetingStage(
      meeting({ subtitle_stage: 'draft', vod_url: 'https://kms.example/a.mp4' }),
    );

    expect(info.currentIndex).toBe(1);
    expect(info.states).toEqual(['done', 'current', 'pending']);
    expect(info.statusLabel).toBe('VOD 등록됨');
    expect(info.filterKey).toBe('vod');
    // 관리자가 누를 일이 아니다 — VOD 가 등록되면 서버가 알아서 만든다 (2026-09-10)
    expect(info.guidance).toContain('자동으로');
    expect(info.guidance).not.toContain('요청하면');
  });

  it('AI 자막 생성 중이면 마지막 단계가 진행 중이다 (생성과 완료를 따로 두지 않는다)', () => {
    const info = getMeetingStage(
      meeting({ status: 'processing', vod_url: 'https://kms.example/a.mp4' }),
    );

    expect(info.currentIndex).toBe(2);
    expect(info.states).toEqual(['done', 'done', 'current']);
    expect(info.statusLabel).toBe('AI 자막 생성 중');
    expect(info.tone).toBe('warning');
    expect(info.filterKey).toBe('ai_generating');
  });

  it.each(['ai', 'reviewing', 'final'] as const)(
    'subtitle_stage=%s 는 세 단계 모두 완료로 본다 (속기사 검토·확정 포함)',
    (stage) => {
      const info = getMeetingStage(
        meeting({ subtitle_stage: stage, vod_url: 'https://kms.example/a.mp4' }),
      );

      expect(info.states).toEqual(['done', 'done', 'done']);
      expect(info.statusLabel).toBe('AI 자막 완료');
      expect(info.filterKey).toBe('ai_done');
    },
  );

  it('생중계는 AI 자막이 있어도 생중계가 우선이다', () => {
    // 지난 회의의 AI 자막이 남은 채 같은 회의가 다시 생중계될 수 있다
    const info = getMeetingStage(meeting({ status: 'live', subtitle_stage: 'ai' }));

    expect(info.isLive).toBe(true);
    expect(info.currentIndex).toBe(0);
  });

  it('자막도 VOD도 없으면 어떤 상태 칩에도 잡히지 않는다', () => {
    const info = getMeetingStage(meeting());

    expect(info.statusLabel).toBe('VOD 등록 대기');
    expect(info.filterKey).toBe('waiting');
    expect(info.tone).toBe('neutral');
  });
});

/**
 * 목록 전용 2칸 요약 (2026-08-25 개선안 2f).
 * 3단계 모델은 그대로 두고, /vod 목록에서만 두 칸으로 접어 보여준다.
 */
describe('getListSegments — 목록용 2칸', () => {
  it('범례는 두 칸이고 각 칸에 설명 툴팁이 붙는다', () => {
    expect(LIST_STAGE_LEGEND.map((l) => l.key)).toEqual(['live', 'ai_done']);
    LIST_STAGE_LEGEND.forEach((l) => expect(l.tip.length).toBeGreaterThan(10));
  });

  it('생중계 중이면 첫 칸이 빨강이고 둘째 칸은 비어 있다', () => {
    expect(getListSegments(meeting({ status: 'live', subtitle_stage: 'draft' }))).toEqual([
      'live',
      'empty',
    ]);
  });

  it('AI 자막 완료면 두 칸이 모두 채워진다', () => {
    expect(
      getListSegments(meeting({ subtitle_stage: 'ai', vod_url: 'https://kms.example/a.mp4' })),
    ).toEqual(['done', 'done']);
  });

  it('AI 생성 중이면 둘째 칸이 진행 중이다', () => {
    expect(
      getListSegments(meeting({ status: 'processing', vod_url: 'https://kms.example/a.mp4' })),
    ).toEqual(['empty', 'progress']);
  });

  it('자막도 VOD도 없으면 두 칸 모두 비어 있다', () => {
    expect(getListSegments(meeting())).toEqual(['empty', 'empty']);
  });
});
