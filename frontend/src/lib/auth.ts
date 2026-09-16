// 브라우저는 same-origin(basePath 접두)으로 호출 → k3s 는 Ingress, Vercel 은 rewrite 가 중계.
const API_URL =
  typeof window === 'undefined'
    ? process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
    : process.env.NEXT_PUBLIC_BASE_PATH || '';

export interface UserResponse {
  id: string;
  username: string;
  display_name: string;
  role: 'anonymous' | 'staff' | 'committee_staff' | 'meeting_manager' | 'stenographer' | 'admin';
  assigned_committee: string | null;
  is_active: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: UserResponse;
}

/**
 * 화면이 쓰는 역할 — 로그인 역할 + 로그인하지 않은 의회망 방문자(council_guest, 2026-09-11).
 * council_guest 는 서버가 발급하는 역할이 아니다: /api/auth/network 판정으로 화면이 붙이는 이름이고,
 * 서버는 요청마다 IP 로 다시 판정한다(require_role_or_council).
 */
export type EffectiveRole = UserResponse['role'] | 'council_guest';

export interface NetworkResponse {
  council_network: boolean;
  ip: string;
  /** 이 대역(의회사무처 직원 PC)에서는 로그인해야 서비스를 볼 수 있다 (2026-09-16) */
  login_required?: boolean;
  /** 앱 설치 안내 주소 */
  app_install_guide_url?: string;
}

/** 이 브라우저가 의회망에서 왔는가 — 실패하면 null(= 의회망 아님으로 본다) */
export async function getNetwork(): Promise<NetworkResponse | null> {
  try {
    const res = await fetch(`${API_URL}/api/auth/network`);
    if (!res.ok) return null;
    return (await res.json()) as NetworkResponse;
  } catch {
    return null;
  }
}

export function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('auth_token');
}

export function setToken(token: string): void {
  localStorage.setItem('auth_token', token);
}

export function clearToken(): void {
  localStorage.removeItem('auth_token');
}

// 아이디·비밀번호 로그인(`POST /api/auth/login`)은 2026-08-28 에 없앴다 —
// 화면·클라이언트·백엔드 라우터를 함께 걷어냈으므로 여기에 되살리지 말 것.
// 들어오는 길은 QR(createQrSession/pollQrSession)과 SSO 교환(ssoExchange) 둘뿐이다.
// 아래 pinLogin 은 로그인이 아니라 **관리 기능 앞의 별도 관문**이라 남아 있다.

/**
 * 빠른 관리자 PIN 로그인.
 * 정식 계정 없이 관리자 PIN (4자리)만으로 임시 admin JWT 발급.
 */
export async function pinLogin(pin: string): Promise<TokenResponse> {
  const res = await fetch(`${API_URL}/api/auth/pin-login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pin }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || 'PIN 로그인에 실패했습니다');
  }
  const data: TokenResponse = await res.json();
  setToken(data.access_token);
  return data;
}

export async function logout(): Promise<void> {
  clearToken();
}

// ── QR 로그인 (경기도의정포털 앱) ─────────────────────────────
// 세션 생성·폴링은 백엔드가 상류(모바일 로그인 서비스)로 중계한다.
// 세션은 5분 유효·1회용 — expired/unregistered 를 받으면 새 QR 을 발급해야 한다.

export interface QrSessionResponse {
  sessionId: string;
  apiUrl: string;
  ttl: number;
}

export type QrPollResponse =
  | { status: 'pending' }
  | { status: 'expired' }
  | { status: 'unregistered'; usercode?: string; user_name?: string; detail?: string }
  | ({ status: 'authenticated' } & TokenResponse);

export async function createQrSession(): Promise<QrSessionResponse> {
  const res = await fetch(`${API_URL}/api/auth/qr/session`, { method: 'POST' });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || 'QR 세션 발급에 실패했습니다');
  }
  return res.json() as Promise<QrSessionResponse>;
}

/** 폴링. authenticated 면 토큰을 저장한 뒤 반환한다. */
export async function pollQrSession(sessionId: string): Promise<QrPollResponse> {
  const res = await fetch(`${API_URL}/api/auth/qr/${encodeURIComponent(sessionId)}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || 'QR 상태 조회에 실패했습니다');
  }
  const data = (await res.json()) as QrPollResponse;
  if (data.status === 'authenticated') {
    setToken(data.access_token);
  }
  return data;
}

// ── SSO (플랫폼 통합 로그인 ggc-sso) ─────────────────────────
// 로그인 화면이 마운트될 때 **페이지당 1회** 호출한다. SSO 쿠키(__Host-ggc_sso)가
// 있으면 백엔드가 클러스터 내부 introspection 으로 확인하고 QR authenticated 와
// 같은 형태로 이 서비스 JWT 를 준다. 쿠키가 없으면 401 — 기존 QR 화면을 그대로 쓴다.

export type SsoExchangeResult =
  | ({ status: 'authenticated' } & TokenResponse)
  | { status: 'none'; login?: string } // 401 — SSO 세션 없음(통합 로그인 버튼 노출)
  | { status: 'unregistered'; usercode?: string; detail?: string } // 403 — 사용 불가 계정
  | { status: 'error' }; // 네트워크/기타 — QR 화면으로 폴백

/** SSO 쿠키 → 이 서비스 JWT 교환. authenticated 면 토큰을 저장한 뒤 반환한다. */
export async function ssoExchange(): Promise<SsoExchangeResult> {
  try {
    const res = await fetch(`${API_URL}/api/auth/sso`, { credentials: 'same-origin' });
    if (res.status === 401) {
      const body = await res.json().catch(() => ({}));
      return { status: 'none', login: body.login };
    }
    if (res.status === 403) {
      const body = await res.json().catch(() => ({}));
      return { status: 'unregistered', usercode: body.usercode, detail: body.detail };
    }
    if (!res.ok) return { status: 'error' };
    const data = await res.json();
    if (data?.status !== 'authenticated' || !data.access_token) return { status: 'error' };
    setToken(data.access_token);
    return data as { status: 'authenticated' } & TokenResponse;
  } catch {
    return { status: 'error' };
  }
}

export async function getMe(): Promise<UserResponse | null> {
  const token = getToken();
  if (!token) return null;
  const res = await fetch(`${API_URL}/api/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    clearToken();
    return null;
  }
  return res.json() as Promise<UserResponse>;
}
