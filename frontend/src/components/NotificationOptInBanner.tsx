'use client';

/**
 * NotificationOptInBanner — 방송 시작 알림 권한 안내 줄
 *
 * useChannelStatus 가 채널 상태 0→1 전환을 감지해 데스크톱 알림을 띄우는데,
 * 브라우저 권한이 'default' 인 동안에는 아무 일도 일어나지 않는다. 그 사실을
 * 알 방법이 화면에 없어서 안내와 요청 버튼을 대시보드에 둔다.
 *
 * - 권한을 이미 받았거나(granted) 거절했으면(denied) 렌더하지 않는다 — 거절한
 *   사람에게 계속 물으면 배너가 아니라 잔소리가 된다.
 * - 권한 상태는 useEffect 에서 읽는다(SSR 에는 Notification 이 없다).
 */

import React, { useEffect, useState } from 'react';

type PermissionState = NotificationPermission | 'unsupported' | 'unknown';

export default function NotificationOptInBanner() {
  const [permission, setPermission] = useState<PermissionState>('unknown');

  useEffect(() => {
    if (typeof window === 'undefined' || !('Notification' in window)) {
      setPermission('unsupported');
      return;
    }
    setPermission(Notification.permission);
  }, []);

  const handleRequest = async () => {
    if (typeof window === 'undefined' || !('Notification' in window)) return;
    try {
      setPermission(await Notification.requestPermission());
    } catch {
      // 권한 요청 실패(브라우저 정책 등)는 조용히 무시 — 배너는 그대로 남는다
    }
  };

  if (permission !== 'default') return null;

  return (
    // 2026-08-25 개선안 2d: 테두리 있는 배너 → **한 줄 안내**.
    // 알림 허용은 대시보드에서 가장 덜 급한 일인데 상자를 두르면 경고처럼 읽혔다.
    <p
      data-testid="notification-optin-banner"
      className="flex items-center gap-2 text-[13px] text-text-muted"
    >
      <svg
        className="h-[15px] w-[15px] shrink-0 text-text-dim"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="9.25" />
        <path strokeLinecap="round" d="M12 11v5.5M12 7.75h.01" />
      </svg>
      <span className="break-keep">
        방송이 시작될 때 알림을 받으려면{' '}
        <button
          type="button"
          onClick={handleRequest}
          data-testid="notification-optin-button"
          className="font-semibold text-primary underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          알림을 허용
        </button>
        하세요.
      </span>
    </p>
  );
}
