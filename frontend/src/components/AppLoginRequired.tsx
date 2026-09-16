'use client';

import { useEffect, useRef } from 'react';

import Link from 'next/link';

import { useAuth } from '@/contexts/AuthContext';
import { logAccess } from '@/hooks/useAccessLog';

/**
 * 「모바일 의정지원서비스 앱으로 로그인해 주세요」 안내 화면 (2026-09-16 담당자 결정)
 *
 * 의회사무처 직원 PC 대역에서 **로그인하지 않고** 들어오면 서비스 대신 이 화면이 뜬다.
 * 2026-09-15 에는 같은 대역을 Traefik 이 아예 막아 "접속할 수 없습니다" 만 보여줬는데,
 * 막는 대신 **로그인 길을 안내**하도록 바꾼 것이다(앱이 없으면 설치 안내로 보낸다).
 *
 * 로그인하면 이 화면은 사라지고 서비스가 그대로 열린다.
 */
export default function AppLoginRequired() {
  const { appInstallGuideUrl } = useAuth();
  const logged = useRef(false);

  useEffect(() => {
    if (logged.current) return;
    logged.current = true;
    logAccess('login_prompt', { path: '/login-required' });
  }, []);

  return (
    <div
      className="min-h-screen flex items-center justify-center bg-bg px-4 py-10"
      data-testid="app-login-required"
    >
      <div className="w-full max-w-lg bg-surface border border-border rounded-2xl p-8 text-center shadow-sm">
        <div className="mx-auto mb-5 w-14 h-14 rounded-2xl bg-primary-10 flex items-center justify-center">
          <svg className="w-7 h-7 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.8}>
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M10.5 1.5H8.25A2.25 2.25 0 006 3.75v16.5a2.25 2.25 0 002.25 2.25h7.5A2.25 2.25 0 0018 20.25V3.75a2.25 2.25 0 00-2.25-2.25H13.5m-3 0V3h3V1.5m-3 0h3m-3 18.75h3"
            />
          </svg>
        </div>

        <h1 className="text-xl font-semibold text-text">
          모바일 의정지원서비스 앱으로 로그인해 주세요
        </h1>
        <p className="mt-3 text-sm text-text-secondary leading-relaxed">
          이 컴퓨터에서는 로그인한 뒤에 실시간 자막 서비스를 볼 수 있습니다.
          <br />
          휴대폰의 <strong>모바일 의정지원서비스</strong> 앱으로 QR 을 찍으면 바로 열립니다.
        </p>

        <Link
          href="/login"
          className="mt-6 inline-flex items-center justify-center w-full rounded-lg bg-primary px-5 py-3 text-sm font-medium text-white hover:bg-primary-dark focus-visible:ring-2 focus-visible:ring-primary"
          data-testid="app-login-required-login"
        >
          로그인하기 (QR 받기)
        </Link>

        <div className="mt-5 pt-5 border-t border-hairline text-sm text-text-secondary">
          앱이 아직 없으신가요?
          <a
            href={appInstallGuideUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="ml-1.5 font-medium text-primary hover:underline"
            data-testid="app-install-guide-link"
          >
            설치 방법 보기
          </a>
          <p className="mt-1 text-xs text-text-muted">
            설치 화면이 새 창으로 열립니다. 설치한 뒤 위 [로그인하기] 를 누르세요.
          </p>
        </div>
      </div>
    </div>
  );
}
