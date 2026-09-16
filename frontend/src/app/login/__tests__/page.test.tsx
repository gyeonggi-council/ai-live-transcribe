import React from 'react';

import { render, screen, waitFor, fireEvent } from '@testing-library/react';

// next/navigation mock
const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}));

// @/lib/auth mock — QrLoginBox 가 page import 시점에 이 모듈을 당기므로,
// 팩토리가 파일 상단 const 를 참조하면 TDZ(초기화 전 접근)로 죽는다. 전부 인라인으로 만들고
// 테스트 본문에서는 requireMock 으로 꺼내 쓴다.
//
// **login(아이디·비밀번호)은 여기 없다** — 2026-08-28 에 모듈에서 없앴다.
// 로그인 화면은 QR 과 통합 로그인만 부른다.
jest.mock('@/lib/auth', () => ({
  logout: jest.fn(),
  getMe: jest.fn(),
  getToken: jest.fn(() => null),
  setToken: jest.fn(),
  clearToken: jest.fn(),
  createQrSession: jest.fn(async () => ({ sessionId: 's1', apiUrl: 'https://example.test', ttl: 300 })),
  pollQrSession: jest.fn(async () => ({ status: 'pending' })),
  // SSO 자동 교환 — 테스트 기본값은 '세션 없음'(기존 QR 화면 경로)
  ssoExchange: jest.fn(async () => ({ status: 'none' })),
}));

// AuthContext mock — 같은 이유로 인라인 팩토리 + requireMock.
jest.mock('@/contexts/AuthContext', () => {
  const useAuthValue = {
    user: null,
    loading: false,
    error: null,
    pinLogin: jest.fn(),
    adoptSession: jest.fn(),
    logout: jest.fn(),
  };
  return {
    __useAuthValue: useAuthValue,
    useAuth: () => useAuthValue,
    AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  };
});

import LoginPage from '../page';

const authMock = jest.requireMock('@/lib/auth') as {
  createQrSession: jest.Mock;
  ssoExchange: jest.Mock;
};

describe('LoginPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    authMock.ssoExchange.mockResolvedValue({ status: 'none' });
    authMock.createQrSession.mockResolvedValue({
      sessionId: 's1',
      apiUrl: 'https://example.test',
      ttl: 300,
    });
  });

  it('test_render_qr_only: QR 안내가 보이고 아이디·비밀번호 입력은 없다', async () => {
    render(<LoginPage />);

    expect(screen.getByText('모바일 의정지원서비스 앱으로 로그인')).toBeInTheDocument();
    // 아이디·비밀번호 로그인은 없앴다 — 되살아나면 여기서 걸린다.
    expect(screen.queryByLabelText(/아이디/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/비밀번호/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '로그인' })).not.toBeInTheDocument();

    expect(screen.getByText('비로그인으로 계속')).toBeInTheDocument();
  });

  it('test_qr_issued_on_arrival: 접속하자마자 QR 을 발급한다(버튼을 누르지 않는다)', async () => {
    render(<LoginPage />);
    await waitFor(() => expect(authMock.createQrSession).toHaveBeenCalledTimes(1));
  });

  it('test_sso_button_when_no_session: SSO 세션이 없으면 통합 로그인 버튼을 노출한다', async () => {
    render(<LoginPage />);
    await waitFor(() =>
      expect(screen.getByText('통합 로그인 (업무플랫폼 공통)')).toBeInTheDocument(),
    );
  });

  it('test_continue_without_login: "비로그인으로 계속" 클릭 시 "/" 로 이동', () => {
    render(<LoginPage />);
    fireEvent.click(screen.getByText('비로그인으로 계속'));
    expect(mockPush).toHaveBeenCalledWith('/');
  });
});
