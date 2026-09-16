// 의회망 손님(로그인하지 않은 의회망 방문자, 2026-09-11)의 브라우저 표식.
// lib/auth 와 떼어 둔 이유: 로그인 화면 테스트들이 '@/lib/auth' 를 통째로 모킹해서, 거기 두면
// api.ts 의 apiClient 가 모킹된 undefined 를 부른다.

const GUEST_ID_KEY = 'guest_id';
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function randomUuid(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

/**
 * 의회망 손님의 브라우저 표식 — 백엔드가 추출 기록을 브라우저별로 가른다(헤더 X-Guest-Id).
 * 의회망은 NAT 뒤라 IP 로는 사람을 못 가른다. 개인정보가 아닌 무작위 값이다.
 */
export function getGuestId(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    let id = localStorage.getItem(GUEST_ID_KEY);
    if (!id || !UUID_RE.test(id)) {
      id = randomUuid();
      localStorage.setItem(GUEST_ID_KEY, id);
    }
    return id;
  } catch {
    return null;
  }
}

/** 로그인하지 않았을 때만 붙는 손님 헤더 */
export function guestHeaders(token: string | null): Record<string, string> {
  if (token) return {};
  const gid = getGuestId();
  return gid ? { 'X-Guest-Id': gid } : {};
}
