import React from 'react';

import { render, screen, fireEvent } from '@testing-library/react';

const mockPush = jest.fn();

jest.mock('next/navigation', () => ({
  usePathname: () => '/',
  useRouter: () => ({
    push: mockPush,
  }),
}));

const mockSetMobileOpen = jest.fn();

jest.mock('@/contexts/SidebarContext', () => ({
  useSidebar: () => ({
    collapsed: false,
    mobileOpen: false,
    toggleCollapsed: jest.fn(),
    setMobileOpen: mockSetMobileOpen,
  }),
}));

jest.mock('@/lib/api', () => ({
  getNotifications: jest.fn().mockResolvedValue([]),
  markNotificationRead: jest.fn().mockResolvedValue(undefined),
}));

import GlobalNavControls from '../GlobalNavControls';

describe('GlobalNavControls', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders the controls wrapper', () => {
    render(<GlobalNavControls />);
    expect(screen.getByTestId('global-nav-controls')).toBeInTheDocument();
  });

  it('navigates to search on Cmd/Ctrl+K shortcut', () => {
    render(<GlobalNavControls />);
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    expect(mockPush).toHaveBeenCalledWith('/search');
  });

  it('renders mobile menu button', () => {
    render(<GlobalNavControls />);
    expect(screen.getByLabelText('메뉴 열기')).toBeInTheDocument();
  });

  it('calls setMobileOpen on menu button click', () => {
    render(<GlobalNavControls />);
    fireEvent.click(screen.getByLabelText('메뉴 열기'));
    expect(mockSetMobileOpen).toHaveBeenCalledWith(true);
  });

  it('renders notification bell icon', () => {
    render(<GlobalNavControls />);
    expect(screen.getByTestId('notification-bell')).toBeInTheDocument();
  });

  it('does not show notification badge when no unread notifications', () => {
    render(<GlobalNavControls />);
    expect(screen.queryByTestId('notification-badge')).not.toBeInTheDocument();
  });
});
