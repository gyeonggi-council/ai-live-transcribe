'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';

import { useRouter } from 'next/navigation';

import { useSidebar } from '@/contexts/SidebarContext';
import { getNotifications, markNotificationRead } from '@/lib/api';
import type { NotificationType } from '@/types';

function formatRelativeTime(dateString: string): string {
  const now = new Date();
  const date = new Date(dateString);
  const diffInSeconds = Math.floor((now.getTime() - date.getTime()) / 1000);

  if (diffInSeconds < 60) {
    return '방금 전';
  }
  if (diffInSeconds < 3600) {
    const minutes = Math.floor(diffInSeconds / 60);
    return `${minutes}분 전`;
  }
  if (diffInSeconds < 86400) {
    const hours = Math.floor(diffInSeconds / 3600);
    return `${hours}시간 전`;
  }
  const days = Math.floor(diffInSeconds / 86400);
  return `${days}일 전`;
}

/**
 * GlobalNavControls — 전역 내비게이션 컨트롤 (모바일 햄버거 + 알림 + 검색)
 *
 * 상단 헤더 바를 제거하고, 이 컨트롤을 PlatformLayout이 우측 상단에 띄워
 * 각 페이지의 제목 줄과 같은 높이에 표시한다.
 */
export default function GlobalNavControls() {
  const { setMobileOpen } = useSidebar();
  const router = useRouter();

  const [notifications, setNotifications] = useState<NotificationType[]>([]);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const unreadCount = notifications.filter((n) => !n.is_read).length;

  const loadNotifications = useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await getNotifications(20);
      setNotifications(data);
    } catch (error) {
      console.error('알림 조회 실패:', error);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadNotifications();
    const interval = setInterval(() => {
      void loadNotifications();
    }, 60000); // 1분마다 갱신

    return () => clearInterval(interval);
  }, [loadNotifications]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsDropdownOpen(false);
      }
    }

    if (isDropdownOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isDropdownOpen]);

  // 글로벌 단축키: Cmd/Ctrl+K → 통합 검색
  useEffect(() => {
    function handleGlobalKeydown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        const target = e.target as HTMLElement;
        if (
          target instanceof HTMLInputElement ||
          target instanceof HTMLTextAreaElement ||
          target.isContentEditable
        ) {
          return;
        }
        e.preventDefault();
        router.push('/search');
      }
    }
    window.addEventListener('keydown', handleGlobalKeydown);
    return () => window.removeEventListener('keydown', handleGlobalKeydown);
  }, [router]);

  const handleNotificationClick = async (notification: NotificationType) => {
    if (!notification.is_read) {
      try {
        await markNotificationRead(notification.id);
        setNotifications((prev) =>
          prev.map((n) => (n.id === notification.id ? { ...n, is_read: true } : n))
        );
      } catch (error) {
        console.error('알림 읽음 처리 실패:', error);
      }
    }

    if (notification.related_meeting_id) {
      setIsDropdownOpen(false);
      router.push(`/vod/${notification.related_meeting_id}`);
    }
  };

  return (
    <div data-testid="global-nav-controls" className="flex items-center gap-2">
      {/* 모바일 햄버거 메뉴 */}
      <button
        className="lg:hidden p-1.5 text-text-muted hover:text-text-secondary hover:bg-gray-100 rounded-md transition-colors"
        onClick={() => setMobileOpen(true)}
        aria-label="메뉴 열기"
      >
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
        </svg>
      </button>

      {/* 알림 드롭다운 */}
      <div ref={dropdownRef} className="relative">
        <button
          data-testid="notification-bell"
          onClick={() => setIsDropdownOpen(!isDropdownOpen)}
          className="p-1.5 text-text-muted hover:text-text-secondary hover:bg-gray-100 rounded-md transition-colors relative"
          title="알림"
          aria-label={unreadCount > 0 ? `알림 (읽지 않음 ${unreadCount}건)` : '알림'}
          aria-expanded={isDropdownOpen}
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
          </svg>
          {unreadCount > 0 && (
            <span
              data-testid="notification-badge"
              className="absolute -top-0.5 -right-0.5 bg-error text-white text-xs font-bold rounded-full w-4 h-4 flex items-center justify-center"
            >
              {unreadCount > 9 ? '9+' : unreadCount}
            </span>
          )}
        </button>

        {isDropdownOpen && (
          <>
            <div className="fixed inset-0 z-10" onClick={() => setIsDropdownOpen(false)} />
            <div
              data-testid="notification-dropdown"
              className="absolute right-0 mt-1 w-80 bg-white border border-border rounded-lg shadow-card-elevated z-20 max-h-96 overflow-y-auto"
            >
              <div className="p-3 border-b border-border">
                <h3 className="text-sm font-semibold text-text">알림</h3>
              </div>

              {isLoading ? (
                <div className="flex items-center justify-center py-8">
                  <div className="w-6 h-6 border-2 border-border border-t-primary rounded-full animate-spin" />
                </div>
              ) : notifications.length === 0 ? (
                <div className="p-8 text-center text-sm text-text-muted">알림이 없습니다.</div>
              ) : (
                <div className="divide-y divide-border">
                  {notifications.map((notification) => (
                    <button
                      key={notification.id}
                      data-testid={`notification-item-${notification.id}`}
                      onClick={() => handleNotificationClick(notification)}
                      className={`w-full px-3 py-3 text-left hover:bg-gray-50 transition-colors ${
                        notification.is_read ? 'bg-white' : 'bg-primary-5'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2 mb-1">
                        <p className={`text-sm font-medium ${notification.is_read ? 'text-text-secondary' : 'text-text'}`}>
                          {notification.title}
                        </p>
                        {!notification.is_read && (
                          <span className="w-2 h-2 bg-primary rounded-full flex-shrink-0 mt-1" />
                        )}
                      </div>
                      <p className="text-xs text-text-muted mb-1 line-clamp-2">{notification.message}</p>
                      <p className="text-xs text-text-muted">{formatRelativeTime(notification.created_at)}</p>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>

    </div>
  );
}
