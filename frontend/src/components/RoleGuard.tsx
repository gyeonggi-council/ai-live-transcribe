'use client';

import type { ReactNode } from 'react';

import { useAuth } from '@/contexts/AuthContext';

// @TASK P11A-S0-T3 - RoleGuard 컴포넌트

interface RoleGuardProps {
  roles: string[];
  children: ReactNode;
  fallback?: ReactNode;
}

export default function RoleGuard({ roles, children, fallback }: RoleGuardProps) {
  const { user, loading, councilNetwork } = useAuth();
  if (loading) return null;
  // 로그인하지 않은 의회망 방문자는 'council_guest' — roles 에 그 이름이 있는 화면만 열린다(2026-09-11)
  const role = user?.role ?? (councilNetwork ? 'council_guest' : null);
  if (!role || !roles.includes(role)) {
    return fallback ?? (
      <div className="p-8 text-center text-text-muted">접근 권한이 없습니다.</div>
    );
  }
  return <>{children}</>;
}
