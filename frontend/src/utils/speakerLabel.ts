/**
 * 라이브 자막 화자 표기 유틸
 *
 * 실시간 방송 화면에서는 화자 실명 대신 기관 구분(도의원/집행부)만 표시한다.
 * 라이브 화자식별(회의 구조 추적 기반)은 오인식이 있어 잘못된 실명이 그대로
 * 나가는 것이 이름 없는 것보다 해롭다는 운영 판단(2026-07-22).
 * VOD AI 자막(사후 정밀 분석, 명부 기반)은 실명을 유지한다 — 이 유틸은
 * 라이브 화면 표시 전용이며 저장 데이터는 바꾸지 않는다.
 */

// 의회 구성원 직위 (도의원 판정)
const COUNCILOR_RE = /(위원장|부위원장|위원|의원|의장|부의장)\s*$/;
// 집행부(도청·교육청 등) 직책 (실명·직책 조합 라벨 포함)
const EXECUTIVE_RE =
  /(국장|과장|실장|단장|원장|본부장|부장|팀장|청장|서장|소장|센터장|차관|장관|교육감|지사|대변인|담당관)\s*$/;

/**
 * 화자 라벨 → 기관 구분 라벨.
 * 판정 불가(미상 '화자 N' 포함)는 null — 잘못된 표기 방지 취지상 숨긴다.
 */
export function coarsenLiveSpeaker(speaker?: string | null): string | null {
  if (!speaker) return null;
  const s = speaker.trim();
  if (!s) return null;
  if (s.startsWith('집행부')) return '집행부';
  // 의회 직위를 먼저 검사 — '위원장'이 집행부 패턴의 '원장'에 오매칭되는 것 방지
  if (COUNCILOR_RE.test(s)) return '도의원';
  if (EXECUTIVE_RE.test(s)) return '집행부';
  return null;
}
