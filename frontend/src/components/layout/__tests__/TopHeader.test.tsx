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

jest.mock('@/contexts/BreadcrumbContext', () => ({
  useBreadcrumb: () => ({
    dynamicTitle: null,
    setTitle: jest.fn(),
  }),
}));

jest.mock('@/lib/api', () => ({
  getNotifications: jest.fn().mockResolvedValue([]),
  markNotificationRead: jest.fn().mockResolvedValue(undefined),
}));

import TopHeader from '../TopHeader';

describe('TopHeader', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders top header with data-testid', () => {
    render(<TopHeader />);
    expect(screen.getByTestId('top-header')).toBeInTheDocument();
  });

  it('renders search link', () => {
    render(<TopHeader />);
    const searchLink = screen.getByTitle('통합 검색');
    expect(searchLink).toBeInTheDocument();
    expect(searchLink.closest('a')).toHaveAttribute('href', '/search');
  });

  it('renders mobile menu button', () => {
    render(<TopHeader />);
    const menuButton = screen.getByLabelText('메뉴 열기');
    expect(menuButton).toBeInTheDocument();
  });

  it('calls setMobileOpen on menu button click', () => {
    render(<TopHeader />);
    const menuButton = screen.getByLabelText('메뉴 열기');
    fireEvent.click(menuButton);
    expect(mockSetMobileOpen).toHaveBeenCalledWith(true);
  });

  it('hides breadcrumbs on home page', () => {
    render(<TopHeader />);
    // 홈(/)에서는 브레드크럼이 표시되지 않음
    expect(screen.queryByText('대시보드')).not.toBeInTheDocument();
  });

  it('renders notification bell icon', () => {
    render(<TopHeader />);
    const bellButton = screen.getByTestId('notification-bell');
    expect(bellButton).toBeInTheDocument();
  });

  it('does not show notification badge when no unread notifications', () => {
    render(<TopHeader />);
    expect(screen.queryByTestId('notification-badge')).not.toBeInTheDocument();
  });
});
