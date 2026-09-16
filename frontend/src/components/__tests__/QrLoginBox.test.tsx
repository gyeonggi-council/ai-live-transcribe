import React from 'react';

import { render, screen, waitFor, act } from '@testing-library/react';

jest.mock('@/lib/auth', () => ({
  createQrSession: jest.fn(),
  pollQrSession: jest.fn(),
}));

import QrLoginBox from '../QrLoginBox';

const { createQrSession, pollQrSession } = jest.requireMock('@/lib/auth') as {
  createQrSession: jest.Mock;
  pollQrSession: jest.Mock;
};

const SESSION = { sessionId: 'sid-1', apiUrl: 'https://magent.ggc.go.kr', ttl: 300 };

describe('QrLoginBox', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
  });
  afterEach(() => {
    jest.useRealTimers();
  });

  // 접속 즉시 발급(2026-08-28) — '시작' 버튼은 더 이상 없다. 남은 버튼은
  // 만료·미등록·오류 뒤의 '새 QR 발급'/'다시 시도' 뿐이다.
  it('마운트하면 바로 세션을 발급받아 QR 을 표시한다', async () => {
    createQrSession.mockResolvedValueOnce(SESSION);
    render(<QrLoginBox onSuccess={jest.fn()} />);

    // 버튼을 누르지 않는다 — 마운트와 동시에 발급한다(2026-08-28).
    // 화면 상태는 프로즈가 아니라 **정본 계약**으로 확인한다 —
    // .ggc-qr-stage 의 data-state 가 상태기계의 단일 표면이다(ggc-components.css §11).
    await waitFor(() => {
      expect(document.querySelector('.ggc-qr-stage')).toHaveAttribute('data-state', 'showing');
    });
    expect(createQrSession).toHaveBeenCalledTimes(1);
  });

  it('폴링이 authenticated 를 받으면 onSuccess 를 호출한다', async () => {
    createQrSession.mockResolvedValueOnce(SESSION);
    const tokenRes = {
      status: 'authenticated',
      access_token: 't',
      token_type: 'bearer',
      user: { id: 'u1', username: '3000000008' },
    };
    pollQrSession.mockResolvedValue(tokenRes);
    const onSuccess = jest.fn();
    render(<QrLoginBox onSuccess={onSuccess} />);

    await waitFor(() =>
      expect(document.querySelector('.ggc-qr-stage')).toHaveAttribute('data-state', 'showing'),
    );

    await act(async () => {
      jest.advanceTimersByTime(3000);
    });

    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith(tokenRes));
  });

  it('미등록 계정이면 usercode 안내를 보여준다', async () => {
    createQrSession.mockResolvedValueOnce(SESSION);
    pollQrSession.mockResolvedValue({
      status: 'unregistered',
      usercode: '9999999999',
      detail: '등록되지 않은 계정입니다.',
    });
    render(<QrLoginBox onSuccess={jest.fn()} />);

    await waitFor(() =>
      expect(document.querySelector('.ggc-qr-stage')).toHaveAttribute('data-state', 'showing'),
    );

    await act(async () => {
      jest.advanceTimersByTime(3000);
    });

    await waitFor(() => {
      expect(screen.getByText(/9999999999/)).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /새 QR 발급/ })).toBeInTheDocument();
  });

  it('세션 발급 실패 시 오류 메시지를 보여준다', async () => {
    createQrSession.mockRejectedValueOnce(new Error('QR 세션 발급에 실패했습니다'));
    render(<QrLoginBox onSuccess={jest.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/발급에 실패/)).toBeInTheDocument();
    });
  });
});
