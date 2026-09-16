import React from 'react';

import { render, screen } from '@testing-library/react';

jest.mock('next/navigation', () => ({
  usePathname: () => '/',
  // 모바일 의회 마크가 채널 선택 여부(`?channel=`)를 보고 표시를 정한다 (2026-08-25)
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({
    push: jest.fn(),
    back: jest.fn(),
  }),
}));

jest.mock('@/lib/api', () => ({
  getNotifications: jest.fn().mockResolvedValue([]),
  markNotificationRead: jest.fn().mockResolvedValue(undefined),
}));

jest.mock('@/contexts/SidebarContext', () => ({
  useSidebar: () => ({
    collapsed: false,
    mobileOpen: false,
    toggleCollapsed: jest.fn(),
    setMobileOpen: jest.fn(),
  }),
}));

jest.mock('@/contexts/BreadcrumbContext', () => ({
  useBreadcrumb: () => ({
    dynamicTitle: null,
    setTitle: jest.fn(),
  }),
}));

jest.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: null,
    loading: false,
    error: null,
    login: jest.fn(),
    logout: jest.fn(),
  }),
}));

import PlatformLayout from '../PlatformLayout';

describe('PlatformLayout', () => {
  it('renders children within the layout', () => {
    render(
      <PlatformLayout>
        <div data-testid="test-content">Hello</div>
      </PlatformLayout>
    );
    expect(screen.getByTestId('test-content')).toBeInTheDocument();
    expect(screen.getByText('Hello')).toBeInTheDocument();
  });

  it('renders sidebar desktop element', () => {
    render(
      <PlatformLayout>
        <div>Content</div>
      </PlatformLayout>
    );
    expect(screen.getByTestId('sidebar-desktop')).toBeInTheDocument();
  });

  it('renders global nav controls (no separate header bar)', () => {
    render(
      <PlatformLayout>
        <div>Content</div>
      </PlatformLayout>
    );
    // 상단 헤더 바는 제거됨 — 전역 컨트롤(알림/검색)만 우측 상단에 표시
    expect(screen.getByTestId('global-nav-controls')).toBeInTheDocument();
    expect(screen.queryByTestId('top-header')).not.toBeInTheDocument();
  });

  it('renders skip link pointing to main content (접근성)', () => {
    render(
      <PlatformLayout>
        <div>Content</div>
      </PlatformLayout>
    );
    const skipLink = screen.getByText('본문 바로가기');
    expect(skipLink).toBeInTheDocument();
    expect(skipLink).toHaveAttribute('href', '#main-content');
  });

  it('main region is the skip link target (id + tabIndex)', () => {
    render(
      <PlatformLayout>
        <div>Content</div>
      </PlatformLayout>
    );
    const main = screen.getByRole('main');
    expect(main).toHaveAttribute('id', 'main-content');
    expect(main).toHaveAttribute('tabindex', '-1');
  });
});
