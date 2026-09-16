/**
 * 회의 자막 처리 3단계 모델 — 대시보드·회의 목록·회의 상세가 공유하는 유일한 정본.
 *
 *   ① 실시간 자막 → ② VOD 등록 → ③ AI 자막 생성 완료
 *
 * 2026-08-22 사용자 지시로 4단계에서 3단계로 줄였다. 'AI 자막 생성'과 'AI 자막 완료'가
 * 따로 있으면 칸은 둘인데 실제로는 한 작업의 진행/끝이라 읽는 사람이 헷갈린다.
 * 생성 중은 마지막 칸의 '진행 중' 상태(주황)로 표현한다.
 *
 * 예전에는 화면마다 다른 라벨("라이브 자막 (AI 생성 전)"·"AI 자막 생성 전"·"자막 대기" …)을
 * 써서 같은 회의가 화면마다 다르게 보였다. 라벨·색·순서를 여기 한 곳에서만 정한다.
 *
 * 배지 라벨(statusLabel)과 안내 문구(guidance)는 다른 것이다:
 *   - statusLabel — "지금 어느 단계인가" (예: 실시간 자막(초안))
 *   - guidance    — "다음에 무엇을 해야 하는가" (예: VOD를 등록하면 AI 자막을 생성할 수 있습니다)
 */

import type { MeetingType } from '@/types';

export type MeetingStageKey = 'live' | 'vod' | 'ai_done';

/** 단계 노드의 표시 상태 — 지난 단계 / 현재 단계 / 아직 안 온 단계 */
export type StageNodeState = 'done' | 'current' | 'pending';

/** 배지·노드 색 계열 */
export type StageTone = 'live' | 'brand' | 'warning' | 'success' | 'neutral';

/** 목록 상태 필터 칩 키 — 'waiting'(자막·VOD 둘 다 없음)은 [전체]에만 잡힌다 */
export type StageFilterKey = 'live' | 'vod' | 'ai_generating' | 'ai_done' | 'waiting';

export interface MeetingStageDef {
  key: MeetingStageKey;
  /** 단계바 아래 라벨 */
  label: string;
  /** 단계 설명 — 툴팁·이용 안내에 쓴다 */
  description: string;
}

export const MEETING_STAGES: readonly MeetingStageDef[] = [
  {
    key: 'live',
    label: '실시간 자막',
    description: '회의 중 실시간으로 자막이 생성되는 단계입니다. 빠른 대신 초안이라 오인식이 있을 수 있습니다.',
  },
  {
    key: 'vod',
    label: 'VOD 등록',
    description: '회의 영상(VOD)이 시스템에 등록된 단계입니다. 등록되어야 AI 자막을 생성할 수 있습니다.',
  },
  {
    key: 'ai_done',
    label: 'AI 자막 생성 완료',
    description:
      'AI가 VOD 음성을 다시 분석해 만든 최종 자막입니다. 화자 구분과 정확도가 가장 높습니다. 생성 중에는 이 칸이 진행 중으로 표시됩니다.',
  },
] as const;

export interface MeetingStageInfo {
  /** MEETING_STAGES 와 같은 순서의 4칸 */
  states: StageNodeState[];
  /** 현재 단계 인덱스 (0~3) */
  currentIndex: number;
  /** 배지 라벨 — "지금 어느 단계인가" */
  statusLabel: string;
  tone: StageTone;
  /** 상세 화면 안내 배너 — "다음에 무엇을 해야 하는가" */
  guidance: string;
  /** 목록 상태 칩 매칭 키 */
  filterKey: StageFilterKey;
  /** 생중계 진행 중 — 배지에 점멸 점을 붙인다 */
  isLive: boolean;
}

type StageSource = Pick<MeetingType, 'status'> &
  Partial<Pick<MeetingType, 'subtitle_stage' | 'vod_url'>>;

/** AI 자막이 만들어진 상태 — 속기사 검토·확정도 AI 자막 완료에 포함한다 */
export function hasAiSubtitle(meeting: StageSource): boolean {
  const stage = meeting.subtitle_stage ?? 'none';
  return stage === 'ai' || stage === 'reviewing' || stage === 'final';
}

/** 발언영상 화면의 「의원 구분」 상태 — 그 회의에 의원별 발언 구간이 있는가 */
export interface ClipIndexStatus {
  ready: boolean;
  /** 목록 배지 라벨 */
  label: string;
  /** 배지 툴팁 — 왜 그런지, 그러면 무엇을 하면 되는지 */
  hint: string;
}

/**
 * 발언영상(clips) 화면에서 쓸 수 있는 회의인지.
 *
 * ★설치형 프로그램(`ggc-extractor` webui/app.html 의 indexBadge)이 회의 목록에
 * 같은 배지를 그린다 — 담당자가 두 화면을 오가므로 **같은 말을 해야 한다.**
 * 한쪽만 고치지 말 것. 판정 근거도 같다(AI 자막 완료 + 영상 등록).
 * 공식 영상회의록 인덱스는 회의 행의 값으로 알 수 없어 이 판정은 보수적이다 —
 * 회의를 열면 실제 인덱스가 나오므로 화면에서 바로잡힌다.
 */
export function getClipIndexStatus(meeting: StageSource): ClipIndexStatus {
  if (!meeting.vod_url) {
    return {
      ready: false,
      label: '영상 등록 전',
      hint: 'VOD 가 아직 등록되지 않았습니다 — 보통 회의 다음 날 오전에 자동 등록됩니다',
    };
  }
  if (hasAiSubtitle(meeting)) {
    return { ready: true, label: '의원 구분 완료', hint: '의원별 발언 구간이 준비돼 있습니다' };
  }
  return {
    ready: false,
    label: '의원 구분 아직',
    hint: 'AI 자막이 만들어지면 의원별 발언 구간이 생깁니다 — 그 전에는 시작·종료를 직접 지정해 자르세요',
  };
}

/**
 * 회의 하나의 4단계 상태를 산출한다.
 *
 * 판정 순서가 곧 우선순위다 — 생중계 > AI 완료 > AI 생성 중 > VOD 등록 > 실시간 자막 > 대기.
 */
export function getMeetingStage(meeting: StageSource): MeetingStageInfo {
  const stage = meeting.subtitle_stage ?? 'none';
  const hasAi = hasAiSubtitle(meeting);
  const hasDraft = stage === 'draft' || hasAi;
  const hasVod = !!meeting.vod_url;

  const build = (
    currentIndex: number,
    statusLabel: string,
    tone: StageTone,
    guidance: string,
    filterKey: StageFilterKey,
    opts: { allDone?: boolean; isLive?: boolean } = {},
  ): MeetingStageInfo => ({
    states: MEETING_STAGES.map((_, i) => {
      if (opts.allDone) return 'done' as StageNodeState;
      if (i < currentIndex) return 'done' as StageNodeState;
      if (i === currentIndex) return 'current' as StageNodeState;
      return 'pending' as StageNodeState;
    }),
    currentIndex,
    statusLabel,
    tone,
    guidance,
    filterKey,
    isLive: !!opts.isLive,
  });

  if (meeting.status === 'live') {
    return build(
      0,
      '실시간 자막 생성 중',
      'live',
      '회의가 진행 중입니다. 실시간 자막(초안)이 만들어지고 있습니다.',
      'live',
      { isLive: true },
    );
  }

  if (hasAi) {
    return build(
      2,
      'AI 자막 완료',
      'success',
      'AI 자막이 완료되었습니다. 최종 자막을 확인하고 내려받을 수 있습니다.',
      'ai_done',
      { allDone: true },
    );
  }

  if (meeting.status === 'processing') {
    // 마지막 칸이 '진행 중'이다 — 생성과 완료를 따로 두지 않는다(3단계 모델).
    return build(
      2,
      'AI 자막 생성 중',
      'warning',
      'AI가 VOD 음성을 분석하고 있습니다. 회의당 약 10분이 걸리며, 이 화면을 닫아도 서버에서 계속 진행됩니다.',
      'ai_generating',
    );
  }

  if (hasVod) {
    return build(
      1,
      'VOD 등록됨',
      'brand',
      'VOD가 등록되었습니다. 정교한 최종 자막(AI 자막)이 자동으로 순서대로 만들어집니다 — 회의당 약 10~20분.',
      'vod',
    );
  }

  if (hasDraft) {
    return build(
      0,
      '실시간 자막(초안)',
      'brand',
      '실시간 자막(초안)이 완료되었습니다. VOD가 의회 홈페이지에 올라오면 자동으로 등록되고, 이어서 AI 자막이 자동으로 만들어집니다.',
      'live',
    );
  }

  return build(
    0,
    'VOD 등록 대기',
    'neutral',
    '아직 자막도 VOD도 없습니다. 회의 영상이 등록되면 다음 단계로 진행할 수 있습니다.',
    'waiting',
  );
}

/** 배지 색 — tone 하나로 배경·글자를 함께 정한다 */
export const STAGE_TONE_CLASS: Record<StageTone, string> = {
  live: 'bg-live/10 text-live',
  brand: 'bg-primary-5 text-brand',
  warning: 'bg-warning-bg/15 text-warning-dark',
  success: 'bg-success/10 text-success',
  neutral: 'bg-gray-100 text-gray-600',
};

/** 단계 노드(원) 색 — 현재 단계에만 tone 색을 칠한다 */
export const STAGE_NODE_CLASS: Record<StageTone, string> = {
  live: 'bg-live text-white',
  brand: 'bg-primary text-white',
  warning: 'bg-warning-bg text-gray-900',
  success: 'bg-success text-white',
  neutral: 'bg-gray-400 text-white',
};

/** 목록 상태 칩 정의 — 순서가 곧 화면 순서 */
export const STAGE_FILTERS: readonly { key: StageFilterKey; label: string }[] = [
  { key: 'live', label: '실시간' },
  { key: 'vod', label: 'VOD' },
  { key: 'ai_generating', label: 'AI 생성 중' },
  { key: 'ai_done', label: 'AI 완료' },
] as const;

/* ===========================================================================
 * 목록용 2칸 요약 — 회의 목록(/vod)에서만 쓴다
 *
 * 3단계 모델은 그대로 두되, **목록에서는 두 칸만 보여준다**(2026-08-25 개선안 2f).
 * 중간 단계(VOD 등록 · AI 자막 생성)는 이용자가 할 일이 없는 내부 처리다. 그것까지
 * 칸으로 세우면 카드 6개마다 10px 라벨이 24개 깔려 정작 회의명을 덮는다.
 * 관리자는 /admin 과 회의 상세에서 3단계 전부를 본다.
 *
 * 단계 이름은 목록 **머리 범례에 한 번만** 나오고, 각 행은 배지(현재 단계) +
 * 2칸 막대(어디까지 왔나)로 줄인다.
 * =========================================================================== */

/** 막대 한 칸의 상태 — 비어 있음 / 생중계 중 / 진행 중 / 끝남 */
export type ListSegmentTone = 'empty' | 'live' | 'progress' | 'done';

export interface ListStageLegendItem {
  key: 'live' | 'ai_done';
  /** 범례에 적히는 짧은 이름 */
  name: string;
  /** ⓘ 툴팁 — 이 칸이 무엇인지 한 문장 */
  tip: string;
}

export const LIST_STAGE_LEGEND: readonly ListStageLegendItem[] = [
  {
    key: 'live',
    name: '실시간',
    tip: '회의가 방송되는 동안 실시간 자막이 생성되는 단계입니다. 붉은 칸이 채워져 있으면 지금 방송 중입니다.',
  },
  {
    key: 'ai_done',
    name: 'AI 완료',
    tip: '회의 종료 후 AI 자막 생성까지 끝나 회의록으로 쓸 수 있는 단계입니다. 두 칸이 모두 초록이면 완료입니다.',
  },
] as const;

/** 막대 칸 색 — 채운 칸만 색을 갖는다 */
export const LIST_SEGMENT_CLASS: Record<ListSegmentTone, string> = {
  empty: 'bg-gray-100',
  live: 'bg-live',
  progress: 'bg-warning-bg',
  done: 'bg-success',
};

/**
 * 회의 하나를 목록용 2칸으로 요약한다.
 *
 *   ① 실시간  — 방송 중이면 빨강, 초안이 이미 있으면 초록, 아무것도 없으면 빈 칸
 *   ② AI 완료 — 완료면 초록, 생성 중이면 주황, 아니면 빈 칸
 */
export function getListSegments(meeting: StageSource): ListSegmentTone[] {
  const stage = meeting.subtitle_stage ?? 'none';
  const hasAi = hasAiSubtitle(meeting);
  const hasDraft = stage === 'draft' || hasAi;
  const isLive = meeting.status === 'live';

  const first: ListSegmentTone = isLive ? 'live' : hasDraft ? 'done' : 'empty';
  const second: ListSegmentTone = hasAi
    ? 'done'
    : meeting.status === 'processing'
      ? 'progress'
      : 'empty';

  return [first, second];
}
