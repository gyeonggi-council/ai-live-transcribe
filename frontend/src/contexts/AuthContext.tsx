'use client';

import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';

import { getMe, getNetwork, logout as authLogout, pinLogin as authPinLogin } from '@/lib/auth';
import type { EffectiveRole, TokenResponse, UserResponse } from '@/lib/auth';

interface AuthContextType {
  user: UserResponse | null;
  loading: boolean;
  /** 의회망에서 온 브라우저인가 (/api/auth/network — 판정은 서버가 한다, 2026-09-11) */
  councilNetwork: boolean;
  /**
   * 이 브라우저는 로그인해야 서비스를 볼 수 있는가 (2026-09-16 담당자 결정).
   * 의회사무처 직원 PC 대역 — 예전에는 Traefik 이 아예 막았고, 막는 대신 앱 로그인 안내를 띄운다.
   */
  loginRequired: boolean;
  /** 앱 설치 안내 주소 (서버가 준다) */
  appInstallGuideUrl: string;
  /**
   * 화면 판정용 역할 — 로그인했으면 그 역할, 아니면 의회망이면 'council_guest', 그 밖엔 'anonymous'.
   * 사이드바·RoleGuard 가 이것 하나로 가른다. 서버는 요청마다 IP 로 다시 판정한다.
   */
  effectiveRole: EffectiveRole;
  error: string | null;
  pinLogin: (pin: string) => Promise<void>;
  /** 토큰이 이미 저장된 로그인 결과(QR 로그인 등)를 컨텍스트에 반영한다. */
  adoptSession: (res: TokenResponse) => void;
  logout: () => void;
}

/** 서버가 값을 주지 못했을 때 쓰는 앱 설치 안내 주소(2026-09-16 담당자 제공) */
const DEFAULT_APP_INSTALL_GUIDE_URL = 'https://ggc-install-video.vercel.app/';

export const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [councilNetwork, setCouncilNetwork] = useState(false);
  const [loginRequired, setLoginRequired] = useState(false);
  const [appInstallGuideUrl, setAppInstallGuideUrl] = useState(DEFAULT_APP_INSTALL_GUIDE_URL);

  useEffect(() => {
    // 둘 다 끝나야 loading 을 푼다 — 의회망 판정 전에 RoleGuard 가 "로그인이 필요합니다" 를 잠깐 띄우지 않게
    Promise.allSettled([
      getMe().then((u) => setUser(u)),
      getNetwork().then((n) => {
        setCouncilNetwork(Boolean(n?.council_network));
        setLoginRequired(Boolean(n?.login_required));
        if (n?.app_install_guide_url) setAppInstallGuideUrl(n.app_install_guide_url);
      }),
    ]).finally(() => setLoading(false));
  }, []);

  const pinLogin = useCallback(async (pin: string) => {
    setError(null);
    try {
      const res = await authPinLogin(pin);
      setUser(res.user);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'PIN 로그인 실패');
      throw e;
    }
  }, []);

  const adoptSession = useCallback((res: TokenResponse) => {
    setError(null);
    setUser(res.user);
  }, []);

  const logout = useCallback(() => {
    authLogout();
    setUser(null);
    // 플랫폼 통합 로그아웃(ggc_sso/docs/integrate.md §4-⑤) — 로컬 토큰을 지운 뒤
    // SSO 세션도 끝낸다. SSO 쿠키(__Host-ggc_sso)는 이 서비스가 지우지 않는다 —
    // 삭제는 /sso/logout 이 하고, 끝나면 /transcribe/ 로 돌아온다.
    if (typeof window !== 'undefined') {
      window.location.href = '/sso/logout?next=/transcribe/';
    }
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        councilNetwork,
        loginRequired,
        appInstallGuideUrl,
        effectiveRole: user?.role ?? (councilNetwork ? 'council_guest' : 'anonymous'),
        error,
        pinLogin,
        adoptSession,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
