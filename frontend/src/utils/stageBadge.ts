import type { MeetingType } from '@/types';

/**
 * 속기·교정 워크큐(StageWorkQueue) 전용 그룹핑.
 *
 * ★화면에 보이는 자막 처리 단계·라벨·색은 여기가 아니라 `@/utils/meetingStage` 가 정본이다.
 *   예전에는 이 파일에도 3단계 모델(getStageBadge·WORKFLOW_STEPS)이 있어서 화면마다
 *   같은 회의가 다른 이름으로 보였다(2026-08-22 4단계로 통일하며 제거).
 *   여기 남은 것은 '속기사 작업 대기열'을 나누는 내부 분류뿐이다.
 *
 *  초안 | AI 자막 대기 | 속기사 교정 중 | 교정 완료
 */
export type StageGroupKey = 'draft' | 'ai_waiting' | 'reviewing' | 'final';

export function groupByStage(vods: MeetingType[]): Record<StageGroupKey, MeetingType[]> {
  const groups: Record<StageGroupKey, MeetingType[]> = {
    draft: [],
    ai_waiting: [],
    reviewing: [],
    final: [],
  };
  for (const v of vods) {
    const stage = v.subtitle_stage ?? 'none';
    if (stage === 'final') {
      groups.final.push(v);
    } else if (stage === 'reviewing' || stage === 'ai') {
      // AI 자막은 속기사 교정 대기 상태. AI 생성 완료된 것은 reviewing 그룹에 포함.
      groups.reviewing.push(v);
    } else if (stage === 'draft') {
      groups.draft.push(v);
    } else if (stage === 'none' && v.vod_url) {
      groups.ai_waiting.push(v);
    }
    // none + !vod_url (VOD 대기)는 어떤 그룹에도 안 들어감 — 아직 워크플로우 시작 전
  }
  return groups;
}
