// AI 어시스턴트 접근 역할 — 백엔드 core/auth_middleware.AI_ROLES 와 짝(2026-09-14). 한쪽만 고치지 말 것.
// lib/auth 와 떼어 둔 이유는 lib/guest.ts 와 같다: 로그인 화면 테스트들이 '@/lib/auth' 를 통째로 모킹한다.
//
// staff 가 들어간 이유 — 의정포털 QR 로 들어온 의원은 staff 다(portal_role.PORTAL_ROLE_MAP). 빠져 있던 동안
// 의원이 AI 메뉴를 못 봤다. council_guest 는 로그인하지 않은 의회망 방문자(집행부 직원 등, 2026-09-11).
import type { EffectiveRole } from '@/lib/auth';

export const AI_ROLES: readonly EffectiveRole[] = [
  'staff',
  'committee_staff',
  'meeting_manager',
  'stenographer',
  'admin',
  'council_guest',
];

export function canUseAi(role: EffectiveRole | string | null | undefined): boolean {
  return Boolean(role) && (AI_ROLES as readonly string[]).includes(role as string);
}
