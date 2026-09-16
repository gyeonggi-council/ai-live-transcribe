import { render, screen } from '@testing-library/react';

import AppLoginRequired from '../AppLoginRequired';

/**
 * 의회사무처 직원 PC 대역 — 막지 않고 "앱으로 로그인하세요" 를 안내한다 (2026-09-16 담당자 결정).
 */

const mockAuth = {
  user: null as unknown,
  loading: false,
  councilNetwork: false,
  loginRequired: true,
  appInstallGuideUrl: 'https://ggc-install-video.vercel.app/',
};

jest.mock('@/contexts/AuthContext', () => ({
  useAuth: () => mockAuth,
}));

jest.mock('@/hooks/useAccessLog', () => ({
  __esModule: true,
  logAccess: jest.fn(),
}));

describe('AppLoginRequired', () => {
  it('앱 로그인 안내와 로그인 버튼을 보여준다', () => {
    render(<AppLoginRequired />);

    expect(screen.getByTestId('app-login-required')).toHaveTextContent(
      '모바일 의정지원서비스 앱으로 로그인해 주세요'
    );
    expect(screen.getByTestId('app-login-required-login')).toHaveAttribute('href', '/login');
  });

  it('앱이 없는 사람에게 설치 방법을 새 창으로 안내한다', () => {
    render(<AppLoginRequired />);

    const link = screen.getByTestId('app-install-guide-link');
    expect(link).toHaveAttribute('href', 'https://ggc-install-video.vercel.app/');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
  });

  it('안내를 본 것을 접속 통계에 남긴다', () => {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { logAccess } = require('@/hooks/useAccessLog');
    render(<AppLoginRequired />);

    expect(logAccess).toHaveBeenCalledWith('login_prompt', expect.any(Object));
  });
});
