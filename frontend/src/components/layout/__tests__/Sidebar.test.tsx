import React from 'react';

import { render, screen, fireEvent } from '@testing-library/react';

jest.mock('next/navigation', () => ({
  usePathname: () => '/',
}));

// Mock contexts
const mockToggleCollapsed = jest.fn();
const mockSetMobileOpen = jest.fn();

jest.mock('@/contexts/SidebarContext', () => ({
  useSidebar: () => ({
    collapsed: false,
    mobileOpen: false,
    toggleCollapsed: mockToggleCollapsed,
    setMobileOpen: mockSetMobileOpen,
  }),
}));

jest.mock('@/contexts/BreadcrumbContext', () => ({
  useBreadcrumb: () => ({
    dynamicTitle: null,
    setTitle: jest.fn(),
  }),
}));

// AuthContext mock - 각 테스트에서 user 상태를 제어
const mockUseAuth = jest.fn();
jest.mock('@/contexts/AuthContext', () => ({
  useAuth: () => mockUseAuth(),
}));

import Sidebar from '../Sidebar';

describe('Sidebar', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  // 기존 테스트 유지
  it('renders logo and system title', () => {
    mockUseAuth.mockReturnValue({ user: null, loading: false, error: null, login: jest.fn(), logout: jest.fn() });
    render(<Sidebar />);
    expect(screen.getAllByText('경기도의회').length).toBeGreaterThan(0);
    expect(screen.getAllByText('영상회의록 통합플랫폼').length).toBeGreaterThan(0);
  });

  // 접기 버튼은 하단 한 줄에 합쳐지며 아이콘만 남았다(2026-08-25 개선안 2c).
  // 글자가 아니라 aria-label 로 찾는다 — 그것이 접근성상 이름이기도 하다.
  it('renders collapse button', () => {
    mockUseAuth.mockReturnValue({ user: null, loading: false, error: null, login: jest.fn(), logout: jest.fn() });
    render(<Sidebar />);
    expect(screen.getAllByLabelText('사이드바 접기').length).toBeGreaterThan(0);
  });

  it('calls toggleCollapsed on collapse button click', () => {
    mockUseAuth.mockReturnValue({ user: null, loading: false, error: null, login: jest.fn(), logout: jest.fn() });
    render(<Sidebar />);
    const collapseButtons = screen.getAllByLabelText('사이드바 접기');
    const collapseButton = collapseButtons[0];
    if (!collapseButton) throw new Error('Expected collapse button to exist.');
    fireEvent.click(collapseButton);
    expect(mockToggleCollapsed).toHaveBeenCalled();
  });

  it('도구 묶음에 외부 링크·다운로드·공지를 모아 둔다', () => {
    mockUseAuth.mockReturnValue({ user: null, loading: false, error: null, login: jest.fn(), logout: jest.fn() });
    render(<Sidebar />);
    expect(screen.getAllByText('도구').length).toBeGreaterThan(0);
    expect(screen.getAllByText('의회 영상 페이지').length).toBeGreaterThan(0);
    // 2026-09-08 설치형 추출기 재개 — 다운로드 링크가 도구 절에 다시 있다 (웹 워크벤치 /clips 와 병행)
    expect(screen.getAllByText('영상추출기 다운로드').length).toBeGreaterThan(0);
    expect(screen.getAllByText('업데이트 소식').length).toBeGreaterThan(0);
  });

  it('자식이 하나뿐인 모듈은 아코디언 없이 곧바로 링크다', () => {
    mockUseAuth.mockReturnValue({ user: null, loading: false, error: null, login: jest.fn(), logout: jest.fn() });
    render(<Sidebar />);
    // 통합검색 = 자식 1개(/search) → 펼치지 않아도 링크여야 한다
    const search = screen.getAllByRole('link', { name: '통합검색' });
    expect(search.length).toBeGreaterThan(0);
    expect(search[0]).toHaveAttribute('href', '/search');
  });

  it('자식이 여럿인 모듈은 펼치지 않아도 자식이 보인다', () => {
    mockUseAuth.mockReturnValue({ user: null, loading: false, error: null, login: jest.fn(), logout: jest.fn() });
    render(<Sidebar />);
    // 회의관리 = 자식 3개 → 클릭 없이 대시보드·실시간 방송·회의 목록이 보인다
    expect(screen.getAllByText('대시보드').length).toBeGreaterThan(0);
    expect(screen.getAllByText('실시간 방송').length).toBeGreaterThan(0);
    expect(screen.getAllByText('회의 목록').length).toBeGreaterThan(0);
  });

  it('renders desktop sidebar with data-testid', () => {
    mockUseAuth.mockReturnValue({ user: null, loading: false, error: null, login: jest.fn(), logout: jest.fn() });
    render(<Sidebar />);
    expect(screen.getByTestId('sidebar-desktop')).toBeInTheDocument();
  });

  // 역할 기반 메뉴 필터링 테스트
  it('test_admin_sees_all_menus: admin 역할은 시스템관리 포함 노출 메뉴 표시', () => {
    mockUseAuth.mockReturnValue({
      user: { id: '1', username: 'admin', display_name: '관리자', role: 'admin', assigned_committee: null, is_active: true },
      loading: false,
      error: null,
      login: jest.fn(),
      logout: jest.fn(),
    });
    render(<Sidebar />);
    expect(screen.getAllByText('회의관리').length).toBeGreaterThan(0);
    // admin 전용 시스템관리 메뉴가 보여야 함
    expect(screen.getAllByText('시스템관리').length).toBeGreaterThan(0);
    expect(screen.getAllByText('AI 어시스턴트').length).toBeGreaterThan(0);
    expect(screen.getAllByText('통합검색').length).toBeGreaterThan(0);
  });

  it('test_anonymous_sees_limited_menus: 비로그인 사용자는 시스템관리 메뉴 미표시', () => {
    mockUseAuth.mockReturnValue({ user: null, loading: false, error: null, login: jest.fn(), logout: jest.fn() });
    render(<Sidebar />);
    // 회의관리, 통합검색은 보임
    expect(screen.getAllByText('회의관리').length).toBeGreaterThan(0);
    expect(screen.getAllByText('통합검색').length).toBeGreaterThan(0);
    // 시스템관리는 숨김
    expect(screen.queryByText('시스템관리')).not.toBeInTheDocument();
  });

  it('test_login_button_shown_when_anonymous: 비로그인 시 로그인 버튼 표시', () => {
    mockUseAuth.mockReturnValue({ user: null, loading: false, error: null, login: jest.fn(), logout: jest.fn() });
    render(<Sidebar />);
    expect(screen.getAllByText('로그인').length).toBeGreaterThan(0);
  });

  it('test_logout_button_shown_when_logged_in: 로그인 상태에서 사용자 정보와 로그아웃 버튼 표시', () => {
    const mockLogout = jest.fn();
    mockUseAuth.mockReturnValue({
      user: { id: '1', username: 'staff01', display_name: '김담당', role: 'staff', assigned_committee: null, is_active: true },
      loading: false,
      error: null,
      login: jest.fn(),
      logout: mockLogout,
    });
    render(<Sidebar />);
    expect(screen.getAllByText('김담당').length).toBeGreaterThan(0);
    const logoutBtns = screen.getAllByText('로그아웃');
    expect(logoutBtns.length).toBeGreaterThan(0);
    fireEvent.click(logoutBtns[0]!);
    expect(mockLogout).toHaveBeenCalled();
  });

  it('test_committee_staff_sees_role_menu: committee_staff는 권한 메뉴(AI 어시스턴트) 표시, 관리자 전용 메뉴는 미표시', () => {
    mockUseAuth.mockReturnValue({
      user: { id: '2', username: 'cs01', display_name: '이위원', role: 'committee_staff', assigned_committee: '기획재정위원회', is_active: true },
      loading: false,
      error: null,
      login: jest.fn(),
      logout: jest.fn(),
    });
    render(<Sidebar />);
    // committee_staff 권한이 부여된 AI 어시스턴트 메뉴는 표시
    expect(screen.getAllByText('AI 어시스턴트').length).toBeGreaterThan(0);
    // admin 전용 시스템관리는 미표시
    expect(screen.queryByText('시스템관리')).not.toBeInTheDocument();
  });
});
